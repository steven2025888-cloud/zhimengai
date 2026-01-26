# core/ws_command_router.py
import time
import datetime
import json
import os
import tempfile
import urllib.request
import subprocess
import shutil
import urllib.parse
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from audio.audio_picker import pick_by_prefix
from audio.voice_reporter import schedule_report_after

# ✅ 默认：5 分钟（可通过 state.follow_like_cooldown_seconds 或 runtime_state 配置覆盖）
DEFAULT_FOLLOW_LIKE_COOLDOWN_SECONDS = 300
RUNTIME_KEY_COOLDOWN_SECONDS = "follow_like_cooldown_seconds"


def _load_cooldown_seconds_from_runtime(default: int) -> int:
    """可选：从 core.runtime_state 读取冷却秒数（如果项目里有该模块）。"""
    try:
        from core.runtime_state import load_runtime_state  # type: ignore
        st = load_runtime_state() or {}
        v = st.get(RUNTIME_KEY_COOLDOWN_SECONDS, None)
        if v is None:
            return int(default)
        # 允许配置成分钟
        if isinstance(v, (int, float)):
            return int(v)
        v = str(v).strip()
        if not v:
            return int(default)
        if v.endswith("m") or v.endswith("min") or v.endswith("分钟"):
            # 例如 "5m" / "5min" / "5分钟"
            num = "".join(ch for ch in v if ch.isdigit())
            return int(num) * 60 if num else int(default)
        return int(float(v))
    except Exception:
        return int(default)


def _save_cooldown_seconds_to_runtime(seconds: int) -> None:
    """可选：保存到 core.runtime_state（如果项目里有该模块）。"""
    try:
        from core.runtime_state import load_runtime_state, save_runtime_state  # type: ignore
        st = load_runtime_state() or {}
        st[RUNTIME_KEY_COOLDOWN_SECONDS] = int(seconds)
        save_runtime_state(st)
    except Exception:
        pass


class WSCommandRouter:
    """处理 WS 的 type 指令。"""

    def __init__(self, state, dispatcher):
        self.state = state
        self.dispatcher = dispatcher

        # ---- 运行态默认字段（不改 core.state 也能跑）----
        if not hasattr(self.state, "last_follow_ts"):
            self.state.last_follow_ts = 0.0
        if not hasattr(self.state, "last_like_ts"):
            self.state.last_like_ts = 0.0

        # ✅ 两个开关：收到关注/点赞才播
        if not hasattr(self.state, "enable_follow_audio"):
            self.state.enable_follow_audio = False
        if not hasattr(self.state, "enable_like_audio"):
            self.state.enable_like_audio = False

        # ✅ 冷却：默认 5 分钟（可被 runtime_state 覆盖）
        if not hasattr(self.state, "follow_like_cooldown_seconds"):
            self.state.follow_like_cooldown_seconds = _load_cooldown_seconds_from_runtime(
                DEFAULT_FOLLOW_LIKE_COOLDOWN_SECONDS
            )

        # ===== 指令映射表 =====
        self.command_map = {
            # ⭐ -2：关注事件（抖音/视频号都可用这个）
            -2: self._cmd_follow,
            # 👍 -3：点赞事件（抖音/视频号都可用这个）
            -3: self._cmd_like,

            10001: self._cmd_play_on,
            10002: self._cmd_play_off,

            # 10003：2分钟后报时（一次性插播）
            10003: self._cmd_report_after_2min,
            # 10004：烟实验
            10004: lambda: self._cmd_play_prefix("烟实验"),

            # 10005：下一条（跳过当前，立即播放下一条）
            10005: self._cmd_play_next,

            # 20010：手机端请求当前状态
            20010: self._cmd_status_req,
        }

    # ---------------- public ----------------

    def handle(self, type_: int):
        handler = self.command_map.get(type_)
        if handler:
            print(f"🎮 WS指令触发：{type_}")
            handler()
            return

        # 自动兜底：1000X → 前缀
        if 10000 < type_ < 10100:
            prefix = f"{type_ - 10000}"
            self._cmd_play_prefix(prefix)

    def handle_message(self, data: dict):
        if not isinstance(data, dict):
            return
        type_raw = data.get("type")
        if type_raw in ("ping", "pong", None, ""):
            return
        try:
            type_ = int(type_raw)
        except (TypeError, ValueError):
            return

        # 录音急插：需要 url
        if type_ == 30001:
            self._cmd_record_urgent(data)
            return

        # 其它仍走旧逻辑
        self.handle(type_)

    # ---------------- follow/like core ----------------

    def set_follow_like_cooldown_seconds(self, seconds: int, persist: bool = True):
        """给 UI 调用：设置关注/点赞冷却间隔（秒）。"""
        seconds = max(1, int(seconds))
        self.state.follow_like_cooldown_seconds = seconds
        if persist:
            _save_cooldown_seconds_to_runtime(seconds)
        print(f"✅ 已设置关注/点赞冷却：{seconds} 秒")

    def _cooldown_seconds(self) -> int:
        try:
            return int(getattr(self.state, "follow_like_cooldown_seconds", DEFAULT_FOLLOW_LIKE_COOLDOWN_SECONDS))
        except Exception:
            return DEFAULT_FOLLOW_LIKE_COOLDOWN_SECONDS

    def _cmd_follow(self):
        """WS: type = -2 → 关注事件（冷却 + 开关 + 入队给调度器）。"""
        if not bool(getattr(self.state, "enable_follow_audio", False)):
            print("🔕 关注音频开关关闭，忽略本次关注")
            return

        now = time.time()
        cd = self._cooldown_seconds()

        if now - float(getattr(self.state, "last_follow_ts", 0.0) or 0.0) < cd:
            print(f"⏳ 关注在冷却期内（{cd}s），忽略本次")
            return

        self.state.last_follow_ts = now

        # ✅ 直接交给 dispatcher：它自己会从 other_audio/关注 随机挑一个，并按优先级排队/打断
        if hasattr(self.dispatcher, "push_follow_event"):
            self.dispatcher.push_follow_event()
            print("⭐ 已触发：关注音频入队")
        else:
            print("⚠️ dispatcher 缺少 push_follow_event()，请更新 audio_dispatcher.py")

    def _cmd_like(self):
        """WS: type = -3 → 点赞事件（冷却 + 开关 + 入队给调度器）。"""
        if not bool(getattr(self.state, "enable_like_audio", False)):
            print("🔕 点赞音频开关关闭，忽略本次点赞")
            return

        now = time.time()
        cd = self._cooldown_seconds()

        if now - float(getattr(self.state, "last_like_ts", 0.0) or 0.0) < cd:
            print(f"⏳ 点赞在冷却期内（{cd}s），忽略本次")
            return

        self.state.last_like_ts = now

        if hasattr(self.dispatcher, "push_like_event"):
            self.dispatcher.push_like_event()
            print("👍 已触发：点赞音频入队")
        else:
            print("⚠️ dispatcher 缺少 push_like_event()，请更新 audio_dispatcher.py")

    # ---------------- other commands ----------------

    def _cmd_play_on(self):
        print("▶️ 播放/继续（不跳下一条）")
        # ✅ 不再改 state.enabled；由调度器 paused 控制暂停/继续
        try:
            if hasattr(self.dispatcher, "set_paused"):
                self.dispatcher.set_paused(False)
            elif hasattr(self.dispatcher, "toggle_paused") and bool(getattr(self.dispatcher, "paused", False)) is True:
                self.dispatcher.toggle_paused()
        except Exception:
            pass
        self._push_status()

    def _cmd_play_off(self):
        print("⏸️ 暂停（保持当前位置，恢复后继续播放）")
        # ✅ 不再 clear_all/stop_now，否则恢复会跳下一条
        try:
            if hasattr(self.dispatcher, "set_paused"):
                self.dispatcher.set_paused(True)
            elif hasattr(self.dispatcher, "toggle_paused") and bool(getattr(self.dispatcher, "paused", False)) is False:
                self.dispatcher.toggle_paused()
        except Exception:
            pass
        self._push_status()

    def _cmd_play_prefix(self, prefix: str):
        print(f"🎯 播放前缀音频：{prefix}*")
        wav = pick_by_prefix(prefix)
        self.dispatcher.push_priority(wav)

    def _cmd_report_after_2min(self):
        """WS:10003 → 2分钟后报时（一次性插播，不影响循环报时）"""
        print("⏰ WS触发：2分钟后报时（定时插播）")
        schedule_report_after(minutes=2, state=self.state, dispatcher=self.dispatcher)

    # ---------------- status / next ----------------

    # ---------------- record urgent (mobile upload -> pc play) ----------------
    def _cmd_record_urgent(self, data: dict):
        """手机端录音急插（type=30001）：data.url -> 下载本地 -> dispatcher.push_urgent() 播放"""
        url = ""
        try:
            url = str((data or {}).get("url") or "").strip()
            print("录音url" + url)
        except Exception:
            url = ""
        if not url:
            print("⚠️ 录音急插缺少 url")
            return

        # 仅允许 http/https
        try:
            u = urlparse(url)
        except Exception:
            print("⚠️ 录音急插 url 解析失败：", url)
            return
        if u.scheme not in ("http", "https"):
            print("⚠️ 录音急插仅支持 http/https：", url)
            return

        # ✅ 从 URL 推断扩展名：
        # 1) 先看 query 里的 file=xxx.wav（我们的签名下载接口就是这样）
        # 2) 再看 path 的扩展名
        ext = ""
        try:
            qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            qfile = (qs.get("file", [""])[0] or "").strip()
            if qfile:
                ext = os.path.splitext(qfile)[1].lower()
        except Exception:
            ext = ""

        if not ext:
            ext = os.path.splitext(u.path or "")[1].lower()

        # 允许的格式（和后端允许一致即可）
        if ext not in (".wav", ".mp3", ".aac", ".m4a", ".ogg", ".flac", ".webm", ".opus"):
            # 没扩展名就先用 .wav（后面会用文件头再纠正一次）
            ext = ".wav"

        # 保存目录：优先 app_dir/recordings，其次系统 temp
        save_dir = None
        try:
            from config import get_app_dir  # type: ignore
            base = get_app_dir()
            if base:
                save_dir = os.path.join(str(base), "recordings")
        except Exception:
            save_dir = None
        if not save_dir:
            save_dir = os.path.join(tempfile.gettempdir(), "zhimo_recordings")

        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception:
            pass

        ts = time.strftime("%Y%m%d_%H%M%S")
        local_path = os.path.join(save_dir, f"mobile_record_{ts}{ext}")

        # 下载（限制大小避免被投喂）
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ZhimoAI/1.0 (record-urgent)"})
            with urllib.request.urlopen(req, timeout=15) as resp, open(local_path, "wb") as f:
                max_bytes = 25 * 1024 * 1024
                total = 0
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise RuntimeError("文件过大（>25MB）")
                    f.write(chunk)
        except Exception as e:
            print("❌ 录音急插下载失败：", e)
            try:
                if os.path.exists(local_path):
                    os.remove(local_path)
            except Exception:
                pass
            return

        # ✅ 文件头探测：避免「URL 无扩展名导致保存成 .wav，但内容其实是 mp3/m4a/webm」从而播放器解码失败
        try:
            with open(local_path, "rb") as f:
                head = f.read(64)

            # ✅ 如果下载到的是错误文本/HTML（例如 403/404 页面），直接退出，避免送给播放器
            try:
                head_text = head[:32].decode("utf-8", "ignore").lower()
                if ("forbidden" in head_text) or ("expired" in head_text) or ("<html" in head_text) or ("not found" in head_text):
                    print("❌ 录音急插下载内容疑似错误页：", head_text.strip())
                    try:
                        os.remove(local_path)
                    except Exception:
                        pass
                    return
            except Exception:
                pass

            # 后续仅需前 16 字节判断格式
            head = head[:16]
            real_ext = None
            if head.startswith(b"RIFF") and b"WAVE" in head:
                real_ext = ".wav"
            elif head.startswith(b"ID3") or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
                # 可能是 MP3 或 AAC(ADTS)。先按 ADTS 特征判断。
                if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xF6) == 0xF0:
                    real_ext = ".aac"
                else:
                    real_ext = ".mp3"
            elif head.startswith(b"\x1A\x45\xDF\xA3"):
                real_ext = ".webm"  # Matroska/WebM
            elif len(head) >= 8 and head[4:8] == b"ftyp":
                real_ext = ".m4a"  # MP4/M4A/AAC 容器（粗略）
            if real_ext and not local_path.lower().endswith(real_ext):
                new_path = os.path.splitext(local_path)[0] + real_ext
                try:
                    os.replace(local_path, new_path)
                    local_path = new_path
                    print("ℹ️ 录音文件扩展名已纠正为：", real_ext)
                except Exception:
                    pass
        except Exception:
            pass

        # ✅ 转码：soundfile/libsndfile 对 mp3/aac/m4a/webm 等支持不稳定（很多情况下直接报 Format not recognised）
        # 所以这里统一把「非 wav/flac/ogg」或「看起来不像 wav」的文件转成 PCM WAV，再交给播放器。
        def _needs_transcode(p: str) -> bool:
            # ✅ 统一转码：即便扩展名是 .wav，也可能是 ADPCM/AAC 等 libsndfile 不支持的编码
            # 录音急插一般很短，转码成本可接受，能最大化兼容性。
            return True

        def _ffmpeg_bin() -> str:
            return shutil.which("ffmpeg") or "ffmpeg"

        def _run_ffmpeg(cmd: list[str]) -> bool:
            try:
                kw = {}
                if os.name == "nt":
                    # CREATE_NO_WINDOW
                    kw["creationflags"] = 0x08000000
                p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)
                if p.returncode != 0:
                    # 打印一小段 stderr 方便定位
                    err = (p.stderr or b"")[:500].decode("utf-8", "ignore")
                    print("🎧 ffmpeg 转码失败：", err)
                    return False
                return True
            except Exception as e:
                print("🎧 ffmpeg 调用异常：", e)
                return False

        if _needs_transcode(local_path):
            wav_out = os.path.splitext(local_path)[0] + "_pcm.wav"
            cmd = [
                _ffmpeg_bin(),
                "-y",
                "-i", local_path,
                "-ac", "1",
                "-c:a", "pcm_s16le",
                wav_out,
            ]
            if _run_ffmpeg(cmd) and os.path.exists(wav_out):
                local_path = wav_out
                print("🎧 已转码为 wav：", os.path.basename(local_path))

        # 播放（急插优先）
        try:
            if hasattr(self.dispatcher, "set_paused"):
                try:
                    self.dispatcher.set_paused(False)
                except Exception:
                    pass

            if hasattr(self.dispatcher, "push_urgent"):
                self.dispatcher.push_urgent(local_path)
            elif hasattr(self.dispatcher, "push_insert"):
                self.dispatcher.push_insert(local_path)
            else:
                print("⚠️ dispatcher 不支持 push_urgent/push_insert，无法播放录音")
                return

            print("✅ 录音已急插：", os.path.basename(local_path))
        except Exception as e:
            print("❌ 录音急插播放失败：", e)
            return

        # 推送状态同步手机
        try:
            self._push_status()
        except Exception:
            pass

    def _push_status(self):
        """向同卡密广播当前播放状态（手机端用来同步 UI）。"""
        ws = getattr(self.state, "ws_client", None)
        if not ws or not hasattr(ws, "push"):
            return

        # ✅ 状态来源：以 state.enabled 为主；如果 dispatcher 暴露 paused，则以它为准（因为我们在 on/off 里同步了它）
        enabled = bool(getattr(self.state, "enabled", False))
        paused = (not enabled)
        if hasattr(self.dispatcher, "paused"):
            try:
                paused = bool(getattr(self.dispatcher, "paused"))
            except Exception:
                paused = (not enabled)

        status = {
            "enabled": bool(getattr(self.state, "enabled", True)),
            "paused": bool(getattr(self.dispatcher, "paused", False)),
            "current_playing": bool(getattr(self.dispatcher, "current_playing", False)),
            "current_name": getattr(self.dispatcher, "current_name", "") or "",
            "ts": int(time.time()),
        }
        try:
            ws.push("PC", json.dumps(status, ensure_ascii=False), 20011)
        except Exception as e:
            print("⚠️ 推送状态失败：", e)

    def _cmd_status_req(self):
        """手机端请求状态（type=20010）。"""
        print("📲 收到状态请求（20010）")
        self._push_status()

    def _cmd_play_next(self):
        """下一条（type=10005）。"""
        print("⏭ 下一条")
        # 优先调用 dispatcher.play_next()；否则调用 audio.audio_dispatcher.play_next(dispatcher)
        try:
            if hasattr(self.dispatcher, "play_next"):
                self.dispatcher.play_next()
            else:
                from audio.audio_dispatcher import play_next as _play_next_func
                _play_next_func(self.dispatcher)
        except Exception as e:
            print("⚠️ 下一条失败：", e)

