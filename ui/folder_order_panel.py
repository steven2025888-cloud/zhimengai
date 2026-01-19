from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QPushButton, QHBoxLayout, QMessageBox
)
from PySide6.QtCore import Qt
from audio.folder_order_manager import FolderOrderManager

class FolderOrderPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = FolderOrderManager()

        layout = QVBoxLayout(self)

        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.InternalMove)
        self.refresh()

        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("💾 保存顺序")
        self.btn_reload = QPushButton("🔄 重新扫描")
        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_reload)

        layout.addWidget(self.list)
        layout.addLayout(btn_row)

        self.btn_save.clicked.connect(self.save_order)
        self.btn_reload.clicked.connect(self.reload_folders)

    def refresh(self):
        self.list.clear()
        for name in self.manager.folders:
            self.list.addItem(name)

    def get_current_order(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def save_order(self):
        order = self.get_current_order()
        self.manager.save(order)
        QMessageBox.information(self, "保存成功", "讲解文件夹顺序已保存，下次播放将按此顺序轮播。")

    def reload_folders(self):
        self.manager.load()
        self.refresh()
