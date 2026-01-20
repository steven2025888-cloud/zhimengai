# core/douyin_listener.py
import os
import time
import json
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


class DouyinListener:
    """
    抖音直播监听器（稳定版）
    - 进入控制台才监听
    - 监听 /api/anchor/comment/info
    - 调用 on_danmaku（主逻辑：关键词+语音，只算一次）
    - on_danmaku 返回 reply_text 后，这里负责发文字（enable_auto_reply 控制）
    - ✅ 自动回复：优先使用抓到的 operate_v2 完整URL；没有就由 info URL 推导
    - ✅ 修复：Playwright Sync API 不支持 json= 参数 -> 用 data=json.dumps(...)
    - ✅ 修复：命中关键词但无文本时，语音开关开启仍需播语音（兜底逻辑）
    """

    def __init__(
        self,
        state: AppState,
        on_danmaku: Callable[[str, str], str],
        hit_qa_question=None,  # 兼容旧构造，不使用
        cooldown_seconds: int = AUTO_REPLY_COOLDOWN_SECONDS,
    ):
        self.state = state
        self.on_danmaku = on_danmaku
        self.cooldown_seconds = cooldown_seconds

        self.state.dy_is_listening = False
        self._context = None
        self._page: Optional[Page] = None  # ✅用于403时 reload 自愈

        if not hasattr(self.state, "dy_last_info_url"):
            self.state.dy_last_info_url = None
        if not hasattr(self.state, "dy_last_info_headers"):
            self.state.dy_last_info_headers = {}

        if not hasattr(self.state, "seen_seq"):
            self.state.seen_seq = set()
        if not hasattr(self.state, "dy_reply_cooldown"):
            self.state.dy_reply_cooldown = {}  # uid -> ts

        # ✅保存你手动回复时抓到的 operate_v2 完整 URL（带签名参数）
        if not hasattr(self.state, "dy_operate_url_template"):
            self.state.dy_operate_url_template = None

        # ✅语音兜底：避免同一条评论重复触发语音
        if not hasattr(self.state, "dy_voice_done_cids"):
            self.state.dy_voice_done_cids = set()

    # ===== 抓取请求：捕获 operate_v2 模板 URL（更稳）=====
    def _handle_request(self, req: Request):
        try:
            if req.method.upper() != "POST":
                return
            url = req.url
            if "/api/anchor/comment/operate_v2" in url:
                self.state.dy_operate_url_template = url
                print("✅ 已捕获抖音 operate_v2 模板URL（带签名）：", url)
        except Exception as e:
            print("⚠️ 抖音 _handle_request error:", e)

    # ===== 403 自愈：reload 控制台页面 =====
    def _reload_dashboard(self):
        try:
            if self._page:
                print("🔄 尝试刷新抖音控制台页面（403自愈）...")
                self._page.reload(wait_until="domcontentloaded", timeout=60_000)
                time.sleep(0.8)
        except Exception as e:
            print("⚠️ 抖音 reload 失败：", e)

    # ===== 发送抖音文本回复 =====
    def _send_douyin_reply(self, comment: dict, reply_text: str) -> bool:
        # ✅ 优先用已捕获/推导的 operate_v2 URL；如果没有，就用最新 info URL 推导
        url = (self.state.dy_operate_url_template or "").strip()
        if not url:
            info_url = (self.state.dy_last_info_url or "").strip()
            if info_url and "/api/anchor/comment/info" in info_url:
                url = _swap_info_to_operate(info_url)
                self.state.dy_operate_url_template = url
                print("✅ 使用最新 info 推导 operate_v2：", url)

        if not url:
            print("⚠️ 还没拿到 operate_v2 URL：等待一次 comment/info 响应或手动回一次")
            return False

        nick = str(comment.get("nick_name") or "")
        uid = str(comment.get("uid") or "")
        cid = str(comment.get("comment_id") or "")

        if not (nick and uid and cid):
            print("⚠️ 抖音回复缺字段：nick/uid/comment_id")
            return False

        # 你抓包里 “@梦想家” length=4（包含@），所以这里用 len(nick)+1
        mention_len = len(nick) + 1

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
                    "length": mention_len
                }
            }
        }

        if not self._context:
            print("⚠️ 抖音 context 未就绪")
            return False

        # ✅ 从最近一次 info 请求头里拿 x-secsdk-csrf-token（很多403就差这个）
        h = self.state.dy_last_info_headers or {}
        secsdk_csrf = (
            h.get("x-secsdk-csrf-token")
            or h.get("X-SecSdk-Csrf-Token")
            or h.get("x-secsdk-csrf_token")
            or ""
        )

        def do_post_once() -> tuple[bool, int, str]:
            resp = self._context.request.post(
                url,
                data=json.dumps(body, ensure_ascii=False),
                headers={
                    "content-type": "application/json",
                    "origin": "https://buyin.jinritemai.com",
                    "referer": DOUYIN_DASHBOARD_URL,
                    **({"x-secsdk-csrf-token": secsdk_csrf} if secsdk_csrf else {}),
                },
                timeout=10_000
            )
            status = resp.status
            ok = False
            extra = ""

            try:
                j = resp.json()
                ok = (200 <= status < 300) and (j.get("code") == 0) and (j.get("st") == 0)
                extra = f"code={j.get('code')} st={j.get('st')} msg={j.get('msg')}"
            except Exception:
                try:
                    extra = (resp.text() or "")[:200]
                except Exception:
                    extra = ""
                ok = (200 <= status < 300)

            return ok, status, extra

        try:
            ok, status, extra = do_post_once()
            print(f"📨 抖音自动回复 status={status} {extra}")
            if ok:
                return True

            # ✅ 403 自愈：reload + 用最新 info 再推导模板 + 重试一次
            if status == 403:
                self._reload_dashboard()

                info_url = (self.state.dy_last_info_url or "").strip()
                if info_url and "/api/anchor/comment/info" in info_url:
                    self.state.dy_operate_url_template = _swap_info_to_operate(info_url)
                    url = self.state.dy_operate_url_template

                ok2, status2, extra2 = do_post_once()
                print(f"📨 抖音自动回复 retry status={status2} {extra2}")
                return ok2

            return False
        except Exception as e:
            print("❌ 抖音发送异常：", e)
            return False

    # ===== 语音兜底：命中关键词但没有文本回复，也要播语音 =====
    def _voice_fallback_if_needed(self, comment: dict, reply_text: str):
        try:
            if not getattr(self.state, "enable_danmaku_reply", False):
                return

            cid = str(comment.get("comment_id") or "")
            if not cid:
                return
            if cid in self.state.dy_voice_done_cids:
                return

            if (reply_text or "").strip():
                return

            pending = getattr(self.state, "pending_hit", None)
            if not pending or not isinstance(pending, (tuple, list)) or len(pending) < 1:
                return
            prefix = pending[0]
            if not prefix:
                return

            dispatcher = getattr(self.state, "audio_dispatcher", None)
            folder_manager = getattr(self.state, "folder_manager", None)
            if not dispatcher or not folder_manager:
                return

            if getattr(dispatcher, "current_playing", None):
                return

            wav = None
            try:
                wav = folder_manager.pick_next_audio()
            except Exception:
                wav = None

            if wav:
                dispatcher.push_random(wav)
                self.state.dy_voice_done_cids.add(cid)
                print(f"🔊 语音兜底已触发：prefix={prefix}（无文本回复）")
        except Exception as e:
            print("⚠️ 语音兜底触发失败：", e)

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
            except Exception as e:
                print("⚠️ on_danmaku 异常：", e)
                reply_text = ""

            self._voice_fallback_if_needed(c, reply_text)

            if not getattr(self.state, "enable_auto_reply", False):
                if (reply_text or "").strip():
                    print("💤 文本自动回复已关闭，本次仅命中关键词，不发文字")
                continue

            if not (reply_text or "").strip():
                continue

            now = time.time()
            last = self.state.dy_reply_cooldown.get(uid or nickname, 0)
            if now - last < self.cooldown_seconds:
                continue

            if self._send_douyin_reply(c, (reply_text or "").strip()):
                self.state.dy_reply_cooldown[uid or nickname] = now
                print("✅ 抖音自动回复成功")
            else:
                print("❌ 抖音自动回复失败（看 status / 是否抓到模板URL）")

    # ===== 响应监听 =====
    def _handle_response(self, resp: Response):
        if not self.state.dy_is_listening:
            return
        if DOUYIN_API_KEYWORD not in resp.url:
            return

        try:
            self.state.dy_last_info_url = resp.url
            self.state.dy_last_info_headers = resp.request.headers or {}
        except Exception:
            pass

        try:
            if not (self.state.dy_operate_url_template or "").strip():
                if "/api/anchor/comment/info" in resp.url:
                    self.state.dy_operate_url_template = _swap_info_to_operate(resp.url)
                    print("✅ 已从 info URL 推导 operate_v2 模板：", self.state.dy_operate_url_template)
        except Exception as e:
            print("⚠️ 从 info 推导 operate_v2 失败：", e)

        try:
            data = resp.json()
        except Exception:
            return
        self._handle_comment_json(data)

    # ===== 登录态 =====
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
