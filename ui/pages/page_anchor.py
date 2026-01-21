# ui/page_anchor.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ui.anchor_folder_order_panel import AnchorFolderOrderPanel


class AnchorPage(QWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        title = QLabel("主播设置")
        title.setStyleSheet("font-size:16px;font-weight:800;")

        desc = QLabel("选择主播音频目录，并设置讲解文件夹轮播顺序")
        desc.setStyleSheet("color:#93A4B7;")

        lay.addWidget(title)
        lay.addWidget(desc)

        panel = AnchorFolderOrderPanel(
            parent=ctx["main"],
            resource_path_func=ctx["resource_path"],
            save_flag_cb=ctx["save_runtime_flag"],
        )
        lay.addWidget(panel, 1)
