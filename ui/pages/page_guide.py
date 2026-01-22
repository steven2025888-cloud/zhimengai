# ui/pages/page_guide.py
import os
from typing import Callable, List, Tuple, Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QApplication
)

from core.state import app_state
from config import AUDIO_BASE_DIR


class _Card(QFrame):
    def __init__(self, title: str, number: int, body_html: str, actions: Optional[List[Tuple[str, Callable]]] = None):
        super().__init__()
        self.setObjectName("GuideCard")
        self.setFrameShape(QFrame.NoFrame)
        self.setAttribute(Qt.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # header row: number badge + title
        header = QHBoxLayout()
        header.setSpacing(10)

        badge = QLabel(str(number))
        badge.setObjectName("GuideBadge")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(26, 26)

        lbl_title = QLabel(title)
        lbl_title.setObjectName("GuideTitle")
        lbl_title.setTextInteractionFlags(Qt.TextSelectableByMouse)

        header.addWidget(badge)
        header.addWidget(lbl_title, 1)
        root.addLayout(header)

        body = QLabel()
        body.setObjectName("GuideBody")
        body.setTextFormat(Qt.RichText)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setText(body_html)
        root.addWidget(body)

        if actions:
            row = QHBoxLayout()
            row.addStretch(1)
            for i, (text, fn) in enumerate(actions):
                btn = QPushButton(text)
                btn.setFixedHeight(34)
                btn.setCursor(Qt.PointingHandCursor)
                if i == 0:
                    btn.setObjectName("GuideBtnPrimary")
                else:
                    btn.setObjectName("GuideBtnSecondary")
                btn.clicked.connect(fn)
                row.addWidget(btn)
            root.addLayout(row)


class GuidePage(QWidget):
    """
    新手引导页：一步一步引导用户完成设置 -> 开启自动化 -> 启动 -> 登录进入直播控制台
    """
    def __init__(self, ctx: dict):
        super().__init__()
        self.ctx = ctx
        self.jump_to = (ctx or {}).get("jump_to")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scroll container
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll, 1)

        content = QWidget()
        scroll.setWidget(content)

        root = QVBoxLayout(content)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # Top header (title + short description)
        header = QFrame()
        header.setObjectName("GuideHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        header_l = QVBoxLayout(header)
        header_l.setContentsMargins(16, 16, 16, 16)
        header_l.setSpacing(6)

        title = QLabel("新手引导")
        title.setObjectName("GuidePageTitle")

        subtitle = QLabel("按下面 4 步做一遍，你就能完整跑通：设置 → 关键词 → 自动化 → 启动/登录 → 直播控制台")
        subtitle.setObjectName("GuidePageSubtitle")
        subtitle.setWordWrap(True)

        header_l.addWidget(title)
        header_l.addWidget(subtitle)
        root.addWidget(header)

        # Step 1: anchor audio dir
        current_dir = getattr(app_state, "anchor_audio_dir", "") or str(AUDIO_BASE_DIR)
        current_dir = str(current_dir)

        step1_body = f"""
        <div style="line-height:1.6">
          <b>要做什么：</b>指定“主播音频目录”（用于放你的主播讲解音频 / 话术音频）。<br/>
          <b>当前默认：</b><span style="opacity:0.9">{current_dir}</span><br/>
          <b>可以不设置：</b>你直接用默认目录也能跑通流程（建议后续再整理自己的音频库）。<br/><br/>
          <b>怎么用：</b><br/>
          1）把你的音频文件（mp3/wav）放进这个目录；<br/>
          2）建议按“产品/场景”建立子文件夹，后续更好管理；<br/>
          3）回到工作台启动后，系统会按你的设置播放。<br/>
        </div>
        """

        step1_actions = []
        if callable(self.jump_to):
            step1_actions = [("去设置主播音频目录", lambda: self.jump_to("主播设置"))]

        root.addWidget(_Card("设置主播音频目录（可选）", 1, step1_body, step1_actions))

        # Step 2: keywords
        step2_body = """
        <div style="line-height:1.6">
          <b>要做什么：</b>配置“关键词分类 + 触发词”，让系统知道观众说什么时该怎么回应/播放。<br/><br/>
          <b>怎么用：</b><br/>
          1）左侧 <b>新建分类</b>（例如：价格 / 尺寸 / 售后）；<br/>
          2）右侧填 <b>必含词/意图词/排除词</b>（支持批量粘贴）；<br/>
          3）需要自动回复的话，把内容加到 <b>回复词</b>；<br/>
          4）点 <b>保存并热更新</b>：立即生效，不用重启。<br/>
        </div>
        """

        step2_actions = []
        if callable(self.jump_to):
            step2_actions = [("去设置关键词", lambda: self.jump_to("关键词设置"))]
        root.addWidget(_Card("设置关键词（必做）", 2, step2_body, step2_actions))

        # Step 3: automation toggles
        step3_body = """
        <div style="line-height:1.6">
          <b>要做什么：</b>在 AI 工作台打开你需要的自动化开关（例如：弹幕回复/自动回复/助播/报时等）。<br/><br/>
          <b>怎么用：</b><br/>
          1）进入 <b>AI工作台</b>；<br/>
          2）打开你需要的功能开关（新手建议先只开：<b>弹幕/关键词</b>相关）；<br/>
          3）如果有“测试/试听”按钮，先点一下确认音频正常。<br/>
        </div>
        """
        step3_actions = []
        if callable(self.jump_to):
            step3_actions = [("去 AI 工作台开启自动化", lambda: self.jump_to("AI工作台"))]
        root.addWidget(_Card("开启自动化控制（必做）", 3, step3_body, step3_actions))

        # Step 4: start & login
        step4_body = """
        <div style="line-height:1.6">
          <b>要做什么：</b>启动系统后扫码登录抖音/视频号，进入直播控制台开始工作。<br/><br/>
          <b>怎么用：</b><br/>
          1）在工作台点击 <b>启动系统</b>（或开始监听/开始自动化）；<br/>
          2）按提示 <b>扫码登录抖音</b> 和 <b>扫码登录视频号</b>（只要你用哪个平台就登录哪个）；<br/>
          3）登录成功后打开 <b>直播控制台</b>：你能看到弹幕、触发记录、播放队列等；<br/>
          4）开播后，观众发言命中关键词 → 系统自动播放/回复，你只要专注带货。<br/>
        </div>
        """
        step4_actions = []
        if callable(self.jump_to):
            step4_actions = [("回到 AI 工作台启动系统", lambda: self.jump_to("AI工作台"))]
        root.addWidget(_Card("启动系统 + 扫码登录 + 进入直播控制台（必做）", 4, step4_body, step4_actions))

        # bottom tips
        tip = QLabel("小提示：你可以先用“测试直播间/小号”跑通一次流程，再正式开播。")
        tip.setObjectName("GuideTip")
        tip.setWordWrap(True)
        root.addWidget(tip)

        root.addStretch(1)

        self._apply_local_style()

    def _apply_local_style(self):
        """
        深色主题友好的局部样式（只作用于本页）
        """
        self.setStyleSheet(self.styleSheet() + """
        /* Page */
        #GuideHeader {
            border-radius: 14px;
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
        }
        #GuidePageTitle {
            font-size: 18px;
            font-weight: 900;
        }
        #GuidePageSubtitle {
            font-size: 12px;
            opacity: 0.85;
        }

        /* Card */
        #GuideCard {
            border-radius: 14px;
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.08);
        }
        #GuideTitle {
            font-size: 14px;
            font-weight: 800;
        }
        #GuideBody {
            font-size: 12px;
            opacity: 0.92;
        }
        #GuideBadge {
            border-radius: 13px;
            background: rgba(255,255,255,0.10);
            border: 1px solid rgba(255,255,255,0.14);
            font-weight: 900;
        }
        #GuideTip {
            opacity: 0.8;
            padding: 6px 4px;
        }

        /* Buttons */
        QPushButton#GuideBtnPrimary {
            border: none;
            border-radius: 10px;
            padding: 8px 14px;
            background: rgba(0, 153, 255, 0.85);
            font-weight: 800;
        }
        QPushButton#GuideBtnPrimary:hover { background: rgba(0, 153, 255, 0.95); }
        QPushButton#GuideBtnPrimary:pressed { background: rgba(0, 120, 210, 0.95); }

        QPushButton#GuideBtnSecondary {
            border-radius: 10px;
            padding: 8px 14px;
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.12);
            font-weight: 700;
        }
        QPushButton#GuideBtnSecondary:hover { background: rgba(255,255,255,0.10); }
        """)
