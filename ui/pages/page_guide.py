# ui/pages/page_guide.py
from __future__ import annotations

from typing import Callable, Optional, List, Tuple
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy
)

from core.state import app_state
from config import AUDIO_BASE_DIR


class _StepCard(QFrame):
    """
    深色主题友好的「步骤卡片」
    - 左侧：序号圆点 + 竖线（时间线效果）
    - 右侧：标题、摘要、详情、操作按钮
    """
    toggled = Signal(bool)

    def __init__(
        self,
        number: int,
        title: str,
        summary: str,
        details: List[str],
        actions: Optional[List[Tuple[str, Callable]]] = None,
        expanded: bool = True,
        is_last: bool = False,
    ):
        super().__init__()
        self.setObjectName("GuideStepCard")

        self.setAttribute(Qt.WA_StyledBackground, True)
        self._expanded = expanded
        self._is_last = is_last


        root = QHBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # ===== Left timeline column =====
        left = QFrame()
        left.setObjectName("GuideTimeline")
        left.setAttribute(Qt.WA_StyledBackground, True)
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(6)
        left_l.setAlignment(Qt.AlignTop)

        dot = QLabel(str(number))
        dot.setObjectName("GuideStepDot")
        dot.setAlignment(Qt.AlignCenter)
        dot.setFixedSize(28, 28)
        left_l.addWidget(dot, 0, Qt.AlignHCenter)

        line = QFrame()
        line.setObjectName("GuideStepLine")
        line.setFixedWidth(2)
        line.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        line.setVisible(not is_last)
        left_l.addWidget(line, 1, Qt.AlignHCenter)

        root.addWidget(left)

        # ===== Right content =====
        right = QVBoxLayout()
        right.setSpacing(8)
        root.addLayout(right, 1)

        # header row (clickable)
        header = QHBoxLayout()
        header.setSpacing(8)

        lbl_title = QLabel(title)
        lbl_title.setObjectName("GuideStepTitle")
        lbl_title.setWordWrap(True)

        btn_toggle = QPushButton("收起" if expanded else "展开")
        btn_toggle.setObjectName("GuideBtnGhost")
        btn_toggle.setCursor(Qt.PointingHandCursor)
        btn_toggle.setFixedHeight(30)

        header.addWidget(lbl_title, 1)
        header.addWidget(btn_toggle)
        right.addLayout(header)

        lbl_summary = QLabel(summary)
        lbl_summary.setObjectName("GuideStepSummary")
        lbl_summary.setWordWrap(True)
        right.addWidget(lbl_summary)

        # details container
        self.details_wrap = QFrame()
        self.details_wrap.setObjectName("GuideDetailsWrap")
        self.details_wrap.setAttribute(Qt.WA_StyledBackground, True)
        details_l = QVBoxLayout(self.details_wrap)
        details_l.setContentsMargins(12, 10, 12, 10)
        details_l.setSpacing(6)

        for s in details:
            lab = QLabel("• " + s)
            lab.setObjectName("GuideDetailLine")
            lab.setWordWrap(True)
            details_l.addWidget(lab)

        right.addWidget(self.details_wrap)
        self.details_wrap.setVisible(expanded)

        # actions row
        if actions:
            act = QHBoxLayout()
            act.addStretch(1)
            for i, (text, fn) in enumerate(actions):
                b = QPushButton(text)
                b.setFixedHeight(34)
                b.setCursor(Qt.PointingHandCursor)
                b.setObjectName("GuideBtnPrimary" if i == 0 else "GuideBtnSecondary")
                b.clicked.connect(fn)
                act.addWidget(b)
            right.addLayout(act)

        # toggle handler
        def _toggle():
            self._expanded = not self._expanded
            self.details_wrap.setVisible(self._expanded)
            btn_toggle.setText("收起" if self._expanded else "展开")
            self.toggled.emit(self._expanded)

        btn_toggle.clicked.connect(_toggle)

    @property
    def expanded(self) -> bool:
        return self._expanded


class GuidePage(QWidget):
    """
    新手引导：让用户 3 分钟跑通闭环（设置目录 → 配关键词 → 开自动化 → 启动&扫码登录）
    """
    def __init__(self, ctx: dict):
        super().__init__()
        self.ctx = ctx or {}
        self.jump_to = self.ctx.get("jump_to")
        self.resource_path = self.ctx.get("resource_path")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName("GuideScroll")
        outer.addWidget(scroll, 1)

        content = QWidget()
        content.setObjectName("GuideContent")
        content.setAttribute(Qt.WA_StyledBackground, True)

        scroll.setWidget(content)

        root = QVBoxLayout(content)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # ===== Top banner =====
        banner = QFrame()
        banner.setObjectName("GuideBanner")
        banner.setAttribute(Qt.WA_StyledBackground, True)
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(16, 16, 16, 16)
        bl.setSpacing(6)

        title = QLabel("新手引导")
        title.setObjectName("GuideBannerTitle")

        subtitle = QLabel("照着做 4 步：你就能从 0 到 1 跑通“自动播音 + 关键词触发 + 直播控制台”。")
        subtitle.setObjectName("GuideBannerSubTitle")
        subtitle.setWordWrap(True)

        bl.addWidget(title)
        bl.addWidget(subtitle)

        # quick tip row
        tiprow = QHBoxLayout()
        tip = QLabel("建议：先用测试号/小号跑通一次，再正式开播。")
        tip.setObjectName("GuideBannerTip")
        tip.setWordWrap(True)

        btn_open_doc = QPushButton("打开说明文档")
        btn_open_doc.setObjectName("GuideBtnGhost")
        btn_open_doc.setFixedHeight(30)
        btn_open_doc.setCursor(Qt.PointingHandCursor)
        btn_open_doc.clicked.connect(self._open_doc)

        tiprow.addWidget(tip, 1)
        tiprow.addWidget(btn_open_doc)
        bl.addLayout(tiprow)

        root.addWidget(banner)

        # ===== Steps =====
        current_dir = getattr(app_state, "anchor_audio_dir", "") or str(AUDIO_BASE_DIR)
        current_dir = str(current_dir)

        # Step 1
        s1_title = "第 1 步：设置主播音频目录（可选）"
        s1_summary = f"当前已默认：{current_dir}（你可以不改，后面照样能跑通）"
        s1_details = [
            "用途：放主播讲解音频/话术音频（mp3/wav）。",
            "建议：按“产品/场景”建子文件夹，后续更好管理。",
            "设置完返回工作台，启动后系统会按目录读取音频。",
        ]
        s1_actions = []
        if callable(self.jump_to):
            s1_actions = [("去主播设置", lambda: self.jump_to("主播设置"))]
        root.addWidget(_StepCard(1, s1_title, s1_summary, s1_details, s1_actions, expanded=True))

        # Step 2
        s2_title = "第 2 步：设置关键词（必做）"
        s2_summary = "让系统知道：观众说什么 → 触发哪一类回复/播放（支持批量粘贴，保存后立即生效）"
        s2_details = [
            "左侧新建分类（例如：价格/尺寸/售后/材质）。",
            "右侧填写：必含词 / 意图词 / 排除词；需要自动回复就填“回复词”。",
            "点“保存并热更新”：马上生效，不用重启。",
        ]
        s2_actions = []
        if callable(self.jump_to):
            s2_actions = [("去关键词设置", lambda: self.jump_to("关键词设置"))]
        root.addWidget(_StepCard(2, s2_title, s2_summary, s2_details, s2_actions, expanded=True))

        # Step 3
        s3_title = "第 3 步：开启自动化控制（必做）"
        s3_summary = "在 AI 工作台打开你需要的开关（新手建议先开：弹幕监听/关键词回复相关）"
        s3_details = [
            "进入 AI 工作台，把需要的自动化开关打开（弹幕/关键词/助播/报时等）。",
            "如果有“测试/试听”，先点一下确认声音与路径正常。",
            "开关状态一般会保存，下次启动也能沿用。",
        ]
        s3_actions = []
        if callable(self.jump_to):
            s3_actions = [("去 AI 工作台", lambda: self.jump_to("AI工作台"))]
        root.addWidget(_StepCard(3, s3_title, s3_summary, s3_details, s3_actions, expanded=True))

        # Step 4
        s4_title = "第 4 步：启动系统 → 扫码登录 → 进入直播控制台（必做）"
        s4_summary = "启动后扫码登录抖音/视频号（用哪个登哪个），然后进直播控制台开始使用"
        s4_details = [
            "在 AI 工作台点击“启动系统/开始监听/开始自动化”。",
            "按提示扫码登录抖音和/或视频号（平台二选一或全登）。",
            "进入直播控制台：你能看到弹幕、触发记录、播放队列等。",
            "观众命中关键词 → 系统自动回复/播放，你专注讲解与促单。",
        ]
        s4_actions = []
        if callable(self.jump_to):
            s4_actions = [("回到 AI 工作台启动", lambda: self.jump_to("AI工作台"))]
        root.addWidget(_StepCard(4, s4_title, s4_summary, s4_details, s4_actions, expanded=True, is_last=True))

        root.addStretch(1)

        self._apply_local_style()

    def _open_doc(self):
        # 这里不强依赖你的 config 字段：如果你已有 KEYWORD_RULE_URL/DOC_URL，可在此接入
        try:
            from config import DOC_URL  # 你之前加过
            url = (DOC_URL or "").strip()
            if url:
                QDesktopServices.openUrl(QUrl(url))
                return
        except Exception:
            pass

        # fallback：啥也没配就不报错，避免新手页卡死
        # 你也可以在这里弹窗提示，但为了不打扰用户先静默
        return

    def _apply_local_style(self):
        """只给本页加局部样式（深色主题），并强制覆盖 Qt 默认浅灰底色。"""
        # 关键：没有 objectName + WA_StyledBackground，QSS 的背景不会绘制，会透出系统默认 #f0f0f0
        self.setObjectName("GuidePageRoot")
        self.setAttribute(Qt.WA_StyledBackground, True)

        # 本页的滚动内容容器，在 __init__ 里已经 setObjectName("GuideContent") + WA_StyledBackground
        # 这里补上 scrollArea/viewport 的透明化，避免 viewport 透出默认浅灰
        self.setStyleSheet(self.styleSheet() + """
        /* ===== Page background ===== */
        #GuidePageRoot{
            background: #0f1115;     /* 改这里：整页背景色 */
        }
        #GuideContent{
            background: #0f1115;     /* 改这里：滚动内容背景色（必须） */
        }
        QScrollArea#GuideScroll{
            background: transparent;
        }
        QScrollArea#GuideScroll > QWidget#qt_scrollarea_viewport{
            background: transparent;
        }

        /* ===== Banner ===== */
        #GuideBanner{
            border-radius: 14px;
            background: rgba(15, 26, 46, 0.75);
            border: 1px solid rgba(255,255,255,0.08);
        }
        #GuideBannerTitle{
            font-size: 18px;
            font-weight: 900;
            color: rgba(230,238,248,0.95);
        }
        #GuideBannerSubTitle{
            font-size: 12px;
            color: rgba(230,238,248,0.86);
        }
        #GuideBannerTip{
            font-size: 12px;
            color: rgba(230,238,248,0.72);
        }

        /* ===== Step card ===== */
        #GuideStepCard{
            border-radius: 14px;
            background: rgba(15, 26, 46, 0.55);
            border: 1px solid rgba(255,255,255,0.08);
        }
        #GuideStepTitle{
            font-size: 14px;
            font-weight: 850;
            color: rgba(230,238,248,0.95);
        }
        #GuideStepSummary{
            font-size: 12px;
            color: rgba(230,238,248,0.78);
        }
        #GuideDetailsWrap{
            border-radius: 12px;
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.06);
        }
        #GuideDetailLine{
            font-size: 12px;
            color: rgba(230,238,248,0.88);
        }

        /* ===== Timeline ===== */
        #GuideTimeline{ background: transparent; }
        #GuideStepDot{
            border-radius: 14px;
            background: rgba(57, 113, 249, 0.25);
            border: 1px solid rgba(57, 113, 249, 0.55);
            color: rgba(230,238,248,0.95);
            font-weight: 900;
        }
        #GuideStepLine{
            background: rgba(255,255,255,0.10);
            border-radius: 1px;
        }

        /* ===== Buttons (local only) ===== */
        QPushButton#GuideBtnPrimary{
            background: rgba(57, 113, 249, 0.92);
            border: 1px solid rgba(57, 113, 249, 0.85);
            border-radius: 10px;
            padding: 8px 14px;
            font-weight: 900;
            color: rgba(230,238,248,0.98);
        }
        QPushButton#GuideBtnPrimary:hover{ background: rgba(57, 113, 249, 1.0); }

        QPushButton#GuideBtnSecondary{
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.14);
            border-radius: 10px;
            padding: 8px 14px;
            font-weight: 800;
            color: rgba(230,238,248,0.92);
        }
        QPushButton#GuideBtnSecondary:hover{ background: rgba(255,255,255,0.10); }

        QPushButton#GuideBtnGhost{
            background: rgba(255,255,255,0.00);
            border: 1px solid rgba(255,255,255,0.14);
            border-radius: 10px;
            padding: 6px 12px;
            font-weight: 800;
            color: rgba(230,238,248,0.85);
        }
        QPushButton#GuideBtnGhost:hover{ background: rgba(255,255,255,0.06); }
        """)
