# ui/pages/page_public_screen.py
import random

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QSpinBox, QTextEdit, QMessageBox, QFrame
)
from PySide6.QtCore import Qt

from core.runtime_state import load_runtime_state, save_runtime_state
from core.state import app_state


class PublicScreenPage(QWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        self.ctx = ctx or {}
        self.setObjectName("PublicScreenPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # 标题
        title = QLabel("公屏轮播")
        title.setObjectName("PS_Title")
        root.addWidget(title)

        tip = QLabel(
            "说明：开启后会按“间隔(分钟)”随机发送下方公屏内容。\n"
            "抖音公屏发送：请先在抖音控制台手动发一条公屏消息，让系统抓到真实发送接口模板后才会稳定轮播。"
        )
        tip.setWordWrap(True)
        tip.setObjectName("PS_Tip")
        root.addWidget(tip)

        # 卡片：开关 + 间隔
        card1 = self._card()
        c1 = QVBoxLayout(card1)
        c1.setContentsMargins(12, 12, 12, 12)
        c1.setSpacing(10)

        row1 = QHBoxLayout()
        row1.setSpacing(12)

        self.chk_wx = QCheckBox("视频号公屏")
        self.chk_dy = QCheckBox("抖音公屏")
        self.chk_wx.setCursor(Qt.PointingHandCursor)
        self.chk_dy.setCursor(Qt.PointingHandCursor)

        row1.addWidget(self.chk_wx)
        row1.addWidget(self.chk_dy)
        row1.addStretch(1)

        lbl_int = QLabel("间隔(分钟)：")
        lbl_int.setObjectName("PS_Label")
        row1.addWidget(lbl_int)

        self.spn_min = QSpinBox()
        self.spn_min.setRange(1, 240)
        self.spn_min.setValue(5)
        self.spn_min.setFixedWidth(110)
        self.spn_min.setObjectName("PS_Spin")
        row1.addWidget(self.spn_min)

        c1.addLayout(row1)

        subtip = QLabel("提示：建议间隔 ≥ 2 分钟，且内容不要太硬广，避免风控。")
        subtip.setObjectName("PS_SubTip")
        subtip.setWordWrap(True)
        c1.addWidget(subtip)

        root.addWidget(card1)

        # 卡片：内容编辑
        card2 = self._card()
        c2 = QVBoxLayout(card2)
        c2.setContentsMargins(12, 12, 12, 12)
        c2.setSpacing(10)

        lbl = QLabel("公屏内容（每行一条，轮播时随机发送）")
        lbl.setObjectName("PS_SectionTitle")
        c2.addWidget(lbl)

        self.edt = QTextEdit()
        self.edt.setObjectName("PS_Text")
        self.edt.setPlaceholderText(
            "例如：\n"
            "欢迎新朋友～点点关注不迷路\n"
            "今天福利在橱窗，先到先得\n"
            "需要链接扣 1"
        )
        self.edt.setMinimumHeight(240)
        c2.addWidget(self.edt, 1)

        root.addWidget(card2, 1)

        # 按钮行
        row_btn = QHBoxLayout()
        row_btn.setSpacing(10)

        self.btn_save = QPushButton("保存设置")
        self.btn_test = QPushButton("立即发送一次（随机测试）")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_test.setCursor(Qt.PointingHandCursor)
        self.btn_save.setObjectName("PS_BtnPrimary")
        self.btn_test.setObjectName("PS_BtnGhost")

        row_btn.addWidget(self.btn_save)
        row_btn.addWidget(self.btn_test)
        row_btn.addStretch(1)

        root.addLayout(row_btn)

        self.btn_save.clicked.connect(self.on_save)
        self.btn_test.clicked.connect(self.on_test_send)

        self._apply_local_style()
        self._load()

    def _card(self) -> QFrame:
        f = QFrame()
        f.setObjectName("PS_Card")
        f.setFrameShape(QFrame.NoFrame)
        f.setAttribute(Qt.WA_StyledBackground, True)
        return f

    def _apply_local_style(self):
        # 深色友好：解决 QSpinBox 输入区默认白底的问题
        self.setStyleSheet("""
        QLabel#PS_Title{
            font-size:18px;
            font-weight:800;
            color:#EAEFF7;
        }
        QLabel#PS_Tip{
            color:#A9B1BD;
            line-height:1.4;
        }
        QFrame#PS_Card{
            background:#151A22;
            border:1px solid #242B36;
            border-radius:12px;
        }
        QLabel#PS_Label{
            color:#D7DEE9;
            font-weight:700;
        }
        QLabel#PS_SubTip{
            color:#98A3B3;
        }
        QLabel#PS_SectionTitle{
            color:#D7DEE9;
            font-weight:800;
        }

        QCheckBox{
            color:#E6ECF5;
            font-weight:700;
            spacing:8px;
        }

        QSpinBox#PS_Spin{
            background:#0F141C;
            color:#E6ECF5;
            border:1px solid #2A3240;
            border-radius:10px;
            padding:6px 10px;
        }
        QSpinBox#PS_Spin:focus{
            border:1px solid #3B82F6;
        }

        QTextEdit#PS_Text{
            background:#0F141C;
            color:#E6ECF5;
            border:1px solid #2A3240;
            border-radius:12px;
            padding:10px;
            selection-background-color:#3B82F6;
        }
        QTextEdit#PS_Text:focus{
            border:1px solid #3B82F6;
        }

        QPushButton#PS_BtnPrimary{
            background:#2563EB;
            color:white;
            border:none;
            border-radius:12px;
            padding:10px 14px;
            font-weight:800;
        }
        QPushButton#PS_BtnPrimary:hover{ background:#1D4ED8; }
        QPushButton#PS_BtnPrimary:pressed{ background:#1E40AF; }

        QPushButton#PS_BtnGhost{
            background:transparent;
            color:#D7DEE9;
            border:1px solid #2A3240;
            border-radius:12px;
            padding:10px 14px;
            font-weight:800;
        }
        QPushButton#PS_BtnGhost:hover{ border:1px solid #3B82F6; }
        """)

    def _load(self):
        rt = load_runtime_state() or {}

        self.chk_wx.setChecked(bool(rt.get("enable_public_screen_wx", False)))
        self.chk_dy.setChecked(bool(rt.get("enable_public_screen_dy", False)))

        try:
            m = int(rt.get("public_screen_interval_min", 5) or 5)
        except Exception:
            m = 5
        self.spn_min.setValue(max(1, m))

        msgs = rt.get("public_screen_messages", []) or []
        if not isinstance(msgs, list):
            msgs = []
        msgs = [str(x).strip() for x in msgs if str(x).strip()]
        self.edt.setPlainText("\n".join(msgs))

        # 同步到 app_state（立即生效）
        app_state.enable_public_screen_wx = self.chk_wx.isChecked()
        app_state.enable_public_screen_dy = self.chk_dy.isChecked()
        app_state.public_screen_interval_min = self.spn_min.value()
        app_state.public_screen_messages = msgs

    def _collect(self):
        enabled_wx = self.chk_wx.isChecked()
        enabled_dy = self.chk_dy.isChecked()
        interval_min = int(self.spn_min.value())

        lines = self.edt.toPlainText().splitlines()
        msgs = [str(x).strip() for x in lines if str(x).strip()]
        return enabled_wx, enabled_dy, interval_min, msgs

    def on_save(self):
        enabled_wx, enabled_dy, interval_min, msgs = self._collect()

        rt = load_runtime_state() or {}
        rt["enable_public_screen_wx"] = bool(enabled_wx)
        rt["enable_public_screen_dy"] = bool(enabled_dy)
        rt["public_screen_interval_min"] = int(interval_min)
        rt["public_screen_messages"] = msgs
        save_runtime_state(rt)

        # 同步到 app_state（立即生效）
        app_state.enable_public_screen_wx = bool(enabled_wx)
        app_state.enable_public_screen_dy = bool(enabled_dy)
        app_state.public_screen_interval_min = int(interval_min)
        app_state.public_screen_messages = msgs

        QMessageBox.information(self, "已保存", "公屏轮播设置已保存并立即生效。")

    def on_test_send(self):
        enabled_wx, enabled_dy, interval_min, msgs = self._collect()
        if not msgs:
            QMessageBox.warning(self, "提示", "请先填写至少一条公屏内容（每行一条）。")
            return

        text = random.choice(msgs)

        # 直接丢队列，交给 listener 线程发送
        pushed = False
        try:
            if enabled_wx and getattr(app_state, "public_screen_queue_wx", None):
                app_state.public_screen_queue_wx.put(text, block=False)
                pushed = True
        except Exception:
            pass

        try:
            if enabled_dy and getattr(app_state, "public_screen_queue_dy", None):
                app_state.public_screen_queue_dy.put(text, block=False)
                pushed = True
        except Exception:
            pass

        if pushed:
            QMessageBox.information(self, "已触发", f"已随机触发发送：\n{text}\n\n（如未发送，请先确保对应平台已抓到发送接口模板）")
        else:
            QMessageBox.warning(self, "未触发", "队列未就绪或开关未开启。请先启动系统并确保对应平台监听正常。")
