from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Set


class PlayMode(Enum):
    RANDOM = 1
    SIZE = 2


@dataclass
class AppState:
    # 是否在直播页
    is_listening: bool = False
    live_ready: bool = False  # ⭐ 是否已成功接收到真实弹幕（语音系统总开关）

    # 是否允许播放（WS 10001 / 10002 控制）
    enabled: bool = True

    # 去重用的 seq 集合（兼容旧逻辑）
    seen_seq: Set[str] = field(default_factory=set)

    # 当前播放模式
    play_mode: PlayMode = PlayMode.RANDOM

    # ===== 关注/点赞播报控制 =====
    last_follow_ts: float = 0.0
    pending_follow: bool = False
    last_like_ts: float = 0.0
    pending_like: bool = False

    # ===== 云TTS / 授权相关 =====
    license_key: str = ""
    machine_code: str = ""
    current_model_id: int | None = None

    # ===== UI 开关 =====
    enable_voice_report: bool = False          # ⏱ 自动报时
    enable_danmaku_reply: bool = False         # 📣 弹幕语音回复
    enable_auto_reply: bool = False            # 💬 关键词文本回复

    # ===== 助播关键词（语音） =====
    enable_zhuli: bool = True
    # 模式A：主播关键词优先；模式B：助播关键词优先
    zhuli_mode: str = "A"  # "A" or "B"

    # ===== 运行时注入（FolderOrderPanel 会注入） =====
    folder_manager: Any = None


# ✅ 全局唯一实例
app_state = AppState()
