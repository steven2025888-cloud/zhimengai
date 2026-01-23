# core/entry_service.py
import os
import sys
import time
import threading
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog
from ui.license_login_dialog import LicenseLoginDialog

from config import ( WS_URL
)
from core.state import AppState, app_state
from core.ws_client import WSClient
from core.live_listener import LiveListener
from audio.audio_picker import pick_by_prefix
from audio.audio_dispatcher import AudioDispatcher

from keywords import QA_KEYWORDS
from core.ws_command_router import WSCommandRouter
from core.douyin_listener import DouyinListener

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

    from config import AUDIO_BASE_DIR
    from audio.folder_order_manager import FolderOrderManager

    try:
        from core.runtime_state import load_runtime_state
        rt_flags = load_runtime_state() or {}
    except Exception:
        rt_flags = {}

    if rt_flags.get("anchor_audio_dir"):
        state.anchor_audio_dir = str(rt_flags.get("anchor_audio_dir"))
    if rt_flags.get("zhuli_audio_dir"):
        state.zhuli_audio_dir = str(rt_flags.get("zhuli_audio_dir"))

    # ✅ 关注/点赞目录也要在引擎启动时从 runtime_state.json 同步到 app_state
    if rt_flags.get("follow_audio_dir"):
        state.follow_audio_dir = str(rt_flags.get("follow_audio_dir"))
    if rt_flags.get("like_audio_dir"):
        state.like_audio_dir = str(rt_flags.get("like_audio_dir"))

    # （建议）关注/点赞播放开关和冷却也一并同步
    if "enable_follow_audio" in rt_flags:
        state.enable_follow_audio = bool(rt_flags.get("enable_follow_audio"))
    if "enable_like_audio" in rt_flags:
        state.enable_like_audio = bool(rt_flags.get("enable_like_audio"))
    if rt_flags.get("follow_like_cooldown_seconds") is not None:
        try:
            state.follow_like_cooldown_seconds = int(rt_flags.get("follow_like_cooldown_seconds"))
        except Exception:
            pass


    anchor_dir = getattr(state, "anchor_audio_dir", None) or str(AUDIO_BASE_DIR)
    state.folder_manager = FolderOrderManager(anchor_dir)

    from audio.voice_reporter import start_reporter_thread
    start_reporter_thread(dispatcher, state)

    router = WSCommandRouter(state, dispatcher)

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

        router.handle(type_)

    ws = WSClient(url=WS_URL, license_key=license_key, on_message=on_ws_message)
    ws.start()

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

        # 降级：只要 must
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

        prefix, reply_text = hit_qa_question(content)

        if prefix:
            app_state.pending_hit = (prefix, reply_text)

            if getattr(app_state, "enable_danmaku_reply", False):
                try:
                    wav = pick_by_prefix(prefix)
                    if wav:
                        dispatcher.push_anchor_keyword(wav)
                except Exception as e:
                    print("anchor keyword error:", e)

            return reply_text

        return ""

    app_state.on_danmaku_cb = on_danmaku

    def on_event(nickname: str, content: str, type_: int):
        ws.push(nickname, content, type_)

        # ===== 视频号事件：关注/点赞触发音频 =====
        # LiveListener: 关注 type_=4 (msgType=20078), 点赞 type_=2 (msgType=20122)
        # 我们统一映射到 WSCommandRouter：-2 关注 / -3 点赞（内部做冷却+开关+入队）
        try:
            if int(type_) == 4:  # 关注
                router.handle(-2)
            elif int(type_) == 2:  # 点赞
                router.handle(-3)
        except Exception as e:
            print("on_event follow/like error:", e)

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

    def listener_thread():
        listener = LiveListener(state=app_state, on_danmaku=on_danmaku, on_event=on_event)
        listener.run(tick=lambda: None)

    threading.Thread(target=listener_thread, daemon=True).start()

    def douyin_listener_thread():
        dy_listener = DouyinListener(state=app_state, on_danmaku=on_danmaku)
        dy_listener.run(tick=lambda: None)

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
