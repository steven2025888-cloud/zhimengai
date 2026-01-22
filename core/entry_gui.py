# core/entry_gui.py
import os
import sys
import shutil
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog

import logger_bootstrap
from core.updater import force_check_update_and_exit_if_needed
from ui.license_login_dialog import LicenseLoginDialog
from ui.main_window import MainWindow


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(relative: str) -> str:
    return str(app_dir() / relative)


def setup_playwright_env():
    p = app_dir() / "ms-playwright"
    if p.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(p)


def clear_audio_cache():
    cache_dir = app_dir() / "audio_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for f in cache_dir.iterdir():
        try:
            if f.is_file():
                f.unlink()
            elif f.is_dir():
                shutil.rmtree(f)
        except Exception:
            pass


def run():

    setup_playwright_env()

    app = QApplication(sys.argv)

    # 启动第一时间强制检查更新
    force_check_update_and_exit_if_needed()

    clear_audio_cache()

    app.setWindowIcon(QIcon(resource_path("logo.ico")))

    translator = QTranslator()
    translator.load("qt_zh_CN", QLibraryInfo.path(QLibraryInfo.TranslationsPath))
    app.installTranslator(translator)

    login = LicenseLoginDialog()
    if login.exec() != QDialog.Accepted:
        sys.exit(0)

    expire_time = getattr(login, "expire_time", None)
    license_key = login.edit.text().strip()

    win = MainWindow(resource_path, expire_time=expire_time, license_key=license_key)
    win.show()

    qss_path = Path(resource_path("ui/style.qss"))
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
    else:
        print("⚠️ style.qss not found:", qss_path)

    sys.exit(app.exec())
