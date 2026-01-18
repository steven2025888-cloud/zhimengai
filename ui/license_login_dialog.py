import os, sys
import json

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QLineEdit,
    QWidget
)
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from core.device import get_machine_code

from api.voice_api import LicenseApi
from config import BASE_URL


from core.runtime_state import load_runtime_state, save_runtime_state


# ------------------ 旋转加载动画 ------------------
class Spinner(QWidget):
    def __init__(self, size=36, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.angle = 0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.rotate)
        self.timer.start(30)

    def rotate(self):
        self.angle = (self.angle + 8) % 360
        self.update()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self.angle)

        pen = QPen(QColor(96, 165, 250), 4)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)

        r = min(self.width(), self.height()) // 2 - 4
        painter.drawArc(-r, -r, r * 2, r * 2, 0, 270 * 16)


# ------------------ Loading 窗口（居中修复版） ------------------
class LoadingDialog(QDialog):
    def __init__(self, text="正在请求验证中，请稍后..."):
        super().__init__()
        self.setFixedSize(300, 180)
        self.setWindowTitle("验证中")
        self.setModal(True)
        # 保留关闭按钮（你也可以不要：去掉 WindowCloseButtonHint）
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint)

        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                border-radius: 12px;
            }
            QLabel {
                color: white;
                font-size: 14px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self.spinner = Spinner(40, self)
        self.spinner.setFixedSize(40, 40)

        label = QLabel(text, self)
        label.setAlignment(Qt.AlignCenter)

        # 关键：用 stretch + 每个 widget 强制居中
        layout.addStretch(1)
        layout.addWidget(self.spinner, alignment=Qt.AlignHCenter)
        layout.addWidget(label, alignment=Qt.AlignHCenter)
        layout.addStretch(1)


# ------------------ 错误弹窗（保留你原来的美化 UI） ------------------
class ErrorDialog(QDialog):
    def __init__(self, title: str, message: str):
        super().__init__()
        self.setFixedSize(360, 200)
        self.setWindowTitle(title)
        # 不要问号按钮，但保留关闭按钮
        self.setWindowFlags((self.windowFlags() & ~Qt.WindowContextHelpButtonHint) | Qt.WindowCloseButtonHint)

        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #2b0f0f, stop:1 #7f1d1d);
                border-radius: 12px;
            }
            QLabel#title {
                color: #f87171;
                font-size: 20px;
                font-weight: bold;
            }
            QLabel#msg {
                color: white;
                font-size: 14px;
            }
            QPushButton {
                background-color: #ef4444;
                color: white;
                border-radius: 6px;
                height: 34px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #dc2626;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(25, 20, 25, 20)

        title_label = QLabel(f"✖ {title}")
        title_label.setObjectName("title")
        title_label.setAlignment(Qt.AlignCenter)

        msg_label = QLabel(message)
        msg_label.setObjectName("msg")
        msg_label.setWordWrap(True)
        msg_label.setAlignment(Qt.AlignCenter)

        btn = QPushButton("确定")
        btn.clicked.connect(self.accept)

        layout.addStretch()
        layout.addWidget(title_label)
        layout.addWidget(msg_label)
        layout.addStretch()
        layout.addWidget(btn)


# ------------------ 成功弹窗（保留你原来的美化 UI） ------------------
class SuccessDialog(QDialog):
    def __init__(self, expire_time: str):
        super().__init__()
        self.setFixedSize(360, 200)
        self.setWindowTitle("授权成功")
        self.setWindowFlags((self.windowFlags() & ~Qt.WindowContextHelpButtonHint) | Qt.WindowCloseButtonHint)

        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #0f172a, stop:1 #1e3a8a);
                border-radius: 12px;
            }
            QLabel#title {
                color: #60a5fa;
                font-size: 20px;
                font-weight: bold;
            }
            QLabel#time {
                color: white;
                font-size: 14px;
            }
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border-radius: 6px;
                height: 34px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(25, 20, 25, 20)

        title = QLabel("✔ 授权验证成功")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)

        time_label = QLabel(f"有效期至：{expire_time}")
        time_label.setObjectName("time")
        time_label.setAlignment(Qt.AlignCenter)

        btn = QPushButton("进入系统")
        btn.clicked.connect(self.accept)

        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(time_label)
        layout.addStretch()
        layout.addWidget(btn)




# ------------------ 后台验证线程 ------------------
class VerifyWorker(QThread):
    finished = Signal(dict, object)

    def __init__(self, license_key: str):
        super().__init__()
        self.license_key = license_key
        self.api = LicenseApi(BASE_URL)

    def run(self):
        try:
            result = self.api.login(self.license_key)
            self.finished.emit(result, None)
        except Exception as e:
            self.finished.emit(None, e)



# ------------------ 登录主界面（完全保留你原来的登录 UI） ------------------
class LicenseLoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("织梦AI · 软件授权验证")
        self.setFixedSize(460, 280)

        # ✅ 修复：一定要保留关闭按钮
        self.setWindowFlags((self.windowFlags() & ~Qt.WindowContextHelpButtonHint) | Qt.WindowCloseButtonHint)

        # ✅ 修复：提前初始化，避免 AttributeError
        self.expire_time = None

        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #1e3c72, stop:1 #2a5298);
            }
            QLabel#title {
                color: white;
                font-size: 22px;
                font-weight: bold;
            }
            QLabel#sub {
                color: #d0d8ff;
                font-size: 12px;
            }
            QLineEdit {
                height: 40px;
                border-radius: 8px;
                padding-left: 10px;
                font-size: 14px;
                border: 1px solid #ccc;
            }
            QPushButton {
                height: 40px;
                border-radius: 8px;
                background-color: #3b82f6;
                color: white;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(30, 25, 30, 25)
        root.setSpacing(15)

        title = QLabel("织梦AI 商用授权登录")
        title.setObjectName("title")

        sub = QLabel("请输入卡密验证后使用系统功能")
        sub.setObjectName("sub")

        self.edit = QLineEdit()
        self.edit.setPlaceholderText("请输入您的授权卡密（例如：ZM-2026-XXXX）")

        self.btn = QPushButton("立即验证并进入系统")
        self.btn.clicked.connect(self.do_login)

        root.addWidget(title)
        root.addWidget(sub)
        root.addSpacing(10)
        root.addWidget(self.edit)
        root.addSpacing(10)
        root.addWidget(self.btn)

        self.load_saved_key()

    def load_saved_key(self):
        state = load_runtime_state()
        self.edit.setText(state.get("license_key", ""))
        self.expire_time = state.get("expire_time")

    def save_key(self, key: str, expire_time: str | None):
        state = load_runtime_state()
        state["license_key"] = key
        state["expire_time"] = expire_time
        save_runtime_state(state)

    def do_login(self):
        key = self.edit.text().strip()
        if not key:
            ErrorDialog("提示", "请输入卡密").exec()
            return

        self.loading = LoadingDialog("正在请求验证中，请稍后...")
        self.loading.show()

        self.worker = VerifyWorker(key)
        self.worker.finished.connect(self.on_verify_result)
        self.worker.start()

    def on_verify_result(self, res, err):
        if hasattr(self, "loading") and self.loading:
            self.loading.close()

        if err:
            ErrorDialog("网络错误", str(err)).exec()
            return

        if not isinstance(res, dict):
            ErrorDialog("验证失败", "返回数据异常").exec()
            return

        if res.get("code") != 0:
            ErrorDialog("验证失败", res.get("msg", "卡密无效或已到期")).exec()
            return

        if not self.isVisible():
            return

        expire_time = res.get("expire_time")
        self.expire_time = expire_time  # ✅ 修复：确保赋值
        self.save_key(self.edit.text().strip(), expire_time)

        # ✅ 保留你的成功弹窗UI
        dlg = SuccessDialog(expire_time)
        dlg.exec()

        # ✅ 成功后关闭登录窗口
        self.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    dlg = LicenseLoginDialog()
    dlg.exec()
