# ui/page_anchor.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ui.anchor_folder_order_panel import AnchorFolderOrderPanel


class AnchorPage(QWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        panel = AnchorFolderOrderPanel(
            parent=ctx["main"],
            resource_path_func=ctx["resource_path"],
            save_flag_cb=ctx["save_runtime_flag"],
        )
        lay.addWidget(panel, 1)
