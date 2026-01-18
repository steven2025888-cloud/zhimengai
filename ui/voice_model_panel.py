import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from api.voice_api import VoiceApiClient
from core.state import app_state


class VoiceModelPanel(QWidget):
    def __init__(self, base_url: str, license_key: str, parent=None):
        super().__init__(parent)
        self.api = VoiceApiClient(base_url, license_key)
        self.current_model = None

        self.setMinimumWidth(360)
        self.init_ui()
        self.load_models()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("🎙 主播音色库")
        title.setFont(QFont("微软雅黑", 14, QFont.Bold))
        title.setAlignment(Qt.AlignLeft)

        self.btn_upload = QPushButton("➕ 上传新音色模型")
        self.btn_upload.setFixedHeight(36)
        self.btn_upload.clicked.connect(self.upload_model)

        self.list = QListWidget()
        self.list.setSpacing(6)
        self.list.itemClicked.connect(self.on_select_model)

        btn_row = QHBoxLayout()
        self.btn_default = QPushButton("⭐ 设为默认")
        self.btn_delete = QPushButton("🗑 删除模型")

        self.btn_default.clicked.connect(self.set_default)
        self.btn_delete.clicked.connect(self.delete_model)

        btn_row.addWidget(self.btn_default)
        btn_row.addWidget(self.btn_delete)

        layout.addWidget(title)
        layout.addWidget(self.btn_upload)
        layout.addWidget(self.list, 1)
        layout.addLayout(btn_row)

        self.setStyleSheet("""
        QListWidget {
            background-color: #0F172A;
            border-radius: 10px;
            padding: 6px;
        }
        QListWidget::item {
            background-color: #1E293B;
            border-radius: 8px;
            padding: 10px;
            margin: 4px;
            color: white;
        }
        QListWidget::item:selected {
            background-color: #2563EB;
        }
        QPushButton {
            background-color: #1E40AF;
            color: white;
            border-radius: 6px;
            padding: 6px 12px;
        }
        QPushButton:hover {
            background-color: #3B82F6;
        }
        """)

    def load_models(self):
        self.list.clear()
        resp = self.api.list_models()

        if not isinstance(resp, dict) or resp.get("code", -1) != 0:
            QMessageBox.warning(self, "错误", resp.get("msg", f"接口异常返回：{resp}"))
            return

        models = resp["data"]
        default_item = None

        for m in models:
            text = f"{'⭐ ' if m['is_default'] else ''}{m['name']}  ({m['describe'] or '无描述'})"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, m)
            self.list.addItem(item)

            # 找默认模型
            if m.get("is_default"):
                default_item = item
                app_state.current_model_id = m["id"]

        # 如果没有默认模型，自动选第一个
        if not default_item and models:
            first = models[0]
            app_state.current_model_id = first["id"]
            self.list.setCurrentRow(0)
            self.current_model = first
        elif default_item:
            self.list.setCurrentItem(default_item)
            self.current_model = default_item.data(Qt.UserRole)

    def upload_model(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择音色文件", "", "WAV Files (*.wav)")
        if not file_path:
            return

        name = os.path.basename(file_path).replace(".wav", "")
        resp = self.api.upload_model(file_path, name, "桌面端上传模型")

        if not isinstance(resp, dict) or resp.get("code", -1) != 0:
            QMessageBox.warning(self, "上传失败", resp.get("msg", f"接口返回异常：{resp}"))
            return

        QMessageBox.information(self, "成功", "声纹模型创建成功！")
        self.load_models()

    def on_select_model(self, item: QListWidgetItem):
        self.current_model = item.data(Qt.UserRole)
        app_state.current_model_id = self.current_model["id"]

    def set_default(self):
        if not self.current_model:
            QMessageBox.warning(self, "提示", "请先选择一个模型")
            return

        resp = self.api.set_default(self.current_model["id"])
        if resp["code"] == 0:
            QMessageBox.information(self, "成功", "已设为默认模型")
            app_state.current_model_id = self.current_model["id"]
            self.load_models()
        else:
            QMessageBox.warning(self, "失败", resp.get("msg", "设置失败"))

    def delete_model(self):
        if not self.current_model:
            QMessageBox.warning(self, "提示", "请先选择一个模型")
            return

        if QMessageBox.question(self, "确认删除", "确定要删除该音色模型吗？") != QMessageBox.Yes:
            return

        resp = self.api.delete_model(self.current_model["id"])
        if resp["code"] == 0:
            QMessageBox.information(self, "成功", "模型已删除")
            app_state.current_model_id = None
            self.load_models()
        else:
            QMessageBox.warning(self, "失败", resp.get("msg", "删除失败"))
