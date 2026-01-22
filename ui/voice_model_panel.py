import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFileDialog, QMessageBox,
    QFrame
)
from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QFont, QIcon
from api.voice_api import VoiceApiClient
from core.state import app_state
from ui.dialogs import confirm_dialog


class VoiceModelLoader(QThread):
    finished = Signal(list)

    def __init__(self, api: VoiceApiClient):
        super().__init__()
        self.api = api

    def run(self):
        try:
            resp = self.api.list_models()
            if isinstance(resp, dict) and resp.get("code") == 0:
                self.finished.emit(resp.get("data", []))
            else:
                self.finished.emit([])
        except Exception:
            self.finished.emit([])


class _ModelItemWidget(QWidget):
    """更好看的列表项：名称 + 默认徽章"""
    def __init__(self, name: str, is_default: bool):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)

        self.lbl_name = QLabel(name)
        self.lbl_name.setObjectName("ModelName")
        row.addWidget(self.lbl_name)

        row.addStretch(1)

        self.badge = QLabel("默认" if is_default else "")
        self.badge.setVisible(bool(is_default))
        self.badge.setObjectName("DefaultBadge")
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setFixedHeight(22)
        self.badge.setMinimumWidth(46)
        row.addWidget(self.badge)

    def set_default(self, val: bool):
        self.badge.setVisible(bool(val))
        self.badge.setText("默认" if val else "")


class VoiceModelPanel(QWidget):
    """
    云端音色库面板（美化版）
    - 头部：标题 + 数量 + 刷新
    - 主按钮：上传新音色
    - 列表：更清爽的 item（名称 + 默认徽章）
    - 空态：提示用户上传
    """

    def __init__(self, base_url: str, license_key: str, parent=None):
        super().__init__(parent)
        self.api = VoiceApiClient(base_url, license_key)
        self.current_model = None
        self.loader = None

        self.setMinimumWidth(380)
        self.init_ui()
        self.load_models_async()

    # ================= UI =================

    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # 统一样式（深色主题友好：不强制白底；按钮本地美化，避免依赖全局 QPushButton 默认蓝块）
        self.setStyleSheet("""
        QWidget { background: transparent; }

        /* 卡片容器：适配深色主题（半透明提亮，不会变成白底） */
        QFrame#Card {
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 14px;
        }

        QLabel#Title {
            font-size: 16px;
            font-weight: 800;
        }
        QLabel#Subtle {
            color: rgba(255,255,255,0.60);
            font-size: 12px;
        }

        /* ===== 按钮（本地定义更明显的层级：主/次/危险） ===== */
        QPushButton {
            border-radius: 10px;
            padding: 8px 14px;
            font-weight: 800;
        }

        /* 主按钮：更明显、更“实心” */
        QPushButton#BtnPrimary {
            background: rgba(57,113,249,0.95);
            border: 1px solid rgba(57,113,249,0.55);
            color: rgba(255,255,255,0.95);
        }
        QPushButton#BtnPrimary:hover {
            background: rgba(57,113,249,0.78);
            border: 1px solid rgba(120,180,255,0.95);
        }
        QPushButton#BtnPrimary:pressed {
            background: rgba(57,113,249,0.55);
        }

        /* 次按钮：描边/半透明（用于“刷新”“设为默认”） */
        QPushButton#BtnSecondary {
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.14);
            color: rgba(230,238,248,0.92);
        }
        QPushButton#BtnSecondary:hover {
            background: rgba(255,255,255,0.10);
            border: 1px solid rgba(120,180,255,0.55);
        }
        QPushButton#BtnSecondary:pressed {
            background: rgba(255,255,255,0.05);
        }

        /* 危险按钮：红色提醒（用于删除） */
        QPushButton#BtnDanger {
            background: rgba(255,77,79,0.18);
            border: 1px solid rgba(255,77,79,0.45);
            color: rgba(255,230,230,0.95);
        }
        QPushButton#BtnDanger:hover {
            background: rgba(255,77,79,0.28);
            border: 1px solid rgba(255,77,79,0.70);
        }
        QPushButton#BtnDanger:pressed {
            background: rgba(255,77,79,0.14);
        }

        /* 禁用态统一 */
        QPushButton:disabled {
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.10);
            color: rgba(255,255,255,0.35);
        }

        /* 列表：不强制白底，避免白底+白字；边距与圆角保留 */
        QListWidget {
            background: transparent;
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 12px;
            padding: 6px;
        }
        QListWidget::item {
            border-radius: 12px;
            margin: 4px;
            padding: 0px;
        }
        QListWidget::item:selected {
            background: rgba(43,127,255,0.22);
            border: 1px solid rgba(43,127,255,0.35);
        }

        QLabel#ModelName { font-size: 13px; font-weight: 650; }

        /* 默认徽章：深色主题高对比 */
        QLabel#DefaultBadge {
            color: rgba(255,255,255,0.92);
            background: rgba(43,127,255,0.28);
            border: 1px solid rgba(43,127,255,0.55);
            border-radius: 11px;
            padding-left: 8px;
            padding-right: 8px;
            font-size: 12px;
            font-weight: 800;
        }
        """)

        # 卡片容器
        card = QFrame()
        card.setObjectName("Card")
        root.addWidget(card, 1)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # ===== 头部 =====
        header = QHBoxLayout()
        header.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)

        self.lbl_title = QLabel("🎙 主播音色库")
        self.lbl_title.setObjectName("Title")
        self.lbl_title.setFont(QFont("微软雅黑", 14, QFont.Bold))
        title_col.addWidget(self.lbl_title)

        self.lbl_meta = QLabel("正在加载…")
        self.lbl_meta.setObjectName("Subtle")
        title_col.addWidget(self.lbl_meta)

        header.addLayout(title_col)
        header.addStretch(1)

        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setObjectName("BtnSecondary")
        self.btn_refresh.setFixedHeight(34)
        self.btn_refresh.clicked.connect(self.load_models_async)
        header.addWidget(self.btn_refresh)

        layout.addLayout(header)

        # ===== 上传按钮 =====
        self.btn_upload = QPushButton("➕ 上传新音色模型（MP3 / WAV）")
        self.btn_upload.setObjectName("BtnPrimary")
        self.btn_upload.setFixedHeight(40)
        self.btn_upload.clicked.connect(self.upload_model)
        layout.addWidget(self.btn_upload)

        # ===== 列表 + 空态 =====
        self.list = QListWidget()
        self.list.setSpacing(0)
        self.list.setUniformItemSizes(False)
        self.list.setSelectionMode(QListWidget.SingleSelection)
        self.list.currentItemChanged.connect(self.on_current_changed)
        layout.addWidget(self.list, 1)

        self.empty = QLabel("暂无音色模型\n点击上方按钮上传 MP3 / WAV，即可在这里选择并设为默认。")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setObjectName("Subtle")
        self.empty.setVisible(False)
        layout.addWidget(self.empty)

        # ===== 底部操作 =====
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_default = QPushButton("⭐ 设为默认")
        self.btn_delete = QPushButton("🗑 删除模型")
        self.btn_default.setObjectName("BtnSecondary")
        self.btn_delete.setObjectName("BtnDanger")
        self.btn_default.setFixedHeight(36)
        self.btn_delete.setFixedHeight(36)

        self.btn_default.clicked.connect(self.set_default)
        self.btn_delete.clicked.connect(self.delete_model)

        btn_row.addWidget(self.btn_default)
        btn_row.addWidget(self.btn_delete)
        layout.addLayout(btn_row)

        self.btn_default.setEnabled(False)
        self.btn_delete.setEnabled(False)

    # ================= 云端异步加载 =================

    def load_models_async(self):
        self.list.clear()
        self.current_model = None
        self.btn_default.setEnabled(False)
        self.btn_delete.setEnabled(False)

        self.empty.setVisible(False)
        self.lbl_meta.setText("正在加载…")

        self.loader = VoiceModelLoader(self.api)
        self.loader.finished.connect(self.render_models)
        self.loader.start()

    def render_models(self, models: list):
        self.list.clear()
        self.current_model = None
        app_state.current_model_id = None

        if not models:
            self.lbl_meta.setText("0 个模型")
            self.empty.setVisible(True)
            return

        default_item = None

        for m in models:
            # 列表项
            item = QListWidgetItem()
            item.setData(Qt.UserRole, m)

            w = _ModelItemWidget(m.get("name", "未命名"), bool(m.get("is_default")))
            item.setSizeHint(QSize(10, 44))  # 高度
            self.list.addItem(item)
            self.list.setItemWidget(item, w)

            if m.get("is_default"):
                default_item = item
                app_state.current_model_id = m.get("id")

        self.lbl_meta.setText(f"{len(models)} 个模型")

        if default_item:
            self.list.setCurrentItem(default_item)
        else:
            # 默认选第一个
            self.list.setCurrentRow(0)

    # ================= 选择逻辑 =================

    def on_current_changed(self, current: QListWidgetItem, _prev: QListWidgetItem):
        if not current:
            self.current_model = None
            self.btn_default.setEnabled(False)
            self.btn_delete.setEnabled(False)
            return
        self.current_model = current.data(Qt.UserRole)
        self.btn_default.setEnabled(True)
        self.btn_delete.setEnabled(True)

    # ================= 操作逻辑 =================

    def upload_model(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择音色模型文件（支持 MP3 / WAV）",
            "",
            "音频文件 (*.mp3 *.wav)"
        )
        if not files:
            return

        valid_ext = (".mp3", ".wav")

        for file_path in files:
            if not file_path.lower().endswith(valid_ext):
                confirm_dialog(self, "格式错误", "仅支持上传 MP3 或 WAV 格式音色模型")
                return

        success = 0
        fail = []

        for file_path in files:
            name = os.path.splitext(os.path.basename(file_path))[0]
            resp = self.api.upload_model(file_path, name, "桌面端上传模型")

            if not isinstance(resp, dict) or resp.get("code", -1) != 0:
                fail.append(name)
            else:
                success += 1

        if success:
            confirm_dialog(self, "上传完成", f"成功上传 {success} 个音色模型")

        if fail:
            confirm_dialog(self, "部分失败", "以下模型上传失败：\n" + "\n".join(fail))

        self.load_models_async()

    def set_default(self):
        if not self.current_model:
            confirm_dialog(self, "提示", "请先选择一个模型")
            return

        resp = self.api.set_default(self.current_model["id"])
        if isinstance(resp, dict) and resp.get("code") == 0:
            confirm_dialog(self, "成功", "已设为默认模型")
            self.load_models_async()
        else:
            confirm_dialog(self, "失败", (resp or {}).get("msg", "设置失败"))

    def delete_model(self):
        if not self.current_model:
            confirm_dialog(self, "提示", "请先选择一个模型")
            return

        if QMessageBox.question(self, "确认删除", "确定要删除该音色模型吗？") != QMessageBox.Yes:
            return

        deleted_id = self.current_model["id"]
        resp = self.api.delete_model(deleted_id)

        if isinstance(resp, dict) and resp.get("code") == 0:
            confirm_dialog(self, "成功", "模型已删除")

            if app_state.current_model_id == deleted_id:
                app_state.current_model_id = None

            self.load_models_async()
        else:
            confirm_dialog(self, "失败", (resp or {}).get("msg", "删除失败"))
