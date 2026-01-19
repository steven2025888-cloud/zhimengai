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
import uuid
from playwright.sync_api import sync_playwright, Response, Page, Request
from copy import deepcopy

# ✅自动回复配置（改为：由关键词命中返回的“自动回复内容”驱动，不再写死“挺好的”）
AUTO_REPLY_COOLDOWN_SECONDS = 60  # 同一用户 60 秒内只回一次

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

        if not hasattr(self.state, "wx_post_url"):
            self.state.wx_post_url = None  # ✅发消息接口 post_live_app_msg

        # ✅给 state 补默认字段（不改 state.py 也能跑）
        if not hasattr(self.state, "wx_send_url"):
            self.state.wx_send_url = None
        if not hasattr(self.state, "wx_liveCookies"):
            self.state.wx_liveCookies = None
        if not hasattr(self.state, "wx_objectId"):
            self.state.wx_objectId = None
        if not hasattr(self.state, "wx_finderUsername"):
            self.state.wx_finderUsername = None
        if not hasattr(self.state, "wx_liveId"):
            self.state.wx_liveId = None
        if not hasattr(self.state, "wx_reply_cooldown"):
            self.state.wx_reply_cooldown = {}  # username -> last_ts

        # ✅保存 context 方便发请求
        self._context = None



    # ✅抓取轮询请求体字段（复用同一个接口做发送）
    def _handle_request(self, req: Request):
        try:
            if req.method.upper() != "POST":
                return

            url = req.url

            # 取 POST JSON
            post = None

            # ✅兼容：post_data_json 可能是 “方法” 也可能是 “属性”
            try:
                pdj = getattr(req, "post_data_json", None)
                post = pdj() if callable(pdj) else pdj
            except Exception:
                post = None

            # ✅兜底：拿原始 post_data 再 json.loads
            if not isinstance(post, dict):
                raw = ""
                try:
                    pd = getattr(req, "post_data", None)
                    raw = pd() if callable(pd) else (pd or "")
                except Exception:
                    raw = ""

                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8", "ignore")

                raw = (raw or "").strip()
                if raw.startswith("{"):
                    try:
                        post = json.loads(raw)
                    except Exception:
                        post = None



            # ✅轮询接口：缓存必要参数（liveCookies / objectId / finderUsername / liveId）
            if "mmfinderassistant-bin/live/msg" in url:
                # ✅post 不是 dict 就别往下走，避免 post.get 报错
                if not isinstance(post, dict):
                    return

                self.state.wx_liveCookies = post.get("liveCookies") or self.state.wx_liveCookies
                self.state.wx_objectId = post.get("objectId") or self.state.wx_objectId
                self.state.wx_finderUsername = post.get("finderUsername") or self.state.wx_finderUsername
                self.state.wx_liveId = post.get("liveId") or self.state.wx_liveId

                # ✅关键：没有捕获到 post_live_app_msg 时，直接由 live/msg 推导发送接口
                if not self.state.wx_post_url:
                    self.state.wx_post_url = url.replace(
                        "mmfinderassistant-bin/live/msg",
                        "mmfinderassistant-bin/live/post_live_app_msg"
                    )
                    print("✅ 已由 live/msg 推导 wx_post_url =", self.state.wx_post_url)

                return

            # ✅发送接口：保存 post_live_app_msg 的完整 URL（带 _aid/_rid/_pageUrl）
            if "mmfinderassistant-bin/live/post_live_app_msg" in url:
                if not isinstance(post, dict):
                    return
                self.state.wx_post_url = url
                # 顺手也更新关键字段（一般这里也会带）
                self.state.wx_liveCookies = post.get("liveCookies") or self.state.wx_liveCookies
                self.state.wx_objectId = post.get("objectId") or self.state.wx_objectId
                self.state.wx_finderUsername = post.get("finderUsername") or self.state.wx_finderUsername
                self.state.wx_liveId = post.get("liveId") or self.state.wx_liveId
                print("✅ 已捕获发消息接口 wx_post_url")

                # ✅保存一份模板（第一次抓到就存）
                if not getattr(self.state, "wx_post_template", None) and isinstance(post, dict):
                    self.state.wx_post_template = post
                    print("✅ 已捕获管理员发送模板（wx_post_template）")

                return

        except Exception as e:
            print("⚠️ _handle_request error:", e)
            return

    # ✅真正发“定向回复”
    def _send_reply_to_user(self, m: dict, text: str) -> bool:
        tpl = getattr(self.state, "wx_post_template", None)
        if not isinstance(tpl, dict):
            print("⚠️ 还没抓到 wx_post_template：请在页面手动发一次消息（比如'测试'）")
            return False
        if not self.state.wx_post_url:
            print("⚠️ wx_post_url 为空，无法发送")
            return False
        if not self._context:
            print("⚠️ Playwright context 未就绪，无法发送")
            return False

        # 取目标用户
        finder = m.get("finder_live_contact") or m.get("finderLiveContact") or {}
        contact = (finder.get("contact") or {}) if isinstance(finder, dict) else {}
        to_username = contact.get("username") or m.get("username") or ""
        to_nickname = contact.get("nickname") or m.get("nickname") or "用户"
        if not to_username:
            print("⚠️ 找不到对方 username，无法回复")
            return False

        payload_b64 = base64.b64encode(
            json.dumps({"content": text}, ensure_ascii=False).encode("utf-8")
        ).decode("utf-8")

        # ✅只用一份 body：deepcopy + 覆盖动态字段 + 改 msgJson + 发
        body = deepcopy(tpl)

        # ✅动态字段用最新 state 覆盖（很重要）
        if self.state.wx_liveCookies:
            body["liveCookies"] = self.state.wx_liveCookies
        if self.state.wx_objectId:
            body["objectId"] = self.state.wx_objectId
        if self.state.wx_finderUsername:
            body["finderUsername"] = self.state.wx_finderUsername
            body["_log_finder_id"] = self.state.wx_finderUsername
        if self.state.wx_liveId:
            body["liveId"] = self.state.wx_liveId

        body["timestamp"] = str(int(time.time() * 1000))

        msg = json.loads(body.get("msgJson") or "{}")

        # client msg id
        if "client_msg_id" in msg:
            msg["client_msg_id"] = f"pc_{self.state.wx_finderUsername}_{uuid.uuid4()}"
        if "clientMsgId" in msg:
            msg["clientMsgId"] = f"pc_{self.state.wx_finderUsername}_{uuid.uuid4()}"

        # to_user_contact
        key = "to_user_contact" if "to_user_contact" in msg else (
            "toUserContact" if "toUserContact" in msg else "to_user_contact")
        tuc = msg.get(key) or {}
        c = tuc.get("contact") or {}
        c["username"] = to_username
        c["nickname"] = to_nickname
        tuc["contact"] = c
        msg[key] = tuc

        # ✅关键：payload 必须写在 msg 顶层
        msg["payload"] = payload_b64

        body["msgJson"] = json.dumps(msg, ensure_ascii=False)

        resp = self._context.request.post(
            self.state.wx_post_url,
            data=json.dumps(body, ensure_ascii=False),
            headers={"content-type": "application/json"},
            timeout=10_000
        )
        print("📨 自动回复发送 status=", resp.status)
        return 200 <= resp.status < 300

    # ✅弹幕触发自动回复（由上层“关键词命中”提供回复文本）
    def _auto_reply_by_text(self, m: Dict[str, Any], reply_text: str):
        reply_text = (reply_text or "").strip()
        if not reply_text:
            return

        # 冷却（同一用户 N 秒内只回一次）
        finder = m.get("finder_live_contact") or m.get("finderLiveContact") or {}
        contact = (finder.get("contact") or {}) if isinstance(finder, dict) else {}
        to_username = contact.get("username") or m.get("username") or ""
        if not to_username:
            return

        now = time.time()
        last = self.state.wx_reply_cooldown.get(to_username, 0)
        if now - last < AUTO_REPLY_COOLDOWN_SECONDS:
            return

        print(f"🎯 触发关键词自动回复：{reply_text}")
        if self._send_reply_to_user(m, reply_text):
            self.state.wx_reply_cooldown[to_username] = now
            print("✅ 自动回复成功")
        else:
            print("❌ 自动回复失败（看上面缺的字段/状态码）")

    def _update_listen_state(self, page: Page, reason: str = ""):
        url = _get_real_url(page)
        should = url.startswith(LIVE_URL_PREFIX)

        # ✅只在变化时打印一次
        if not hasattr(self, "_last_wx_post_url"):
            self._last_wx_post_url = None

        cur = self.state.wx_post_url
        if cur and cur != self._last_wx_post_url:
            print("✅ wx_post_url 已就绪 =", cur)
            self._last_wx_post_url = cur
        elif (not cur) and self._last_wx_post_url:
            print("⚠️ wx_post_url 丢失/被清空")
            self._last_wx_post_url = None

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
            if self.state.enable_voice_report and not getattr(self.state, "report_thread_started", False):
                from audio.voice_reporter import voice_report_loop
                import threading

                threading.Thread(
                    target=voice_report_loop,
                    args=(self.state, self.state.audio_dispatcher),
                    daemon=True
                ).start()

                self.state.report_thread_started = True
                print("⏱ 视频号语音报时线程已启动（开关已开启）")


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

            try:
                t = int(m.get("type") or 0)
            except Exception:
                t = 0
            nickname = m.get("nickname", "") or "未知用户"
            content = m.get("content", "") or ""

            if t == 1:
                print(f"💬 弹幕｜{nickname}：{content}")
                # 📣 弹幕自动回复总开关
                if not self.state.enable_danmaku_reply:
                    continue  # 或 continue，看你是否还要走音频逻辑


                # ✅把“自动回复”从写死关键词，改为：由 on_danmaku（关键词命中逻辑）返回回复文本
                ret = None
                try:
                    ret = self.on_danmaku(nickname, content)
                except TypeError:
                    self.on_danmaku(nickname, content)

                # ✅兼容：上层不 return，但把结果塞到 state 里
                reply_text = ret if isinstance(ret, str) else getattr(self.state, "pending_auto_reply_text", None)

                # 🔥 总开关控制
                if not self.state.enable_auto_reply:
                    if isinstance(reply_text, str) and reply_text.strip():
                        print("💤 自动回复已关闭，本次仅命中关键词，不发送文字回复")
                    continue  # ❗ 只跳过当前这条弹幕，不退出整个监听函数

                if isinstance(reply_text, str) and reply_text.strip():
                    self._auto_reply_by_text(m, reply_text)

                    if hasattr(self.state, "pending_auto_reply_text"):
                        self.state.pending_auto_reply_text = None




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
        if TARGET_API_KEYWORD not in resp.url:
            return

        if not self.state.is_listening:
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
            self._context = context
            page = context.new_page()

            page.on("request", self._handle_request)  # ✅新增
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
