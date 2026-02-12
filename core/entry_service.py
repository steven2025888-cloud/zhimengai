# core/entry_service.py
import os
import sys
import time
import threading
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog
from ui.license_login_dialog import LicenseLoginDialog

from config import WS_URL
from core.state import app_state
from core.ws_client import WSClient
from core.live_listener import LiveListener
from core.douyin_listener import DouyinListener

from audio.audio_picker import pick_by_prefix
from audio.audio_dispatcher import AudioDispatcher
from core.ws_command_router import WSCommandRouter
from audio.folder_order_manager import FolderOrderManager

folder_manager = FolderOrderManager()


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def setup_playwright_env():
    p = app_dir() / "ms-playwright"
    if p.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(p)


def run_engine(license_key: str):
    setup_playwright_env()  # ✅ 必须：否则会去 _internal\.local-browsers 找，必炸

    state = app_state
    dispatcher = AudioDispatcher(state)
    state.audio_dispatcher = dispatcher

    state.enabled = True
    state.live_ready = True
    
    # ✅ 设置 license_key 和 machine_code 到 app_state
    state.license_key = license_key
    from core.device import get_machine_code
    state.machine_code = get_machine_code()

    from config import AUDIO_BASE_DIR
    from audio.folder_order_manager import FolderOrderManager

    # ===== runtime_state.json 同步到 app_state =====
    try:
        from core.runtime_state import load_runtime_state
        rt_flags = load_runtime_state() or {}
    except Exception:
        rt_flags = {}

    if rt_flags.get("anchor_audio_dir"):
        state.anchor_audio_dir = str(rt_flags.get("anchor_audio_dir"))
    if rt_flags.get("zhuli_audio_dir"):
        state.zhuli_audio_dir = str(rt_flags.get("zhuli_audio_dir"))

    if rt_flags.get("follow_audio_dir"):
        state.follow_audio_dir = str(rt_flags.get("follow_audio_dir"))
    if rt_flags.get("like_audio_dir"):
        state.like_audio_dir = str(rt_flags.get("like_audio_dir"))

    if "ai_reply" in rt_flags:
        state.ai_reply = bool(rt_flags.get("ai_reply"))

    if rt_flags.get("ai_api_key") is not None:
        state.ai_api_key = str(rt_flags.get("ai_api_key") or "")

    if rt_flags.get("ai_model") is not None:
        state.ai_model = str(rt_flags.get("ai_model") or "")

    if "enable_follow_audio" in rt_flags:
        state.enable_follow_audio = bool(rt_flags.get("enable_follow_audio"))
    if "enable_like_audio" in rt_flags:
        state.enable_like_audio = bool(rt_flags.get("enable_like_audio"))
    if rt_flags.get("follow_like_cooldown_seconds") is not None:
        try:
            state.follow_like_cooldown_seconds = int(rt_flags.get("follow_like_cooldown_seconds"))
        except Exception:
            pass

    if "enable_comment_record" in rt_flags:
        state.enable_comment_record = bool(rt_flags.get("enable_comment_record"))
    if "enable_reply_record" in rt_flags:
        state.enable_reply_record = bool(rt_flags.get("enable_reply_record"))
    if "enable_reply_collect" in rt_flags:
        state.enable_reply_collect = bool(rt_flags.get("enable_reply_collect"))

    anchor_dir = getattr(state, "anchor_audio_dir", None) or str(AUDIO_BASE_DIR)
    state.folder_manager = FolderOrderManager(anchor_dir)

    # ===== 报时线程 =====
    from audio.voice_reporter import start_reporter_thread
    start_reporter_thread(dispatcher, state)

    router = WSCommandRouter(state, dispatcher)

    # ===== AudioDispatcher worker =====
    def audio_worker(dispatcher_: AudioDispatcher):
        while True:
            try:
                if hasattr(dispatcher_, "process_once"):
                    dispatcher_.process_once()
                elif hasattr(dispatcher_, "tick"):
                    dispatcher_.tick()
                else:
                    raise AttributeError("AudioDispatcher has no process_once/tick")
            except Exception as e:
                print("🎧 audio_worker error:", e)
            time.sleep(0.02)

    threading.Thread(target=audio_worker, args=(app_state.audio_dispatcher,), daemon=True).start()

    # ===== runtime keywords 辅助（你原逻辑保留）=====
    def get_runtime_qa_keywords() -> dict:
        try:
            from core.runtime_state import load_runtime_state
            rt = load_runtime_state() or {}
        except Exception:
            rt = {}

        for k in ("qa_keywords", "QA_KEYWORDS", "keywords", "keyword_rules"):
            v = rt.get(k)
            if isinstance(v, dict) and v:
                return v

        try:
            from keywords import QA_KEYWORDS as _QA
            return _QA
        except Exception:
            return {}

    def _rt_get() -> dict:
        try:
            from core.runtime_state import load_runtime_state
            return load_runtime_state() or {}
        except Exception:
            return {}

    def _rt_save(d: dict) -> bool:
        try:
            from core.runtime_state import save_runtime_state
            save_runtime_state(d)
            return True
        except Exception as e:
            print("⚠️ save_runtime_state failed:", e)
            return False

    def _qa_key_name(rt: dict) -> str:
        for k in ("qa_keywords", "QA_KEYWORDS", "keywords", "keyword_rules"):
            if isinstance(rt.get(k), dict):
                return k
        return "qa_keywords"

    def collect_reply_to_keyword(prefix: str, reply_text: str) -> bool:
        if not bool(getattr(app_state, "enable_reply_collect", False)):
            return False

        prefix = str(prefix or "").strip()
        reply_text = str(reply_text or "").strip()
        if not prefix or not reply_text:
            return False

        rt = _rt_get()
        key = _qa_key_name(rt)

        qa_map = rt.get(key)
        if not isinstance(qa_map, dict) or not qa_map:
            try:
                from keywords import QA_KEYWORDS as _QA
                qa_map = dict(_QA) if isinstance(_QA, dict) else {}
            except Exception:
                qa_map = {}

        target_cfg = None
        for cfg in qa_map.values():
            if not isinstance(cfg, dict):
                continue
            if str(cfg.get("prefix") or "") == prefix:
                target_cfg = cfg
                break

        if target_cfg is None:
            return False

        arr = target_cfg.get("reply", []) or []
        if not isinstance(arr, list):
            arr = []
        arr = [str(x).strip() for x in arr if str(x).strip()]

        if reply_text in arr:
            return True

        arr.insert(0, reply_text)

        MAX_REPLY_PER_KEYWORD = 60
        if len(arr) > MAX_REPLY_PER_KEYWORD:
            arr = arr[:MAX_REPLY_PER_KEYWORD]

        target_cfg["reply"] = arr
        rt[key] = qa_map
        return _rt_save(rt)

    app_state.collect_reply_to_keyword_cb = collect_reply_to_keyword

    # ===== WS 回调（你原逻辑保留）=====
    def on_ws_message(data):
        if not isinstance(data, dict):
            return
        type_raw = data.get("type")
        content = data.get("content", "")
        nickname = data.get("nickname", "WS用户")

        if str(type_raw) == "-1":
            on_danmaku(nickname, content)
            return

        if type_raw in ("ping", "pong", None, ""):
            return

        try:
            type_ = int(type_raw)
        except (TypeError, ValueError):
            return

        # ✅ 允许携带 url 等字段
        if hasattr(router, 'handle_message'):
            router.handle_message(data)
        else:
            router.handle(type_)

    ws = WSClient(url=WS_URL, license_key=license_key, on_message=on_ws_message)

    # ✅ 关键：让 UI / Router 都拿得到同一个 ws 实例
    state.ws_client = ws  # state = app_state
    app_state.ws_client = ws  # 可写可不写（但写了更稳）

    ws.start()
    # ✅ 让 WSCommandRouter 可以回推状态给手机端
    state.ws_client = ws

    def _pick_reply_text(cfg: dict) -> str:
        arr = cfg.get("reply", []) or []
        arr = [str(x).strip() for x in arr if str(x).strip()]
        return arr[0] if arr else ""

    def hit_qa_question(text: str):
        best_prefix = None
        best_reply = ""
        best_score = -10 ** 9

        qa_map = get_runtime_qa_keywords()

        for cfg in qa_map.values():
            prefix = cfg.get("prefix")
            if not prefix:
                continue
            must = cfg.get("must", [])
            any_ = cfg.get("any", [])
            deny = cfg.get("deny", []) or []
            priority = cfg.get("priority", 0)
            auto_reply = _pick_reply_text(cfg)

            if deny and any(d in text for d in deny):
                continue

            must_hit_list = [m for m in must if m in text]
            any_hit_list = [a for a in any_ if a in text]
            must_hit = len(must_hit_list)
            any_hit = len(any_hit_list)

            if must and must_hit == 0:
                continue
            if any_ and any_hit == 0:
                continue

            score = priority * 1000 + must_hit * 50 + any_hit * 10
            if score > best_score:
                best_score = score
                best_prefix = prefix
                best_reply = auto_reply

        if best_prefix:
            app_state.pending_hit = (best_prefix, best_reply)
            return best_prefix, best_reply

        for cfg in qa_map.values():
            prefix = cfg.get("prefix")
            if not prefix:
                continue
            must = cfg.get("must", [])
            deny = cfg.get("deny", []) or []
            priority = cfg.get("priority", 0)
            auto_reply = _pick_reply_text(cfg)

            if deny and any(d in text for d in deny):
                continue

            must_hit_list = [m for m in must if m in text]
            must_hit = len(must_hit_list)
            if must and must_hit == 0:
                continue

            score = priority * 1000 + must_hit * 50
            if score > best_score:
                best_score = score
                best_prefix = prefix
                best_reply = auto_reply

        if best_prefix:
            app_state.pending_hit = (best_prefix, best_reply)

        return best_prefix, best_reply

    def on_danmaku(nickname: str, content: str):
        if not app_state.live_ready:
            app_state.live_ready = True

        ws.push(nickname, content, 1)

        if not hasattr(app_state, "hit_keyword_by_nick"):
            app_state.hit_keyword_by_nick = {}
        app_state.last_comment = {"nickname": nickname or "未知用户", "content": content or "", "ts": time.time()}

        prefix, reply_text = hit_qa_question(content)

        if prefix:
            app_state.pending_hit = (prefix, reply_text)
            app_state.last_trigger_keyword = prefix
            try:
                app_state.hit_keyword_by_nick[str(nickname or "")] = prefix
            except Exception:
                pass

            app_state.last_hit_detail = {
                "nickname": nickname or "未知用户",
                "content": content or "",
                "trigger_keyword": prefix,
                "reply_text": reply_text or "",
                "ts": time.time(),
            }

            if getattr(app_state, "enable_danmaku_reply", False):
                try:
                    wav = pick_by_prefix(prefix)
                    if wav:
                        dispatcher.push_anchor_keyword(wav)
                except Exception as e:
                    print("anchor keyword error:", e)

            return reply_text

        app_state.last_trigger_keyword = ""
        try:
            app_state.hit_keyword_by_nick[str(nickname or "")] = ""
        except Exception:
            pass
        app_state.last_hit_detail = {
            "nickname": nickname or "未知用户",
            "content": content or "",
            "trigger_keyword": "",
            "reply_text": "",
            "ts": time.time(),
        }
        return ""

    app_state.on_danmaku_cb = on_danmaku

    def on_event(nickname: str, content: str, type_: int):
        ws.push(nickname, content, type_)
        try:
            if int(type_) == 4:  # 关注
                router.handle(-2)
            elif int(type_) == 2:  # 点赞
                router.handle(-3)
        except Exception as e:
            print("on_event follow/like error:", e)

    # ===== 轮播线程 =====
    def random_push_loop():
        from core.state import app_state as s
        while True:
            try:
                if not s.enabled:
                    time.sleep(0.3)
                    continue
                if dispatcher.has_pending():
                    time.sleep(0.2)
                    continue
                fm = getattr(s, "folder_manager", None)
                if fm:
                    p = fm.pick_next_audio()
                    if p:
                        dispatcher.push_random(p)
                time.sleep(0.2)
            except Exception as e:
                print("random loop error:", e)
                time.sleep(0.5)

    threading.Thread(target=random_push_loop, daemon=True).start()

    # ===== 公屏轮播：队列 + rotator =====
    import queue
    from core.public_screen_rotator import start_public_screen_rotator

    if not hasattr(app_state, "public_screen_queue_wx") or app_state.public_screen_queue_wx is None:
        app_state.public_screen_queue_wx = queue.Queue()
    if not hasattr(app_state, "public_screen_queue_dy") or app_state.public_screen_queue_dy is None:
        app_state.public_screen_queue_dy = queue.Queue()

    start_public_screen_rotator(app_state)

    # ===== 视频号 listener 线程 =====
    def listener_thread():
        listener = LiveListener(state=app_state, on_danmaku=on_danmaku, on_event=on_event)
        listener.run(tick=listener.process_public_screen_queue)  # ✅ 依赖 LiveListener 里实现

    threading.Thread(target=listener_thread, daemon=True).start()

    # ===== 抖音 listener 线程 =====
    def douyin_listener_thread():
        # ✅ 修复：必须把 on_event 传进去（哪怕抖音暂时不用）
        dy_listener = DouyinListener(state=app_state, on_danmaku=on_danmaku, on_event=on_event)
        dy_listener.run(tick=dy_listener.process_public_screen_queue)  # ✅ 依赖 DouyinListener 里实现

    threading.Thread(target=douyin_listener_thread, daemon=True).start()

    while True:
        time.sleep(1)


def run():
    setup_playwright_env()

    app = QApplication(sys.argv)

    login = LicenseLoginDialog()
    if login.exec() != QDialog.Accepted:
        sys.exit(0)

    license_key = login.edit.text().strip()
    run_engine(license_key)
