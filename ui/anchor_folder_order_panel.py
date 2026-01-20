from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QPushButton, QHBoxLayout, QMessageBox,
    QLabel, QToolButton
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from audio.folder_order_manager import FolderOrderManager


class AnchorFolderOrderPanel(QWidget):
    """
    主播讲解文件夹排序面板（拖拽 + 上下箭头）
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = FolderOrderManager()

        self._last_saved_order: list[str] = []
        self._dirty = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ===== 标题 =====
        top_row = QHBoxLayout()
        title = QLabel("主播讲解播放顺序")
        f = QFont()
        f.setBold(True)
        f.setPointSize(11)
        title.setFont(f)

        top_row.addWidget(title)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        hint = QLabel("拖拽或使用右侧箭头调整播放顺序，越靠前优先播放")
        hint.setStyleSheet("color:#666;")
        layout.addWidget(hint)

        # ===== 中间区域 =====
        center = QHBoxLayout()
        layout.addLayout(center, 1)

        # 列表
        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.setSelectionMode(QListWidget.SingleSelection)
        center.addWidget(self.list, 1)

        # 右侧箭头
        arrow_col = QVBoxLayout()
        arrow_col.setSpacing(6)
        center.addLayout(arrow_col)

        from PySide6.QtGui import QIcon
        from PySide6.QtCore import QSize
        import os

        icon_up = QIcon(os.path.join("img", "MingcuteUpFill.svg"))
        icon_down = QIcon(os.path.join("img", "MingcuteDownFill.svg"))

        self.btn_up = QToolButton()
        self.btn_up.setIcon(icon_up)
        self.btn_up.setIconSize(QSize(20, 20))
        self.btn_up.setFixedSize(36, 36)
        self.btn_up.setToolTip("向上移动")
        self.btn_up.setStyleSheet("""
        QToolButton {
            border-radius: 6px;
            background: #F3F6FA;
        }
        QToolButton:hover {
            background: #E3E9F3;
        }
        QToolButton:pressed {
            background: #D6E0F0;
        }
        """)

        self.btn_down = QToolButton()
        self.btn_down.setIcon(icon_down)
        self.btn_down.setIconSize(QSize(20, 20))
        self.btn_down.setFixedSize(36, 36)
        self.btn_down.setToolTip("向下移动")
        self.btn_down.setStyleSheet("""
        QToolButton {
            border-radius: 6px;
            background: #F3F6FA;
        }
        QToolButton:hover {
            background: #E3E9F3;
        }
        QToolButton:pressed {
            background: #D6E0F0;
        }
        """)

        arrow_col.addWidget(self.btn_up)
        arrow_col.addWidget(self.btn_down)
        arrow_col.addStretch(1)

        # ===== 底部按钮 =====
        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("💾 保存并应用排序")
        self.btn_reload = QPushButton("🔄 重新扫描文件夹")

        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_reload)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # 事件
        self.btn_up.clicked.connect(self.move_up)
        self.btn_down.clicked.connect(self.move_down)
        self.btn_save.clicked.connect(self.save_order)
        self.btn_reload.clicked.connect(self.reload_folders)

        self.list.model().rowsMoved.connect(self._mark_dirty)

        self.refresh(set_saved_snapshot=True)

    # ---------------- 核心逻辑 ----------------

    def refresh(self, set_saved_snapshot=False):
        self.list.clear()
        for name in getattr(self.manager, "folders", []) or []:
            self.list.addItem(name)

        if set_saved_snapshot:
            self._last_saved_order = self.get_current_order()
            self._dirty = False

    def get_current_order(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def _mark_dirty(self, *args):
        self._dirty = True

    def move_up(self):
        row = self.list.currentRow()
        if row <= 0:
            return
        item = self.list.takeItem(row)
        self.list.insertItem(row - 1, item)
        self.list.setCurrentRow(row - 1)
        self._dirty = True

    def move_down(self):
        row = self.list.currentRow()
        if row < 0 or row >= self.list.count() - 1:
            return
        item = self.list.takeItem(row)
        self.list.insertItem(row + 1, item)
        self.list.setCurrentRow(row + 1)
        self._dirty = True

    def save_order(self):
        order = self.get_current_order()
        if not order:
            QMessageBox.warning(self, "无法保存", "没有可保存的文件夹顺序。")
            return

        self.manager.save(order)
        self._last_saved_order = order[:]
        self._dirty = False
        QMessageBox.information(self, "保存成功", "主播讲解文件夹播放顺序已生效。")

    def reload_folders(self):
        if self._dirty:
            r = QMessageBox.question(
                self, "确认重新扫描？",
                "当前顺序尚未保存，重新扫描会丢失排序，是否继续？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if r != QMessageBox.Yes:
                return

        self.manager.load()
        self.refresh(set_saved_snapshot=True)
