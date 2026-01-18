# core/live_listener.py
import os
import json
import base64
import time
from typing import Any, Dict, Callable, Optional
from playwright.sync_api import sync_playwright, Response, Page

from config import (
    LOGIN_URL, LIVE_URL_PREFIX, TARGET_API_KEYWORD, STATE_FILE,HOME_URL,DOUYIN_DASHBOARD_URL
)



from core.state import AppState

def _get_real_url(page: Page) -> str:
    try:
        return page.evaluate("location.href")
    except Exception:
        return page.url

def _extract_nickname(app_msg: Dict[str, Any]) -> str:
    from_user = app_msg.get("fromUserContact") or app_msg.get("from_user_contact") or {}
    contact = from_user.get("contact") or {}
    nickname = (
        contact.get("nickname")
        or from_user.get("displayNickname")
        or from_user.get("display_nickname")
    )
    return nickname or "未知用户"

def _parse_app_msg(app_msg: Dict[str, Any]):
    msg_type = app_msg.get("msgType") or app_msg.get("msg_type")
    nickname = _extract_nickname(app_msg)

    payload_b64 = app_msg.get("payload")
    payload = {}
    if payload_b64:
        try:
            payload = json.loads(base64.b64decode(payload_b64).decode("utf-8"))
        except Exception:
            payload = {}

    # 关注
    if msg_type == 20078:
        wording = payload.get("wording", "关注了主播")
        return nickname, wording, 4

    # 点赞
    if msg_type == 20122:
        wording = payload.get("wording", "")
        return nickname, wording, 2

    return nickname, "", 5

class LiveListener:
    """
    Playwright 监听器：
    - 监听页面 response
    - 解析 msg_list / app_msg_list
    - 回调 on_danmaku / on_event
    """
    def __init__(
        self,
        state: AppState,
        on_danmaku: Callable[[str, str], None],
        on_event: Callable[[str, str, int], None],
    ):
        self.state = state
        self.on_danmaku = on_danmaku
        self.on_event = on_event

    def _update_listen_state(self, page: Page, reason: str = ""):
        url = _get_real_url(page)
        should = url.startswith(LIVE_URL_PREFIX)  # 视频号直播控制页

        # 进入直播
        if should and not self.state.is_listening:
            self.state.is_listening = True
            self.state.live_ready = True

            print("🎬 已进入视频号直播控制台，启动讲解 / 报时 / TTS")
            print(f"🎧 监听状态切换：True（{reason}） 当前URL={url}")

            # 启动随机讲解
            from config import PREFIX_RANDOM
            from audio.audio_picker import pick_by_prefix

            if not self.state.audio_dispatcher.current_playing:
                try:
                    wav = pick_by_prefix(PREFIX_RANDOM)
                    self.state.audio_dispatcher.push_random(wav)
                except Exception as e:
                    print("⚠️ 启动随机讲解失败：", e)

            # 启动报时线程（只启动一次）
            if not getattr(self.state, "report_thread_started", False):
                from audio.voice_reporter import voice_report_loop
                import threading
                threading.Thread(
                    target=voice_report_loop,
                    args=(self.state, self.state.audio_dispatcher),
                    daemon=True
                ).start()
                self.state.report_thread_started = True
                print("⏱ 视频号语音报时线程已启动")

        # 离开直播
        elif not should and self.state.is_listening:
            self.state.is_listening = False
            print("🚪 已离开视频号直播页（不中断播放与报时）")

    def _create_context(self, browser):
        if os.path.exists(STATE_FILE):
            print("🔐 使用登录缓存：", STATE_FILE)
            return browser.new_context(storage_state=STATE_FILE, no_viewport=True)

        print("🆕 未发现登录缓存，需要扫码登录")
        return browser.new_context(no_viewport=True)

    def _maybe_save_login_state(self, context, page):
        if getattr(self, "_login_state_saved", False):
            return

        url = _get_real_url(page)

        # ✅ 只要不在 login.html，就保存一次
        if "login.html" in url:
            return

        try:
            context.storage_state(path=STATE_FILE)
            self._login_state_saved = True
            print("💾 登录态已保存：", STATE_FILE, " url=", url)
            print("💾 文件存在：", os.path.exists(STATE_FILE))
        except Exception as e:
            print("⚠️ 保存登录态失败：", e)

    def _handle_live_msg_json(self, inner: Dict[str, Any]):
        # msg_list：弹幕/进场
        for m in inner.get("msg_list", []):
            seq_raw = m.get("seq")
            if not seq_raw:
                continue

            seq = str(seq_raw)
            if seq in self.state.seen_seq:
                continue
            self.state.seen_seq.add(seq)

            # 过滤主播 / 管理员自己发的消息
            finder = m.get("finder_live_contact") or m.get("finderLiveContact") or {}
            contact = finder.get("contact") or {}

            is_self = (
                    finder.get("is_self") is True or
                    finder.get("isSelf") is True or
                    finder.get("is_self_for_web") is True or
                    finder.get("isSelfForWeb") is True
            )

            if is_self:
                print(f"🙈 已过滤管理员/主播消息：{m.get('nickname')} -> {m.get('content')}")
                continue



            t = m.get("type")
            nickname = m.get("nickname", "") or "未知用户"
            content = m.get("content", "") or ""

            if t == 1:
                print(f"💬 弹幕｜{nickname}：{content}")
                self.on_danmaku(nickname, content)

            elif t == 10005:
                print(f"👋 进场｜{nickname} 进入直播间")
                self.on_event(nickname, "进入直播间", 3)

        # app_msg_list：点赞/关注
        for app_msg in inner.get("app_msg_list", []):
            seq = app_msg.get("seq")
            if seq and seq in self.state.seen_seq:
                continue
            if seq:
                self.state.seen_seq.add(seq)

            nickname, content, type_ = _parse_app_msg(app_msg)
            if type_ == 2:
                print(f"👍 点赞｜{nickname} {content}")
            elif type_ == 4:
                print(f"⭐ 关注｜{nickname} {content}")
            else:
                print(f"❓ 未知｜{nickname}")

            self.on_event(nickname, content, type_)

    def _handle_response(self, resp: Response):
        if not self.state.is_listening:
            return
        if TARGET_API_KEYWORD not in resp.url:
            return

        try:
            outer = resp.json()
        except Exception:
            return

        resp_json_str = outer.get("data", {}).get("respJsonStr")
        if not resp_json_str:
            return

        try:
            inner = json.loads(resp_json_str)
        except Exception:
            return

        self._handle_live_msg_json(inner)

    def simulate_follow(self, nickname="测试关注用户"):
        """
        手动模拟一次关注事件（type=4）
        """
        print(f"🧪 模拟关注：{nickname}")
        self.on_event(nickname, "关注了主播", 4)


    def run(self, tick: Callable[[], None]):
        """
        tick：主循环每次迭代要做的事（例如音频 dispatcher.process_once）
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
            )
            context = self._create_context(browser)
            page = context.new_page()

            page.on("response", self._handle_response)

            start_url = LOGIN_URL
            if os.path.exists(STATE_FILE):
                start_url = HOME_URL

            start_url = HOME_URL if os.path.exists(STATE_FILE) else LOGIN_URL

            try:
                page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
                print("👉 已打开：", start_url)
            except Exception as e:
                print("⚠️ 直达首页失败，回退到登录页：", e)
                page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)

            last_url = ""

            while True:
                url = _get_real_url(page)

                if url != last_url:
                    last_url = url
                    print(f"🔁 URL 变化：{url}")
                    self._update_listen_state(page, reason="url changed")

                self._maybe_save_login_state(context, page)
                self._update_listen_state(page, reason="poll")

                # 交给 main 注入的 tick（音频在主线程播放）
                tick()

                time.sleep(0.3)
