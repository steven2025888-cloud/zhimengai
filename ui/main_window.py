# ui/main_window.py
import os
import functools
from dataclasses import dataclass
from typing import Callable, Optional, List, Dict

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QStackedWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from core.runtime_state import load_runtime_state
from core.state import app_state
from config import AUDIO_BASE_DIR, ZHULI_AUDIO_DIR, other_gz_audio, other_dz_audio

from ui.pages.page_script_rewrite import ScriptRewritePage
from ui.pages.page_comment_manager import CommentManagerPage
from ui.pages.page_public_screen import PublicScreenPage


print = functools.partial(print, flush=True)


def _safe_mkdir(p: str) -> str:
    p = str(p or "").strip()
    if not p:
        return ""
    try:
        os.makedirs(p, exist_ok=True)
        return p
    except Exception:
        return ""


def bootstrap_runtime_into_app_state():
    """把 runtime_state.json 的状态灌进 app_state（含关注/点赞目录，避免被 UI 默认值覆盖）"""
    runtime = load_runtime_state() or {}

    # 主播目录
    anchor_default = str(AUDIO_BASE_DIR)
    app_state.anchor_audio_dir = str(runtime.get("anchor_audio_dir", anchor_default) or anchor_default)
    app_state.anchor_audio_dir = _safe_mkdir(app_state.anchor_audio_dir) or anchor_default

    # 助播目录
    zhuli_default = str(ZHULI_AUDIO_DIR)
    app_state.zhuli_audio_dir = str(runtime.get("zhuli_audio_dir", zhuli_default) or zhuli_default)
    app_state.zhuli_audio_dir = _safe_mkdir(app_state.zhuli_audio_dir) or zhuli_default

    # ✅ 关注目录（runtime 优先，其次 config 默认）
    follow_default = str(other_gz_audio)
    app_state.follow_audio_dir = str(runtime.get("follow_audio_dir", follow_default) or follow_default)
    app_state.follow_audio_dir = _safe_mkdir(app_state.follow_audio_dir) or follow_default

    # ✅ 点赞目录（runtime 优先，其次 config 默认）
    like_default = str(other_dz_audio)
    app_state.like_audio_dir = str(runtime.get("like_audio_dir", like_default) or like_default)
    app_state.like_audio_dir = _safe_mkdir(app_state.like_audio_dir) or like_default

    # 其它开关
    app_state.enable_voice_report = bool(runtime.get("enable_voice_report", False))
    app_state.enable_danmaku_reply = bool(runtime.get("enable_danmaku_reply", False))
    app_state.enable_auto_reply = bool(runtime.get("enable_auto_reply", False))
    app_state.enable_zhuli = bool(runtime.get("enable_zhuli", True))

    # ✅ 评论/回复日志开关（默认 False）
    app_state.enable_comment_record = bool(runtime.get("enable_comment_record", False))
    app_state.enable_reply_record = bool(runtime.get("enable_reply_record", False))
    app_state.enable_reply_collect = bool(runtime.get("enable_reply_collect", False))

    # ===== 公屏轮播 =====
    app_state.enable_public_screen_wx = bool(runtime.get("enable_public_screen_wx", False))
    app_state.enable_public_screen_dy = bool(runtime.get("enable_public_screen_dy", False))

    try:
        app_state.public_screen_interval_min = int(runtime.get("public_screen_interval_min", 5) or 5)
    except Exception:
        app_state.public_screen_interval_min = 5

    msgs = runtime.get("public_screen_messages", []) or []
    if not isinstance(msgs, list):
        msgs = []
    app_state.public_screen_messages = [str(x).strip() for x in msgs if str(x).strip()]

    # 变量调节
    app_state.var_pitch_enabled = bool(runtime.get("var_pitch_enabled", True))
    app_state.var_volume_enabled = bool(runtime.get("var_volume_enabled", True))
    app_state.var_speed_enabled = bool(runtime.get("var_speed_enabled", True))
    app_state.var_pitch_delta = str(runtime.get("var_pitch_delta", "-5~+5"))
    app_state.var_volume_delta = str(runtime.get("var_volume_delta", "+0~+10"))
    app_state.var_speed_delta = str(runtime.get("var_speed_delta", "+0~+10"))
    app_state.var_apply_anchor = bool(runtime.get("var_apply_anchor", True))
    app_state.var_apply_zhuli = bool(runtime.get("var_apply_zhuli", True))

    # ✅ 关注/点赞开关 + 冷却（如果你 UI 已经做了）
    if "enable_follow_audio" in runtime:
        app_state.enable_follow_audio = bool(runtime.get("enable_follow_audio"))
    if "enable_like_audio" in runtime:
        app_state.enable_like_audio = bool(runtime.get("enable_like_audio"))
    if "follow_like_cooldown_seconds" in runtime:
        try:
            app_state.follow_like_cooldown_seconds = int(runtime.get("follow_like_cooldown_seconds") or 0)
        except Exception:
            pass


def save_runtime_flag(key: str, value):
    from core.runtime_state import load_runtime_state, save_runtime_state
    state = load_runtime_state() or {}
    state[key] = value
    save_runtime_state(state)


@dataclass
class PageSpec:
    name: str
    factory: Callable[[], QWidget]


class MainWindow(QWidget):
    """
    ✅ MainWindow 只负责：菜单/stack/切换/标题同步
    ✅ 每个页面都是独立 py 文件
    """
    def __init__(self, resource_path_func, expire_time: Optional[str] = None, license_key: str = ""):
        super().__init__()

        # ✅ 先灌 runtime，避免 UI 初始化覆盖目录等
        bootstrap_runtime_into_app_state()

        self.setObjectName("MainWindow")

        self.license_key = license_key
        self.resource_path = resource_path_func
        self.expire_time = expire_time

        self.setWindowTitle("织梦AI直播工具")
        self.setWindowIcon(QIcon(self.resource_path("logo.ico")))

        # ✅ 初始化时尽量减少闪烁（可选，但建议保留）
        self.setUpdatesEnabled(False)
        try:
            # ===== 外层：背景容器（只改它的背景色）=====
            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)

            bg = QWidget()
            bg.setObjectName("AppBackground")
            bg.setAttribute(Qt.WA_StyledBackground, True)  # ✅关键：让QSS背景生效
            outer.addWidget(bg, 1)

            # ===== 内层：左右两栏容器，放在 bg 里面 =====
            root = QHBoxLayout(bg)
            root.setContentsMargins(5, 10, 5, 10)
            root.setSpacing(5)

            # ===== 左侧容器 =====
            left = QWidget()
            left.setObjectName("LeftPane")
            left.setAttribute(Qt.WA_StyledBackground, True)  # ✅关键
            left_l = QVBoxLayout(left)
            left_l.setContentsMargins(0, 0, 0, 0)
            left_l.setSpacing(0)
            root.addWidget(left)

            self.side = QListWidget()
            self.side.setObjectName("SideMenu")
            self.side.setFixedWidth(130)
            self.side.setSpacing(6)
            left_l.addWidget(self.side, 1)

            # ===== 右侧容器 =====
            right = QWidget()
            right.setObjectName("RightPane")
            right.setAttribute(Qt.WA_StyledBackground, True)  # ✅关键
            right_l = QVBoxLayout(right)
            right_l.setContentsMargins(12, 12, 12, 12)
            right_l.setSpacing(12)
            root.addWidget(right, 1)

            # ===== Top title =====
            top = QHBoxLayout()
            self.lbl_title = QLabel("AI工作台")
            self.lbl_title.setStyleSheet("font-size: 20px; font-weight: 800;")
            top.addWidget(self.lbl_title)
            top.addSpacing(10)
            top.addStretch(1)

            expire_text = self.expire_time or "未知"
            self.lbl_expire = QLabel(f"到期时间：{expire_text}")
            self.lbl_expire.setStyleSheet("color:#FFB020; font-weight:700;")
            top.addWidget(self.lbl_expire)
            right_l.addLayout(top)

            # ===== Load QSS =====
            qss_path = self.resource_path(os.path.join("ui", "style.qss"))
            if os.path.exists(qss_path):
                with open(qss_path, "r", encoding="utf-8") as f:
                    self.setStyleSheet(f.read())
            else:
                print("⚠️ 未找到 style.qss：", qss_path)

            # ===== Stack pages =====
            self.stack = QStackedWidget()
            right_l.addWidget(self.stack, 1)

            # ===== Page registry =====
            self.pages: List[PageSpec] = self._build_page_specs()

            # ✅ 懒加载：idx -> widget
            self._page_widgets: Dict[int, QWidget] = {}

            # ✅ 先塞一个空白页（防止 stack 为空导致 setCurrentWidget 出问题）
            self._blank = QWidget()
            self._blank.setObjectName("PageBlank")
            self.stack.addWidget(self._blank)

            # ✅ 只生成左侧菜单项，不创建页面
            for p in self.pages:
                item = QListWidgetItem(p.name)
                item.setTextAlignment(Qt.AlignCenter)
                self.side.addItem(item)

            self.side.currentRowChanged.connect(self._on_page_changed)

            # ✅ 只创建第 0 页（避免启动时全页 factory 导致闪）
            self.side.setCurrentRow(0)

        finally:
            self.setUpdatesEnabled(True)
            self.update()

    def _build_page_specs(self) -> List[PageSpec]:
        # 延迟 import：避免互相引用/启动慢
        from ui.pages.page_workbench import WorkbenchPage
        from ui.pages.page_guide import GuidePage
        from ui.pages.page_anchor import AnchorPage
        from ui.pages.page_keywords import KeywordPage
        from ui.pages.page_zhuli import ZhuliPage
        from ui.pages.page_voice_model import VoiceModelPage
        from ui.pages.page_ai_reply import AiReplyPage
        from ui.pages.page_placeholder import PlaceholderPage

        # ✅ 新页：音频目录工具（替代 AudioToolsPage）
        from ui.pages.page_audio_dir_tools import AudioDirToolsPage

        def ctx():
            return {
                "main": self,
                "resource_path": self.resource_path,
                "license_key": self.license_key,
                "expire_time": self.expire_time,
                "save_runtime_flag": save_runtime_flag,
                "jump_to": self.jump_to,
            }

        return [
            PageSpec("AI工作台", lambda: WorkbenchPage(ctx())),
            PageSpec("新手引导", lambda: GuidePage(ctx())),
            PageSpec("主播设置", lambda: AnchorPage(ctx())),
            PageSpec("关键词设置", lambda: KeywordPage(ctx())),
            PageSpec("助播设置", lambda: ZhuliPage(ctx())),
            PageSpec("音色模型", lambda: VoiceModelPage(ctx())),

            PageSpec("音频目录工具", lambda: AudioDirToolsPage(ctx())),
            PageSpec("AI回复", lambda: AiReplyPage(ctx())),

            PageSpec("话术改写", lambda: ScriptRewritePage(ctx())),
            PageSpec("评论管理", lambda: CommentManagerPage(ctx())),
            PageSpec("公屏轮播", lambda: PublicScreenPage(ctx())),

            PageSpec("回复弹窗", lambda: PlaceholderPage("回复弹窗（开发中）")),
        ]

    def _ensure_page(self, idx: int) -> QWidget:
        """确保 idx 页已创建；未创建则 factory 一次并缓存。"""
        if idx in self._page_widgets:
            return self._page_widgets[idx]

        if not (0 <= idx < len(self.pages)):
            return self._blank

        try:
            w = self.pages[idx].factory()
        except Exception as e:
            print("⚠️ 页面创建失败：", self.pages[idx].name, e)
            w = QWidget()
            w.setObjectName(f"PageError_{idx}")

        self._page_widgets[idx] = w
        self.stack.addWidget(w)
        return w

    # 在 MainWindow 类里加入这个方法
    def _call_page_on_show(self, w: QWidget):
        """
        切换到页面后回调：
        - 优先调用 w.on_show()
        - 兼容：w.panel.on_show()
        """
        try:
            if hasattr(w, "on_show") and callable(getattr(w, "on_show")):
                w.on_show()
                return
            panel = getattr(w, "panel", None)
            if panel is not None and hasattr(panel, "on_show") and callable(getattr(panel, "on_show")):
                panel.on_show()
                return
        except Exception as e:
            print("⚠️ on_show 回调异常：", e)

    # 然后把你原来的 _on_page_changed 替换为这个
    def _on_page_changed(self, idx: int):
        # ✅ 懒加载关键：不要 setCurrentIndex(idx)，而是 setCurrentWidget(真实页面)
        w = self._ensure_page(idx)
        self.stack.setCurrentWidget(w)

        if 0 <= idx < len(self.pages):
            name = self.pages[idx].name
            self.lbl_title.setText(name)
            self.setWindowTitle(f"织梦AI直播工具 · {name}")

        # ✅ 新增：切到页面后触发 on_show
        self._call_page_on_show(w)

    def jump_to(self, menu_name: str):
        for i, p in enumerate(self.pages):
            if p.name == menu_name:
                self.side.setCurrentRow(i)
                return
