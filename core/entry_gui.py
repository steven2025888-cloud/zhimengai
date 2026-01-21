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

# ✅ 运行时状态（记住上次选择的目录/模式）
try:
    from core.state import app_state
    from core.runtime_state import load_runtime_state
except Exception:
    app_state = None
    load_runtime_state = None



def app_dir() -> Path:
    """开发态=项目根目录；打包态=exe 所在目录（onedir 推荐）"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # 这个文件在 core/ 下，所以根目录是上一级
    return Path(__file__).resolve().parent.parent


def resource_path(relative: str) -> str:
    """永远从 exe 同级目录找资源（onedir），避免 cwd 飘移"""
    return str(app_dir() / relative)


def setup_playwright_env():
    # 你是 onedir：ms-playwright 会在 exe 同级目录
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
        except Exception as e:
            print("清理缓存失败：", f, e)
    print("🧹 已清空 audio_cache 目录")


def run():
    setup_playwright_env()

    app = QApplication(sys.argv)

    # 启动第一时间强制检查更新
    force_check_update_and_exit_if_needed()

    # 初始化目录
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

    # ✅ 启动 GUI 时也同步 runtime_state（让面板一打开就显示上次选择的目录）
    try:
        if app_state is not None and callable(load_runtime_state):
            rt = load_runtime_state() or {}
            if rt.get("anchor_audio_dir"):
                app_state.anchor_audio_dir = str(rt.get("anchor_audio_dir"))
            if rt.get("zhuli_audio_dir"):
                app_state.zhuli_audio_dir = str(rt.get("zhuli_audio_dir"))
            if rt.get("zhuli_mode"):
                app_state.zhuli_mode = str(rt.get("zhuli_mode")).upper()
    except Exception:
        pass

    # 主窗口
    win = MainWindow(resource_path, expire_time=expire_time, license_key=license_key)
    win.show()

    sys.exit(app.exec())
