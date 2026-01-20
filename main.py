import time
import sys
import threading

from config import (
    PREFIX_RANDOM, PREFIX_SIZE,
    RANDOM_PUSH_INTERVAL, MAIN_TICK_INTERVAL, WS_URL
)
from core.state import AppState, app_state
from core.ws_client import WSClient
from core.live_listener import LiveListener
from audio.audio_picker import pick_by_prefix
from audio.audio_dispatcher import AudioDispatcher

from keywords import QA_KEYWORDS
from core.ws_command_router import WSCommandRouter
from core.douyin_listener import DouyinListener

from PySide6.QtWidgets import QApplication, QDialog
from ui.license_login_dialog import LicenseLoginDialog

from audio.folder_order_manager import FolderOrderManager
folder_manager = FolderOrderManager()


def main(license_key: str):

    state = app_state
    dispatcher = AudioDispatcher(state)
    state.audio_dispatcher = dispatcher

    # =========================
    # ✅ 关键修复：启动就允许播放（不再依赖首次弹幕）
    # =========================
    state.enabled = True  # 确保 random_push_loop 不会一直 continue
    state.live_ready = True  # ✅ 关键：否则 push_random 直接 return

    # ✅ 确保 folder_manager 一开始就有（否则 random_push_loop 可能 fm 为 None）
    from config import AUDIO_BASE_DIR
    from audio.folder_order_manager import FolderOrderManager
    anchor_dir = getattr(state, "anchor_audio_dir", None) or str(AUDIO_BASE_DIR)
    state.folder_manager = FolderOrderManager(anchor_dir)

    # ⭐ 启动语音报时线程
    from audio.voice_reporter import start_reporter_thread
    start_reporter_thread(dispatcher, state)


    # WS 命令路由
    router = WSCommandRouter(state, dispatcher)

    def audio_worker(dispatcher_: AudioDispatcher):
        while True:
            try:
                # 兼容：万一旧 dispatcher 没有 process_once
                if hasattr(dispatcher_, "process_once"):
                    dispatcher_.process_once()
                elif hasattr(dispatcher_, "tick"):
                    dispatcher_.tick()
                else:
                    raise AttributeError("AudioDispatcher has no process_once/tick")
            except Exception as e:
                print("🎧 audio_worker error:", e)
            time.sleep(0.02)

    # 启动音频线程（只启动一次）
    threading.Thread(target=audio_worker, args=(app_state.audio_dispatcher,), daemon=True).start()

    # =========================
    # runtime_state 读取（实时）
    # =========================
    def get_runtime_qa_keywords() -> dict:
        """从 runtime_state 读取主播关键词（实时生效）。"""
        try:
            from core.runtime_state import load_runtime_state
            rt = load_runtime_state() or {}
        except Exception:
            rt = {}

        # 兼容多个 key（你面板最终用哪个都能读到）
        for k in ("qa_keywords", "QA_KEYWORDS", "keywords", "keyword_rules"):
            v = rt.get(k)
            if isinstance(v, dict) and v:
                return v

        # 兜底：还没迁移时用旧的 QA_KEYWORDS
        try:
            from keywords import QA_KEYWORDS as _QA
            return _QA
        except Exception:
            return {}

    def get_runtime_zhuli_keywords() -> dict:
        from core.zhuli_keyword_io import load_zhuli_keywords
        return load_zhuli_keywords()

    # =========================
    # ===== WS 回调 =====
    # =========================
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

    # =========================
    # ===== 关键词匹配 =====
    # =========================
    def _pick_reply_text(cfg: dict) -> str:
        """从“回复词”中挑一句（优先第一句；你也可以改成随机）。"""
        arr = cfg.get("reply", []) or []
        arr = [str(x).strip() for x in arr if str(x).strip()]
        return arr[0] if arr else ""

    def hit_qa_question(text: str):
        print("\n================= 关键词匹配开始 =================")
        print(f"原始弹幕：{text}")

        best_prefix = None
        best_reply = ""
        best_score = -10 ** 9

        qa_map = get_runtime_qa_keywords()

        # 第一轮：严格模式（must + any）
        print("\n--- 第一轮：严格模式（must + any） ---")
        for cfg in qa_map.values():
            prefix = cfg.get("prefix")
            if not prefix:
                continue
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
            state.pending_hit = (best_prefix, best_reply)
            print(f"\n🎯 第一轮命中结果：{best_prefix}  分数={best_score}")
            print("================= 关键词匹配结束 =================\n")
            return best_prefix, best_reply

        # 第二轮：降级模式（只要 must）——✅ 仍然使用 qa_map（实时一致）
        print("\n--- 第二轮：降级模式（只要 must） ---")
        for cfg in qa_map.values():
            prefix = cfg.get("prefix")
            if not prefix:
                continue
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
                best_reply = auto_reply  # ✅ 第二轮也要同步 best_reply

        if best_prefix:
            print(f"\n🎯 第二轮命中结果：{best_prefix}  分数={best_score}")
            state.pending_hit = (best_prefix, best_reply)
        else:
            print("\n🚫 未命中任何关键词分类")

        print("================= 关键词匹配结束 =================\n")
        return best_prefix, best_reply

    def hit_zhuli_question(text: str) -> str | None:
        data = get_runtime_zhuli_keywords()
        if not isinstance(data, dict) or not data:
            return None

        best_prefix = None
        best_score = -10 ** 9

        # ---------- 第一轮：严格 must + any（如果 any 非空则必须命中 any） ----------
        for cfg in data.values():
            if not isinstance(cfg, dict):
                continue
            prefix = str(cfg.get("prefix") or "").strip()
            if not prefix:
                continue

            must = cfg.get("must", []) or []
            any_ = cfg.get("any", []) or []
            deny = cfg.get("deny", []) or []
            pr = int(cfg.get("priority", 0) or 0)

            if deny and any(d in text for d in deny):
                continue

            must_hit = [m for m in must if m in text]
            any_hit = [a for a in any_ if a in text]

            if must and not must_hit:
                continue
            if any_ and not any_hit:
                continue

            score = pr * 1000 + len(must_hit) * 50 + len(any_hit) * 10
            if score > best_score:
                best_score = score
                best_prefix = prefix

        if best_prefix:
            return best_prefix

        # ---------- 第二轮：降级（只要求 must 命中，不要求 any） ----------
        for cfg in data.values():
            if not isinstance(cfg, dict):
                continue
            prefix = str(cfg.get("prefix") or "").strip()
            if not prefix:
                continue

            must = cfg.get("must", []) or []
            deny = cfg.get("deny", []) or []
            pr = int(cfg.get("priority", 0) or 0)

            if deny and any(d in text for d in deny):
                continue

            must_hit = [m for m in must if m in text]
            if must and not must_hit:
                continue

            score = pr * 1000 + len(must_hit) * 50
            if score > best_score:
                best_score = score
                best_prefix = prefix

        return best_prefix

    def pick_zhuli_audio_by_prefix(prefix: str) -> str | None:
        from pathlib import Path
        try:
            from config import ZHULI_AUDIO_DIR, SUPPORTED_AUDIO_EXTS
            base = Path(ZHULI_AUDIO_DIR)
            exts = tuple(SUPPORTED_AUDIO_EXTS)
        except Exception:
            base = Path.cwd() / "zhuli_audio"
            exts = (".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg")

        if not base.exists():
            return None

        cands = []
        for p in base.iterdir():
            if p.is_file() and p.suffix.lower() in exts:
                if p.stem.startswith(prefix):
                    cands.append(str(p))
        return cands[0] if cands else None

    # =========================
    # ===== 弹幕入口 =====
    # =========================
    def on_danmaku(nickname: str, content: str):
        print("✅ on_danmaku 触发了：", nickname, content)

        # ⭐ 首次连上公屏，开启语音系统
        if not state.live_ready:
            state.live_ready = True
            print("🎯 已连接直播公屏，语音系统正式启动")

        ws.push(nickname, content, 1)

        prefix, reply_text = hit_qa_question(content)

        if prefix:
            state.pending_hit = (prefix, reply_text)

            # 1) 主播关键词语音
            if getattr(state, "enable_danmaku_reply", False):
                try:
                    wav = pick_by_prefix(prefix)
                    if wav:
                        dispatcher.push_anchor_keyword(wav)
                        print(f"🔊 主播语音触发：prefix={prefix} wav={wav}")
                    else:
                        print(f"⚠️ 未找到主播关键词音频：{prefix}")
                except Exception as e:
                    print("❌ 主播关键词语音触发异常：", e)


            # 2) 助播关键词语音（同条弹幕）
            if getattr(state, "enable_zhuli", False):
                try:
                    zhuli_prefix = hit_zhuli_question(content)
                    if zhuli_prefix:
                        zhuli_wav = pick_zhuli_audio_by_prefix(zhuli_prefix)
                        if zhuli_wav:
                            dispatcher.push_zhuli_keyword(zhuli_wav)
                            print(f"🎧 助播语音触发：prefix={zhuli_prefix} wav={zhuli_wav}")
                        else:
                            print(f"⚠️ 未找到助播关键词音频：{zhuli_prefix}（检查 zhuli_audio 命名）")
                except Exception as e:
                    print("❌ 助播关键词语音触发异常：", e)

            return reply_text

        return ""

    # ⭐ 注册给本地测试按钮用（UI 调 app_state.on_danmaku_cb）
    app_state.on_danmaku_cb = on_danmaku
    print("🧪 本地弹幕测试回调已注册：app_state.on_danmaku_cb")

    def on_event(nickname: str, content: str, type_: int):
        ws.push(nickname, content, type_)

    # ===== 随机讲解线程 =====
    def random_push_loop():

        from core.state import app_state
        fm = getattr(app_state, "folder_manager", None)
        print("🔎 runtime.anchor_audio_dir =", getattr(app_state, "anchor_audio_dir", None))
        print("🔎 folder_manager =", type(fm), "base_dir =", getattr(fm, "base_dir", None), "AUDIO_BASE_DIR =",
              __import__("config").AUDIO_BASE_DIR)

        """轮播：只有在没有任何高优先级任务时才 push random。"""
        while True:
            try:
                if not app_state.enabled:
                    time.sleep(0.3)
                    continue

                # 有插播/报时排队时，不要推轮播
                if dispatcher.has_pending():
                    time.sleep(0.2)
                    continue

                fm = getattr(app_state, "folder_manager", None)
                if fm:
                    p = fm.pick_next_audio()
                    if p:
                        dispatcher.push_random(p)
                time.sleep(0.2)
            except Exception as e:
                print("随机讲解异常：", e)
                time.sleep(0.5)

    threading.Thread(target=random_push_loop, daemon=True).start()

    # ===== 监听线程 =====
    def listener_thread():
        listener = LiveListener(state=app_state, on_danmaku=on_danmaku, on_event=on_event)
        listener.run(tick=lambda: None)

    threading.Thread(target=listener_thread, daemon=True).start()

    def douyin_listener_thread():
        dy_listener = DouyinListener(
            state=app_state,
            on_danmaku=on_danmaku
        )
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
