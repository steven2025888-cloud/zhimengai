# core/douyin_live_listener.py
import time
from typing import Any, Dict, Callable
from playwright.sync_api import sync_playwright, Response, Page

from config import (
    DOUYIN_STATE_FILE,
    DOUYIN_LOGIN_URL,      # https://buyin.jinritemai.com/
    DOUYIN_DASHBOARD_URL,  # https://buyin.jinritemai.com/dashboard/live/control
    DOUYIN_API_KEYWORD     # /api/anchor/comment/info
)

import random, glob, os

def pick_random_explain_audio():
    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "audio_assets")
    base_dir = os.path.abspath(base_dir)
    files = glob.glob(os.path.join(base_dir, "讲解*.mp3")) + glob.glob(os.path.join(base_dir, "讲解*.wav"))
    if not files:
        raise RuntimeError("未找到讲解音频文件")
    return random.choice(files)



def _get_real_url(page: Page) -> str:
    try:
        return page.evaluate("location.href")
    except Exception:
        return page.url


class DouyinListener:
    """
    抖音直播监听器（结构完全对齐视频号 LiveListener）
    - 监听 URL 变化
    - 进入控制台才开启监听
    - 监听 /api/anchor/comment/info
    - 过滤管理员（无 tags）
    """
    def __init__(
        self,
        state: AppState,
        on_danmaku: Callable[[str, str], None],
    ):
        self.state = state
        self.on_danmaku = on_danmaku
        self.state.dy_is_listening = False

    def _update_listen_state(self, page: Page, reason: str = ""):
        url = _get_real_url(page)
        should = url.startswith(DOUYIN_DASHBOARD_URL)

        if should and not self.state.dy_is_listening:
            self.state.dy_is_listening = True
            self.state.live_ready = True

            print("🎬 已进入抖音直播控制台，启动完整直播系统（讲解 + 报时 + TTS）")
            print(f"🎧 抖音监听状态切换：True（{reason}） 当前URL={url}")

            # ① 启动随机讲解
            if not self.state.audio_dispatcher.current_playing:
                try:
                    wav = pick_random_explain_audio()
                    print("▶️ 启动首条随机讲解：", wav)
                    self.state.audio_dispatcher.push_random(wav)
                except Exception as e:
                    print("⚠️ 启动随机讲解失败：", e)

            # ② 启动语音报时线程（需开关打开）
            if self.state.enable_voice_report and not getattr(self.state, "report_thread_started", False):
                from audio.voice_reporter import voice_report_loop
                import threading

                t = threading.Thread(
                    target=voice_report_loop,
                    args=(self.state, self.state.audio_dispatcher),
                    daemon=True
                )
                t.start()

                self.state.report_thread_started = True
                print("⏱ 已启动语音报时线程（开关已开启）")

    def _handle_comment_json(self, data: Dict[str, Any]):
        comments = data.get("data", {}).get("comment_infos", [])
        internal_ext = data.get("data", {}).get("internal_ext", "")

        # 从 internal_ext 解析主播 uid
        anchor_uid = None
        for part in internal_ext.split("|"):
            if part.startswith("wss_push_did:"):
                anchor_uid = part.split(":", 1)[1]
                break

        for c in comments:
            cid = c.get("comment_id")
            if not cid or cid in self.state.seen_seq:
                continue
            self.state.seen_seq.add(cid)

            uid = str(c.get("uid", ""))

            # ⭐ 按真实规则过滤管理员（主播自己）
            if anchor_uid and uid == anchor_uid:
                print(f"🙈 跳过抖音主播/管理员：{c.get('nick_name')} -> {c.get('content')}")
                continue

            nickname = c.get("nick_name", "未知用户")
            content = c.get("content", "")

            print(f"🎤 抖音弹幕｜{nickname}：{content}")
            self.on_danmaku(nickname, content)

    def _handle_response(self, resp: Response):
        if not self.state.dy_is_listening:
            return
        if DOUYIN_API_KEYWORD not in resp.url:
            return

        try:
            data = resp.json()
        except Exception:
            return

        self._handle_comment_json(data)

    def _maybe_save_login_state(self, context, page):
        if getattr(self, "_login_state_saved", False):
            return

        url = _get_real_url(page)

        # ✅ 进入控制台才保存（避免保存半登录态）
        if not url.startswith(DOUYIN_DASHBOARD_URL):
            return

        try:
            context.storage_state(path=DOUYIN_STATE_FILE)
            self._login_state_saved = True
            print("💾 抖音登录态已保存：", DOUYIN_STATE_FILE)
            print("💾 文件存在：", os.path.exists(DOUYIN_STATE_FILE))
        except Exception as e:
            print("⚠️ 保存抖音登录态失败：", e)

    def _create_context(self, browser):
        if os.path.exists(DOUYIN_STATE_FILE):
            print("🔐 使用抖音登录缓存：", DOUYIN_STATE_FILE)
            return browser.new_context(storage_state=DOUYIN_STATE_FILE, no_viewport=True)

        print("🆕 未发现抖音登录缓存，需要登录")
        return browser.new_context(no_viewport=True)

    def run(self, tick: Callable[[], None]):
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
            )
            context = self._create_context(browser)



            page = context.new_page()
            page.on("response", self._handle_response)

            # 初始进入抖音登录页或控制台
            try:
                page.goto(DOUYIN_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
                print("👉 已打开抖音登录页：", DOUYIN_LOGIN_URL)
            except Exception as e:
                print("⚠️ 打开抖音失败：", e)

            last_url = ""

            while True:
                url = _get_real_url(page)

                if url != last_url:
                    last_url = url
                    print(f"🔁 抖音 URL 变化：{url}")
                    self._update_listen_state(page, reason="url changed")

                self._maybe_save_login_state(context, page)
                self._update_listen_state(page, reason="poll")
                tick()
                time.sleep(0.3)




