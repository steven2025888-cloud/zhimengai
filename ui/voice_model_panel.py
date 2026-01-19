import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from api.voice_api import VoiceApiClient
from core.state import app_state


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


class VoiceModelPanel(QWidget):
    def __init__(self, base_url: str, license_key: str, parent=None):
        super().__init__(parent)
        self.api = VoiceApiClient(base_url, license_key)
        self.current_model = None
        self.loader = None

        self.setMinimumWidth(360)
        self.init_ui()
        self.load_models_async()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("🎙 主播音色库")
        title.setFont(QFont("微软雅黑", 14, QFont.Bold))
        title.setAlignment(Qt.AlignLeft)

        self.btn_upload = QPushButton("➕ 上传新音色模型（MP3 / WAV）")
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

    # ================= 云端异步加载 =================

    def load_models_async(self):
        self.list.clear()
        self.current_model = None
        self.btn_default.setEnabled(False)
        self.btn_delete.setEnabled(False)

        self.loader = VoiceModelLoader(self.api)
        self.loader.finished.connect(self.render_models)
        self.loader.start()

    def render_models(self, models: list):
        self.list.clear()
        self.current_model = None
        app_state.current_model_id = None

        if not models:
            return

        default_item = None

        for m in models:
            text = f"{'⭐ ' if m.get('is_default') else ''}{m['name']}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, m)
            self.list.addItem(item)

            if m.get("is_default"):
                default_item = item
                app_state.current_model_id = m["id"]

        if default_item:
            self.list.setCurrentItem(default_item)
            self.current_model = default_item.data(Qt.UserRole)
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
                QMessageBox.warning(self, "格式错误", "仅支持上传 MP3 或 WAV 格式音色模型")
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
            QMessageBox.information(self, "上传完成", f"成功上传 {success} 个音色模型")

        if fail:
            QMessageBox.warning(self, "部分失败", "以下模型上传失败：\n" + "\n".join(fail))

        self.load_models_async()

    def on_select_model(self, item: QListWidgetItem):
        self.current_model = item.data(Qt.UserRole)
        self.btn_default.setEnabled(True)
        self.btn_delete.setEnabled(True)

    def set_default(self):
        if not self.current_model:
            QMessageBox.warning(self, "提示", "请先选择一个模型")
            return

        resp = self.api.set_default(self.current_model["id"])
        if resp.get("code") == 0:
            QMessageBox.information(self, "成功", "已设为默认模型")
            self.load_models_async()
        else:
            QMessageBox.warning(self, "失败", resp.get("msg", "设置失败"))

    def delete_model(self):
        if not self.current_model:
            QMessageBox.warning(self, "提示", "请先选择一个模型")
            return

        if QMessageBox.question(self, "确认删除", "确定要删除该音色模型吗？") != QMessageBox.Yes:
            return

        deleted_id = self.current_model["id"]
        resp = self.api.delete_model(deleted_id)

        if resp.get("code") == 0:
            QMessageBox.information(self, "成功", "模型已删除")

            if app_state.current_model_id == deleted_id:
                app_state.current_model_id = None

            self.load_models_async()
        else:
            QMessageBox.warning(self, "失败", resp.get("msg", "删除失败"))
