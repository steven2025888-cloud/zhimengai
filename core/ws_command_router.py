# core/ws_command_router.py
import time
import datetime
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
        print("▶️ 开始播放（恢复随机讲解）")
        self.state.enabled = True

    def _cmd_play_off(self):
        print("⏸️ 暂停播放（停止所有音频）")
        self.state.enabled = False
        self.dispatcher.clear()
        self.dispatcher.stop_now()

    def _cmd_play_prefix(self, prefix: str):
        print(f"🎯 播放前缀音频：{prefix}*")
        wav = pick_by_prefix(prefix)
        self.dispatcher.push_priority(wav)

    def _cmd_report_after_2min(self):
        """WS:10003 → 2分钟后报时（一次性插播，不影响循环报时）"""
        print("⏰ WS触发：2分钟后报时（定时插播）")
        schedule_report_after(minutes=2, state=self.state, dispatcher=self.dispatcher)
