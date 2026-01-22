# audio/audio_dispatcher.py
import os
import random
import threading
from dataclasses import dataclass
from typing import Optional, Callable
from collections import deque

import sounddevice as sd

from core.state import AppState
from audio.audio_player import play_audio_interruptible, play_audio_and_wait
import time
import tempfile
import subprocess
import shutil



PLAY_REPORT = "PLAY_REPORT"
# 为了兼容你现有调用：主播关键词仍叫 PLAY_SIZE
PLAY_ANCHOR = "PLAY_SIZE"
PLAY_ZHULI = "PLAY_ZHULI"
PLAY_RANDOM = "PLAY_RANDOM"


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

        self.current_playing = False
        self.current_name: str | None = None
        self.current_path: str | None = None

        # stop_event：用于可中断播放（轮播一定用；关键词/报时靠 sd.stop 也能停）
        self.stop_event = threading.Event()

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
        self._cur_pitch_pct = 0      # percent, 例如 -5 ~ +5
        self._cur_speed_pct = 0      # percent, 例如 +0 ~ +10
        self._cur_volume_db = 0      # dB, 例如 +0 ~ +10

        # 为避免极端慢机卡顿：每段音频的平滑过渡拆成多少段（越大越平滑但越慢）
        self._var_ramp_steps = 5



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
            out = subprocess.check_output(
                [
                    self._ffprobe_bin(),
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    src_path,
                ],
                stderr=subprocess.STDOUT,
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
            subprocess.run(cmd, check=True)

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

        # 本段音频：从“上一段目标值”过渡到“本段目标值”
        pitch_start, speed_start, vol_start = self._cur_pitch_pct, self._cur_speed_pct, self._cur_volume_db
        pitch_t, speed_t, vol_t = self._pick_next_targets()

        # 过渡在本段音频内“随机完成”：
        #  - 可以在开头就完成（0%）
        #  - 也可以到结束才完成（100%）
        dur = self._get_duration_sec(src_path)
        if dur <= 0.05:
            # 拿不到时长，退化为“直接用目标值”
            pitch_start, speed_start, vol_start = pitch_t, speed_t, vol_t
            ramp_end = 0.0
        else:
            # 0 ~ 1 的随机，允许非常“突兀”的测试；
            # 正常使用你也可以改成 random.uniform(0.2, 1.0)
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

        # 1) 过渡段（拆 steps 段）
        if steps == 1:
            # 直接目标值
            cf = self._build_const_filter(pitch_t, speed_t, vol_t)
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
                p = int(round(_interp(pitch_start, pitch_t, tt)))
                sp = int(round(_interp(speed_start, speed_t, tt)))
                vb = int(round(_interp(vol_start, vol_t, tt)))
                cf = self._build_const_filter(p, sp, vb) or "anull"
                seg_filters.append(
                    f"[0:a]atrim=start={s:.6f}:end={e:.6f},asetpts=PTS-STARTPTS,{cf}[a{seg_idx}]"
                )
                seg_labels.append(f"[a{seg_idx}]")
                seg_idx += 1

            # 2) 过渡完成后的剩余段：用目标值
            if dur > ramp_end + 0.02:
                cf = self._build_const_filter(pitch_t, speed_t, vol_t) or "anull"
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
            subprocess.run(cmd, check=True)

            # 本段结束：把“目标值”作为下一段的起点
            self._cur_pitch_pct = int(pitch_t)
            self._cur_speed_pct = int(speed_t)
            self._cur_volume_db = int(vol_t)

            # 调试：显示本段从多少到多少
            print(
                f"🎛️ 变量调节：pitch {pitch_start}%→{pitch_t}%, speed {speed_start}%→{speed_t}%, volume {vol_start}dB→{vol_t}dB | ramp={ramp_end:.2f}s/{dur:.2f}s | src={os.path.basename(src_path)}"
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
            return bool(self.report_q or self.anchor_q or self.zhuli_q or self.random_q)

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

            # 当前是轮播：打断轮播并记住恢复点
            if self.current_playing and self.current_name == PLAY_RANDOM:
                if self.current_path:
                    self.resume_after_high = self.current_path
                print("📌 主播关键词（打断轮播）->", os.path.basename(path))
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

            if self.current_playing and self.current_name == PLAY_RANDOM:
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
            if self.current_playing and self.current_name in (PLAY_RANDOM, PLAY_ANCHOR, PLAY_ZHULI):
                print("🕒 报时插播（打断一切）->", os.path.basename(report_path))
                self.stop_now()
                self.random_q.clear()

            # 3) 报时置顶（永远最先播）
            self.report_q.appendleft(AudioCommand(name=PLAY_REPORT, path=report_path))

    # 兼容 voice_reporter 旧调用
    def push_report_resume(self, report_path: str):
        # 兼容 voice_reporter 旧调用
        return self.push_report(report_path)

    def clear_all(self):
        with self._lock:
            self.report_q.clear()
            self.anchor_q.clear()
            self.zhuli_q.clear()
            self.random_q.clear()

    # ===================== 播放调度主循环 =====================

    def _pick_next_high(self) -> Optional[AudioCommand]:
        """根据模式A/B 决定主播关键词与助播关键词的先后。"""
        mode = str(getattr(self.state, "zhuli_mode", "A") or "A").upper()

        if mode == "B":
            # 模式B：报时 > 助播关键词 > 主播关键词 > 轮播
            if self.zhuli_q:
                return self.zhuli_q.popleft()
            if self.anchor_q:
                return self.anchor_q.popleft()
            return None

        # 默认模式A：报时 > 主播关键词 > 助播关键词 > 轮播
        if self.anchor_q:
            return self.anchor_q.popleft()
        if self.zhuli_q:
            return self.zhuli_q.popleft()
        return None

    def process_once(self):

        if not self.state.enabled or not self.state.live_ready:
            return
        if self.current_playing:
            return

        with self._lock:
            cmd: Optional[AudioCommand] = None

            # 1) 报时最高
            if self.report_q:
                cmd = self.report_q.popleft()
            else:
                # 2) 主播/助播按模式优先
                cmd = self._pick_next_high()

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

            # ✅ 只对 主播/助播关键词 生效（并按“主播/助播”勾选决定是否应用）
            if cmd.name in (PLAY_ANCHOR, PLAY_ZHULI, PLAY_RANDOM):
                # 轮播是否也应用：先直接复用主播/助播开关，或者你加一个新开关 var_apply_random
                if cmd.name == PLAY_RANDOM:
                    should_apply = True  # 先强制轮播也处理
                else:
                    apply_anchor = bool(getattr(self.state, "var_apply_anchor", True))
                    apply_zhuli = bool(getattr(self.state, "var_apply_zhuli", True))
                    should_apply = (cmd.name == PLAY_ANCHOR and apply_anchor) or (
                                cmd.name == PLAY_ZHULI and apply_zhuli)

                if should_apply:
                    play_path, tmp_to_cleanup = self._prepare_processed_audio(cmd.path)

            if cmd.name == PLAY_REPORT:
                print("🕒 播放整点报时：", cmd.path)
                play_audio_and_wait(cmd.path)

            elif cmd.name in (PLAY_ANCHOR, PLAY_ZHULI):
                tag = "主播关键词" if cmd.name == PLAY_ANCHOR else "助播关键词"
                print(f"🎯 播放{tag}插播：", play_path)
                play_audio_and_wait(play_path)

            elif cmd.name == PLAY_RANDOM:
                print("🎲 播放轮播音频：", play_path)
                self.stop_event.clear()
                play_audio_interruptible(play_path, self.stop_event)

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

    # ===================== 强制中断 =====================

    def stop_now(self):
        """只发停止信号 + sd.stop()，不要把 current_playing 置 False。"""
        print("⛔ 强制停止播放")
        self.stop_event.set()
        try:
            sd.stop()
        except Exception:
            pass
