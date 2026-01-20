# core/auto_reply_engine.py
import time
from dataclasses import dataclass
from typing import Callable, Optional, Tuple


@dataclass
class AutoReplyResult:
    prefix: str
    reply_text: str


class LiveAutoReplyEngine:
    """
    全平台通用自动回复引擎
    - 支持外部已算好的命中结果（already_hit），避免重复 hit_qa_question
    - 冷却、开关、平台隔离
    """

    def __init__(
        self,
        state,
        hit_qa_question: Callable[[str], Tuple[Optional[str], Optional[str]]],
        cooldown_seconds: int = 60,
        cooldown_store_attr: str = "auto_reply_cooldown_map",
    ):
        self.state = state
        self.hit_qa_question = hit_qa_question
        self.cooldown_seconds = cooldown_seconds
        self.cooldown_store_attr = cooldown_store_attr

        if not hasattr(self.state, cooldown_store_attr):
            setattr(self.state, cooldown_store_attr, {})  # key -> last_ts

    def _get_cooldown_map(self) -> dict:
        m = getattr(self.state, self.cooldown_store_attr, None)
        if not isinstance(m, dict):
            m = {}
            setattr(self.state, self.cooldown_store_attr, m)
        return m

    def try_auto_reply(
        self,
        platform: str,
        user_key: str,
        nickname: str,
        content: str,
        send_func: Callable[[str], bool],
        already_hit: Optional[Tuple[Optional[str], Optional[str]]] = None,
    ) -> Optional[AutoReplyResult]:

        if not getattr(self.state, "enable_auto_reply", False):
            return None

        # 命中结果（避免重复计算）
        if already_hit is not None:
            prefix, reply_text = already_hit
        else:
            prefix, reply_text = self.hit_qa_question(content)

        prefix = (prefix or "").strip()
        reply_text = (reply_text or "").strip()
        if not prefix or not reply_text:
            return None

        key = f"{platform}:{user_key}"
        now = time.time()
        cd_map = self._get_cooldown_map()
        last = float(cd_map.get(key, 0) or 0)

        if now - last < self.cooldown_seconds:
            return AutoReplyResult(prefix=prefix, reply_text="")

        ok = False
        try:
            ok = bool(send_func(reply_text))
        except Exception as e:
            print("❌ send_func exception:", e)
            ok = False

        if ok:
            cd_map[key] = now
            return AutoReplyResult(prefix=prefix, reply_text=reply_text)

        return AutoReplyResult(prefix=prefix, reply_text="")
