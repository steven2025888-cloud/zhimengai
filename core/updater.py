import sys
import webbrowser
import requests
from PySide6.QtWidgets import QMessageBox


from config import (
    UPDATE_API,CURRENT_VERSION
)

def force_check_update_and_exit_if_needed():
    print("🔍 启动检查更新...")

    try:
        r = requests.get(UPDATE_API, timeout=5)
        info = r.json()
    except Exception as e:
        print("❌ 更新接口访问失败：", e)
        return

    server_ver = str(info.get("version", "")).strip()
    if not server_ver or server_ver == CURRENT_VERSION:
        print("✅ 当前已是最新版本")
        return

    msg = (
        f"检测到新版本：{server_ver}\n\n"
        f"{info.get('desc','')}\n\n"
        "点击【确定】将打开下载页面，下载完成后请重新运行最新版。"
    )

    box = QMessageBox()
    box.setWindowTitle("必须更新")
    box.setIcon(QMessageBox.warning())
    box.setText(msg)
    box.setStandardButtons(QMessageBox.Ok)
    box.exec()

    url = info.get("url")
    if url:
        webbrowser.open(url)

    # 强制退出旧版本
    sys.exit(0)
