from dataclasses import dataclass, field
from enum import Enum
from typing import Set
import time


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

    # 去重用的 seq 集合
    seen_seq: Set[str] = field(default_factory=set)

    # 当前播放模式
    play_mode: PlayMode = PlayMode.RANDOM

    # ===== 新增：关注播报控制 =====
    last_follow_ts: float = 0.0
    pending_follow: bool = False

    # ===== 点赞播报控制 =====
    last_like_ts: float = 0.0
    pending_like: bool = False

    # ===== 新增：云TTS / 授权相关 =====
    license_key: str = ""          # 卡密
    machine_code: str = ""         # 设备指纹
    current_model_id: int | None = None  # 当前选择的声纹模型ID
    enable_voice_report: bool = False  # ⏱ 自动报时开关（默认关闭）

    enable_auto_reply: bool = True

# ... 你的 AppState dataclass 定义不变

app_state = AppState()   # ✅ 全局唯一实例


