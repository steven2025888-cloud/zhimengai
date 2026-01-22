# ui/page_zhuli.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ui.zhuli_keyword_panel import ZhuliKeywordPanel


class ZhuliPage(QWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)


        panel = ZhuliKeywordPanel(ctx["main"])
        lay.addWidget(panel, 1)
