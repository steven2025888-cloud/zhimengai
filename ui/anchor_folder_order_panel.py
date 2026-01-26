# ui/anchor_folder_order_panel.py
import os
import sys
import json
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QToolButton, QFileDialog, QLineEdit
)

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QListWidget, QListWidgetItem
from PySide6.QtCore import Qt, QTimer, Signal,QSize


from audio.folder_order_manager import FolderOrderManager
from core.state import app_state
from config import AUDIO_BASE_DIR

from ui.dialogs import confirm_dialog, choice_dialog, ChoiceItem


def _open_in_file_manager(path: str):
    p = os.path.abspath(path)
    if sys.platform.startswith("win"):
        os.startfile(p)  # type: ignore
    elif sys.platform == "darwin":
        os.system(f'open "{p}"')
    else:
        os.system(f'xdg-open "{p}"')


def _project_root() -> Path:
    # ui/*.py -> parents[1] is project root
    return Path(__file__).resolve().parents[1]


def _runtime_state_path() -> Path:
    return _project_root() / "runtime_state.json"


def _load_runtime_state() -> dict:
    p = _runtime_state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_runtime_state(state: dict):
    p = _runtime_state_path()
    try:
        p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # 最差也别让 UI 崩
        pass


class DraggableListWidget(QListWidget):
    reorderFinished = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropOverwriteMode(False)
        self.setDefaultDropAction(Qt.MoveAction)

    def dropEvent(self, event):
        # ✅ 让 Qt 自己完成 InternalMove（最稳，不会丢文本）
        super().dropEvent(event)
        QTimer.singleShot(0, self.reorderFinished.emit)


class AnchorFolderOrderPanel(QWidget):
    """
    主播设置：音频目录选择 + 讲解文件夹播放顺序
    兼容旧版 FolderOrderManager（没有 set_base_dir 的情况也能跑）
    """

    def __init__(self, parent=None, resource_path_func=None, save_flag_cb=None):
        super().__init__(parent)
        self._resource_path = resource_path_func
        self._save_flag = save_flag_cb

        # 目录：默认 AUDIO_BASE_DIR，可由用户选择并持久化
        default_dir = str(AUDIO_BASE_DIR)
        cur_dir = getattr(app_state, "anchor_audio_dir", "") or default_dir
        self._apply_anchor_dir_to_state(cur_dir, persist=False)

        self._last_saved_order: list[str] = []
        self._order_change_scheduled = False
        self._dirty = False

        # ✅ 创建 manager（兼容旧实现）
        self.manager = self._build_manager_for_dir(self.anchor_audio_dir)
        app_state.folder_manager = self.manager  # 始终让播放用最新的

        # ===== UI =====
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        top_row = QHBoxLayout()
        lbl_title = QLabel("主播设置")
        f = QFont()
        f.setBold(True)
        f.setPointSize(12)
        lbl_title.setFont(f)
        top_row.addWidget(lbl_title)
        top_row.addStretch(1)
        root.addLayout(top_row)

        lbl_desc = QLabel("选择主播音频目录，并设置讲解文件夹轮播顺序（越靠前优先级越高）")
        lbl_desc.setStyleSheet("color:#93A4B7;")
        root.addWidget(lbl_desc)

        # ===== 目录行（复用助播那套风格：路径输入框 + 打开/选择 + 复制） =====
        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)

        lbl_dir_title = QLabel("主播音频目录：")
        lbl_dir_title.setMinimumWidth(92)

        self.edt_dir = QLineEdit()
        self.edt_dir.setReadOnly(True)
        self.edt_dir.setPlaceholderText("请选择主播音频目录…")
        self.edt_dir.setMinimumHeight(34)
        self.edt_dir.setStyleSheet("""
            QLineEdit {
                border: 1px solid rgba(255,255,255,0.14);
                border-radius: 10px;
                padding: 0 10px;
                background: rgba(0,0,0,0.18);
                color: #E6EEF8;
            }
            QLineEdit:focus {
                border: 1px solid rgba(57,113,249,0.45);
                background: rgba(0,0,0,0.22);
            }
        """)

        self.btn_open_dir = QPushButton("打开")
        self.btn_choose_dir = QPushButton("选择文件夹")

        for b in (self.btn_open_dir, self.btn_choose_dir):
            b.setFixedHeight(34)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("""
                QPushButton {
                    border: 1px solid rgba(255,255,255,0.14);
                    border-radius: 10px;
                    padding: 0 12px;
                    background: rgba(255,255,255,0.06);
                    color: #E6EEF8;
                }
                QPushButton:hover {
                    background: rgba(255,255,255,0.10);
                    border: 1px solid rgba(255,255,255,0.20);
                }
                QPushButton:pressed {
                    background: rgba(255,255,255,0.14);
                }
            """)

        dir_row.addWidget(lbl_dir_title)
        dir_row.addWidget(self.edt_dir, 1)
        dir_row.addWidget(self.btn_open_dir)
        dir_row.addWidget(self.btn_choose_dir)
        root.addLayout(dir_row)

        self._refresh_dir_label()

        # ===== 状态 =====
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color:#93A4B7;")
        root.addWidget(self.lbl_status)

        # ===== 列表 + 箭头 =====
        center = QHBoxLayout()
        root.addLayout(center, 1)

        self.list = DraggableListWidget()
        self.list.setDragDropMode(QListWidget.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.setSelectionMode(QListWidget.SingleSelection)
        self.list.setToolTip("提示：按住某一项拖动即可改变顺序")
        self.list.setStyleSheet("""
            QListWidget {
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 12px;
                background: rgba(0,0,0,0.16);
                color: #E6EEF8;
                padding: 6px;
            }
            QListWidget::item {
                padding: 8px 10px;
                border-radius: 10px;
            }
            QListWidget::item:selected {
                background: rgba(57,113,249,0.22);
                border: 1px solid rgba(57,113,249,0.35);
            }
        """)
        center.addWidget(self.list, 1)

        arrow_col = QVBoxLayout()
        arrow_col.setSpacing(8)
        arrow_col.setAlignment(Qt.AlignTop)
        center.addLayout(arrow_col)

        self.btn_up = QToolButton()
        self.btn_down = QToolButton()
        self._setup_arrow_buttons()

        arrow_col.addWidget(self.btn_up)
        arrow_col.addWidget(self.btn_down)
        arrow_col.addStretch(1)

        # ===== 底部按钮 =====
        bottom = QHBoxLayout()
        self.btn_save = QPushButton("💾 保存并应用排序")
        self.btn_reload = QPushButton("🔄 重新扫描文件夹")
        self.btn_save.setEnabled(False)

        for b in (self.btn_save, self.btn_reload):
            b.setFixedHeight(36)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("""
                QPushButton {
                    border: 1px solid rgba(255,255,255,0.14);
                    border-radius: 12px;
                    padding: 0 14px;
                    background: rgba(255,255,255,0.06);
                    color: #E6EEF8;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: rgba(255,255,255,0.10);
                    border: 1px solid rgba(255,255,255,0.20);
                }
                QPushButton:pressed {
                    background: rgba(255,255,255,0.14);
                }
                QPushButton:disabled {
                    color: rgba(230,238,248,0.35);
                    background: rgba(255,255,255,0.03);
                }
            """)

        bottom.addWidget(self.btn_save)
        bottom.addWidget(self.btn_reload)
        bottom.addStretch(1)
        root.addLayout(bottom)

        # ===== 事件 =====
        self.btn_choose_dir.clicked.connect(self.choose_dir)
        self.btn_open_dir.clicked.connect(self.open_dir)

        self.btn_up.clicked.connect(self.move_up)
        self.btn_down.clicked.connect(self.move_down)

        self.btn_save.clicked.connect(self.save_order)
        self.btn_reload.clicked.connect(self.reload_folders)

        model = self.list.model()
        model.rowsMoved.connect(self._on_order_changed)
        model.rowsInserted.connect(self._on_order_changed)
        model.rowsRemoved.connect(self._on_order_changed)
        # 顶部吸附/手动移动会通过此信号通知完成，保证不丢项
        self.list.reorderFinished.connect(self._on_order_changed)

        self.reload_folders(set_saved_snapshot=True)

    # ------------------- 目录 -------------------

    @property
    def anchor_audio_dir(self) -> str:
        return getattr(app_state, "anchor_audio_dir", str(AUDIO_BASE_DIR))

    def _apply_anchor_dir_to_state(self, path: str, persist: bool = True):
        p = Path(path).expanduser().resolve()
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            p = Path(str(AUDIO_BASE_DIR)).expanduser().resolve()
            p.mkdir(parents=True, exist_ok=True)

        app_state.anchor_audio_dir = str(p)

        if persist:
            st = _load_runtime_state()
            st["anchor_audio_dir"] = str(p)
            _save_runtime_state(st)

    def _refresh_dir_label(self):
        self.edt_dir.setText(self.anchor_audio_dir)

    def choose_dir(self):
        picked = QFileDialog.getExistingDirectory(self, "选择主播音频目录", self.anchor_audio_dir)
        if not picked:
            return

        self._apply_anchor_dir_to_state(picked, persist=True)
        self._refresh_dir_label()

        # ✅ 切目录：重建 manager（兼容旧版，没有 set_base_dir 也可）
        self.manager = self._build_manager_for_dir(self.anchor_audio_dir)
        app_state.folder_manager = self.manager

        self.reload_folders(set_saved_snapshot=True)
        confirm_dialog(self, "已切换目录", f"主播音频目录已更新：\n{self.anchor_audio_dir}")

    def open_dir(self):
        try:
            _open_in_file_manager(self.anchor_audio_dir)
        except Exception as e:
            confirm_dialog(self, "打开失败", str(e))

    # ------------------- manager 兼容层 -------------------

    def _order_file(self, base_dir: str) -> str:
        return os.path.join(base_dir, "_folder_order.json")

    def _scan_folders(self, base_dir: str) -> list[str]:
        if not os.path.isdir(base_dir):
            return []
        return sorted([
            f for f in os.listdir(base_dir)
            if os.path.isdir(os.path.join(base_dir, f))
        ])

    def _load_order_for_dir(self, base_dir: str) -> list[str]:
        all_folders = self._scan_folders(base_dir)
        of = self._order_file(base_dir)

        if os.path.exists(of):
            try:
                with open(of, "r", encoding="utf-8") as f:
                    saved = json.load(f) or []
                folders = [x for x in saved if x in all_folders]
                for x in all_folders:
                    if x not in folders:
                        folders.append(x)
                return folders
            except Exception:
                return all_folders
        return all_folders

    def _save_order_for_dir(self, base_dir: str, order: list[str]):
        of = self._order_file(base_dir)
        with open(of, "w", encoding="utf-8") as f:
            json.dump(order, f, ensure_ascii=False, indent=2)

    def _build_manager_for_dir(self, base_dir: str):
        """
        兼容你现有 FolderOrderManager：
        - 如果有 set_base_dir()，直接用
        - 如果没有，就：实例化后挂上 base_dir + folders + 自己的 load/save
        """
        m = FolderOrderManager()

        # 新版：有 set_base_dir
        if hasattr(m, "set_base_dir"):
            try:
                m.set_base_dir(base_dir)
                return m
            except Exception:
                pass

        # 旧版：没有 set_base_dir，做兼容绑定
        m.base_dir = base_dir  # 给 pick_next_audio 可能用到（如果你代码里用）
        m.folders = self._load_order_for_dir(base_dir)

        def _load():
            m.folders = self._load_order_for_dir(base_dir)

        def _save(order: list[str]):
            self._save_order_for_dir(base_dir, order)
            m.folders = order
            if hasattr(m, "index"):
                m.index = 0

        # 覆盖到对象上
        m.load = _load  # type: ignore
        m.save = _save  # type: ignore

        return m

    # ------------------- SVG 按钮 -------------------

    def _icon_path(self, rel_path: str) -> str:
        if callable(self._resource_path):
            return self._resource_path(rel_path)
        return os.path.join(os.path.abspath("."), rel_path)

    def _setup_arrow_buttons(self):
        up_svg = self._icon_path(os.path.join("img", "MingcuteUpFill.svg"))
        down_svg = self._icon_path(os.path.join("img", "MingcuteDownFill.svg"))

        if os.path.exists(up_svg):
            self.btn_up.setIcon(QIcon(up_svg))
        else:
            self.btn_up.setText("↑")

        if os.path.exists(down_svg):
            self.btn_down.setIcon(QIcon(down_svg))
        else:
            self.btn_down.setText("↓")

        self.btn_up.setToolTip("向上移动")
        self.btn_down.setToolTip("向下移动")

        for b in (self.btn_up, self.btn_down):
            b.setIconSize(QSize(18, 18))
            b.setFixedSize(36, 36)
            b.setStyleSheet("""
                QToolButton { border-radius: 10px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.14); }
                QToolButton:hover { background: rgba(255,255,255,0.10); border: 1px solid rgba(255,255,255,0.20); }
                QToolButton:pressed { background: rgba(255,255,255,0.14); }
            """)

    # ------------------- 排序/状态 -------------------

    def get_current_order(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

    def _refresh_status(self):
        order = self.get_current_order()
        extra = "（有未保存更改）" if self._dirty else ""
        self.lbl_status.setText(f"当前目录共 {len(order)} 个文件夹 {extra}".strip())

    def _set_dirty(self, dirty: bool):
        self._dirty = bool(dirty)
        self.btn_save.setEnabled(self._dirty)
        self._refresh_status()

    def _apply_order_runtime(self, order: list[str]):
        """让新排序立即影响播放（不必重启）。不持久化到磁盘。"""
        try:
            # 保持播放端拿到的是同一个 manager 对象：直接改其内部状态
            if hasattr(self.manager, "folders"):
                self.manager.folders = order  # type: ignore
            if hasattr(self.manager, "index"):
                self.manager.index = 0  # type: ignore
            # 统一入口：播放端应读取 app_state.folder_manager
            app_state.folder_manager = self.manager
        except Exception:
            pass

    def _on_order_changed(self, *args, **kwargs):
        # 拖动时 model 会触发多次（rowsRemoved/rowsInserted/rowsMoved），
        # 这里做一次 0ms 去抖：等事件循环结束再读取最终顺序，避免“拖到第一个后消失”。
        if self._order_change_scheduled:
            return
        self._order_change_scheduled = True
        QTimer.singleShot(0, self._apply_order_change)

    def _apply_order_change(self):
        self._order_change_scheduled = False
        cur = self.get_current_order()
        # ✅ 实时应用到 manager（即刻生效），但仍需点“保存”来持久化
        self._apply_order_runtime(cur)
        self._set_dirty(cur != self._last_saved_order)

    def move_up(self):
        row = self.list.currentRow()
        if row <= 0:
            return
        item = self.list.takeItem(row)
        self.list.insertItem(row - 1, item)
        self.list.setCurrentRow(row - 1)
        self._on_order_changed()

    def move_down(self):
        row = self.list.currentRow()
        if row < 0 or row >= self.list.count() - 1:
            return
        item = self.list.takeItem(row)
        self.list.insertItem(row + 1, item)
        self.list.setCurrentRow(row + 1)
        self._on_order_changed()

    def reload_folders(self, set_saved_snapshot: bool = False):
        if self._dirty and not set_saved_snapshot:
            choice, ok = choice_dialog(
                self,
                "确认重新扫描？",
                "你有未保存的排序。\n重新扫描会从磁盘重新读取列表，可能覆盖当前顺序。\n\n仍要继续吗？",
                items=[
                    ChoiceItem("继续扫描", role="destructive"),
                    ChoiceItem("取消", role="cancel"),
                ],
            )
            if not ok or choice != "继续扫描":
                return

        self.manager.load()
        self.list.clear()
        for name in getattr(self.manager, "folders", []) or []:
            it = QListWidgetItem(name)
            it.setData(Qt.UserRole, name)  # ✅ uid：文件夹名（通常唯一）
            self.list.addItem(it)

        if set_saved_snapshot:
            self._last_saved_order = self.get_current_order()
            self._set_dirty(False)
        else:
            self._refresh_status()

    def save_order(self):
        order = self.get_current_order()
        if not order:
            confirm_dialog(self, "无法保存", "列表为空，无法保存顺序。")
            return

        self.manager.save(order)
        # ✅ 保存后也立即应用一次（防止播放端仍读旧缓存）
        self._apply_order_runtime(order)

        self._last_saved_order = order[:]
        self._set_dirty(False)
        confirm_dialog(self, "保存成功", "文件夹顺序已保存，并已立即生效。")
