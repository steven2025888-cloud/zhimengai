import time

from config import (
    PREFIX_RANDOM, PREFIX_SIZE,
    RANDOM_PUSH_INTERVAL, MAIN_TICK_INTERVAL, WS_URL
)
from core.state import AppState
from core.ws_client import WSClient
from core.live_listener import LiveListener
from audio.audio_picker import pick_by_prefix
from audio.audio_dispatcher import AudioDispatcher

from keywords import QA_KEYWORDS
from core.ws_command_router import WSCommandRouter
from audio.voice_reporter import voice_report_loop
from core.douyin_listener import DouyinListener

from PySide6.QtWidgets import QApplication, QDialog
from ui.license_login_dialog import LicenseLoginDialog
import sys
import threading
from core.state import app_state

from audio.folder_order_manager import FolderOrderManager
folder_manager = FolderOrderManager()


def main(license_key: str):

    state = app_state
    dispatcher = AudioDispatcher(state)
    state.audio_dispatcher = dispatcher

    # WS 命令路由
    router = WSCommandRouter(state, dispatcher)

    def audio_worker(dispatcher):
        while True:
            try:
                dispatcher.process_once()
            except Exception as e:
                print("🎧 audio_worker error:", e)
            time.sleep(0.02)

    # 启动音频线程（只启动一次）
    threading.Thread(target=audio_worker, args=(app_state.audio_dispatcher,), daemon=True).start()

    # 监听线程：tick 传 lambda:None，保证永不阻塞
    def wx_listener_thread():
        listener = LiveListener(state=app_state, on_danmaku=on_danmaku, on_event=on_event)
        listener.run(tick=lambda: None)

    def dy_listener_thread():
        dy_listener = DouyinListener(state=app_state, on_danmaku=on_danmaku)
        dy_listener.run(tick=lambda: None)

    # ===== WS 回调 =====
    def on_ws_message(data):
        if not isinstance(data, dict):
            return

        type_raw = data.get("type")
        content = data.get("content", "")
        nickname = data.get("nickname", "WS用户")

        # 模拟弹幕
        if str(type_raw) == "-1":
            print("🧪 WS模拟弹幕：", content)
            on_danmaku(nickname, content)
            return

        # 心跳
        if type_raw in ("ping", "pong", None, ""):
            return

        # 控制指令
        try:
            type_ = int(type_raw)
        except (TypeError, ValueError):
            return

        router.handle(type_)

    # 🔐 带卡密的 WS 客户端
    ws = WSClient(url=WS_URL, license_key=license_key, on_message=on_ws_message)
    ws.start()


    # ===== 关键词匹配 =====
    def _pick_reply_text(cfg: dict) -> str:
        """从“回复词”中挑一句（优先第一句；你也可以改成随机）。"""
        arr = cfg.get("reply", []) or []
        arr = [str(x).strip() for x in arr if str(x).strip()]
        if not arr:
            return ""
        # 想更自然就随机：return random.choice(arr)
        return arr[0]

    def hit_qa_question(text: str):
        print("\n================= 关键词匹配开始 =================")
        print(f"原始弹幕：{text}")

        best_prefix = None
        best_reply = ""
        best_score = -10 ** 9

        # 第一轮：严格模式（must + any）
        print("\n--- 第一轮：严格模式（must + any） ---")
        for cfg in QA_KEYWORDS.values():
            prefix = cfg["prefix"]
            must = cfg.get("must", [])
            any_ = cfg.get("any", [])
            deny = cfg.get("deny", []) or []
            priority = cfg.get("priority", 0)
            auto_reply = _pick_reply_text(cfg)

            # 排除词
            if deny and any(d in text for d in deny):
                hit_deny = [d for d in deny if d in text]
                print(f"❌ [{prefix}] 被排除词命中：{hit_deny}")
                continue

            must_hit_list = [m for m in must if m in text]
            any_hit_list = [a for a in any_ if a in text]

            must_hit = len(must_hit_list)
            any_hit = len(any_hit_list)

            if must and must_hit == 0:
                print(f"⏭ [{prefix}] 必含词未命中，跳过")
                continue
            if any_ and any_hit == 0:
                print(f"⏭ [{prefix}] 意图词未命中，跳过")
                continue

            score = priority * 1000 + must_hit * 50 + any_hit * 10
            print(f"✅ [{prefix}] 命中 must={must_hit_list}, any={any_hit_list}, 分数={score}")

            if score > best_score:
                best_score = score
                best_prefix = prefix
                best_reply = auto_reply

        if best_prefix:
            print(f"\n🎯 第一轮命中结果：{best_prefix}  分数={best_score}")
            print("================= 关键词匹配结束 =================\n")
            return best_prefix, best_reply

        # 第二轮：降级模式（只要 must）
        print("\n--- 第二轮：降级模式（只要 must） ---")
        for cfg in QA_KEYWORDS.values():
            prefix = cfg["prefix"]
            must = cfg.get("must", [])
            deny = cfg.get("deny", []) or []
            priority = cfg.get("priority", 0)
            auto_reply = _pick_reply_text(cfg)

            if deny and any(d in text for d in deny):
                hit_deny = [d for d in deny if d in text]
                print(f"❌ [{prefix}] 被排除词命中：{hit_deny}")
                continue

            must_hit_list = [m for m in must if m in text]
            must_hit = len(must_hit_list)

            if must and must_hit == 0:
                print(f"⏭ [{prefix}] 必含词未命中，跳过")
                continue

            score = priority * 1000 + must_hit * 50
            print(f"🟡 [{prefix}] 降级命中 must={must_hit_list}, 分数={score}")

            if score > best_score:
                best_score = score
                best_prefix = prefix
                best_reply = auto_reply

        if best_prefix:
            print(f"\n🎯 第二轮命中结果：{best_prefix}  分数={best_score}")
        else:
            print("\n🚫 未命中任何关键词分类")

        print("================= 关键词匹配结束 =================\n")
        return best_prefix, best_reply

    def on_danmaku(nickname: str, content: str):
        print("✅ on_danmaku 触发了：", nickname, content)
        # ⭐ 首次连上公屏，开启语音系统
        if not state.live_ready:
            state.live_ready = True
            print("🎯 已连接直播公屏，语音系统正式启动")

        ws.push(nickname, content, 1)

        prefix, reply_text = hit_qa_question(content)
        if prefix:
            try:
                wav = folder_manager.pick_next_audio()
                if wav:
                    dispatcher.push_random(wav)
            except Exception as e:
                print(f"{prefix} 音频触发异常：", e)

            # ✅把“自动回复文本”返回给 LiveListener，让它使用捕获到的模板去回消息
            # 说明：抖音/WS 模拟弹幕没有 m(username) 无法回，这里返回给视频号监听器即可
            return reply_text

        return ""

    def on_event(nickname: str, content: str, type_: int):
        ws.push(nickname, content, type_)

    # ===== 随机讲解线程 =====
    def random_push_loop():
        while True:
            try:
                if state.live_ready and not dispatcher.current_playing and dispatcher.q.empty():
                    wav = folder_manager.pick_next_audio()
                    if wav:
                        dispatcher.push_random(wav)
            except Exception as e:
                print("随机讲解异常：", e)

            time.sleep(RANDOM_PUSH_INTERVAL)

    threading.Thread(target=random_push_loop, daemon=True).start()

    # ===== 监听线程 =====
    def listener_thread():
        listener = LiveListener(state=app_state, on_danmaku=on_danmaku, on_event=on_event)
        listener.run(tick=lambda: None)

    threading.Thread(target=listener_thread, daemon=True).start()

    def douyin_listener_thread():
        from core.state import app_state

        dy_listener = DouyinListener(
            state=app_state,
            on_danmaku=on_danmaku
        )

        # ⭐ 关键：驱动音频播放循环
        dy_listener.run(tick=lambda: None)

    threading.Thread(target=douyin_listener_thread, daemon=True).start()

    print("✅ 系统启动：主线程进入音频调度循环")

    while True:
        time.sleep(1)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    login = LicenseLoginDialog()
    if login.exec() != QDialog.Accepted:
        sys.exit(0)

    license_key = login.edit.text().strip()
    print("🔐 当前使用卡密：", license_key)

    main(license_key)
