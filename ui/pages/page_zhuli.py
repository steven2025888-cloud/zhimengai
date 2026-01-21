# ui/page_zhuli.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ui.zhuli_keyword_panel import ZhuliKeywordPanel


class ZhuliPage(QWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        title = QLabel("助播设置")
        title.setStyleSheet("font-size:16px;font-weight:800;")

        desc = QLabel("配置助播关键词：命中后播放 zhuli_audio 目录对应前缀音频")
        desc.setStyleSheet("color:#93A4B7;")

        lay.addWidget(title)
        lay.addWidget(desc)

        panel = ZhuliKeywordPanel(ctx["main"])
        lay.addWidget(panel, 1)
