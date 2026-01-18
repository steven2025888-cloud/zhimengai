# core/ws_command_router.py
import datetime
from zoneinfo import ZoneInfo

from audio.audio_picker import pick_by_prefix

from audio.voice_reporter import schedule_report_after
import time

class WSCommandRouter:
    """
    处理 WS 的 type: 1000* 指令
    """

    def __init__(self, state, dispatcher):
        self.state = state
        self.dispatcher = dispatcher

        # ===== 1000* 指令映射表 =====
        self.command_map = {

            # ⭐ -2：模拟关注事件
            -2: self._cmd_follow,
            -3: self._cmd_like,  # 点赞

            10001: self._cmd_play_on,
            10002: self._cmd_play_off,

            # 10003：2分钟后报时（一次性插播）
            10003: self._cmd_report_after_2min,
            # 10004：烟实验
            10004: lambda: self._cmd_play_prefix("烟实验"),



        }

    def handle(self, type_: int):
        handler = self.command_map.get(type_)
        if handler:
            print(f"🎮 WS指令触发：{type_}")
            handler()
        else:
            # 自动兜底：1000X → 前缀
            if 10000 < type_ < 10100:
                prefix = f"{type_ - 10000}"
                self._cmd_play_prefix(prefix)

    def _cmd_follow(self):
        """
        WS: type = -2
        模拟一次“关注”事件：
        - 5分钟内只触发一次
        - 不打断当前随机讲解
        - 等随机播完后插播 关注*
        """
        now = time.time()

        # 5分钟冷却
        if now - self.state.last_follow_ts < 300:
            print("⏳ WS关注在冷却期内，忽略本次")
            return

        print("⭐ WS模拟关注：已加入待播队列（播完随机后插播）")
        self.state.last_follow_ts = now
        self.state.pending_follow = True

    def _cmd_like(self):
        """
        WS: type = -3
        模拟一次“点赞”事件：
        - 5分钟内只触发一次
        - 不打断当前随机讲解
        - 等随机播完后插播 点赞*
        """
        now = time.time()

        if now - self.state.last_like_ts < 300:
            print("⏳ WS点赞在冷却期内，忽略本次")
            return

        print("👍 WS模拟点赞：已加入待播队列（播完随机后插播）")
        self.state.last_like_ts = now
        self.state.pending_like = True

    # ===== 具体指令实现 =====

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
        """
        WS:10003 → 2分钟后报时（一次性插播，不影响5分钟循环报时）
        """
        print("⏰ WS触发：2分钟后报时（定时插播）")

        schedule_report_after(
            minutes=2,
            state=self.state,
            dispatcher=self.dispatcher,
        )


