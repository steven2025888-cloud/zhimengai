# core/douyin_listener.py
import os
import time
import json
import http.client
from typing import Any, Dict, Callable, Optional
from urllib.parse import urlparse, urlunparse

from playwright.sync_api import sync_playwright, Response, Page, Request

from core.state import AppState
from config import (
    DOUYIN_STATE_FILE,
    DOUYIN_LOGIN_URL,
    DOUYIN_DASHBOARD_URL,
    DOUYIN_API_KEYWORD,
)

AUTO_REPLY_COOLDOWN_SECONDS = 60


def _get_real_url(page: Page) -> str:
    try:
        return page.evaluate("location.href")
    except Exception:
        return page.url


def _swap_info_to_operate(info_url: str) -> str:
    """把 /api/anchor/comment/info?... 变成 /api/anchor/comment/operate_v2?..."""
    u = urlparse(info_url)
    path = u.path.replace("/api/anchor/comment/info", "/api/anchor/comment/operate_v2")
    return urlunparse((u.scheme, u.netloc, path, u.params, u.query, u.fragment))


def _normalize_headers(h: Dict[str, str]) -> Dict[str, str]:
    out = {}
    for k, v in (h or {}).items():
        if not k:
            continue
        out[str(k).lower()] = str(v)
    return out


def _pick_keep_headers(src: Dict[str, str]) -> Dict[str, str]:
    """从浏览器真实请求头里挑关键反爬/鉴权 header"""
    src = _normalize_headers(src)

    keep_keys = [
        "user-agent", "accept", "accept-language", "content-type",
        "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
        "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest",
        "x-secsdk-csrf-token", "cookie",
        "origin", "referer",
    ]
    out = {}
    for k in keep_keys:
        if k in src and src[k]:
            out[k] = src[k]

    out.setdefault("accept", "application/json, text/plain, */*")
    out.setdefault("content-type", "application/json; charset=utf-8")
    out.setdefault("origin", "https://buyin.jinritemai.com")
    out.setdefault("referer", DOUYIN_DASHBOARD_URL)
    return out


def _is_comment_info_url(url: str) -> bool:
    url = url or ""
    return ("/api/anchor/comment/info" in url) or ("comment/info" in url)


class DouyinListener:
    """
    抖音直播监听器（在你原版基础上：只做“稳抓弹幕”的修复 + 公屏轮播）
    """

    def __init__(
        self,
        state: AppState,
        on_danmaku: Callable[[str, str], str],
        on_event: Optional[Callable[[str, str, int], None]] = None,
        hit_qa_question=None,
        cooldown_seconds: int = AUTO_REPLY_COOLDOWN_SECONDS,
    ):
        self.state = state
        self.on_danmaku = on_danmaku
        self.on_event = on_event or (lambda *args, **kwargs: None)
        self.cooldown_seconds = cooldown_seconds

        self.state.dy_is_listening = False
        self._context = None
        self._page: Optional[Page] = None

        if not hasattr(self.state, "seen_seq"):
            self.state.seen_seq = set()
        if not hasattr(self.state, "dy_reply_cooldown"):
            self.state.dy_reply_cooldown = {}

        if not hasattr(self.state, "dy_last_info_url"):
            self.state.dy_last_info_url = None
        if not hasattr(self.state, "dy_last_info_req_headers"):
            self.state.dy_last_info_req_headers = {}

        if not hasattr(self.state, "dy_operate_url_template"):
            self.state.dy_operate_url_template = None
        if not hasattr(self.state, "dy_operate_req_headers"):
            self.state.dy_operate_req_headers = {}

        # cookie / secsdk 兜底
        if not hasattr(self.state, "dy_cookie_header"):
            self.state.dy_cookie_header = ""
        if not hasattr(self.state, "dy_secsdk_csrf_token"):
            self.state.dy_secsdk_csrf_token = ""

        # 公屏发送模板（可选）
        if not hasattr(self.state, "dy_public_send_url_template"):
            self.state.dy_public_send_url_template = ""
        if not hasattr(self.state, "dy_public_send_req_headers"):
            self.state.dy_public_send_req_headers = {}
        if not hasattr(self.state, "dy_public_send_body_template"):
            self.state.dy_public_send_body_template = None

    # ===== request：抓 info/operate_v2 headers + （可选）公屏模板 =====
    def _handle_request(self, req: Request):
        try:
            url = req.url
            method = req.method.upper()
            h = _normalize_headers(req.headers or {})

            secsdk = h.get("x-secsdk-csrf-token", "").strip()
            if secsdk:
                self.state.dy_secsdk_csrf_token = secsdk

            ck = h.get("cookie", "")
            if ck and len(ck) > len(getattr(self.state, "dy_cookie_header", "")):
                self.state.dy_cookie_header = ck

            if _is_comment_info_url(url):
                self.state.dy_last_info_url = url
                self.state.dy_last_info_req_headers = h

            if "/api/anchor/comment/operate_v2" in url and method == "POST":
                self.state.dy_operate_url_template = url
                self.state.dy_operate_req_headers = h
                print("✅ 已捕获抖音 operate_v2 模板URL：", url)

            # 可选：抓“公屏发送模板”
            if method == "POST" and "/api/anchor/comment/operate_v2" not in url:
                post = None
                try:
                    post = req.post_data_json()
                except Exception:
                    post = None
                if isinstance(post, dict):
                    has_content = any(k in post for k in ("content", "text", "msg", "message"))
                    maybe_send = any(x in url for x in ("send", "message", "im", "chat"))
                    if has_content and maybe_send:
                        self.state.dy_public_send_url_template = url
                        self.state.dy_public_send_req_headers = h
                        self.state.dy_public_send_body_template = post
                        print("✅ 已捕获抖音公屏发送模板：", url)

        except Exception as e:
            print("⚠️ 抖音 _handle_request error:", e)

    def _context_cookie_fallback(self) -> str:
        if not self._context:
            return ""
        try:
            cks = self._context.cookies(["https://buyin.jinritemai.com", "https://jinritemai.com"])
            if not cks:
                return ""
            return "; ".join([f"{c['name']}={c['value']}" for c in cks if c.get("name")])
        except Exception:
            return ""

    # ===== 发送抖音回复（原版逻辑）=====
    def _send_douyin_reply(self, comment: dict, reply_text: str) -> bool:
        url = (self.state.dy_operate_url_template or "").strip()
        if not url:
            info_url = (self.state.dy_last_info_url or "").strip()
            if info_url:
                url = _swap_info_to_operate(info_url)

        if not url:
            print("⚠️ 没抓到 operate_v2 / info_url，无法回复")
            return False

        nick = str(comment.get("nick_name") or "")
        uid = str(comment.get("uid") or "")
        cid = str(comment.get("comment_id") or "")
        if not (nick and uid and cid):
            print("⚠️ 抖音回复缺字段：nick/uid/comment_id")
            return False

        body = {
            "operate_type": 1,
            "content": f"@{nick} {reply_text}",
            "comment_id": cid,
            "uid": uid,
            "nick_name": nick,
            "comment_reply_operate": {
                "rtf_content": {"reply_uid": uid, "start": 0, "length": len(nick) + 1}
            }
        }

        src = self.state.dy_operate_req_headers or self.state.dy_last_info_req_headers or {}
        headers_lc = _pick_keep_headers(src)

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": headers_lc.get("accept", "application/json, text/plain, */*"),
            "User-Agent": headers_lc.get("user-agent", ""),
            "Origin": "https://buyin.jinritemai.com",
            "Referer": DOUYIN_DASHBOARD_URL,
            "x-secsdk-csrf-token": (headers_lc.get("x-secsdk-csrf-token", "") or self.state.dy_secsdk_csrf_token).strip(),
        }

        cookie = (headers_lc.get("cookie", "") or self.state.dy_cookie_header or "").strip()
        if not cookie:
            cookie = (self._context_cookie_fallback() or "").strip()
        if cookie:
            headers["cookie"] = cookie

        headers = {k: v for k, v in headers.items() if v}

        u = urlparse(url)
        path = u.path + (("?" + u.query) if u.query else "")
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")

        try:
            conn = http.client.HTTPSConnection(u.netloc, timeout=10)
            conn.request("POST", path, payload, headers)
            res = conn.getresponse()
            raw = res.read()
            text = raw.decode("utf-8", errors="replace")

            if res.status != 200:
                print(f"📨 抖音回复 status={res.status} reason={getattr(res,'reason','')}")
                print("   ↪ body(head800)=", (text or "")[:800].replace("\n", "\\n"))
                return False

            try:
                j = json.loads(text)
                ok = (j.get("code") == 0 and j.get("st") == 0)
                print("📨 抖音回复 code=", j.get("code"), "st=", j.get("st"), "msg=", j.get("msg"))
                return bool(ok)
            except Exception:
                return True

        except Exception as e:
            print("❌ 抖音发送异常：", e)
            return False

    # ===== ✅关键修复：监听状态不要只靠 startswith =====
    def _update_listen_state(self, page: Page, reason: str = ""):
        url = _get_real_url(page) or ""
        # 原来：url.startswith(DOUYIN_DASHBOARD_URL)
        # 修复：只要包含控制台域/前缀即可
        should = False
        if DOUYIN_DASHBOARD_URL:
            should = url.startswith(DOUYIN_DASHBOARD_URL) or (DOUYIN_DASHBOARD_URL in url)
        if (not should) and ("buyin.jinritemai.com" in url):
            should = True

        if should and not self.state.dy_is_listening:
            self.state.dy_is_listening = True
            self.state.live_ready = True
            print(f"🎬 已进入抖音直播控制台（{reason}）URL={url}")

    # ===== 处理评论（保持你原版：comment_infos）=====
    def _handle_comment_json(self, data: Dict[str, Any]):
        comments = data.get("data", {}).get("comment_infos", [])
        if not isinstance(comments, list) or not comments:
            return

        internal_ext = data.get("data", {}).get("internal_ext", "")
        anchor_uid = None
        for part in str(internal_ext).split("|"):
            if part.startswith("wss_push_did:"):
                anchor_uid = part.split(":", 1)[1]
                break

        for c in comments:
            cid = str(c.get("comment_id") or "")
            if not cid:
                continue
            if cid in self.state.seen_seq:
                continue
            self.state.seen_seq.add(cid)

            uid = str(c.get("uid") or "")
            nickname = str(c.get("nick_name") or "未知用户")
            content = str(c.get("content") or "")

            if anchor_uid and uid == anchor_uid:
                continue

            print(f"🎤 抖音弹幕｜{nickname}：{content}")

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

            if not reply_text.strip():
                continue

            now = time.time()
            last = self.state.dy_reply_cooldown.get(uid or nickname, 0)
            if now - last < self.cooldown_seconds:
                continue

            ok = self._send_douyin_reply(c, reply_text.strip())
            if ok:
                self.state.dy_reply_cooldown[uid or nickname] = now
                print("✅ 抖音自动回复成功")
            else:
                print("❌ 抖音自动回复失败")

    # ===== ✅关键修复：不要硬依赖 dy_is_listening + keyword 太死 =====
    def _handle_response(self, resp: Response):
        url = resp.url or ""

        # 1) 先做宽松匹配：只要像 comment/info 就尝试解析
        looks_like = _is_comment_info_url(url)
        if not looks_like:
            # 2) 再兼容你 config 的 keyword（有的项目配的是 "comment/info" 或 "anchor/comment"）
            if DOUYIN_API_KEYWORD and (DOUYIN_API_KEYWORD in url):
                looks_like = True
            elif "/api/anchor/comment/" in url:
                looks_like = True

        if not looks_like:
            return

        try:
            data = resp.json()
        except Exception:
            return

        # 如果解析到了 comment_infos，说明已经在直播控制台，直接置 listening True（兜底）
        if not self.state.dy_is_listening:
            self.state.dy_is_listening = True
            self.state.live_ready = True
            print("✅ 通过评论流自动判定已进入直播页（dy_is_listening=True）")

        self._handle_comment_json(data)

    # ===== 公屏发送（轮播用，可不启用）=====
        # core/douyin_listener.py
    def send_public_text(self, text: str) -> bool:
        """
        ✅ 抖音公屏发送（按你提供的可用数据）：
        POST /api/anchor/comment/operate_v2?...  body: {"operate_type":2,"content":"xxx"}
        不需要 comment_id/uid/nick，也不需要另抓“公屏模板”。
        """
        text = (text or "").strip()
        if not text:
            return False

        # 1) 优先用已捕获的 operate_v2 模板 URL（带 verifyFp/msToken/a_bogus 更稳）
        url = (self.state.dy_operate_url_template or "").strip()

        # 2) 没有就用 info_url swap 出 operate_v2（兜底）
        if not url:
            info_url = (self.state.dy_last_info_url or "").strip()
            if info_url:
                url = _swap_info_to_operate(info_url)

        if not url:
            print("⚠️ 没抓到 operate_v2 / info_url，无法发送抖音公屏")
            return False

        body = {"operate_type": 2, "content": text}

        src = self.state.dy_operate_req_headers or self.state.dy_last_info_req_headers or {}
        headers_lc = _pick_keep_headers(src)

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": headers_lc.get("accept", "application/json, text/plain, */*"),
            "User-Agent": headers_lc.get("user-agent", ""),
            "Origin": "https://buyin.jinritemai.com",
            "Referer": DOUYIN_DASHBOARD_URL,
            "x-secsdk-csrf-token": (
                        headers_lc.get("x-secsdk-csrf-token", "") or self.state.dy_secsdk_csrf_token).strip(),
        }

        cookie = (headers_lc.get("cookie", "") or self.state.dy_cookie_header or "").strip()
        if not cookie:
            cookie = (self._context_cookie_fallback() or "").strip()
        if cookie:
            headers["cookie"] = cookie

        headers = {k: v for k, v in headers.items() if v}

        u = urlparse(url)
        path = u.path + (("?" + u.query) if u.query else "")
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")

        try:
            conn = http.client.HTTPSConnection(u.netloc, timeout=10)
            conn.request("POST", path, payload, headers)
            res = conn.getresponse()
            raw = res.read()
            txt = raw.decode("utf-8", errors="replace")

            ok = (res.status == 200)
            print("📢 抖音公屏发送 status=", res.status, "ok=", ok)
            if not ok:
                print("   ↪ body(head800)=", (txt or "")[:800].replace("\n", "\\n"))
            return ok

        except Exception as e:
            print("❌ 抖音公屏发送异常：", e)
            return False

    def process_public_screen_queue(self):
        import queue as _q
        q = getattr(self.state, "public_screen_queue_dy", None)
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
                print("⚠️ process_public_screen_queue(dy) error:", e)

    # ===== 主循环 =====
    def _maybe_save_login_state(self, context, page):
        if getattr(self, "_login_state_saved", False):
            return
        url = _get_real_url(page) or ""
        if "login" in url:
            return
        try:
            context.storage_state(path=DOUYIN_STATE_FILE)
            self._login_state_saved = True
            print("💾 抖音登录态已保存：", DOUYIN_STATE_FILE)
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
            self._context = context

            page = context.new_page()
            self._page = page
            page.on("request", self._handle_request)
            page.on("response", self._handle_response)

            try:
                page.goto(DOUYIN_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
                print("👉 已打开抖音页：", DOUYIN_LOGIN_URL)
            except Exception as e:
                print("⚠️ 打开抖音失败：", e)

            last_url = ""
            while True:
                url = _get_real_url(page)
                if url != last_url:
                    last_url = url
                    print("🔁 抖音 URL：", url)
                    self._update_listen_state(page, reason="url changed")

                self._maybe_save_login_state(context, page)
                self._update_listen_state(page, reason="poll")

                tick()
                time.sleep(0.3)
