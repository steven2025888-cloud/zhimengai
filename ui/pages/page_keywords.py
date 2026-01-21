# ui/page_keywords.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ui.keyword_panel import KeywordPanel


class KeywordPage(QWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        title = QLabel("关键词设置")
        title.setStyleSheet("font-size:16px;font-weight:800;")
        lay.addWidget(title)

        panel = KeywordPanel(ctx["main"])
        lay.addWidget(panel, 1)
