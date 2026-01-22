# ui/page_voice_model.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from config import BASE_URL
from ui.voice_model_panel import VoiceModelPanel


class VoiceModelPage(QWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)


        desc = QLabel("在这里上传 / 删除 / 设置默认主播音色（支持 MP3 / WAV）")
        desc.setStyleSheet("color:#93A4B7;")

        lay.addWidget(desc)

        panel = VoiceModelPanel(
            base_url=BASE_URL,
            license_key=ctx["license_key"],
            parent=self
        )
        lay.addWidget(panel, 1)
