import asyncio
import json
import threading
import time
from typing import Any, Callable, Optional

import websockets

from config import WS_URL


class WSClient:
    """WebSocket 客户端（线程安全版）。

    你的旧版实现里 push() 会在 UI 线程直接调用 asyncio.Queue.put_nowait()。
    asyncio.Queue 不是跨线程安全的，常见表现就是：
    - 手机端操作能同步到 PC（因为是网络 -> receiver 回调）
    - 但 PC 端按钮点了不会同步到手机（因为 push 入队失败被吞掉）

    这里通过 loop.call_soon_threadsafe(...) 解决。
    """

    def __init__(
        self,
        url: str = WS_URL,
        license_key: str = "",
        on_message: Optional[Callable[[Any], None]] = None,
    ):
        if not license_key:
            raise ValueError("license_key 不能为空，必须先登录授权")

        self.url = url
        self.license_key = license_key
        self.on_message = on_message

        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: Optional[asyncio.Queue] = None

        self._pending: list[dict] = []
        self._pending_lock = threading.Lock()

    async def _runner(self):
        while True:
            try:
                print(f"🔌 正在连接 WS：{self.url}")
                async with websockets.connect(self.url, ping_interval=20) as ws:
                    print("✅ WS 已连接")

                    # 记录 loop / queue（必须在运行中的 loop 里创建）
                    self._loop = asyncio.get_running_loop()
                    if self._queue is None:
                        self._queue = asyncio.Queue()

                    # 🔐 发送卡密认证
                    await ws.send(
                        json.dumps({"event": "auth", "license_key": self.license_key}, ensure_ascii=False)
                    )
                    print("🔐 已发送卡密认证：", self.license_key)

                    authed = False

                    async def sender():
                        nonlocal authed
                        # 等待认证完成
                        while not authed:
                            await asyncio.sleep(0.05)

                        # 认证成功后先补发 pending
                        with self._pending_lock:
                            pendings = list(self._pending)
                            self._pending.clear()
                        for p in pendings:
                            await ws.send(json.dumps(p, ensure_ascii=False))
                            print(f"📤 WS(补发) 已发送：{p}")

                        # 持续从 queue 发
                        assert self._queue is not None
                        while True:
                            data = await self._queue.get()
                            await ws.send(json.dumps(data, ensure_ascii=False))
                            print(f"📤 WS 已发送：{data}")

                    async def receiver():
                        nonlocal authed
                        async for message in ws:
                            try:
                                data = json.loads(message)
                            except Exception:
                                data = message

                            # print(f"📥 WS 收到消息：{data}")  # 太吵可以关

                            # 处理认证反馈
                            if isinstance(data, dict) and data.get("event") == "auth_ok":
                                authed = True
                                print("✅ WS 卡密认证成功，进入房间：", self.license_key)
                                continue

                            if isinstance(data, dict) and data.get("event") == "auth_fail":
                                print("❌ WS 卡密认证失败：", data)
                                return

                            if self.on_message:
                                try:
                                    self.on_message(data)
                                except Exception as e:
                                    print("on_message 回调异常：", e)

                    await asyncio.gather(sender(), receiver())

            except Exception as e:
                print(f"⚠️ WS 断开，3 秒后重连：{e}")
                await asyncio.sleep(3)

    def start(self):
        def run():
            asyncio.run(self._runner())

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def push(self, nickname: str, content: str, type_: int):
        payload = {
            "nickname": nickname,
            "content": content,
            "type": int(type_),
            "ts": int(time.time()),
        }

        # 还没连接/loop 未就绪：先暂存
        loop = self._loop
        if loop is None or loop.is_closed() or self._queue is None:
            with self._pending_lock:
                self._pending.append(payload)
            return

        # ✅ 线程安全入队（UI 线程可直接调用）
        try:
            loop.call_soon_threadsafe(self._queue.put_nowait, payload)
        except Exception as e:
            # 不要吞异常，否则你会以为“发出去了”
            print("⚠️ WS push 入队失败：", e)
            with self._pending_lock:
                self._pending.append(payload)
