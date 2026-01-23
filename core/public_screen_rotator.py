# core/public_screen_rotator.py
import random
import threading
import time
import queue
from typing import List, Optional


def _normalize_messages(raw) -> List[str]:
    msgs: List[str] = []
    if isinstance(raw, (list, tuple)):
        for x in raw:
            s = str(x or "").strip()
            if s:
                msgs.append(s)
    elif isinstance(raw, str):
        for line in raw.splitlines():
            s = line.strip()
            if s:
                msgs.append(s)
    return msgs


def start_public_screen_rotator(state) -> None:
    '''
    公屏轮播：
    - interval_min：分钟
    - messages：从 state.public_screen_messages 读取（list[str]）
    - 发送方式：往 state.public_screen_queue_wx / state.public_screen_queue_dy 里 put 文本
      由各自 listener 线程 tick() 里取出并调用 send_public_text 发送（避免跨线程调用 Playwright）
    '''
    if getattr(state, "_public_screen_rotator_started", False):
        return
    state._public_screen_rotator_started = True

    # 确保队列存在
    if not hasattr(state, "public_screen_queue_wx") or state.public_screen_queue_wx is None:
        state.public_screen_queue_wx = queue.Queue()
    if not hasattr(state, "public_screen_queue_dy") or state.public_screen_queue_dy is None:
        state.public_screen_queue_dy = queue.Queue()

    def _worker():
        next_ts: Optional[float] = None
        last_sent: str = ""

        while True:
            try:
                enabled_wx = bool(getattr(state, "enable_public_screen_wx", False))
                enabled_dy = bool(getattr(state, "enable_public_screen_dy", False))

                if not (enabled_wx or enabled_dy):
                    next_ts = None
                    time.sleep(0.5)
                    continue

                # interval
                try:
                    interval_min = int(getattr(state, "public_screen_interval_min", 5) or 5)
                except Exception:
                    interval_min = 5
                interval_min = max(1, min(240, interval_min))
                interval_sec = interval_min * 60

                msgs = _normalize_messages(getattr(state, "public_screen_messages", []) or [])
                if not msgs:
                    next_ts = None
                    time.sleep(0.5)
                    continue

                now = time.time()
                if next_ts is None:
                    next_ts = now + interval_sec

                if now < next_ts:
                    time.sleep(0.3)
                    continue

                # 随机选一条，尽量避免连续重复
                text = random.choice(msgs).strip()
                if len(msgs) >= 2 and text == last_sent:
                    text2 = random.choice(msgs).strip()
                    if text2:
                        text = text2
                if not text:
                    next_ts = now + interval_sec
                    time.sleep(0.3)
                    continue

                # 只有对应平台在“监听中”才入队（更稳）
                if enabled_wx and bool(getattr(state, "is_listening", False)):
                    try:
                        state.public_screen_queue_wx.put(text, block=False)
                        print(f"📢 公屏轮播 -> 视频号 入队：{text}")
                    except Exception:
                        pass

                if enabled_dy and bool(getattr(state, "dy_is_listening", False)):
                    try:
                        state.public_screen_queue_dy.put(text, block=False)
                        print(f"📢 公屏轮播 -> 抖音 入队：{text}")
                    except Exception:
                        pass

                last_sent = text
                next_ts = now + interval_sec

            except Exception as e:
                print("⚠️ 公屏轮播线程异常：", e)
                time.sleep(1.0)

    threading.Thread(target=_worker, daemon=True).start()
