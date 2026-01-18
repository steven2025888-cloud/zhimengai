import asyncio
import json
import threading
import time
import websockets
from config import WS_URL


class WSClient:
    def __init__(self, url: str = WS_URL, license_key: str = "", on_message=None):
        if not license_key:
            raise ValueError("license_key 不能为空，必须先登录授权")

        self.url = url
        self.license_key = license_key
        self.on_message = on_message
        self.queue: "asyncio.Queue[dict]" = asyncio.Queue()
        self._thread: threading.Thread | None = None

    async def _runner(self):
        while True:
            try:
                print(f"🔌 正在连接 WS：{self.url}")
                async with websockets.connect(self.url, ping_interval=20) as ws:
                    print("✅ WS 已连接")

                    # 🔐 发送卡密认证
                    auth_payload = {
                        "event": "auth",
                        "license_key": self.license_key
                    }
                    await ws.send(json.dumps(auth_payload, ensure_ascii=False))
                    print("🔐 已发送卡密认证：", self.license_key)

                    authed = False

                    async def sender():
                        # 等待认证完成
                        while not authed:
                            await asyncio.sleep(0.1)

                        while True:
                            data = await self.queue.get()
                            await ws.send(json.dumps(data, ensure_ascii=False))
                            print(f"📤 WS 已发送：{data}")

                    async def receiver():
                        nonlocal authed
                        async for message in ws:
                            try:
                                data = json.loads(message)
                            except Exception:
                                data = message

                            print(f"📥 WS 收到消息：{data}")

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
            "type": type_,
            "ts": int(time.time())
        }
        try:
            self.queue.put_nowait(payload)
        except Exception:
            pass
