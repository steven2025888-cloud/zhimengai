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
    视频号监听器（稳定版 + 抖音同款 storage_state 登录缓存）：
    - 监听直播控制台
    - 抓 live/msg 参数并推导 wx_post_url
    - 抓管理员手动发送的 post_live_app_msg，保存 headers 模板（更稳）
    - on_danmaku 做关键词/语音；这里负责发文字（enable_auto_reply 控制）
    - 登录缓存：STATE_FILE（Path），第一次扫码，进入 LIVE_URL_PREFIX 后自动保存
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

    # ===== 登录缓存േഴ്：抖音同款 =====
    def _create_context(self, browser):
        state_path = str(STATE_FILE)
        if os.path.exists(state_path):
            print("🔐 使用视频号登录缓存：", state_path, "size=", os.path.getsize(state_path))
            ctx = browser.new_context(storage_state=state_path, no_viewport=True)
        else:
            print("🆕 未发现视频号登录缓存，需要扫码登录：", state_path)
            ctx = browser.new_context(no_viewport=True)

        # ✅ 关键：启动就打印当前 cookies 数量，立刻判断“加载到底生效没”
        try:
            cks = ctx.cookies(["https://channels.weixin.qq.com"])
            print("🍪 启动后 cookies(channels.weixin.qq.com) =", len(cks))
        except Exception as e:
            print("⚠️ 读取 cookies 失败：", e)

        return ctx

    def _is_logged_in(self, page: Page) -> bool:
        """更贴近真实：进入 HOME 或 liveBuild 都算已登录；只要不是登录页"""
        url = (_get_real_url(page) or "").lower()

        if url.startswith(LIVE_URL_PREFIX.lower()):
            return True
        if (HOME_URL or "").lower() and url.startswith((HOME_URL or "").lower()):
            return True

        # 兜底排除登录页
        if "login" in url or "passport" in url or "auth" in url:
            return False

        # 如果已经在 channels.weixin.qq.com 域且不是登录页，一般也算登录完成
        if "channels.weixin.qq.com" in url:
            return True

        return False

    def _maybe_save_login_state(self, context, page):
        if getattr(self, "_login_state_saved", False):
            return

        if not self._is_logged_in(page):
            return

        # ✅ 再保险：必须确认 cookie 非空，才允许保存（避免空态覆盖）
        try:
            cks = context.cookies(["https://channels.weixin.qq.com"])
            if not cks:
                # 很多“看起来登录了但没 cookie”的情况（比如还没跳转完成）
                return
        except Exception:
            # cookies 读失败也别保存
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

    # ===== 抓参数/headers =====
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

                if not self.state.wx_post_url:
                    self.state.wx_post_url = url.replace(
                        "mmfinderassistant-bin/live/msg",
                        "mmfinderassistant-bin/live/post_live_app_msg"
                    )
                    print("✅ 已由 live/msg 推导 wx_post_url =", self.state.wx_post_url)
                return

            # 管理员手动发消息：存完整 URL + headers 模板
            if "mmfinderassistant-bin/live/post_live_app_msg" in url and isinstance(post, dict):
                self.state.wx_post_url = url
                self.state.wx_liveCookies = post.get("liveCookies") or self.state.wx_liveCookies
                self.state.wx_objectId = post.get("objectId") or self.state.wx_objectId
                self.state.wx_finderUsername = post.get("finderUsername") or self.state.wx_finderUsername
                self.state.wx_liveId = post.get("liveId") or self.state.wx_liveId

                self.state.wx_post_headers_template = dict(req.headers or {})
                print("✅ 已捕获管理员发消息接口 wx_post_url（更稳）")
                print("✅ 已捕获 wx_post_headers_template：",
                      f"cookie_len={len(_lower_headers(req.headers or {}).get('cookie',''))} "
                      f"ua_len={len(_lower_headers(req.headers or {}).get('user-agent',''))}")
                return

        except Exception as e:
            print("⚠️ _handle_request error:", e)

    # ===== 发送文字回复 =====
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

    # ===== 监听状态 =====
    def _update_listen_state(self, page: Page, reason: str = ""):
        url = _get_real_url(page)
        should = url.startswith(LIVE_URL_PREFIX)

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

    # ===== 处理消息 =====
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

    # ===== 主循环 =====
    def run(self, tick: Callable[[], None]):
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
            )

            context = self._create_context(browser)
            self._context = context
            page = context.new_page()

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
