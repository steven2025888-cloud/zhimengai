import sys
import webbrowser
import requests
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon, QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextBrowser,
    QPushButton, QFrame, QWidget, QMessageBox
)

from config import (
    UPDATE_API, CURRENT_VERSION
)


def _try_load_app_icon() -> QIcon:
    """
    尝试从常见位置加载 logo.ico 作为窗口图标（找不到就返回空图标）。
    你如果有更稳定的 resource_path，也可以在这里替换为你的实现。
    """
    try:
        # 1) 当前工作目录
        cand = Path.cwd() / "logo.ico"
        if cand.exists():
            return QIcon(str(cand))

        # 2) 脚本所在目录
        cand = Path(__file__).resolve().parent / "logo.ico"
        if cand.exists():
            return QIcon(str(cand))

        # 3) 上级目录（有些项目资源在根目录）
        cand = Path(__file__).resolve().parent.parent / "logo.ico"
        if cand.exists():
            return QIcon(str(cand))
    except Exception:
        pass
    return QIcon()


def _normalize_desc(desc: str) -> str:
    """
    把更新说明做一点友好处理：
    - 支持纯文本 / 带换行
    - 自动把 '\n' 转为 HTML 换行
    """
    if desc is None:
        desc = ""
    desc = str(desc)
    # 简单 HTML 转义（避免 desc 中带 < > 导致富文本乱）
    desc = (
        desc.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )
    desc = desc.replace("\r\n", "\n").replace("\r", "\n")
    desc = desc.replace("\n", "<br>")
    return desc


class ForceUpdateDialog(QDialog):
    """
    更美观的“必须更新”弹窗（深色主题友好）。
    - 立即下载：打开 url 并 accept
    - 复制链接：复制到剪贴板
    - 退出旧版本：reject
    - 关闭窗口：reject（最终仍会强制退出）
    """

    def __init__(self, server_ver: str, info: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("必须更新")
        self.setModal(True)
        self.setObjectName("ForceUpdateDialog")

        self.server_ver = str(server_ver or "").strip()
        self.info = info or {}
        self.url = str(self.info.get("url", "") or "").strip()

        # 基础尺寸
        self.setMinimumWidth(560)
        self.setMinimumHeight(420)

        # 图标（可选）
        icon = _try_load_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        # ===== 顶部标题区 =====
        header = QHBoxLayout()
        header.setSpacing(12)

        badge = QLabel("!")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(34, 34)
        badge.setObjectName("WarnBadge")
        badge_font = QFont()
        badge_font.setPointSize(16)
        badge_font.setBold(True)
        badge.setFont(badge_font)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        title = QLabel("发现新版本，需要立即更新")
        title.setObjectName("TitleLabel")
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title.setFont(title_font)

        sub = QLabel(f"当前版本：{CURRENT_VERSION}    最新版本：{self.server_ver}")
        sub.setObjectName("SubLabel")

        title_box.addWidget(title)
        title_box.addWidget(sub)

        header.addWidget(badge, 0, Qt.AlignTop)
        header.addLayout(title_box, 1)

        root.addLayout(header)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setObjectName("Line")
        root.addWidget(line)

        # ===== 更新说明 =====
        desc_title = QLabel("更新内容")
        desc_title.setObjectName("SectionTitle")
        root.addWidget(desc_title)

        self.desc_view = QTextBrowser()
        self.desc_view.setObjectName("DescView")
        self.desc_view.setOpenExternalLinks(True)
        self.desc_view.setReadOnly(True)
        self.desc_view.setMinimumHeight(230)

        desc_html = _normalize_desc(self.info.get("desc", ""))
        if not desc_html.strip():
            desc_html = "（未提供更新说明）"

        # 可加一个轻量的排版容器
        self.desc_view.setHtml(
            f"""
            <div style="line-height:1.55; font-size: 13px;">
                {desc_html}
            </div>
            """
        )
        root.addWidget(self.desc_view, 1)

        # ===== 下载链接（可选展示）=====
        link_row = QHBoxLayout()
        link_row.setSpacing(8)

        link_label = QLabel("下载地址：")
        link_label.setObjectName("LinkLabel")

        self.link_text = QLabel(self.url if self.url else "（未提供下载链接）")
        self.link_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.link_text.setObjectName("LinkText")

        link_row.addWidget(link_label, 0)
        link_row.addWidget(self.link_text, 1)

        root.addLayout(link_row)

        # ===== 按钮区 =====
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_row.addStretch(1)

        self.btn_copy = QPushButton("复制下载链接")
        self.btn_copy.setObjectName("BtnGhost")
        self.btn_copy.clicked.connect(self._copy_link)

        self.btn_exit = QPushButton("退出旧版本")
        self.btn_exit.setObjectName("BtnGhost")
        self.btn_exit.clicked.connect(self.reject)

        self.btn_download = QPushButton("立即下载")
        self.btn_download.setObjectName("BtnPrimary")
        self.btn_download.setDefault(True)
        self.btn_download.clicked.connect(self._download)

        btn_row.addWidget(self.btn_copy)
        btn_row.addWidget(self.btn_exit)
        btn_row.addWidget(self.btn_download)

        root.addLayout(btn_row)

    def _apply_style(self):
        # 深色弹窗 + 更好看的滚动条 + 更清晰的按钮
        self.setStyleSheet(
            """
            QDialog#ForceUpdateDialog {
                background: #14161a;
                color: #e8e8e8;
            }

            QLabel#TitleLabel {
                color: #ffffff;
            }
            QLabel#SubLabel {
                color: rgba(255,255,255,0.75);
            }

            QLabel#WarnBadge {
                background: rgba(255, 184, 76, 0.18);
                border: 1px solid rgba(255, 184, 76, 0.55);
                color: #ffb84c;
                border-radius: 17px;
            }

            QFrame#Line {
                color: rgba(255,255,255,0.08);
                background: rgba(255,255,255,0.08);
                border: none;
                height: 1px;
            }

            QLabel#SectionTitle {
                color: rgba(255,255,255,0.88);
                font-weight: 600;
            }

            QTextBrowser#DescView {
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 10px;
                padding: 10px;
                color: rgba(255,255,255,0.90);
            }

            QLabel#LinkLabel {
                color: rgba(255,255,255,0.70);
            }
            QLabel#LinkText {
                color: rgba(255,255,255,0.85);
            }

            /* 按钮 */
            QPushButton#BtnPrimary {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 rgba(0, 209, 178, 0.95),
                    stop:1 rgba(0, 159, 221, 0.95)
                );
                border: 1px solid rgba(255,255,255,0.08);
                color: #081015;
                font-weight: 700;
                padding: 9px 14px;
                border-radius: 10px;
                min-width: 110px;
            }
            QPushButton#BtnPrimary:hover {
                border: 1px solid rgba(255,255,255,0.16);
                filter: brightness(1.05);
            }
            QPushButton#BtnPrimary:pressed {
                padding-top: 10px;
                padding-bottom: 8px;
            }

            QPushButton#BtnGhost {
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.10);
                color: rgba(255,255,255,0.88);
                padding: 9px 14px;
                border-radius: 10px;
                min-width: 110px;
            }
            QPushButton#BtnGhost:hover {
                background: rgba(255,255,255,0.09);
                border: 1px solid rgba(255,255,255,0.16);
            }
            QPushButton#BtnGhost:pressed {
                background: rgba(255,255,255,0.05);
            }

            /* 滚动条（更细更现代） */
            QScrollBar:vertical {
                background: transparent;
                width: 10px;
                margin: 6px 2px 6px 2px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.18);
                border-radius: 5px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255,255,255,0.25);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                background: transparent;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
            """
        )

    def _copy_link(self):
        if not self.url:
            QMessageBox.information(self, "提示", "服务端未提供下载链接（url 字段为空）。")
            return
        QGuiApplication.clipboard().setText(self.url)
        QMessageBox.information(self, "已复制", "下载链接已复制到剪贴板。")

    def _download(self):
        # 点击“立即下载”：打开 url（如果有），然后 accept
        if self.url:
            try:
                webbrowser.open(self.url)
            except Exception:
                pass
        else:
            QMessageBox.information(self, "提示", "服务端未提供下载链接（url 字段为空）。")
        self.accept()

    def closeEvent(self, event):
        # 强制更新：用户点右上角关闭也当作 reject（最终会退出旧版本）
        event.accept()
        self.reject()


def force_check_update_and_exit_if_needed(parent=None):
    """
    启动检查更新：
    - 无更新：直接返回
    - 有更新：弹出更美观的强制更新窗口，最终强制退出旧版本
    """
    print("🔍 启动检查更新...")

    try:
        r = requests.get(UPDATE_API, timeout=5)
        info = r.json()
    except Exception as e:
        print("❌ 更新接口访问失败：", e)
        return

    server_ver = str(info.get("version", "")).strip()
    if not server_ver or server_ver == str(CURRENT_VERSION).strip():
        print("✅ 当前已是最新版本")
        return

    # 弹窗（强制）
    dlg = ForceUpdateDialog(server_ver=server_ver, info=info, parent=parent)
    result = dlg.exec()

    # 无论用户点击下载/退出/关闭，旧版本都必须退出
    # 若点击“立即下载”，已在 _download 中打开链接；这里再兜底一次
    url = str(info.get("url", "") or "").strip()
    if result == QDialog.Accepted and url:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    sys.exit(0)
