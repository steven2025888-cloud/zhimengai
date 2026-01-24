# core/live_listener.py
import os
import json
import base64
import time
import uuid
from typing import Any, Dict, Callable, Optional

from playwright.sync_api import sync_playwright, Response, Page, Request

from config import (
    LOGIN_URL, LIVE_URL_PREFIX, TARGET_API_KEYWORD, STATE_FILE, HOME_URL
)
from core.state import AppState

AUTO_REPLY_COOLDOWN_SECONDS = 60


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

    if msg_type == 20078:
        return nickname, payload.get("wording", "关注了主播"), 4
    if msg_type == 20122:
        return nickname, payload.get("wording", ""), 2
    return nickname, "", 5


def _safe_get_post_json(req: Request) -> Optional[dict]:
    post = None
    try:
        pdj = getattr(req, "post_data_json", None)
        post = pdj() if callable(pdj) else pdj
    except Exception:
        post = None

    if isinstance(post, dict):
        return post

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
            return json.loads(raw)
        except Exception:
            return None
    return None


def _lower_headers(h: Dict[str, str]) -> Dict[str, str]:
    out = {}
    for k, v in (h or {}).items():
        if not k:
            continue
        out[str(k).lower()] = str(v)
    return out


class LiveListener:
    """
    视频号监听器（保持你原来抓弹幕逻辑不变 + 修复 is_listening 判断 + 增量公屏轮播）
    """

    def __init__(
        self,
        state: AppState,
        on_danmaku: Callable[[str, str], str],
        on_event: Callable[[str, str, int], None],
        hit_qa_question=None,
    ):
        self.state = state
        self.on_danmaku = on_danmaku
        self.on_event = on_event
        self._context = None

        if not hasattr(self.state, "is_listening"):
            self.state.is_listening = False
        if not hasattr(self.state, "live_ready"):
            self.state.live_ready = False

        if not hasattr(self.state, "wx_seen_seq"):
            self.state.wx_seen_seq = set()

        # core/live_listener.py  (在 __init__ 里补字段)
        if not hasattr(self.state, "wx_public_post_url"):
            self.state.wx_public_post_url = None
        if not hasattr(self.state, "wx_public_headers_template"):
            self.state.wx_public_headers_template = {}
        if not hasattr(self.state, "wx_public_body_template"):
            self.state.wx_public_body_template = None


        for k, v in {
            "wx_post_url": None,
            "wx_liveCookies": None,
            "wx_objectId": None,
            "wx_finderUsername": None,
            "wx_liveId": None,
        }.items():
            if not hasattr(self.state, k):
                setattr(self.state, k, v)

        if not hasattr(self.state, "wx_reply_cooldown"):
            self.state.wx_reply_cooldown = {}

        if not hasattr(self.state, "wx_post_headers_template"):
            self.state.wx_post_headers_template = {}

        # ✅ 公屏发送模板（必须手动发一条“公屏消息”让它捕获到模板）
        if not hasattr(self.state, "wx_public_send_body_template"):
            self.state.wx_public_send_body_template = None
        if not hasattr(self.state, "wx_public_send_msg_template"):
            self.state.wx_public_send_msg_template = None

    # ===== 登录缓存：抖音同款 =====
    def _create_context(self, browser):
        state_path = str(STATE_FILE)
        if os.path.exists(state_path):
            print("🔐 使用视频号登录缓存：", state_path, "size=", os.path.getsize(state_path))
            ctx = browser.new_context(storage_state=state_path, no_viewport=True)
        else:
            print("🆕 未发现视频号登录缓存，需要扫码登录：", state_path)
            ctx = browser.new_context(no_viewport=True)

        try:
            cks = ctx.cookies(["https://channels.weixin.qq.com"])
            print("🍪 启动后 cookies(channels.weixin.qq.com) =", len(cks))
        except Exception as e:
            print("⚠️ 读取 cookies 失败：", e)

        return ctx

    def _is_logged_in(self, page: Page) -> bool:
        url = (_get_real_url(page) or "").lower()
        if url.startswith((LIVE_URL_PREFIX or "").lower()):
            return True
        if (HOME_URL or "").lower() and url.startswith((HOME_URL or "").lower()):
            return True
        if "login" in url or "passport" in url or "auth" in url:
            return False
        if "channels.weixin.qq.com" in url:
            return True
        return False

    def _maybe_save_login_state(self, context, page):
        if getattr(self, "_login_state_saved", False):
            return
        if not self._is_logged_in(page):
            return

        try:
            cks = context.cookies(["https://channels.weixin.qq.com"])
            if not cks:
                return
        except Exception:
            return

        try:
            state_path = str(STATE_FILE)
            tmp = state_path + ".tmp"
            context.storage_state(path=tmp)

            st = json.load(open(tmp, "r", encoding="utf-8"))
            cookies = st.get("cookies") if isinstance(st, dict) else None
            if not (isinstance(cookies, list) and len(cookies) > 0):
                print("⚠️ storage_state cookies 为空，取消保存，避免空态污染")
                try:
                    os.remove(tmp)
                except Exception:
                    pass
                return

            os.replace(tmp, state_path)
            self._login_state_saved = True
            print("💾 视频号登录态已保存：", state_path, "size=", os.path.getsize(state_path))
            print("✅ 保存时 cookies =", len(cookies), "url=", _get_real_url(page))

        except Exception as e:
            print("⚠️ 保存视频号登录态失败：", e)

    # ===== 抓参数/headers + ✅公屏模板 =====
    def _handle_request(self, req: Request):
        try:
            if req.method.upper() != "POST":
                return

            url = req.url
            post = _safe_get_post_json(req)

            # 轮询接口：缓存参数，并推导发消息接口
            if "mmfinderassistant-bin/live/msg" in url and isinstance(post, dict):
                self.state.wx_liveCookies = post.get("liveCookies") or self.state.wx_liveCookies
                self.state.wx_objectId = post.get("objectId") or self.state.wx_objectId
                self.state.wx_finderUsername = post.get("finderUsername") or self.state.wx_finderUsername
                self.state.wx_liveId = post.get("liveId") or self.state.wx_liveId

                # ✅补：保存 headers 模板（后面公屏/回复都能复用）
                self.state.wx_post_headers_template = dict(req.headers or {})

                if not self.state.wx_post_url:
                    self.state.wx_post_url = url.replace(
                        "mmfinderassistant-bin/live/msg",
                        "mmfinderassistant-bin/live/post_live_app_msg"
                    )
                    print("✅ 已由 live/msg 推导 wx_post_url =", self.state.wx_post_url)
                return

            # ✅ 公屏手动发送接口：post_live_msg（按你提供的可用数据）
            if "mmfinderassistant-bin/live/post_live_msg" in url and isinstance(post, dict):
                # 保存公屏发送 URL + headers + body 模板
                self.state.wx_public_post_url = url
                self.state.wx_public_headers_template = dict(req.headers or {})
                self.state.wx_public_body_template = dict(post)

                # 同步关键参数（方便兜底）
                self.state.wx_liveCookies = post.get("liveCookies") or self.state.wx_liveCookies
                self.state.wx_objectId = post.get("objectId") or self.state.wx_objectId
                self.state.wx_finderUsername = post.get("finderUsername") or self.state.wx_finderUsername
                self.state.wx_liveId = post.get("liveId") or self.state.wx_liveId

                print("✅ 已捕获 视频号公屏接口 post_live_msg 模板")
                return

        except Exception as e:
            print("⚠️ _handle_request error:", e)

    # ===== ✅直接发公屏（复用模板，不猜 msgType）=====
    def send_public_text(self, text: str) -> bool:
        """
        ✅ 视频号公屏发送（优先模板；无模板也能兜底发送）
        接口：/mmfinderassistant-bin/live/post_live_msg
        msgJson：{"content":"xxx","type":1}
        """
        text = (text or "").strip()
        if not text:
            return False
        if not self._context:
            print("⚠️ 视频号公屏发送条件未就绪（context缺失）")
            return False

        # 1) URL：优先捕获的公屏 URL；否则由回复 URL 推导
        url = (getattr(self.state, "wx_public_post_url", "") or "").strip()
        if not url:
            wx_post_url = (getattr(self.state, "wx_post_url", "") or "").strip()
            if wx_post_url:
                url = wx_post_url.replace("post_live_app_msg", "post_live_msg")

        if not url:
            print("⚠️ 视频号公屏发送失败：既没有抓到 wx_public_post_url，也无法从 wx_post_url 推导")
            return False

        # 2) body：有模板就克隆模板；无模板就按回复逻辑组装一个最小可用包
        body_tpl = getattr(self.state, "wx_public_body_template", None)
        if isinstance(body_tpl, dict):
            body = dict(body_tpl)
        else:
            # ✅兜底：按 state 组包（和回复逻辑同字段体系）
            if not all([self.state.wx_liveCookies, self.state.wx_objectId, self.state.wx_finderUsername,
                        self.state.wx_liveId]):
                print("⚠️ 视频号公屏兜底组包失败：liveCookies/objectId/finderUsername/liveId 不齐全")
                return False
            body = {
                "liveCookies": self.state.wx_liveCookies,
                "objectId": self.state.wx_objectId,
                "finderUsername": self.state.wx_finderUsername,
                "liveId": self.state.wx_liveId,
                "_log_finder_uin": "",
                "_log_finder_id": self.state.wx_finderUsername,
                "rawKeyBuff": None,
                "pluginSessionId": None,
                "scene": 7,
                "reqScene": 7,
            }

        # 3) 强制覆盖关键字段（避免模板旧了导致发不出去）
        if self.state.wx_liveCookies:
            body["liveCookies"] = self.state.wx_liveCookies
        if self.state.wx_objectId:
            body["objectId"] = self.state.wx_objectId
        if self.state.wx_finderUsername:
            body["finderUsername"] = self.state.wx_finderUsername
            body["_log_finder_id"] = self.state.wx_finderUsername
            body["_log_finder_uin"] = body.get("_log_finder_uin", "") or ""
        if self.state.wx_liveId:
            body["liveId"] = self.state.wx_liveId

        body["msgJson"] = json.dumps({"content": text, "type": 1}, ensure_ascii=False)
        body["clientMsgId"] = f"pc_{self.state.wx_finderUsername}_{uuid.uuid4()}"
        body["timestamp"] = str(int(time.time() * 1000))
        body.setdefault("scene", 7)
        body.setdefault("reqScene", 7)

        # 4) headers：优先公屏模板 headers，其次回复模板 headers；再不行就最小 headers
        headers_tpl = getattr(self.state, "wx_public_headers_template", None) or {}
        if not headers_tpl:
            headers_tpl = getattr(self.state, "wx_post_headers_template", None) or {}

        headers = dict(headers_tpl) if isinstance(headers_tpl, dict) else {}
        # 删掉容易冲突/无意义的
        for k in ["content-length", "Content-Length", "host", "Host"]:
            headers.pop(k, None)

        # 统一 content-type（避免同时存在 Content-Type 和 content-type）
        headers.pop("content-type", None)
        headers.pop("Content-Type", None)
        headers["Content-Type"] = "application/json"

        try:
            resp = self._context.request.post(
                url,
                data=json.dumps(body, ensure_ascii=False),
                headers=headers,
                timeout=10_000
            )
            ok = 200 <= resp.status < 300
            print("📢 视频号公屏发送 status=", resp.status, "ok=", ok)
            if not ok:
                try:
                    print("   ↪ resp.text(head800) =", (resp.text() or "")[:800].replace("\n", "\\n"))
                except Exception:
                    pass
            return ok
        except Exception as e:
            print("❌ 视频号公屏发送异常：", e)
            return False

    # ✅ 给 entry_service tick 用：处理公屏队列
    def process_public_screen_queue(self):
        import queue as _q
        q = getattr(self.state, "public_screen_queue_wx", None)
        if not q:
            return
        for _ in range(3):
            try:
                text = q.get_nowait()
            except _q.Empty:
                break
            try:
                self.send_public_text(text)
            except Exception as e:
                print("⚠️ process_public_screen_queue(wx) error:", e)

    # ===== 发送文字回复（你原版不动）=====
    def _send_reply_to_user(self, m: dict, text: str) -> bool:
        if not self._context or not self.state.wx_post_url:
            print("⚠️ 视频号发送条件未就绪（wx_post_url/context缺失）")
            return False

        finder = m.get("finder_live_contact") or m.get("finderLiveContact") or {}
        contact = (finder.get("contact") or {}) if isinstance(finder, dict) else {}
        to_username = contact.get("username")
        if not to_username:
            print("⚠️ 找不到对方 username")
            return False

        payload_b64 = base64.b64encode(
            json.dumps({"content": text}, ensure_ascii=False).encode("utf-8")
        ).decode("utf-8")

        cid = f"pc_{self.state.wx_finderUsername}_{uuid.uuid4()}"
        msg = {
            "client_msg_id": cid,
            "clientMsgId": cid,
            "to_user_contact": finder,
            "toUserContact": finder,
            "msg_type": 20002,
            "msgType": 20002,
            "payload": payload_b64
        }

        body = {
            "liveCookies": self.state.wx_liveCookies,
            "objectId": self.state.wx_objectId,
            "finderUsername": self.state.wx_finderUsername,
            "liveId": self.state.wx_liveId,
            "msgJson": json.dumps(msg, ensure_ascii=False),
            "timestamp": str(int(time.time() * 1000)),
            "_log_finder_uin": "",
            "_log_finder_id": self.state.wx_finderUsername,
            "rawKeyBuff": None,
            "pluginSessionId": None,
            "scene": 7,
            "reqScene": 7
        }

        try:
            tpl = _lower_headers(self.state.wx_post_headers_template or {})
            headers = {"content-type": "application/json"}

            for k in [
                "user-agent", "referer", "origin", "accept", "accept-language",
                "sec-ch-ua", "sec-ch-ua-platform", "sec-ch-ua-mobile",
                "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest",
                "cookie",
            ]:
                if tpl.get(k):
                    headers[k] = tpl.get(k)

            resp = self._context.request.post(
                self.state.wx_post_url,
                data=json.dumps(body, ensure_ascii=False),
                headers=headers,
                timeout=10_000
            )
            print("📨 视频号自动回复 status=", resp.status)

            if not (200 <= resp.status < 300):
                try:
                    print("   ↪ resp.text(head800) =", (resp.text() or "")[:800].replace("\n", "\\n"))
                except Exception:
                    pass

            return 200 <= resp.status < 300

        except Exception as e:
            print("❌ 视频号发送异常：", e)
            return False

    def _auto_reply_by_text(self, m: dict, reply_text: str):
        reply_text = (reply_text or "").strip()
        if not reply_text:
            return

        finder = m.get("finder_live_contact") or m.get("finderLiveContact") or {}
        contact = (finder.get("contact") or {}) if isinstance(finder, dict) else {}
        to_username = contact.get("username") or ""
        if not to_username:
            return

        now = time.time()
        last = self.state.wx_reply_cooldown.get(to_username, 0)
        if now - last < AUTO_REPLY_COOLDOWN_SECONDS:
            return

        if self._send_reply_to_user(m, reply_text):
            self.state.wx_reply_cooldown[to_username] = now
            print("✅ 视频号自动回复成功")
        else:
            print("❌ 视频号自动回复失败（已打印失败原因）")

    # ===== ✅修复：监听状态更稳（startswith -> contains 兜底）=====
    def _update_listen_state(self, page: Page, reason: str = ""):
        url = _get_real_url(page)
        prefix = (LIVE_URL_PREFIX or "")
        should = bool(prefix and (url.startswith(prefix) or (prefix in url)))

        if should and not self.state.is_listening:
            self.state.is_listening = True
            self.state.live_ready = True
            print(f"🎬 已进入视频号直播控制台（{reason}）URL={url}")

            try:
                if getattr(self.state, "audio_dispatcher", None) and not self.state.audio_dispatcher.current_playing:
                    self.state.audio_dispatcher.start_folder_cycle()
            except Exception as e:
                print("⚠️ 启动轮播失败：", e)

        elif (not should) and self.state.is_listening:
            self.state.is_listening = False
            print("🚪 已离开视频号直播页（不中断播放）")

    # ===== 处理消息（你原版不动）=====
    def _handle_live_msg_json(self, inner: Dict[str, Any]):
        for m in inner.get("msg_list", []):
            seq_raw = m.get("seq")
            if not seq_raw:
                continue
            seq = str(seq_raw)
            if seq in self.state.wx_seen_seq:
                continue
            self.state.wx_seen_seq.add(seq)

            finder = m.get("finder_live_contact") or m.get("finderLiveContact") or {}
            is_self = (
                finder.get("is_self") is True or finder.get("isSelf") is True or
                finder.get("is_self_for_web") is True or finder.get("isSelfForWeb") is True
            )
            if is_self:
                continue

            t = int(m.get("type") or 0)
            nickname = m.get("nickname", "") or "未知用户"
            content = m.get("content", "") or ""

            if t == 1:
                print(f"💬 视频号弹幕｜{nickname}：{content}")

                reply_text = ""
                try:
                    reply_text = self.on_danmaku(nickname, content) or ""
                except TypeError:
                    self.on_danmaku(nickname, content)
                    reply_text = ""

                if not getattr(self.state, "enable_auto_reply", False):
                    if reply_text.strip():
                        print("💤 文本自动回复已关闭，本次仅命中关键词，不发文字")
                    continue

                if reply_text.strip():
                    self._auto_reply_by_text(m, reply_text)

            elif t == 10005:
                print(f"👋 进场｜{nickname} 进入直播间")
                self.on_event(nickname, "进入直播间", 3)

        for app_msg in inner.get("app_msg_list", []):
            seq = app_msg.get("seq")
            if seq:
                seq_s = str(seq)
                if seq_s in self.state.wx_seen_seq:
                    continue
                self.state.wx_seen_seq.add(seq_s)

            nickname, content, type_ = _parse_app_msg(app_msg)
            self.on_event(nickname, content, type_)

    # ===== ✅修复：不要硬依赖 is_listening 才解析（兜底）=====
    def _handle_response(self, resp: Response):
        if TARGET_API_KEYWORD not in resp.url:
            return

        # ✅ 即使 is_listening 还没置 True，也尝试解析一次（防止 URL 变体导致“永远不进”）
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

        # 如果这时还没 listening，但已经能解析到消息，顺手认为“已在直播页”
        if not self.state.is_listening:
            self.state.is_listening = True
            self.state.live_ready = True
            print("✅ 通过消息流自动判定已进入直播页（listening=True）")

        self._handle_live_msg_json(inner)

    # ===== 主循环（你原版不动）=====
    def run(self, tick: Callable[[], None]):
        with sync_playwright() as p:

            user_data_dir = os.path.join(os.getcwd(), "wx_user_data")  # 建议放到 app 数据目录更好
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
                no_viewport=True,
            )
            self._context = context
            page = context.pages[0] if context.pages else context.new_page()

            page.on("request", self._handle_request)
            page.on("response", self._handle_response)

            start_url = HOME_URL or LOGIN_URL
            try:
                page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
                print("👉 视频号已打开：", start_url)
            except Exception as e:
                print("⚠️ 视频号打开失败，回退登录：", e)
                page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)

            last_url = ""
            while True:
                url = _get_real_url(page)
                if url != last_url:
                    last_url = url
                    print("🔁 视频号 URL：", url)

                self._update_listen_state(page, reason="poll")
                self._maybe_save_login_state(context, page)

                tick()
                time.sleep(0.3)
