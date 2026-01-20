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
    """
    把 /api/anchor/comment/info?... 变成 /api/anchor/comment/operate_v2?...
    query 原样保留（含 msToken/a_bogus/verifyFp 等）
    """
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
    """
    从浏览器真实请求头里，挑出最关键的那批“反爬/鉴权”相关 header
    """
    src = _normalize_headers(src)

    keep_keys = [
        "user-agent",
        "accept",
        "accept-language",
        "content-type",

        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "sec-ch-ua-platform",

        "sec-fetch-site",
        "sec-fetch-mode",
        "sec-fetch-dest",

        "x-secsdk-csrf-token",
        "cookie",

        "origin",
        "referer",
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


class DouyinListener:
    """
    抖音直播监听器（稳定版）
    - 监听 /api/anchor/comment/info
    - on_danmaku 做语音/关键词；这里负责文本自动回复（enable_auto_reply 控制）
    - 关键：POST operate_v2 必须带 cookie + x-secsdk-csrf-token 等，否则 403
    """

    def __init__(
        self,
        state: AppState,
        on_danmaku: Callable[[str, str], str],
        hit_qa_question=None,
        cooldown_seconds: int = AUTO_REPLY_COOLDOWN_SECONDS,
    ):
        self.state = state
        self.on_danmaku = on_danmaku
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

        # ✅新增：单独缓存 cookie / secsdk（最重要的兜底）
        if not hasattr(self.state, "dy_cookie_header"):
            self.state.dy_cookie_header = ""
        if not hasattr(self.state, "dy_secsdk_csrf_token"):
            self.state.dy_secsdk_csrf_token = ""

    # ===== 监听 request：抓 info/operate_v2 的真实 headers（重点：cookie + x-secsdk-csrf-token）=====
    def _handle_request(self, req: Request):
        try:
            url = req.url
            h = _normalize_headers(req.headers or {})

            # ✅只要看到 secsdk 就保存
            secsdk = h.get("x-secsdk-csrf-token", "").strip()
            if secsdk:
                self.state.dy_secsdk_csrf_token = secsdk

            # ✅只要看到 cookie 就缓存（取最长那条，通常最完整）
            ck = h.get("cookie", "")
            if ck and len(ck) > len(getattr(self.state, "dy_cookie_header", "")):
                self.state.dy_cookie_header = ck

            # 抓 info：保存 url + headers
            if "/api/anchor/comment/info" in url:
                self.state.dy_last_info_url = url
                self.state.dy_last_info_req_headers = h

            # 抓 operate_v2：保存 url + headers（最贴近手动成功）
            if "/api/anchor/comment/operate_v2" in url and req.method.upper() == "POST":
                self.state.dy_operate_url_template = url
                self.state.dy_operate_req_headers = h
                print("✅ 已捕获抖音 operate_v2 模板URL（带签名）：", url)
                print("✅ 已捕获 operate_v2 headers：",
                      f"cookie_len={len(h.get('cookie',''))} "
                      f"secsdk_len={len(h.get('x-secsdk-csrf-token',''))} "
                      f"ua_len={len(h.get('user-agent',''))}")
        except Exception as e:
            print("⚠️ 抖音 _handle_request error:", e)

    def _context_cookie_fallback(self) -> str:
        """
        ✅兼容不同 Playwright 版本：cookies() 用 list URL 更稳
        """
        if not self._context:
            return ""
        try:
            cks = self._context.cookies(["https://buyin.jinritemai.com", "https://jinritemai.com"])
            print("🍪 context.cookies count =", len(cks))
            if not cks:
                return ""
            return "; ".join([f"{c['name']}={c['value']}" for c in cks if c.get("name")])
        except Exception as e:
            print("⚠️ context.cookies 读取失败：", e)
            return ""

    # ===== 发送抖音回复（http.client，贴近你手动成功脚本）=====
    def _send_douyin_reply(self, comment: dict, reply_text: str) -> bool:
        # 1) URL：优先 operate_v2；否则用 info 推导
        url = (self.state.dy_operate_url_template or "").strip()
        if not url:
            info_url = (self.state.dy_last_info_url or "").strip()
            if info_url:
                url = _swap_info_to_operate(info_url)

        if not url:
            print("⚠️ 既没抓到 operate_v2，也没抓到 info_url，无法发送")
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
                "rtf_content": {
                    "reply_uid": uid,
                    "start": 0,
                    "length": len(nick) + 1
                }
            }
        }

        # 2) headers：优先 operate_v2 请求头；否则 info 请求头
        src = {}
        if getattr(self.state, "dy_operate_req_headers", None):
            src = self.state.dy_operate_req_headers
        elif getattr(self.state, "dy_last_info_req_headers", None):
            src = self.state.dy_last_info_req_headers

        headers_lc = _pick_keep_headers(src)

        # 固定补齐（http.client 更吃这个）
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": headers_lc.get("accept", "application/json, text/plain, */*"),
            "User-Agent": headers_lc.get("user-agent", ""),
            "Origin": "https://buyin.jinritemai.com",
            "Referer": DOUYIN_DASHBOARD_URL,

            "sec-ch-ua": headers_lc.get("sec-ch-ua", ""),
            "sec-ch-ua-mobile": headers_lc.get("sec-ch-ua-mobile", ""),
            "sec-ch-ua-platform": headers_lc.get("sec-ch-ua-platform", ""),
            "Sec-Fetch-Site": headers_lc.get("sec-fetch-site", ""),
            "Sec-Fetch-Mode": headers_lc.get("sec-fetch-mode", ""),
            "Sec-Fetch-Dest": headers_lc.get("sec-fetch-dest", ""),

            # ✅最关键：secsdk csrf（一定要值非空）
            "x-secsdk-csrf-token": (headers_lc.get("x-secsdk-csrf-token", "") or self.state.dy_secsdk_csrf_token).strip(),
        }

        # ✅最关键：cookie（优先：抓包 cookie -> state 缓存 cookie -> context.cookies 拼）
        cookie = (headers_lc.get("cookie", "") or getattr(self.state, "dy_cookie_header", "") or "").strip()
        if not cookie:
            cookie = (self._context_cookie_fallback() or "").strip()

        if cookie:
            headers["cookie"] = cookie

        # 清理空值
        headers = {k: v for k, v in headers.items() if v}

        cookie_len = len(headers.get("cookie", ""))
        secsdk_val = (headers.get("x-secsdk-csrf-token", "") or "").strip()
        has_secsdk = bool(secsdk_val)
        print(f"POST operate_v2 准备发送：cookie_len={cookie_len} has_secsdk={has_secsdk} secsdk_len={len(secsdk_val)} dy_cookie_header_len={len(getattr(self.state,'dy_cookie_header',''))}")

        # cookie 还为空时，直接提示（否则必 403）
        if cookie_len == 0:
            print("❌ cookie_len=0：这会导致 403。说明：")
            print("   1) Playwright 没在 req.headers 暴露 cookie（或你没进入 buyin 域）")
            print("   2) 或 storage_state 里没有 buyin 的 cookie")
            # 继续发也会 403，但你要看响应 body，所以不提前 return

        # 3) 发送（✅payload 必须 utf-8 bytes）
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
                print(f"📨 抖音自动回复 status={res.status} reason={getattr(res, 'reason', '')}")
                rh = {}
                for k, v in res.getheaders():
                    lk = str(k).lower()
                    if lk in ("x-tt-logid", "x-tt-trace-id", "x-ms-token", "server", "content-type", "location"):
                        rh[lk] = v
                if rh:
                    print("   ↪ resp.headers(key) =", rh)
                print("   ↪ resp.body(head800) =", (text or "")[:800].replace("\n", "\\n"))
                return False

            # 200 尝试 json
            try:
                j = json.loads(text)
                ok = (j.get("code") == 0 and j.get("st") == 0)
                print(f"📨 抖音自动回复 status=200 code={j.get('code')} st={j.get('st')} msg={j.get('msg')}")
                if not ok:
                    print("   ↪ resp.json =", j)
                return ok
            except Exception:
                print("📨 抖音自动回复 status=200（非JSON） body(head300)=", (text or "")[:300].replace("\n", "\\n"))
                return True

        except Exception as e:
            print("❌ 抖音发送异常：", e)
            return False

    # ===== 状态切换 =====
    def _update_listen_state(self, page: Page, reason: str = ""):
        url = _get_real_url(page)
        should = url.startswith(DOUYIN_DASHBOARD_URL)

        if should and not self.state.dy_is_listening:
            self.state.dy_is_listening = True
            self.state.live_ready = True
            print(f"🎬 已进入抖音直播控制台（{reason}）URL={url}")

            try:
                if getattr(self.state, "audio_dispatcher", None) and not self.state.audio_dispatcher.current_playing:
                    self.state.audio_dispatcher.start_folder_cycle()
            except Exception as e:
                print("⚠️ 抖音启动轮播失败：", e)

    # ===== 核心：处理评论 =====
    def _handle_comment_json(self, data: Dict[str, Any]):
        comments = data.get("data", {}).get("comment_infos", [])
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
                # ✅允许“只播语音不发文字”
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
                print("❌ 抖音自动回复失败（已打印失败原因）")

    # ===== 响应监听 =====
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
                    print("🔁 抖音 URL 变化：", url)
                    self._update_listen_state(page, reason="url changed")

                self._maybe_save_login_state(context, page)
                self._update_listen_state(page, reason="poll")

                tick()
                time.sleep(0.3)
