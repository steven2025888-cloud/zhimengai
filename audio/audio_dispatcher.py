# audio/audio_dispatcher.py
import os
import random
import threading
from dataclasses import dataclass
from typing import Optional, Callable, Tuple
from collections import deque

import sounddevice as sd

from core.state import AppState
from audio.audio_player import play_audio_interruptible, play_audio_and_wait, set_paused as _player_set_paused, \
    stop_playback as _player_stop
import time
import tempfile
import subprocess
import shutil
import pathlib

PLAY_REPORT = "PLAY_REPORT"
# 为了兼容你现有调用：主播关键词仍叫 PLAY_SIZE
PLAY_ANCHOR = "PLAY_SIZE"
PLAY_ZHULI = "PLAY_ZHULI"
PLAY_RANDOM = "PLAY_RANDOM"

# 插播：当前音频播完后播放（不打断当前）
PLAY_INSERT = "PLAY_INSERT"
# 急插：立即停止当前并播放（最高优先级，仅次于报时）
PLAY_URGENT = "PLAY_URGENT"
# 录音急插（与急插同队列，仅用于标记来源）
PLAY_RECORD = "PLAY_RECORD"

# 关注/点赞事件音频
PLAY_FOLLOW = "PLAY_FOLLOW"
PLAY_LIKE = "PLAY_LIKE"


@dataclass
class AudioCommand:
    name: str
    path: str
    on_finished: Optional[Callable[[], None]] = None


class AudioDispatcher:
    def __init__(self, state: AppState):
        self.state = state

        # 优先级队列：报时 > (主播关键词/助播关键词 按模式决定) > 轮播
        self.report_q: deque[AudioCommand] = deque()
        self.anchor_q: deque[AudioCommand] = deque()
        self.zhuli_q: deque[AudioCommand] = deque()
        self.random_q: deque[AudioCommand] = deque()

        # 关注/点赞队列（优先于轮播，低于主播/助播）
        self.follow_q: deque[AudioCommand] = deque()
        self.like_q: deque[AudioCommand] = deque()

        # 插播/急插队列
        self.insert_q: deque[AudioCommand] = deque()
        self.urgent_q: deque[AudioCommand] = deque()

        self.current_playing = False
        self.current_name: str | None = None
        self.current_path: str | None = None

        # stop_event：用于可中断播放（轮播一定用；关键词/报时靠 sd.stop 也能停）
        self.stop_event = threading.Event()

        # ===== 暂停播放（UI 控制）=====
        self.paused: bool = False
        # 暂停时如果正在播放，先记住这条，恢复时放回队列最前
        self._pause_resume_cmd: Optional[Tuple[str, str]] = None
        # 被打断的轮播，等高优先级都播完再恢复
        self.resume_after_high: str | None = None

        self._lock = threading.RLock()

        # 文件夹轮播控制
        self.folder_cycle_thread: threading.Thread | None = None
        self.folder_cycle_running = False

        # ===== 变量调节（运行态缓存）=====
        # 你最新需求：不再按“随机多少秒刷新一次”，而是【每段音频】都会随机一个目标值，
        # 并在该音频内把当前值平滑过渡到目标值；下一段音频再从上一次目标值继续过渡。
        # 因此这里仅保留“上一次的目标值(=下一段的起点)”。
        self._cur_pitch_pct = 0  # percent, 例如 -5 ~ +5
        self._cur_speed_pct = 0  # percent, 例如 +0 ~ +10
        self._cur_volume_db = 0  # dB, 例如 +0 ~ +10

        # 为避免极端慢机卡顿：每段音频的平滑过渡拆成多少段（越大越平滑但越慢）
        self._var_ramp_steps = 5

        # ===== 录音急插（按住录/松开播 或 开始/停止播） =====
        self._rec_lock = threading.RLock()
        self._rec_stream = None
        self._rec_sf = None
        self._rec_path: str | None = None
        self._rec_running = False
        self._rec_samplerate = 44100
        self._rec_channels = 1
        self._rec_level = 0.0
        self._rec_wave_max = 4096
        self._rec_wave = deque()  # 最近一段波形（float, -1~1）

    def _parse_delta_range(self, s: str) -> tuple[int, int]:
        """
        解析类似 "-5~+5" "+0~+10" "-10~+10"
        返回 (min,max) int
        """
        s = (s or "").strip().replace(" ", "")
        if "~" not in s:
            # 兜底：单值
            try:
                v = int(s.replace("+", ""))
                return v, v
            except Exception:
                return 0, 0
        a, b = s.split("~", 1)

        def _to_int(x: str) -> int:
            x = x.strip()
            if x.startswith("+"):
                x = x[1:]
            try:
                return int(float(x))
            except Exception:
                return 0

        mn = _to_int(a)
        mx = _to_int(b)
        if mx < mn:
            mn, mx = mx, mn
        return mn, mx

    def _ffprobe_bin(self) -> str:
        return shutil.which("ffprobe") or "ffprobe"

    def _get_duration_sec(self, src_path: str) -> float:
        """尽量可靠地拿到音频时长（秒）。失败就返回 0。"""
        try:
            out = self._check_output_hidden(
                [
                    self._ffprobe_bin(),
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    src_path,
                ],
                timeout=8,
            )

            v = float(out.decode("utf-8", "ignore").strip() or "0")
            return max(0.0, v)
        except Exception:
            return 0.0

    def _atempo_chain(self, tempo: float) -> str:
        """
        ffmpeg atempo 只支持 0.5~2.0，超出要拆链
        """
        tempo = float(tempo)
        if tempo <= 0:
            tempo = 1.0
        parts = []
        while tempo > 2.0:
            parts.append(2.0)
            tempo /= 2.0
        while tempo < 0.5:
            parts.append(0.5)
            tempo /= 0.5
        parts.append(tempo)
        return ",".join([f"atempo={p:.6f}" for p in parts])

    def _ffmpeg_bin(self) -> str:
        # 优先用系统 ffmpeg；你如果有自带 ffmpeg，可在这里加路径
        return shutil.which("ffmpeg") or "ffmpeg"

    def _subprocess_hidden_kwargs(self) -> dict:
        """Windows 下隐藏子进程控制台窗口（ffmpeg/ffprobe 不再闪窗）"""
        if os.name != "nt":
            return {}
        # CREATE_NO_WINDOW = 0x08000000
        CREATE_NO_WINDOW = 0x08000000
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        return {"creationflags": CREATE_NO_WINDOW, "startupinfo": si}

    def _run_hidden(self, cmd: list[str], check: bool = False, timeout: float | None = None):
        """subprocess.run 的隐藏窗口封装"""
        kw = self._subprocess_hidden_kwargs()
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            check=check,
            **kw,
        )

    def _check_output_hidden(self, cmd: list[str], timeout: float | None = None) -> bytes:
        """subprocess.check_output 的隐藏窗口封装"""
        kw = self._subprocess_hidden_kwargs()
        return subprocess.check_output(
            cmd,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            **kw,
        )

    def _pick_next_targets(self) -> tuple[int, int, int]:
        """每段音频随机一个目标值（绝对值），并让下一段从上一段目标值继续过渡。"""
        st = self.state

        # 目标值（absolute）：在 UI 选的范围内随机
        if bool(getattr(st, "var_pitch_enabled", False)):
            mn, mx = self._parse_delta_range(str(getattr(st, "var_pitch_delta", "-5~+5")))
            pitch_t = random.randint(mn, mx)
        else:
            pitch_t = self._cur_pitch_pct

        if bool(getattr(st, "var_speed_enabled", False)):
            mn, mx = self._parse_delta_range(str(getattr(st, "var_speed_delta", "+0~+10")))
            speed_t = random.randint(mn, mx)
        else:
            speed_t = self._cur_speed_pct

        if bool(getattr(st, "var_volume_enabled", False)):
            mn, mx = self._parse_delta_range(str(getattr(st, "var_volume_delta", "+0~+10")))
            vol_t = random.randint(mn, mx)
        else:
            vol_t = self._cur_volume_db

        return pitch_t, speed_t, vol_t

    def _build_const_filter(self, pitch_pct: int, speed_pct: int, vol_db: int,
                            pitch_on: bool | None = None,
                            speed_on: bool | None = None,
                            vol_on: bool | None = None) -> str | None:
        """构造“常量”滤镜（用于某一小段音频）。"""
        st = self.state
        _p = bool(getattr(st, "var_pitch_enabled", False))
        _s = bool(getattr(st, "var_speed_enabled", False))
        _v = bool(getattr(st, "var_volume_enabled", False))
        pitch_on = _p if pitch_on is None else bool(pitch_on)
        speed_on = _s if speed_on is None else bool(speed_on)
        vol_on = _v if vol_on is None else bool(vol_on)

        if not (pitch_on or speed_on or vol_on):
            return None

        pitch_factor = 1.0 + (int(pitch_pct) / 100.0)
        speed_factor = 1.0 + (int(speed_pct) / 100.0)

        filters = []
        sr = 44100

        if pitch_on:
            # pitch shift 保持时长：asetrate(sr*pf) -> aresample(sr) -> atempo(补偿)
            filters.append(f"asetrate={sr}*{pitch_factor:.6f}")
            filters.append(f"aresample={sr}")
            tempo = (speed_factor / pitch_factor) if speed_on else (1.0 / pitch_factor)
            filters.append(self._atempo_chain(tempo))
        elif speed_on:
            filters.append(self._atempo_chain(speed_factor))

        if vol_on and int(vol_db) != 0:
            filters.append(f"volume={int(vol_db)}dB")

        return ",".join(filters) if filters else None

    def _prepare_processed_audio(self, src_path: str) -> tuple[str, str | None]:
        """
        返回 (play_path, tmp_path_to_cleanup)
        """
        st = self.state
        pitch_on = bool(getattr(st, "var_pitch_enabled", False))
        speed_on = bool(getattr(st, "var_speed_enabled", False))
        vol_on = bool(getattr(st, "var_volume_enabled", False))
        if not (pitch_on or speed_on or vol_on):
            return src_path, None

        # 先拿到时长，用于“短音频保护”
        dur = self._get_duration_sec(src_path)
        if dur <= 0.05:
            # 拿不到时长/太短：为了避免突兀变化，直接回退原音频
            return src_path, None

        pitch_min = int(getattr(st, "var_pitch_min_sec", 8) or 0)
        vol_min = int(getattr(st, "var_volume_min_sec", 3) or 0)
        speed_min = int(getattr(st, "var_speed_min_sec", 8) or 0)

        apply_pitch = pitch_on and (pitch_min <= 0 or dur >= pitch_min)
        apply_vol = vol_on and (vol_min <= 0 or dur >= vol_min)
        apply_speed = speed_on and (speed_min <= 0 or dur >= speed_min)

        # 这段音频如果三项都被短音频保护挡住，则不做任何处理
        if not (apply_pitch or apply_speed or apply_vol):
            return src_path, None

        # 本段音频：从“上一段目标值”过渡到“本段目标值”
        pitch_start, speed_start, vol_start = self._cur_pitch_pct, self._cur_speed_pct, self._cur_volume_db
        pitch_t, speed_t, vol_t = self._pick_next_targets()

        # 对被“短音频保护”的项：本段不变化，并且不推进内部状态（避免下一段突兀跳变）
        pitch_t_eff = pitch_t if apply_pitch else pitch_start
        speed_t_eff = speed_t if apply_speed else speed_start
        vol_t_eff = vol_t if apply_vol else vol_start

        # 过渡在本段音频内“随机完成”
        frac = random.uniform(0.0, 1.0)
        ramp_end = dur * frac

        steps = max(1, int(getattr(self, "_var_ramp_steps", 5)))
        # ramp_end 太小就视为“开头直接跳到目标”
        if ramp_end <= 0.05:
            steps = 1

        # 输出临时 wav（保证兼容播放）
        tmp = tempfile.NamedTemporaryFile(prefix="var_", suffix=".wav", delete=False)
        tmp_path = tmp.name
        tmp.close()

        # 组装 filter_complex：atrim 分段 + 每段常量滤镜 + concat
        seg_filters = []
        seg_labels = []
        seg_idx = 0

        def _interp(a: float, b: float, t: float) -> float:
            return a + (b - a) * t

        if steps <= 1:
            cf = self._build_const_filter(
                pitch_t_eff, speed_t_eff, vol_t_eff,
                pitch_on=apply_pitch, speed_on=apply_speed, vol_on=apply_vol
            )
            if cf:
                seg_filters.append(f"[0:a]{cf}[a0]")
                seg_labels.append("[a0]")
            else:
                seg_filters.append("[0:a]anull[a0]")
                seg_labels.append("[a0]")
        else:
            # ramp_end 以内分段渐变
            for i in range(steps):
                s = (ramp_end * i) / steps
                e = (ramp_end * (i + 1)) / steps
                # 用“段末插值”更像缓慢靠近
                tt = (i + 1) / steps
                p = int(round(_interp(pitch_start, pitch_t_eff, tt)))
                sp = int(round(_interp(speed_start, speed_t_eff, tt)))
                vb = int(round(_interp(vol_start, vol_t_eff, tt)))
                cf = self._build_const_filter(
                    p, sp, vb,
                    pitch_on=apply_pitch, speed_on=apply_speed, vol_on=apply_vol
                ) or "anull"
                seg_filters.append(
                    f"[0:a]atrim=start={s:.6f}:end={e:.6f},asetpts=PTS-STARTPTS,{cf}[a{seg_idx}]"
                )
                seg_labels.append(f"[a{seg_idx}]")
                seg_idx += 1

            # 2) 过渡完成后的剩余段：用目标值
            if dur > ramp_end + 0.02:
                cf = self._build_const_filter(
                    pitch_t_eff, speed_t_eff, vol_t_eff,
                    pitch_on=apply_pitch, speed_on=apply_speed, vol_on=apply_vol
                ) or "anull"
                seg_filters.append(
                    f"[0:a]atrim=start={ramp_end:.6f},asetpts=PTS-STARTPTS,{cf}[a{seg_idx}]"
                )
                seg_labels.append(f"[a{seg_idx}]")
                seg_idx += 1

        concat_in = "".join(seg_labels)
        concat_n = len(seg_labels)
        filter_complex = ";".join(seg_filters + [f"{concat_in}concat=n={concat_n}:v=0:a=1[aout]"])

        cmd = [
            self._ffmpeg_bin(),
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", src_path,
            "-vn",
            "-ac", "2",
            "-ar", "44100",
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            tmp_path,
        ]

        try:
            r = self._run_hidden(cmd, check=False, timeout=max(30, dur * 3))
            if r.returncode != 0:
                err = (r.stderr or b"").decode("utf-8", "ignore")[-2000:]
                out = (r.stdout or b"").decode("utf-8", "ignore")[-2000:]
                raise RuntimeError(f"ffmpeg failed rc={r.returncode}\nSTDERR:\n{err}\nSTDOUT:\n{out}")

            # 本段结束：只推进“本段实际应用”的项（被保护的项保持不动）
            if apply_pitch:
                self._cur_pitch_pct = int(pitch_t_eff)
            if apply_speed:
                self._cur_speed_pct = int(speed_t_eff)
            if apply_vol:
                self._cur_volume_db = int(vol_t_eff)

            print(
                "🎛️ 变量调节："
                f"pitch {pitch_start}%→{pitch_t_eff}%({'ON' if apply_pitch else 'SKIP'}), "
                f"speed {speed_start}%→{speed_t_eff}%({'ON' if apply_speed else 'SKIP'}), "
                f"volume {vol_start}dB→{vol_t_eff}dB({'ON' if apply_vol else 'SKIP'}) "
                f"| ramp={ramp_end:.2f}s/{dur:.2f}s | src={os.path.basename(src_path)}"
            )
            return tmp_path, tmp_path
        except Exception as e:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            print("⚠️ 变量调节处理失败，回退原音频：", e)
            return src_path, None

    # ===================== 辅助状态 =====================

    def has_pending(self) -> bool:
        with self._lock:
            return bool(
                self.report_q or self.urgent_q or self.insert_q
                or self.anchor_q or self.zhuli_q
                or self.follow_q or self.like_q
                or self.random_q
            )
    def is_idle(self) -> bool:
        return (not self.current_playing) and (not self.has_pending())

    # ===================== 文件夹顺序轮播 =====================

    def start_folder_cycle(self):
        if self.folder_cycle_running:
            return
        self.folder_cycle_running = True
        self.folder_cycle_thread = threading.Thread(target=self._folder_cycle_loop, daemon=True)
        self.folder_cycle_thread.start()
        print("🔁 已启动文件夹顺序轮播线程")

    def _get_ordered_folders_compatible(self):
        fm = getattr(self.state, "folder_manager", None)
        if not fm:
            return []
        if hasattr(fm, "get_ordered_folders"):
            try:
                return fm.get_ordered_folders()
            except Exception:
                return []
        for attr in ("ordered_folders", "folders", "folder_list"):
            if hasattr(fm, attr):
                folders = getattr(fm, attr)
                if isinstance(folders, list):
                    return folders
        return []

    def _scan_folder_audio(self, folder):
        from pathlib import Path

        try:
            # folder 可能是 Path，也可能是 "不挑柴" 这种名字
            if hasattr(folder, "iterdir"):
                folder_p = folder
            else:
                folder_s = str(folder)
                p = Path(folder_s)

                # ✅ 如果是相对路径：基于 folder_manager.base_dir 拼成绝对路径
                if not p.is_absolute():
                    fm = getattr(self.state, "folder_manager", None)
                    base_dir = getattr(fm, "base_dir", None)
                    if base_dir:
                        p = Path(base_dir) / folder_s
                folder_p = p

            if not folder_p.exists() or not folder_p.is_dir():
                return []

            return [
                str(p)
                for p in folder_p.iterdir()
                if p.is_file() and p.suffix.lower() in (".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg")
            ]
        except Exception:
            return []

    def _folder_cycle_loop(self):
        while True:
            if not self.state.enabled or not self.state.live_ready:
                threading.Event().wait(1)
                continue

            folders = self._get_ordered_folders_compatible()
            if not folders:
                threading.Event().wait(1)
                continue

            for folder in folders:
                if not self.state.enabled or not self.state.live_ready:
                    break

                try:
                    audio_files = self._scan_folder_audio(folder)
                except Exception:
                    continue
                if not audio_files:
                    continue

                wav = random.choice(audio_files)
                folder_name = getattr(folder, "name", str(folder))
                print(f"📂 文件夹轮播：{folder_name} -> {os.path.basename(wav)}")
                self.push_random(wav)

                # 等当前播放完（关键词/报时会让 current_playing 一直 True，避免轮播抢跑）
                while self.current_playing and self.state.enabled and self.state.live_ready:
                    threading.Event().wait(0.3)

    # ===================== 入队接口（优先级策略） =====================

    def push_random(self, path: str):
        if not self.state.live_ready:
            return
        with self._lock:
            self.random_q.append(AudioCommand(name=PLAY_RANDOM, path=path))

    def push_anchor_keyword(self, path: str):
        """主播关键词（原 push_size）"""
        if not self.state.live_ready:
            return
        with self._lock:
            # 报时/关键词/助播 在播：不打断，只排队
            if self.current_playing and self.current_name in (PLAY_REPORT, PLAY_ANCHOR, PLAY_ZHULI):
                print("📌 主播关键词：当前是报时/关键词，改为排队 ->", os.path.basename(path))
                self.anchor_q.append(AudioCommand(name=PLAY_ANCHOR, path=path))
                return

            # 当前是低优先级（轮播/关注/点赞）：打断并记住恢复点
            if self.current_playing and self.current_name in (PLAY_RANDOM, PLAY_FOLLOW, PLAY_LIKE):
                if self.current_path:
                    if self.current_name == PLAY_RANDOM:
                        self.resume_after_high = self.current_path
                    elif self.current_name == PLAY_FOLLOW:
                        self.follow_q.appendleft(AudioCommand(name=PLAY_FOLLOW, path=self.current_path))
                    elif self.current_name == PLAY_LIKE:
                        self.like_q.appendleft(AudioCommand(name=PLAY_LIKE, path=self.current_path))
                print("📌 主播关键词（打断低优先级）->", os.path.basename(path))
                self.stop_now()
                self.random_q.clear()
                self.anchor_q.append(AudioCommand(name=PLAY_ANCHOR, path=path))
                return

            # 空闲：直接播
            print("📌 主播关键词（空闲直接播）->", os.path.basename(path))
            self.anchor_q.append(AudioCommand(name=PLAY_ANCHOR, path=path))

    def push_zhuli_keyword(self, path: str):
        """助播关键词"""
        if not self.state.live_ready:
            return
        with self._lock:
            if self.current_playing and self.current_name in (PLAY_REPORT, PLAY_ANCHOR, PLAY_ZHULI):
                print("📌 助播关键词：当前是报时/关键词，改为排队 ->", os.path.basename(path))
                self.zhuli_q.append(AudioCommand(name=PLAY_ZHULI, path=path))
                return

            if self.current_playing and self.current_name in (PLAY_RANDOM, PLAY_FOLLOW, PLAY_LIKE):
                if self.current_path:
                    self.resume_after_high = self.current_path
                print("📌 助播关键词（打断轮播）->", os.path.basename(path))
                self.stop_now()
                self.random_q.clear()
                self.zhuli_q.append(AudioCommand(name=PLAY_ZHULI, path=path))
                return

            print("📌 助播关键词（空闲直接播）->", os.path.basename(path))
            self.zhuli_q.append(AudioCommand(name=PLAY_ZHULI, path=path))

    def push_report(self, report_path: str):
        """报时插播（最高优先级）：打断轮播/关键词/助播，并恢复被打断的关键词/助播。"""
        if not self.state.live_ready:
            return

        with self._lock:
            # 1) 如果当前在播：先把“被打断的那条”放回队列最前（保证报时后能接着播）
            if self.current_playing and self.current_path and self.current_name:
                # 被打断的是主播关键词：回到主播队列最前
                if self.current_name == PLAY_ANCHOR:
                    self.anchor_q.appendleft(AudioCommand(name=PLAY_ANCHOR, path=self.current_path))
                    print("↩️ 关键词被报时打断，已回队列最前 ->", os.path.basename(self.current_path))

                # 被打断的是助播关键词：回到助播队列最前
                elif self.current_name == PLAY_ZHULI:
                    self.zhuli_q.appendleft(AudioCommand(name=PLAY_ZHULI, path=self.current_path))
                    print("↩️ 助播关键词被报时打断，已回队列最前 ->", os.path.basename(self.current_path))

                # 被打断的是轮播：记录恢复点（你原来的逻辑）
                elif self.current_name == PLAY_RANDOM:
                    self.resume_after_high = self.current_path

            # 2) 打断一切（轮播/关键词/助播）
            if self.current_playing and self.current_name in (PLAY_RANDOM, PLAY_ANCHOR, PLAY_ZHULI, PLAY_FOLLOW,
                                                              PLAY_LIKE):
                print("🕒 报时插播（打断一切）->", os.path.basename(report_path))
                self.stop_now()
                self.random_q.clear()

            # 3) 报时置顶（永远最先播）
            self.report_q.appendleft(AudioCommand(name=PLAY_REPORT, path=report_path))

    # ===================== 插播 / 急插 =====================

    def push_insert(self, path: str):
        """插播：不打断当前音频，等“当前音频播放完”后立即播放插播音频（优先于关键词/轮播）。"""
        if not self.state.live_ready:
            return
        if not path:
            return
        with self._lock:
            # 插播永远放队列最前，确保“下一条就是它”
            self.insert_q.appendleft(AudioCommand(name=PLAY_INSERT, path=path))
            print("📌 已加入插播队列（播完当前就播）->", os.path.basename(path))

    def push_urgent(self, path: str, clear_random: bool = True):
        """急插：立即停止当前播放（如果有）并尽快播放急插音频。"""
        if not self.state.live_ready:
            return
        if not path:
            return
        with self._lock:
            # 急插会打断当前，但不把被打断的音频放回队列（“停止所有播放当前音频”）
            if self.current_playing:
                print("🚨 急插：停止当前并准备播放 ->", os.path.basename(path))
                # 轮播就别恢复了
                self.resume_after_high = None
                # 视情况清掉轮播队列，避免插完又抢跑
                if clear_random:
                    self.random_q.clear()
                self.stop_now()
            else:
                print("🚨 急插：空闲直接播放 ->", os.path.basename(path))

            self.urgent_q.appendleft(AudioCommand(name=PLAY_URGENT, path=path))

    def start_recording_urgent(self) -> str | None:
        """开始录音（录音结束后可 stop_recording_urgent 触发急插）。返回录音文件路径。"""
        if not self.state.live_ready:
            return None
        with self._rec_lock:
            if self._rec_running:
                return self._rec_path

            # 保存到 app 目录下 recordings/，便于复用
            try:
                from config import get_app_dir
                base = pathlib.Path(get_app_dir())
            except Exception:
                base = pathlib.Path(os.getcwd())
            rec_dir = (base / "recordings")
            try:
                rec_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

            ts = time.strftime("%Y%m%d_%H%M%S")
            out_path = str(rec_dir / f"record_{ts}.wav")

            try:
                import soundfile as sf
                self._rec_sf = sf.SoundFile(
                    out_path,
                    mode="w",
                    samplerate=int(self._rec_samplerate),
                    channels=int(self._rec_channels),
                    subtype="PCM_16",
                )
            except Exception as e:
                print("❌ 录音初始化失败：", e)
                self._rec_sf = None
                return None

            def _cb(indata, frames, time_info, status):
                if status:
                    # 不要刷屏太多，只打印一次也行；这里保持简单
                    pass
                with self._rec_lock:
                    if not self._rec_running or self._rec_sf is None:
                        return
                    # ===== 音量 & 波形缓存（给 UI 用）=====
                    try:
                        import numpy as _np
                        arr = indata
                        # 转 mono
                        if hasattr(arr, 'ndim') and arr.ndim > 1:
                            mono = _np.mean(arr, axis=1)
                        else:
                            mono = arr.reshape(-1)
                        mono = _np.asarray(mono, dtype=_np.float32)
                        # RMS 音量（0~1 大致）
                        rms = float(_np.sqrt(_np.mean(mono * mono)) + 1e-9)
                        # 归一化（人声 RMS 通常 0.02~0.2）
                        lvl = max(0.0, min(1.0, rms * 6.0))
                        self._rec_level = lvl
                        # 波形缓存：限幅并追加（降采样，限长）
                        mono = _np.clip(mono, -1.0, 1.0)
                        if mono.size > 1024:
                            step = int(mono.size / 1024) or 1
                            mono = mono[::step]
                        for v in mono.tolist():
                            self._rec_wave.append(float(v))
                        overflow = len(self._rec_wave) - int(self._rec_wave_max)
                        if overflow > 0:
                            for _ in range(overflow):
                                self._rec_wave.popleft()
                    except Exception:
                        pass
                    try:
                        self._rec_sf.write(indata.copy())
                    except Exception:
                        pass

            try:
                self._rec_stream = sd.InputStream(
                    samplerate=int(self._rec_samplerate),
                    channels=int(self._rec_channels),
                    callback=_cb,
                )
                self._rec_stream.start()
            except Exception as e:
                print("❌ 打开录音设备失败：", e)
                try:
                    if self._rec_sf:
                        self._rec_sf.close()
                except Exception:
                    pass
                self._rec_sf = None
                self._rec_stream = None
                return None

            self._rec_path = out_path
            self._rec_running = True
            print("🎙️ 开始录音（录音急插）->", os.path.basename(out_path))
            return out_path

    def stop_recording_urgent(self) -> str | None:
        """停止录音，并把录音作为【急插音频】立刻插播。返回录音文件路径。"""
        with self._rec_lock:
            if not self._rec_running:
                return None
            self._rec_running = False

            try:
                if self._rec_stream:
                    self._rec_stream.stop()
                    self._rec_stream.close()
            except Exception:
                pass
            self._rec_stream = None

            try:
                if self._rec_sf:
                    self._rec_sf.flush()
                    self._rec_sf.close()
            except Exception:
                pass
            self._rec_sf = None

            out = self._rec_path
            self._rec_path = None

        if out:
            # 录音完：直接极速急插
            self.push_urgent(out, clear_random=True)
            print("🎙️ 录音已结束，已急插播放 ->", os.path.basename(out))
        return out

    def get_record_level(self) -> float:
        """返回最近一次录音输入音量（0~1）。"""
        try:
            with self._rec_lock:
                return float(getattr(self, "_rec_level", 0.0) or 0.0)
        except Exception:
            return 0.0

    def get_record_waveform(self, max_samples: int = 2048):
        """返回最近一段录音波形（list[float], -1~1）。用于抖音风波形 UI。"""
        try:
            max_samples = int(max_samples or 0) or 2048
        except Exception:
            max_samples = 2048

        try:
            with self._rec_lock:
                buf = list(self._rec_wave)
        except Exception:
            buf = []

        if not buf:
            return []
        if len(buf) <= max_samples:
            return buf
        return buf[-max_samples:]

    # 兼容 voice_reporter 旧调用
    def push_report_resume(self, report_path: str):
        # 兼容 voice_reporter 旧调用
        return self.push_report(report_path)

    def clear_all(self):
        with self._lock:
            self.report_q.clear()
            self.anchor_q.clear()
            self.zhuli_q.clear()
            self.follow_q.clear()
            self.like_q.clear()
            self.random_q.clear()
            self.insert_q.clear()
            self.urgent_q.clear()

    # ===================== 关注 / 点赞事件音频 =====================

    def _other_audio_dirs(self):
        """
        返回 (follow_dir, like_dir, exts)。

        优先级：
          1) runtime_state.json（follow_audio_dir / like_audio_dir）
          2) state 运行态（self.state.follow_audio_dir / self.state.like_audio_dir）
          3) config 默认（other_gz_audio / other_dz_audio）
          4) 兜底：<app_dir>/other_audio/关注 与 <app_dir>/other_audio/点赞

        同时确保目录存在。
        """
        from pathlib import Path
        import os

        # ---------- exts ----------
        try:
            from config import SUPPORTED_AUDIO_EXTS
            exts = tuple(str(e).lower() for e in SUPPORTED_AUDIO_EXTS)
        except Exception:
            exts = (".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg")

        # ---------- base dir fallback ----------
        try:
            from config import get_app_dir
            base = Path(get_app_dir())
        except Exception:
            base = Path(os.getcwd())

        # ---------- config defaults ----------
        cfg_follow = None
        cfg_like = None
        try:
            # 你 config 里定义的默认目录（Path）
            from config import other_gz_audio, other_dz_audio
            cfg_follow = Path(other_gz_audio)
            cfg_like = Path(other_dz_audio)
        except Exception:
            cfg_follow = base / "other_audio" / "关注"
            cfg_like = base / "other_audio" / "点赞"

        # ---------- runtime_state (highest priority) ----------
        rt_follow = ""
        rt_like = ""
        try:
            from core.runtime_state import load_runtime_state
            rt = load_runtime_state() or {}
            rt_follow = str(rt.get("follow_audio_dir", "") or "").strip()
            rt_like = str(rt.get("like_audio_dir", "") or "").strip()
        except Exception:
            pass

        # ---------- state override (second priority) ----------
        st_follow = str(getattr(self.state, "follow_audio_dir", "") or "").strip()
        st_like = str(getattr(self.state, "like_audio_dir", "") or "").strip()

        # ---------- choose final ----------
        def _pick_dir(rt_val: str, st_val: str, cfg_val: Path) -> Path:
            if rt_val:
                return Path(rt_val).expanduser().resolve()
            if st_val:
                return Path(st_val).expanduser().resolve()
            return Path(cfg_val).expanduser().resolve()

        follow_dir = _pick_dir(rt_follow, st_follow, cfg_follow)
        like_dir = _pick_dir(rt_like, st_like, cfg_like)

        # ---------- ensure exists ----------
        try:
            follow_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        try:
            like_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return follow_dir, like_dir, exts

    def _pick_random_audio_in_dir(self, folder) -> str | None:
        """从指定目录递归随机挑一条音频。"""
        from pathlib import Path
        if not folder:
            return None
        try:
            p = folder if hasattr(folder, "rglob") else Path(str(folder)).expanduser().resolve()
        except Exception:
            return None
        if not p.exists() or (not p.is_dir()):
            return None

        # 复用全局支持后缀
        try:
            _, _, exts = self._other_audio_dirs()
        except Exception:
            exts = (".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg")

        cands: list[str] = []
        try:
            for f in p.rglob("*"):
                if f.is_file() and f.suffix.lower() in exts:
                    cands.append(str(f))
        except Exception:
            return None
        if not cands:
            return None
        return random.choice(cands)

    def push_follow_event(self, wav_path: str | None = None):
        if not self.state.live_ready:
            return

        from pathlib import Path

        def _is_under(p: Path, base: Path) -> bool:
            try:
                p.relative_to(base)
                return True
            except Exception:
                return False

        with self._lock:
            follow_dir, _, _ = self._other_audio_dirs()

            # ✅ 如果外部传进来的 wav_path 不属于“当前关注目录”，就丢弃，改用新目录重选
            if wav_path:
                try:
                    p = Path(str(wav_path)).expanduser()
                    p = p.resolve() if p.is_absolute() else (Path.cwd() / p).resolve()
                    base = Path(str(follow_dir)).expanduser().resolve()
                    if (not p.exists()) or (base and (not _is_under(p, base))):
                        # 这里可选：打个日志，方便你确认“确实有人传了旧路径进来”
                        print(f"⚠️ 关注传入旧路径已丢弃 -> {p} (当前关注目录: {base})")
                        wav_path = None

                except Exception:
                    wav_path = None

            if not wav_path:
                wav_path = self._pick_random_audio_in_dir(follow_dir)

            if not wav_path:
                return

            print("⭐ 关注音频排队 ->", os.path.basename(wav_path))
            self.follow_q.append(AudioCommand(name=PLAY_FOLLOW, path=wav_path))

    def push_like_event(self, wav_path: str | None = None):
        if not self.state.live_ready:
            return

        from pathlib import Path

        def _is_under(p: Path, base: Path) -> bool:
            try:
                p.relative_to(base)
                return True
            except Exception:
                return False

        with self._lock:
            _, like_dir, _ = self._other_audio_dirs()

            # ✅ 如果外部传进来的 wav_path 不属于“当前点赞目录”，就丢弃，改用新目录重选
            if wav_path:
                try:
                    p = Path(str(wav_path)).expanduser()
                    p = p.resolve() if p.is_absolute() else (Path.cwd() / p).resolve()
                    base = Path(str(like_dir)).expanduser().resolve()
                    if (not p.exists()) or (base and (not _is_under(p, base))):
                        print(f"⚠️ 点赞传入旧路径已丢弃 -> {p} (当前点赞目录: {base})")
                        wav_path = None
                except Exception:
                    wav_path = None
            if not wav_path:
                wav_path = self._pick_random_audio_in_dir(like_dir)
            if not wav_path:
                return

            print("👍 点赞音频排队 ->", os.path.basename(wav_path))
            self.like_q.append(AudioCommand(name=PLAY_LIKE, path=wav_path))

    # ===================== 助播：根据“主播正在播放的音频文件名”触发（文件夹随机音频） =====================

    def _zhuli_dir_and_exts(self):
        """返回 (zhuli_audio_dir, supported_exts)。"""
        from pathlib import Path
        try:
            from config import ZHULI_AUDIO_DIR, SUPPORTED_AUDIO_EXTS
            default_dir = Path(ZHULI_AUDIO_DIR)
            exts = tuple(SUPPORTED_AUDIO_EXTS)
        except Exception:
            default_dir = Path.cwd() / "zhuli_audio"
            exts = (".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg")

        d = getattr(self.state, "zhuli_audio_dir", "") or str(default_dir)
        base = Path(d).expanduser().resolve()
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return base, tuple(str(e).lower() for e in exts)

    def _pick_zhuli_audio_from_category_folder(self, category: str) -> str | None:
        """从「助播目录/<category>/」中随机挑一条音频（递归包含子目录）。"""
        category = str(category or "").strip()
        if not category:
            return None

        base, exts = self._zhuli_dir_and_exts()
        folder = (base / category).expanduser().resolve()
        if not folder.exists() or not folder.is_dir():
            return None

        cands: list[str] = []
        try:
            # 递归：允许 category 下再分子目录
            for p in folder.rglob("*"):
                if p.is_file() and p.suffix.lower() in exts:
                    cands.append(str(p))
        except Exception:
            return None

        if not cands:
            return None
        return random.choice(cands)

    def _match_zhuli_category_by_anchor_stem(self, anchor_stem: str) -> str | None:
        """从 zhuli_keywords 中查找：如果某条规则的 must 列表里【精准命中】anchor_stem，则返回该规则 prefix(=分类/文件夹名)。"""
        anchor_stem = str(anchor_stem or "").strip()
        if not anchor_stem:
            return None

        try:
            from core.zhuli_keyword_io import load_zhuli_keywords
            data = load_zhuli_keywords() or {}
        except Exception:
            data = {}

        if not isinstance(data, dict) or not data:
            return None

        def _norm(x: str) -> str:
            x = str(x or "").strip()
            # 允许用户填入 xxx.mp3 / xxx.wav
            x = os.path.splitext(x)[0]
            return x

        target = _norm(anchor_stem)

        # 不再有“意图词/排除词/优先模式”，这里只看 must 的精准匹配
        for k in list(data.keys()):
            cfg = data.get(k)
            if not isinstance(cfg, dict):
                continue
            category = str(cfg.get("prefix") or k or "").strip()
            if not category:
                continue
            must = cfg.get("must", []) or []
            for w in must:
                kw = _norm(w)
                if not kw:
                    continue

                # ✅ 包含匹配：主播音频名包含关键词即可触发
                # 例：target="测试语音2" kw="测试语音" -> 命中
                if kw in target or target in kw:
                    return category

        return None

    def _enqueue_zhuli_for_anchor_finished(self, anchor_path: str):
        """主播音频播放完毕后：如果命中助播规则，则从对应分类文件夹随机挑一条助播音频插队播放。"""
        if not bool(getattr(self.state, "enable_zhuli", True)):
            return
        if not anchor_path:
            return

        stem = os.path.splitext(os.path.basename(anchor_path))[0].strip()
        if not stem:
            return

        category = self._match_zhuli_category_by_anchor_stem(stem)
        if not category:
            return

        wav = self._pick_zhuli_audio_from_category_folder(category)
        if not wav:
            return

        with self._lock:
            print(f"🎤 助播触发：主播音频「{stem}」命中 -> 分类「{category}」随机：{os.path.basename(wav)}")
            self.zhuli_q.appendleft(AudioCommand(name=PLAY_ZHULI, path=wav))

    # ===================== 播放调度主循环 =====================

    def _pick_next_high(self) -> Optional[AudioCommand]:
        """固定优先级：报时 > 主播关键词 > 助播（助播通常由主播音频结束后自动插队）。"""
        if self.anchor_q:
            return self.anchor_q.popleft()
        if self.zhuli_q:
            return self.zhuli_q.popleft()
        return None

    def process_once(self):
        """主线程/定时器循环调用：从队列取一条音频并播放。"""
        if not self.state.enabled or not self.state.live_ready:
            return
        if getattr(self, 'paused', False):
            return
        if self.current_playing:
            return

        with self._lock:
            cmd: Optional[AudioCommand] = None

            # 1) 报时最高（会打断一切）
            if self.report_q:
                cmd = self.report_q.popleft()
            # 2) 急插：仅次于报时（会打断一切）
            elif self.urgent_q:
                cmd = self.urgent_q.popleft()
            # 3) 插播：播完当前就播（不打断当前，但优先于关键词/轮播）
            elif self.insert_q:
                cmd = self.insert_q.popleft()
            else:
                # 4) 主播关键词 > 助播
                cmd = self._pick_next_high()

                # 5) 关注/点赞（低于主播/助播，高于轮播）
                if cmd is None:
                    if self.follow_q:
                        cmd = self.follow_q.popleft()
                    elif self.like_q:
                        cmd = self.like_q.popleft()

            # 3) 高优先级都空了：如果有被打断的轮播，先恢复它
            if cmd is None:
                if self.resume_after_high:
                    self.random_q.appendleft(AudioCommand(name=PLAY_RANDOM, path=self.resume_after_high))
                    self.resume_after_high = None
                if self.random_q:
                    cmd = self.random_q.popleft()

            if cmd is None:
                return

            self.current_playing = True
            self.current_name = cmd.name
            self.current_path = cmd.path

        try:
            tmp_to_cleanup = None
            play_path = cmd.path

            # ✅ 变量调节：对 主播/助播/轮播 生效（按开关决定）
            if cmd.name in (PLAY_ANCHOR, PLAY_ZHULI, PLAY_FOLLOW, PLAY_LIKE, PLAY_RANDOM, PLAY_INSERT, PLAY_URGENT,
                            PLAY_RECORD):
                if cmd.name == PLAY_RANDOM:
                    should_apply = True  # 轮播也处理
                else:
                    apply_anchor = bool(getattr(self.state, "var_apply_anchor", True))
                    apply_zhuli = bool(getattr(self.state, "var_apply_zhuli", True))
                    # 插播/急插默认按“主播”处理（你也可以按需改成单独开关）
                    if cmd.name in (PLAY_INSERT, PLAY_URGENT, PLAY_RECORD):
                        should_apply = apply_anchor
                    else:
                        should_apply = (
                                (cmd.name == PLAY_ANCHOR and apply_anchor)
                                or (cmd.name == PLAY_ZHULI and apply_zhuli)
                                or (cmd.name in (PLAY_FOLLOW, PLAY_LIKE) and apply_anchor)
                        )

                if should_apply:
                    play_path, tmp_to_cleanup = self._prepare_processed_audio(cmd.path)

            if cmd.name == PLAY_REPORT:
                self.stop_event.clear()
                print("🕒 播放整点报时：", cmd.path)
                play_audio_and_wait(cmd.path)

            elif cmd.name in (PLAY_URGENT, PLAY_RECORD):
                self.stop_event.clear()
                print("🚨 播放急插音频：", play_path)
                play_audio_and_wait(play_path)

            elif cmd.name == PLAY_INSERT:
                self.stop_event.clear()
                print("📌 播放插播音频：", play_path)
                play_audio_and_wait(play_path)

            elif cmd.name in (PLAY_ANCHOR, PLAY_ZHULI):
                self.stop_event.clear()
                tag = "主播关键词" if cmd.name == PLAY_ANCHOR else "助播关键词"
                print(f"🎯 播放{tag}插播：", play_path)
                play_audio_and_wait(play_path)

                # ✅ 新逻辑：主播音频文件名精准命中 must => 主播播完后插播助播（不再区分 A/B 优先模式）
                if cmd.name == PLAY_ANCHOR and (not self.stop_event.is_set()):
                    self._enqueue_zhuli_for_anchor_finished(cmd.path)

            elif cmd.name in (PLAY_FOLLOW, PLAY_LIKE):
                self.stop_event.clear()
                tag = "关注" if cmd.name == PLAY_FOLLOW else "点赞"
                print(f"✨ 播放{tag}事件音频：", play_path)
                play_audio_and_wait(play_path)

            elif cmd.name == PLAY_RANDOM:
                print("🎲 播放轮播音频：", play_path)
                self.stop_event.clear()
                play_audio_interruptible(play_path, self.stop_event)

                # ✅ 新逻辑：轮播音频播放完也允许按文件名触发助播
                # （例如：轮播播放 spk_1768978871.wav，必含词=spk_1768978871 即可触发）
                if not self.stop_event.is_set():
                    self._enqueue_zhuli_for_anchor_finished(cmd.path)

            # ✅ 清理临时文件
            if tmp_to_cleanup:
                try:
                    os.remove(tmp_to_cleanup)
                except Exception:
                    pass

            if cmd.on_finished:
                cmd.on_finished()

        finally:
            with self._lock:
                self.current_playing = False
                self.current_name = None
                self.current_path = None

    # ===================== 暂停 / 恢复 =====================

    def set_paused(self, paused: bool):
        """暂停/恢复播放（用于 UI 按钮）。

        ✅ 新逻辑（符合你说的“从暂停处继续”）：
        - 暂停：不再 stop/重播，不再回队列；直接把播放器置为 paused（当前位置冻结）
        - 恢复：继续从暂停的位置播放

        说明：暂停期间 process_once() 会直接 return，不会开启下一条。
        """
        paused = bool(paused)
        with self._lock:
            cur = bool(getattr(self, "paused", False))
            if cur == paused:
                return
            self.paused = paused

        try:
            _player_set_paused(paused)
        except Exception:
            pass

    def toggle_paused(self) -> bool:
        """切换暂停状态，返回切换后的 paused 值。"""
        new_val = (not bool(getattr(self, "paused", False)))
        self.set_paused(new_val)
        return bool(getattr(self, "paused", False))

    # ===================== 强制中断 =====================

    def stop_now(self):
        """强制中断当前播放（用于报时/急插）。"""
        print("⛔ 强制停止播放")
        self.stop_event.set()
        try:
            _player_stop()
        except Exception:
            pass
        try:
            sd.stop()
        except Exception:
            pass

def play_next(self):
    """跳过当前音频，立即播放队列中的下一条（不把当前音频回队列）。"""
    # 这个功能主要用于“在播状态下”点一下直接跳到下一条
    try:
        # 如果暂停中，先恢复（否则 stop_now 后可能还在 paused 状态）
        if bool(getattr(self, "paused", False)):
            self.set_paused(False)
    except Exception:
        pass

    # 如果当前播放的是轮播，跳过时不再恢复到同一条
    try:
        with self._lock:
            if bool(getattr(self, "current_playing", False)) and getattr(self, "current_name", None) == PLAY_RANDOM:
                self.resume_after_high = None
    except Exception:
        pass

    # 强制停止当前，调度循环会自然选下一条播放
    if bool(getattr(self, "current_playing", False)):
        print("⏭ 跳到下一条音频")
        self.stop_now()
    else:
        # 空闲时不用做任何事（下一条会由调度循环自然取队列）
        print("⏭ 当前未在播放，等待队列自动播放下一条")