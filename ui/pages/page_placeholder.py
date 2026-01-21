# ui/page_placeholder.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt


class PlaceholderPage(QWidget):
    def __init__(self, text: str):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(text)
        lab.setAlignment(Qt.AlignCenter)
        lab.setStyleSheet("color:#93A4B7; font-size:14px;")
        lay.addStretch(1)
        lay.addWidget(lab)
        lay.addStretch(1)
