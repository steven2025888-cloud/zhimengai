# ui/pages/page_comment_manager.py
from __future__ import annotations

import json
import os
import pathlib
import time
import ast
import pprint
import inspect
from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSpacerItem, QSizePolicy, QTableWidget, QTableWidgetItem,
    QHeaderView, QCheckBox, QAbstractItemView
)

from core.state import app_state
from core.comment_logger import get_log_path, open_logs_dir_in_explorer, clear_log

# ✅ 用你项目里的 confirm_dialog（替代 QMessageBox）
from ui.dialogs import confirm_dialog


def _safe_str(x: Any) -> str:
    try:
        return "" if x is None else str(x)
    except Exception:
        return ""


def _now_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


class CommentManagerPage(QWidget):
    """
    评论管理：
    - 开关：记录弹幕、记录回复（只保存开关到 runtime_state.json）
    - 实时显示：时间/平台/用户/类型/内容/触发关键词/入库状态
    - 每条【回复】支持“入库”按钮（confirm_dialog确认后入库）
    - 入库状态不写 runtime_state.json：写在同目录 sidecar 索引文件
    - 清空日志：清空 jsonl + 清空 sidecar 索引
    """

    def __init__(self, ctx: Dict[str, Any]):
        super().__init__()
        self.ctx = ctx or {}
        self.save_runtime_flag = self.ctx.get("save_runtime_flag")

        self.setObjectName("CommentManagerPage")

        self._log_path = get_log_path()
        self._collect_index_path = self._get_collect_index_path(self._log_path)
        self._collect_index = self._load_collect_index()

        # key_for_collect -> row (O(1) 更新入库状态)
        self._row_by_collect_key: Dict[str, int] = {}
        self._last_pos = 0
        self._timer: Optional[QTimer] = None

        # 只保留两个开关：记录评论/记录回复（不保留全局“回复入库开关”）
        try:
            # 强制关闭旧开关，避免你之前版本残留影响行为
            if hasattr(app_state, "enable_reply_collect"):
                app_state.enable_reply_collect = False
        except Exception:
            pass

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(12)

        # -------- 顶部卡片 --------
        card = QFrame()
        card.setObjectName("Card")
        card.setStyleSheet(
            "#Card{background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.10);"
            "border-radius:14px;}"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 14, 14, 14)
        cl.setSpacing(10)

        title = QLabel("评论管理")
        title.setStyleSheet("font-size:18px;font-weight:900;color:#eaeaea;")
        cl.addWidget(title)

        desc = QLabel("实时显示【弹幕评论 + 自动回复】日志。回复可点击“入库”写入对应关键词的回复词库。")
        desc.setWordWrap(True)
        desc.setStyleSheet("color:rgba(255,255,255,0.75);")
        cl.addWidget(desc)

        rowp = QHBoxLayout()
        self.lb_path = QLabel(f"日志文件：{self._log_path}")
        self.lb_path.setStyleSheet("color:rgba(255,255,255,0.75);")
        rowp.addWidget(self.lb_path, 1)

        btn_open = QPushButton("打开保存位置")
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.setStyleSheet(self._btn_style("ghost"))
        btn_open.clicked.connect(open_logs_dir_in_explorer)
        rowp.addWidget(btn_open, 0)

        btn_clear = QPushButton("清空日志")
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.setStyleSheet(self._btn_style("danger"))
        btn_clear.clicked.connect(self._on_clear_log)
        rowp.addWidget(btn_clear, 0)

        cl.addLayout(rowp)
        root.addWidget(card)

        # -------- 开关区 --------
        toggles = QFrame()
        toggles.setStyleSheet(
            "background:rgba(0,0,0,0.18);border:1px solid rgba(255,255,255,0.08);border-radius:14px;"
        )
        tl = QVBoxLayout(toggles)
        tl.setContentsMargins(14, 14, 14, 14)
        tl.setSpacing(12)

        self._toggle_rows: Dict[str, Tuple[QLabel, QPushButton]] = {}

        self._add_toggle_row(tl, "记录弹幕评论", "记录所有用户发出的弹幕内容（抖音/视频号）。",
                             state_attr="enable_comment_record", runtime_key="enable_comment_record")

        self._add_toggle_row(tl, "记录自动回复", "记录本软件发出的弹幕回复（仅记录发送成功的回复）。",
                             state_attr="enable_reply_record", runtime_key="enable_reply_record")

        root.addWidget(toggles)

        # -------- 表格区 --------
        table_card = QFrame()
        table_card.setStyleSheet(
            "background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:14px;"
        )
        tcl = QVBoxLayout(table_card)
        tcl.setContentsMargins(12, 12, 12, 12)
        tcl.setSpacing(10)

        topbar = QHBoxLayout()
        lb = QLabel("实时日志")
        lb.setStyleSheet("font-size:15px;font-weight:900;color:#eaeaea;")
        topbar.addWidget(lb)

        topbar.addStretch(1)

        self.chk_autoscroll = QCheckBox("自动滚动到底部")
        self.chk_autoscroll.setChecked(True)
        self.chk_autoscroll.setStyleSheet("color:rgba(255,255,255,0.78);font-weight:800;")
        topbar.addWidget(self.chk_autoscroll)

        btn_refresh = QPushButton("刷新")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setStyleSheet(self._btn_style("ghost"))
        btn_refresh.clicked.connect(self._reload_all)
        topbar.addWidget(btn_refresh)

        tcl.addLayout(topbar)

        # 8列：最后一列操作
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["时间", "平台", "用户", "类型", "内容", "触发关键词", "已入库"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.setTextElideMode(Qt.ElideRight)

        # 深色主题：让“回复”不再白到看不清（统一高对比，回复行再加底色区分）
        self.table.setStyleSheet(
            "QTableWidget{background:rgba(0,0,0,0.16);alternate-background-color:rgba(255,255,255,0.04);color:#eaeaea;border:none;gridline-color:rgba(255,255,255,0.08);}"
            "QTableWidget::item{padding:6px;background:transparent;}"
            "QTableWidget::item:selected{background:rgba(70,130,180,0.25);}"
            "QHeaderView::section{background:rgba(255,255,255,0.10);color:#eaeaea;"
            "padding:7px;border:none;font-weight:900;}"
        )

        hh = self.table.horizontalHeader()
        hh.setStretchLastSection(False)
        # ✅ 可拖动列宽（你说“加一个拖动”）
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)  # 内容拉伸
        hh.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.ResizeToContents)

        hh.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

        tcl.addWidget(self.table, 1)

        # ---- 底部固定工具条：入库选中（解决“按钮看不到”时还能操作）----
        bottom = QFrame()
        bottom.setStyleSheet("background:rgba(0,0,0,0.18);border:1px solid rgba(255,255,255,0.08);border-radius:12px;")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.setSpacing(10)

        self.lb_sel = QLabel("未选择任何行")
        self.lb_sel.setStyleSheet("color:rgba(255,255,255,0.78);")
        bl.addWidget(self.lb_sel, 1)

        self.btn_collect_selected = QPushButton("入库选中回复")
        self.btn_collect_selected.setCursor(Qt.PointingHandCursor)
        self.btn_collect_selected.setStyleSheet(self._btn_style("primary"))
        self.btn_collect_selected.clicked.connect(self._collect_selected_reply)
        bl.addWidget(self.btn_collect_selected, 0)

        tcl.addWidget(bottom)

        root.addWidget(table_card, 1)
        root.addItem(QSpacerItem(10, 10, QSizePolicy.Minimum, QSizePolicy.Expanding))

        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        # 初始刷新
        self._refresh_toggles()
        self._reload_all()
        self._start_timer()

    # ---------- UI Helpers ----------
    def _btn_style(self, kind: str) -> str:
        if kind == "danger":
            return (
                "QPushButton{padding:8px 12px;border-radius:10px;background:rgba(255,80,80,0.22);font-weight:900;color:#ffd9d9;}"
                "QPushButton:hover{background:rgba(255,80,80,0.34);}"
            )
        if kind == "primary":
            return (
                "QPushButton{padding:8px 12px;border-radius:10px;background:rgba(70,130,180,0.28);font-weight:900;color:#e8f2ff;}"
                "QPushButton:hover{background:rgba(70,130,180,0.40);}"
            )
        # ghost
        return (
            "QPushButton{padding:8px 12px;border-radius:10px;background:rgba(255,255,255,0.10);font-weight:900;color:#eaeaea;}"
            "QPushButton:hover{background:rgba(255,255,255,0.16);}"
        )

    def _add_toggle_row(self, parent_layout: QVBoxLayout, title: str, tip: str, state_attr: str, runtime_key: str):
        row = QFrame()
        row.setStyleSheet(
            "background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:12px;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(12, 10, 12, 10)
        rl.setSpacing(10)

        left = QVBoxLayout()
        lb_title = QLabel(title)
        lb_title.setStyleSheet("font-size:15px;font-weight:900;color:#eaeaea;")
        left.addWidget(lb_title)

        lb_tip = QLabel(tip)
        lb_tip.setWordWrap(True)
        lb_tip.setStyleSheet("color:rgba(255,255,255,0.72);")
        left.addWidget(lb_tip)

        rl.addLayout(left, 1)

        pill = QLabel("关闭")
        pill.setAlignment(Qt.AlignCenter)
        pill.setFixedHeight(24)
        pill.setMinimumWidth(56)

        btn = QPushButton("开启")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedWidth(92)
        btn.setStyleSheet(self._btn_style("ghost"))

        def on_click():
            cur = bool(getattr(app_state, state_attr, False))
            newv = not cur
            setattr(app_state, state_attr, newv)
            self._save_flag(runtime_key, bool(newv))
            self._refresh_toggles()

        btn.clicked.connect(on_click)

        rl.addWidget(pill, 0)
        rl.addWidget(btn, 0)
        parent_layout.addWidget(row)

        self._toggle_rows[state_attr] = (pill, btn)

    def _refresh_toggles(self):
        for state_attr, (pill, btn) in self._toggle_rows.items():
            ok = bool(getattr(app_state, state_attr, False))
            pill.setText("开启" if ok else "关闭")
            pill.setStyleSheet(
                "padding:0 10px;border-radius:12px;font-weight:900;"
                + ("background:#1f7a3f;color:#dfffe9;" if ok else "background:#3a3a3a;color:#d0d0d0;")
            )
            btn.setText("关闭" if ok else "开启")

        self._log_path = get_log_path()
        self.lb_path.setText(f"日志文件：{self._log_path}")

    def _save_flag(self, key: str, value: bool):
        if callable(self.save_runtime_flag):
            try:
                self.save_runtime_flag(key, value)
                return
            except Exception:
                pass
        # fallback
        try:
            from core.runtime_state import load_runtime_state, save_runtime_state
            rt = load_runtime_state() or {}
            rt[key] = bool(value)
            save_runtime_state(rt)
        except Exception:
            pass

    # ---------- Timer / Poll ----------
    def _start_timer(self):
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.setInterval(400)
            self._timer.timeout.connect(self._poll_new_lines)
            self._timer.start()

    def closeEvent(self, e):
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
            self._timer = None
        super().closeEvent(e)

    def _reload_all(self):
        self.table.setRowCount(0)
        self._row_by_collect_key.clear()
        self._last_pos = 0
        self._poll_new_lines(load_all=True)

    def _poll_new_lines(self, load_all: bool = False):
        path = self._log_path
        if not path or not os.path.exists(path):
            return

        try:
            size = os.path.getsize(path)
            if not load_all and self._last_pos > size:
                self._last_pos = 0

            max_lines = 300  # 每次 tick 最多处理多少行，避免 UI 卡顿
            added = 0

            with open(path, "r", encoding="utf-8") as f:
                if not load_all:
                    f.seek(self._last_pos)

                while True:
                    if added >= max_lines:
                        break
                    line = f.readline()
                    if not line:
                        break
                    line = (line or "").strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except Exception:
                        continue
                    self._append_event_row(evt)
                    added += 1

                self._last_pos = f.tell()

            if added and self.chk_autoscroll.isChecked():
                self.table.scrollToBottom()

        except Exception:
            pass

    # ---------- Row append / style ----------

    def _append_event_row(self, evt: Dict[str, Any]):
        ts = _safe_str(evt.get("ts")) or _now_ts()
        platform = _safe_str(evt.get("platform"))
        nickname = _safe_str(evt.get("nickname")) or "未知用户"
        typ = _safe_str(evt.get("type"))
        content = _safe_str(evt.get("content"))

        meta = evt.get("meta") or {}
        if not isinstance(meta, dict):
            meta = {}

        is_reply = (typ == "reply")
        typ_s = "回复" if is_reply else "评论"
        platform_s = "抖音" if platform == "douyin" else ("视频号" if platform in ("wx_channels", "wx") else platform)

        trigger_kw = _safe_str(meta.get("trigger_keyword") or meta.get("keyword") or "")
        if not trigger_kw and is_reply:
            trigger_kw = self._infer_trigger_keyword(nickname)

        key_for_collect = self._make_collect_key(ts, platform, nickname, content)
        collected = bool(self._collect_index.get(key_for_collect, False))

        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setRowHeight(row, 38)

        def _set(col: int, txt: str) -> QTableWidgetItem:
            it = QTableWidgetItem(txt)
            it.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            it.setForeground(QBrush(QColor("#eaeaea")))
            self.table.setItem(row, col, it)
            return it

        it_ts = _set(0, ts)
        it_plat = _set(1, platform_s)
        it_nick = _set(2, nickname)
        it_typ = _set(3, typ_s)
        it_txt = _set(4, content)
        it_kw = _set(5, trigger_kw)
        it_col = _set(6, "是" if collected else "否")

        # 在 UserRole 存原始数据，避免 show/raw 来回转换
        try:
            it_ts.setData(Qt.UserRole, {
                "ts": ts,
                "platform_raw": platform,
                "platform_show": platform_s,
                "nickname": nickname,
                "type": typ_s,
                "reply_text": content,
                "trigger_kw": trigger_kw,
                "is_reply": bool(is_reply),
                "collect_key": key_for_collect,
            })
        except Exception:
            pass

        # 维护索引：key -> row（便于 O(1) 刷新入库状态）
        self._row_by_collect_key[key_for_collect] = row
        # 行样式：回复行更深一点底色
        if is_reply:
            for c in range(0, 7):  # 0..6 是 item 列
                it = self.table.item(row, c)
                if it:
                    it.setBackground(QBrush(QColor(0, 102, 204, 140)))

    # ---------- Collect logic ----------
    def _infer_trigger_keyword(self, nickname: str) -> str:
        # 1) app_state.hit_keyword_by_nick
        try:
            m = getattr(app_state, "hit_keyword_by_nick", None)
            if isinstance(m, dict):
                kw = _safe_str(m.get(str(nickname or "")) or "")
                if kw:
                    return kw
        except Exception:
            pass
        # 2) app_state.last_trigger_keyword
        try:
            kw = _safe_str(getattr(app_state, "last_trigger_keyword", "") or "")
            if kw:
                return kw
        except Exception:
            pass
        return ""

    def _make_collect_key(self, ts: str, platform: str, nickname: str, reply_text: str) -> str:
        return f"{platform}|{ts}|{nickname}|{reply_text}".strip()

    @staticmethod
    def _get_collect_index_path(log_path: str) -> str:
        # sidecar：同目录、固定文件名
        try:
            base = os.path.dirname(log_path)
            return os.path.join(base, "comment_reply_collect_index.json")
        except Exception:
            return "comment_reply_collect_index.json"

    def _load_collect_index(self) -> Dict[str, bool]:
        p = self._collect_index_path
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, dict):
                    return {str(k): bool(v) for k, v in d.items()}
        except Exception:
            pass
        return {}

    def _save_collect_index(self):
        p = self._collect_index_path
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
        except Exception:
            pass
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self._collect_index, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _collect_one_reply(self, ts: str, platform_raw: str, platform_show: str, nickname: str, reply_text: str,
                           trigger_kw: str):
        # 再兜底一次关键词
        trigger_kw = (trigger_kw or "").strip() or self._infer_trigger_keyword(nickname)
        if not trigger_kw:
            self._alert_dialog("无法入库",
                               "该条回复缺少“触发关键词”，请确认抖音/视频号 listener 已写入 trigger_keyword。")
            return

        ok = confirm_dialog(
            self,
            title="确认入库",
            text=f"确定将这条回复入库到关键词【{trigger_kw}】吗？\n\n平台：{platform_show}\n用户：{nickname}\n回复：{reply_text}")
        if not ok:
            return

        ok2, msg = self._collect_to_keywords_py(trigger_kw, reply_text)
        if not ok2:
            self._alert_dialog("入库失败", msg)
            return

        # 标记为已入库（sidecar）
        key_for_collect = self._make_collect_key(ts, platform_raw, nickname, reply_text)
        self._collect_index[key_for_collect] = True
        self._save_collect_index()

        # 刷新当前行“已入库”
        self._refresh_collected_cells(ts, platform_raw, nickname, reply_text)

        self._alert_dialog("入库成功", f"已入库到关键词【{trigger_kw}】的 reply 列表。")

    def _refresh_collected_cells(self, ts: str, platform_raw: str, nickname: str, reply_text: str):
        key = self._make_collect_key(ts, platform_raw, nickname, reply_text)
        r = self._row_by_collect_key.get(key, None)
        if r is None:
            return

        try:
            if self.table.item(r, 6):
                self.table.item(r, 6).setText("是")
        except Exception:
            pass

        try:
            w = self.table.cellWidget(r, 7)
            if w:
                for b in w.findChildren(QPushButton):
                    b.setEnabled(False)
        except Exception:
            pass

    def _collect_selected_reply(self):
        r = self.table.currentRow()
        if r < 0:
            self._alert_dialog("提示", "请先选择一条【回复】记录。")
            return

        data = None
        try:
            it0 = self.table.item(r, 0)
            data = it0.data(Qt.UserRole) if it0 else None
        except Exception:
            data = None

        typ = ""
        collected = "否"
        try:
            typ = self.table.item(r, 3).text() if self.table.item(r, 3) else ""
            collected = self.table.item(r, 6).text() if self.table.item(r, 6) else "否"
        except Exception:
            pass

        if typ != "回复":
            self._alert_dialog("提示", "当前选择不是【回复】记录。")
            return
        if collected == "是":
            return

        if isinstance(data, dict):
            ts = _safe_str(data.get("ts")) or _now_ts()
            plat_raw = _safe_str(data.get("platform_raw"))
            plat_show = _safe_str(data.get("platform_show"))
            nickname = _safe_str(data.get("nickname")) or "未知用户"
            reply_text = _safe_str(data.get("reply_text"))
            trigger_kw = _safe_str(data.get("trigger_kw"))
        else:
            ts = self.table.item(r, 0).text() if self.table.item(r, 0) else _now_ts()
            plat_show = self.table.item(r, 1).text() if self.table.item(r, 1) else ""
            nickname = self.table.item(r, 2).text() if self.table.item(r, 2) else "未知用户"
            reply_text = self.table.item(r, 4).text() if self.table.item(r, 4) else ""
            trigger_kw = self.table.item(r, 5).text() if self.table.item(r, 5) else ""
            plat_raw = "douyin" if plat_show == "抖音" else ("wx_channels" if plat_show == "视频号" else plat_show)

        self._collect_one_reply(ts, plat_raw, plat_show, nickname, reply_text, trigger_kw)

    def _on_selection_changed(self):
        r = self.table.currentRow()
        if r < 0:
            self.lb_sel.setText("未选择任何行")
            try:
                self.btn_collect_selected.setEnabled(False)
            except Exception:
                pass
            return

        try:
            ts = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
            plat = self.table.item(r, 1).text() if self.table.item(r, 1) else ""
            nick = self.table.item(r, 2).text() if self.table.item(r, 2) else ""
            typ = self.table.item(r, 3).text() if self.table.item(r, 3) else ""
            collected = self.table.item(r, 6).text() if self.table.item(r, 6) else "否"
        except Exception:
            ts, plat, nick, typ, collected = "", "", "", "", "否"

        self.lb_sel.setText(f"已选：{ts} | {plat} | {nick} | {typ}")
        try:
            self.btn_collect_selected.setEnabled(typ == "回复" and collected != "是")
        except Exception:
            pass

    # ---------- Clear / dialogs ----------
    def _on_clear_log(self):
        r = self.table.currentRow()
        if r < 0:
            self.lb_sel.setText("未选择任何行")
            try:
                self.btn_collect_selected.setEnabled(False)
            except Exception:
                pass
            return
        ts = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
        plat = self.table.item(r, 1).text() if self.table.item(r, 1) else ""
        nick = self.table.item(r, 2).text() if self.table.item(r, 2) else ""
        typ = self.table.item(r, 3).text() if self.table.item(r, 3) else ""
        collected = self.table.item(r, 6).text() if self.table.item(r, 6) else "否"
        self.lb_sel.setText(f"已选：{ts} | {plat} | {nick} | {typ}")
        try:
            self.btn_collect_selected.setEnabled(typ == "回复" and collected != "是")
        except Exception:
            pass

    # ---------- Clear / dialogs ----------
    def _on_clear_log(self):
        ok = confirm_dialog(
            self,
            title="确认清空",
            text="确定要清空所有评论/回复日志吗？（清空后无法恢复）")
        if not ok:
            return

        if clear_log():
            self.table.setRowCount(0)
            self._last_pos = 0
            self._collect_index = {}
            try:
                with open(self._collect_index_path, "w", encoding="utf-8") as f:
                    f.write("{}")
            except Exception:
                pass
            self._alert_dialog("完成", "日志已清空。")
        else:
            self._alert_dialog("失败", "清空失败，请稍后重试。")

    def _alert_dialog(self, title: str, text: str):
        # 用 confirm_dialog 做提示（仅“确定”）
        confirm_dialog(self, title=title, text=text)

    # ---------- Keywords realtime refresh ----------
    def _apply_keywords_in_memory(self, var_name: str, mapping: Dict[str, Any]):
        """把入库后的关键词映射同步到内存，避免必须重启才能看到。"""
        try:
            import importlib
            import keywords  # type: ignore
            # 更新模块内变量（如 QA_KEYWORDS / ZHULI_KEYWORDS）
            try:
                setattr(keywords, var_name, mapping)
            except Exception:
                pass
            # 兼容：如果写的是 QA_KEYWORDS，也同步到其它常见变量名
            if var_name == "QA_KEYWORDS":
                for k in ("qa_keywords", "QA_KEYWORDS", "keyword_rules", "keywords"):
                    try:
                        if hasattr(app_state, k) and isinstance(getattr(app_state, k), dict):
                            setattr(app_state, k, mapping)
                    except Exception:
                        pass
            try:
                importlib.invalidate_caches()
            except Exception:
                pass
        except Exception:
            pass
        


    # ---------- Collect to keywords.py ----------
    def _collect_to_keywords_py(self, prefix: str, reply_text: str):
        """直接把回复写入 keywords.py 的 reply 列表（持久化）。返回 (ok, msg)。"""
        prefix = str(prefix or "").strip()
        reply_text = str(reply_text or "").strip()
        if not prefix or not reply_text:
            return False, "参数为空"

        try:
            import keywords  # type: ignore
            kw_path = inspect.getsourcefile(keywords) or getattr(keywords, "__file__", "")
            kw_path = str(kw_path or "")
            if not kw_path or not os.path.exists(kw_path):
                return False, f"未找到 keywords.py 路径：{kw_path}"
        except Exception as e:
            return False, f"导入 keywords 失败：{e}"

        return self._patch_keywords_file(kw_path, prefix, reply_text)

    def _patch_keywords_file(self, kw_path: str, prefix: str, reply_text: str):
        """AST 解析 keywords.py，定位 QA_KEYWORDS / ZHULI_KEYWORDS 字典，把 reply_text 插入到对应 prefix 的 reply 列表。"""
        try:
            code = pathlib.Path(kw_path).read_text(encoding="utf-8")
        except Exception as e:
            return False, f"读取 keywords.py 失败：{e}"

        try:
            mod = ast.parse(code)
        except Exception as e:
            return False, f"解析 keywords.py 失败：{e}"

        target_names = ["QA_KEYWORDS", "ZHULI_KEYWORDS", "KEYWORDS", "KEYWORD_RULES"]
        assign_node = None
        var_name = None
        mapping = None

        for node in mod.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in target_names:
                    try:
                        data = ast.literal_eval(node.value)
                        if isinstance(data, dict):
                            assign_node = node
                            var_name = name
                            mapping = data
                            break
                    except Exception:
                        continue

        if assign_node is None or var_name is None or mapping is None:
            return False, "未能在 keywords.py 中找到可解析的 QA_KEYWORDS / ZHULI_KEYWORDS 字典"

        # 找到目标 cfg（优先按 cfg['prefix'] 匹配）
        target_cfg = None
        for _, cfg in mapping.items():
            if not isinstance(cfg, dict):
                continue
            if str(cfg.get("prefix") or "").strip() == prefix:
                target_cfg = cfg
                break
        if target_cfg is None and prefix in mapping and isinstance(mapping.get(prefix), dict):
            target_cfg = mapping[prefix]

        if target_cfg is None:
            return False, f"keywords.py 中未找到 prefix={prefix} 的关键词配置"

        arr = target_cfg.get("reply", []) or []
        if not isinstance(arr, list):
            arr = []
        arr = [str(x).strip() for x in arr if str(x).strip()]
        if reply_text in arr:
            return True, "已存在（无需重复入库）"

        arr.insert(0, reply_text)
        if len(arr) > 200:
            arr = arr[:200]
        target_cfg["reply"] = arr

        # 回写（会重排该字典段落格式，但不影响运行）
        new_mapping_text = f"{var_name} = " + pprint.pformat(mapping, width=120, sort_dicts=False) + "\n"

        if not (hasattr(assign_node, "lineno") and hasattr(assign_node, "end_lineno")):
            return False, "AST 不支持 end_lineno，无法安全回写（请升级 Python 版本 >= 3.8）"

        lines = code.splitlines(True)
        start = assign_node.lineno - 1
        end = assign_node.end_lineno
        new_code = "".join(lines[:start] + [new_mapping_text] + lines[end:])

        try:
            pathlib.Path(kw_path).write_text(new_code, encoding="utf-8")
            # ✅ 无需重启：同步到内存并通知关键词页刷新
            try:
                self._apply_keywords_in_memory(var_name, mapping)
            except Exception:
                pass
        except Exception as e:
            return False, f"写入 keywords.py 失败：{e}"

        return True, "入库成功"

    # ---------- Compatibility stub ----------
    def _fallback_collect_reply_to_keyword(self, prefix: str, reply_text: str) -> bool:
        ok, _ = self._collect_to_keywords_py(prefix, reply_text)
        return bool(ok)
