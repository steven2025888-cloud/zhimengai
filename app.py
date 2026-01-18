import os
import sys
import shutil
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtGui import QIcon
from PySide6.QtCore import QTranslator, QLibraryInfo

from ui.main_window import MainWindow
from ui.license_login_dialog import LicenseLoginDialog
from core.updater import force_check_update_and_exit_if_needed
from config import AUDIO_BASE_DIR
import logger_bootstrap

# PyInstaller Playwright
if hasattr(sys, "_MEIPASS"):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(sys._MEIPASS, "ms-playwright")


def resource_path(relative: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative)
    return os.path.join(os.path.abspath("."), relative)


def ensure_audio_assets_dir():
    """确保音频资源目录存在"""
    AUDIO_BASE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"📁 audio_assets 目录已就绪：{AUDIO_BASE_DIR}")


def clear_audio_cache():
    cache_dir = Path("audio_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    for f in cache_dir.iterdir():
        try:
            if f.is_file():
                f.unlink()
            elif f.is_dir():
                shutil.rmtree(f)
        except Exception as e:
            print("清理缓存失败：", f, e)

    print("🧹 已清空 audio_cache 目录")


if __name__ == "__main__":
    app = QApplication(sys.argv)


    # 启动第一时间强制检查更新
    force_check_update_and_exit_if_needed()

    # 初始化目录
    ensure_audio_assets_dir()
    clear_audio_cache()

    # 设置窗口图标
    app.setWindowIcon(QIcon(resource_path("logo.ico")))

    # Qt 中文
    translator = QTranslator()
    translator.load("qt_zh_CN", QLibraryInfo.path(QLibraryInfo.TranslationsPath))
    app.installTranslator(translator)

    # 授权登录
    login = LicenseLoginDialog()
    if login.exec() != QDialog.Accepted:
        sys.exit(0)

    expire_time = getattr(login, "expire_time", None)
    license_key = login.edit.text().strip()

    # 主窗口
    win = MainWindow(resource_path, expire_time=expire_time, license_key=license_key)
    win.show()

    sys.exit(app.exec())
