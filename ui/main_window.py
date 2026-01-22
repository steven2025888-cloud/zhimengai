# ui/main_window.py
import os
import functools
from dataclasses import dataclass
from typing import Callable, Optional, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QStackedWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from core.state import app_state
from config import AUDIO_BASE_DIR, ZHULI_AUDIO_DIR, other_gz_audio, other_dz_audio

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
    """把 runtime_state.json 的状态灌进 app_state（原来你写在 MainWindow.__init__ 里）"""
    from core.runtime_state import load_runtime_state

    runtime = load_runtime_state() or {}

    # ===== 主播音频目录（用户可选，默认 AUDIO_BASE_DIR）=====
    anchor_default = str(AUDIO_BASE_DIR)
    app_state.anchor_audio_dir = str(runtime.get("anchor_audio_dir", anchor_default) or anchor_default)
    app_state.anchor_audio_dir = _safe_mkdir(app_state.anchor_audio_dir) or anchor_default

    # ===== 助播音频目录（用户可选，默认 ZHULI_AUDIO_DIR）=====
    zhuli_default = str(ZHULI_AUDIO_DIR)
    app_state.zhuli_audio_dir = str(runtime.get("zhuli_audio_dir", zhuli_default) or zhuli_default)
    app_state.zhuli_audio_dir = _safe_mkdir(app_state.zhuli_audio_dir) or zhuli_default

    # ===== 关注/点赞目录（用户可选，默认 other_gz_audio / other_dz_audio）=====
    follow_default = str(other_gz_audio)
    like_default = str(other_dz_audio)

    app_state.follow_audio_dir = str(runtime.get("follow_audio_dir", follow_default) or follow_default)
    app_state.like_audio_dir = str(runtime.get("like_audio_dir", like_default) or like_default)

    app_state.follow_audio_dir = _safe_mkdir(app_state.follow_audio_dir) or follow_default
    app_state.like_audio_dir = _safe_mkdir(app_state.like_audio_dir) or like_default

    # ===== 其他开关/参数（你原来的逻辑保持）=====
    app_state.enable_voice_report = bool(runtime.get("enable_voice_report", False))
    app_state.enable_danmaku_reply = bool(runtime.get("enable_danmaku_reply", False))
    app_state.enable_auto_reply = bool(runtime.get("enable_auto_reply", False))
    app_state.enable_zhuli = bool(runtime.get("enable_zhuli", True))
    app_state.zhuli_mode = str(runtime.get("zhuli_mode", "A") or "A").upper()
    if app_state.zhuli_mode not in ("A", "B"):
        app_state.zhuli_mode = "A"

    # 变量调节（默认都打开）
    app_state.var_pitch_enabled = bool(runtime.get("var_pitch_enabled", True))
    app_state.var_volume_enabled = bool(runtime.get("var_volume_enabled", True))
    app_state.var_speed_enabled = bool(runtime.get("var_speed_enabled", True))

    app_state.var_pitch_delta = str(runtime.get("var_pitch_delta", "-5~+5"))
    app_state.var_volume_delta = str(runtime.get("var_volume_delta", "+0~+10"))
    app_state.var_speed_delta = str(runtime.get("var_speed_delta", "+0~+10"))

    app_state.var_apply_anchor = bool(runtime.get("var_apply_anchor", True))
    app_state.var_apply_zhuli = bool(runtime.get("var_apply_zhuli", True))

    # ===== 关注/点赞 播放开关 + 冷却间隔 =====
    app_state.enable_follow_audio = bool(runtime.get("enable_follow_audio", False))
    app_state.enable_like_audio = bool(runtime.get("enable_like_audio", False))

    try:
        app_state.follow_like_cooldown_seconds = int(runtime.get("follow_like_cooldown_seconds", 300) or 300)
    except Exception:
        app_state.follow_like_cooldown_seconds = 300


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

        bootstrap_runtime_into_app_state()

        self.setObjectName("MainWindow")

        self.license_key = license_key
        self.resource_path = resource_path_func
        self.expire_time = expire_time

        self.setWindowTitle("织梦AI直播工具")
        self.setWindowIcon(QIcon(self.resource_path("logo.ico")))

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

        for p in self.pages:
            item = QListWidgetItem(p.name)
            item.setTextAlignment(Qt.AlignCenter)
            self.side.addItem(item)
            self.stack.addWidget(p.factory())

        self.side.currentRowChanged.connect(self._on_page_changed)
        self.side.setCurrentRow(0)

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

            # ✅ 合并后的页面
            PageSpec("音频目录工具", lambda: AudioDirToolsPage(ctx())),

            PageSpec("AI回复", lambda: AiReplyPage(ctx())),
            PageSpec("回复弹窗", lambda: PlaceholderPage("回复弹窗（开发中）")),
            PageSpec("话术改写", lambda: PlaceholderPage("话术改写（开发中）")),
            PageSpec("评论管理", lambda: PlaceholderPage("评论管理（开发中）")),
        ]

    def _on_page_changed(self, idx: int):
        self.stack.setCurrentIndex(idx)
        if 0 <= idx < len(self.pages):
            name = self.pages[idx].name
            self.lbl_title.setText(name)
            self.setWindowTitle(f"织梦AI直播工具 · {name}")

    def jump_to(self, menu_name: str):
        for i, p in enumerate(self.pages):
            if p.name == menu_name:
                self.side.setCurrentRow(i)
                return
