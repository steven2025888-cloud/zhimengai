from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QPushButton, QHBoxLayout, QMessageBox,
    QLabel, QToolButton, QSizePolicy
)
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QFont

from audio.folder_order_manager import FolderOrderManager
from ui.dialogs import confirm_dialog, choice_dialog, ChoiceItem


class FolderOrderPanel(QWidget):
    """
    讲解文件夹排序面板（可拖拽排序）
    - 拖动列表项调整顺序
    - “保存并应用排序” 会持久化顺序（下次轮播按此顺序）
    - “重新扫描文件夹” 会从磁盘重新读取文件夹列表（可能覆盖未保存的拖动）
    """

    SETTINGS_KEY_TIP_SHOWN = "folder_order_panel/tip_shown_v1"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = FolderOrderManager()

        self._last_saved_order: list[str] = []
        self._dirty = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ===== 顶部说明栏 =====
        top_row = QHBoxLayout()
        self.lbl_title = QLabel("主播讲解文件夹播放顺序")
        f = QFont()
        f.setBold(True)
        f.setPointSize(11)
        self.lbl_title.setFont(f)

        self.btn_help = QToolButton()
        self.btn_help.setText("❔ 使用说明")
        self.btn_help.setToolTip("点击查看如何拖拽排序、保存与重新扫描的区别")
        self.btn_help.clicked.connect(self.show_help)

        top_row.addWidget(self.lbl_title)
        top_row.addStretch(1)
        top_row.addWidget(self.btn_help)
        layout.addLayout(top_row)

        self.lbl_hint = QLabel(
            "✅ 用法：用鼠标【按住列表项】上下拖动即可调整顺序；调整后点击【保存并应用排序】。\n会按照顺序随机抽取文件夹一个音频播放"
        )
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color: #555;")
        layout.addWidget(self.lbl_hint)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #777;")
        layout.addWidget(self.lbl_status)

        # ===== 列表 =====
        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.setDropIndicatorShown(True)
        self.list.setToolTip("提示：按住某一项拖动即可改变顺序")
        layout.addWidget(self.list)

        # 监听拖拽导致的顺序变化（dirty 状态）
        model = self.list.model()
        model.rowsMoved.connect(self._on_order_changed)
        model.rowsInserted.connect(self._on_order_changed)
        model.rowsRemoved.connect(self._on_order_changed)

        # ===== 按钮栏 =====
        btn_row = QHBoxLayout()

        self.btn_save = QPushButton("💾 保存并应用排序")
        self.btn_save.setToolTip("保存当前拖拽后的顺序，下次轮播按此顺序播放")
        self.btn_save.setEnabled(False)

        self.btn_reload = QPushButton("🔄 重新扫描文件夹")
        self.btn_reload.setToolTip("从磁盘重新读取文件夹列表（会覆盖未保存的拖拽顺序）")

        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_reload)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.btn_save.clicked.connect(self.save_order)
        self.btn_reload.clicked.connect(self.reload_folders)

        # 初次加载
        self.refresh(set_saved_snapshot=True)


    # ---------------- UI/状态 ----------------
    def refresh(self, set_saved_snapshot: bool = False):
        """刷新列表显示。set_saved_snapshot=True 表示把当前列表当作“已保存状态”"""
        self.list.clear()

        # 确保 manager 已加载到 folders
        # （你的旧逻辑是 __init__ 里直接 refresh，这里保持兼容）
        for name in getattr(self.manager, "folders", []) or []:
            self.list.addItem(name)

        order = self.get_current_order()
        self.lbl_status.setText(f"当前共 {len(order)} 个文件夹。"
                               f"{'（有未保存更改）' if self._dirty else ''}")

        if set_saved_snapshot:
            self._last_saved_order = order[:]
            self._set_dirty(False)

        # 空状态提示
        if len(order) == 0:
            self.lbl_hint.setText("⚠️ 未发现任何讲解文件夹。请先在对应目录中放入文件夹，然后点【重新扫描文件夹】。")
            self.lbl_hint.setStyleSheet("color: #b36b00;")
        else:
            self.lbl_hint.setText("✅ 用法：用鼠标【按住列表项】上下拖动即可调整顺序；调整后点击【保存并应用排序】。\n会按照顺序随机抽取文件夹一个音频播放")
            self.lbl_hint.setStyleSheet("color: #555;")

    def _set_dirty(self, dirty: bool):
        self._dirty = dirty
        self.btn_save.setEnabled(dirty)
        # 轻量更新状态文本
        order = self.get_current_order()
        self.lbl_status.setText(f"当前共 {len(order)} 个文件夹。"
                               f"{'（有未保存更改）' if self._dirty else ''}")

    def _on_order_changed(self, *args, **kwargs):
        # 拖拽后与最近一次保存快照对比
        current = self.get_current_order()
        dirty = current != self._last_saved_order
        self._set_dirty(dirty)

    def _maybe_show_first_tip(self):
        s = QSettings()
        if s.value(self.SETTINGS_KEY_TIP_SHOWN, False, type=bool):
            return
        s.setValue(self.SETTINGS_KEY_TIP_SHOWN, True)
        QMessageBox.information(
            self,
            "第一次使用提示",
            "这里可以调整“讲解文件夹”的轮播顺序：\n\n"
            "1）用鼠标按住某一项，上下拖动即可排序\n"
            "2）拖完后点【保存并应用排序】才会生效\n"
            "3）【重新扫描文件夹】是从磁盘重新读取列表（会覆盖未保存拖动）"
        )

    def show_help(self):
        QMessageBox.information(
            self,
            "使用说明",
            "✅ 拖拽排序：\n"
            "  用鼠标按住列表项，上下拖动即可改变播放顺序。\n\n"
            "💾 保存并应用排序：\n"
            "  把当前顺序保存下来，下次轮播按此顺序播放。\n\n"
            "🔄 重新扫描文件夹：\n"
            "  从磁盘重新读取文件夹列表（如果你拖拽了但没保存，会被覆盖）。"
        )

    # ---------------- 数据逻辑 ----------------
    def get_current_order(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def save_order(self):
        order = self.get_current_order()
        if not order:
            QMessageBox.warning(self, "无法保存", "列表为空，无法保存顺序。请先放入文件夹后再试。")
            return

        self.manager.save(order)
        self._last_saved_order = order[:]
        self._set_dirty(False)
        confirm_dialog(self, "保存成功", "文件夹顺序已保存，下次播放将按此顺序轮播。")

    def reload_folders(self):
        if self._dirty:
            r = QMessageBox.question(
                self,
                "确认重新扫描？",
                "你有未保存的拖拽顺序。\n重新扫描会从磁盘重新读取列表，可能覆盖当前顺序。\n\n仍要继续吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if r != QMessageBox.Yes:
                return

        self.manager.load()
        self.refresh(set_saved_snapshot=True)
