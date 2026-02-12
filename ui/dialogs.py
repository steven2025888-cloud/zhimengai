# ui/dialogs.py
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

from PySide6.QtCore import Qt, QThread, Signal, QObject, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QLineEdit,
    QSpinBox, QWidget, QSizePolicy
)


# ========= 统一暗色弹窗样式（不吃你 AppBackground 的全局染色） =========
DIALOG_QSS = """
QDialog {
    background: #1F2329;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 14px;
}
QLabel {
    color: #E6EEF8;
    font-size: 13px;
}
QLabel#DialogTitle {
    font-size: 15px;
    font-weight: 900;
    color: #EAF2FF;
}
QLabel#DialogSub {
    color: rgba(233,236,245,0.70);
}
QWidget#Divider {
    background: rgba(255,255,255,0.08);
    min-height: 1px;
    max-height: 1px;
}
QLineEdit, QTextEdit, QSpinBox {
    background: #0F1A2E;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 10px;
    padding: 8px 10px;
    color: #EAF2FF;
    selection-background-color: rgba(57,113,249,0.35);
}
QTextEdit {
    padding: 10px 12px;
}
QPushButton {
    border-radius: 10px;
    padding: 8px 14px;
    font-weight: 800;
    min-height: 34px;
}
QPushButton#BtnPrimary {
    background: #3971f9;
    color: #FFFFFF;
}
QPushButton#BtnPrimary:hover { background: rgba(57,113,249,0.85); }
QPushButton#BtnPrimary:pressed { background: rgba(57,113,249,0.65); }
QPushButton#BtnPrimary:disabled {
    background: #6B7280;
    color: #D1D5DB;
}

QPushButton#BtnGhost {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.10);
    color: #E6EEF8;
}
QPushButton#BtnGhost:hover { background: rgba(255,255,255,0.10); }
QPushButton#BtnGhost:pressed { background: rgba(255,255,255,0.06); }
QPushButton#BtnGhost:disabled {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.05);
    color: #6B7280;
}
"""


def _divider() -> QWidget:
    w = QWidget()
    w.setObjectName("Divider")
    w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    w.setFixedHeight(1)
    return w


class BaseDialog(QDialog):
    """统一的弹窗基类：自动套用样式、统一间距、统一按钮区。"""

    def __init__(self, parent=None, title: str = "", subtitle: str = ""):
        super().__init__(parent)
        self.setModal(True)
        self.setStyleSheet(DIALOG_QSS)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._ok = False

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(16, 16, 16, 14)
        self.root.setSpacing(10)

        # Header
        if title:
            t = QLabel(title)
            t.setObjectName("DialogTitle")
            t.setWordWrap(True)
            self.root.addWidget(t)

        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("DialogSub")
            s.setWordWrap(True)
            self.root.addWidget(s)

        self.root.addWidget(_divider())

        # Body container
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        self.root.addLayout(self.body)

        # Footer
        self.root.addWidget(_divider())
        self.footer = QHBoxLayout()
        self.footer.setSpacing(10)
        self.footer.addStretch(1)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("BtnGhost")
        self.btn_ok = QPushButton("确认")
        self.btn_ok.setObjectName("BtnPrimary")

        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_ok.clicked.connect(self._confirm)

        self.footer.addWidget(self.btn_cancel)
        self.footer.addWidget(self.btn_ok)
        self.root.addLayout(self.footer)

        self.setMinimumWidth(420)

    def _confirm(self):
        self._ok = True
        self.accept()

    def _cancel(self):
        self._ok = False
        self.reject()

    @property
    def ok(self) -> bool:
        return self._ok


# ===================== 1) 确认/提示 =====================

class ConfirmDialog(BaseDialog):
    def __init__(self, parent, title: str, text: str, subtitle: str = ""):
        super().__init__(parent, title=title, subtitle=subtitle)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        self.body.addWidget(lbl)


def confirm_dialog(parent, title: str, text: str, subtitle: str = "") -> bool:
    dlg = ConfirmDialog(parent, title, text, subtitle=subtitle)
    dlg.exec()
    return dlg.ok


# ===================== 2) 单行输入 =====================

class TextInputDialog(BaseDialog):
    def __init__(self, parent, title: str, label: str, default: str = "",
                 placeholder: str = "", max_len: int = 0):
        super().__init__(parent, title=title)
        lbl = QLabel(label)
        lbl.setWordWrap(True)
        self.body.addWidget(lbl)

        self.input = QLineEdit()
        self.input.setText(default or "")
        if placeholder:
            self.input.setPlaceholderText(placeholder)
        if max_len and max_len > 0:
            self.input.setMaxLength(max_len)
        self.body.addWidget(self.input)

        self.input.returnPressed.connect(self._confirm)
        self._value = ""

    def _confirm(self):
        self._value = (self.input.text() or "").strip()
        super()._confirm()

    @property
    def value(self) -> str:
        return self._value


def text_input_dialog(parent, title: str, label: str, default: str = "",
                      placeholder: str = "", max_len: int = 0) -> Tuple[str, bool]:
    dlg = TextInputDialog(parent, title, label, default=default, placeholder=placeholder, max_len=max_len)
    dlg.exec()
    return dlg.value, dlg.ok


# ===================== 3) 数字输入（替代 QInputDialog.getInt） =====================

class IntInputDialog(BaseDialog):
    def __init__(self, parent, title: str, label: str,
                 value: int = 0, min_value: int = 0, max_value: int = 999999, step: int = 1):
        super().__init__(parent, title=title)
        lbl = QLabel(label)
        lbl.setWordWrap(True)
        self.body.addWidget(lbl)

        self.spin = QSpinBox()
        self.spin.setRange(min_value, max_value)
        self.spin.setSingleStep(step)
        self.spin.setValue(value)
        self.body.addWidget(self.spin)

        self._value = value

    def _confirm(self):
        self._value = int(self.spin.value())
        super()._confirm()

    @property
    def value(self) -> int:
        return self._value


def int_input_dialog(parent, title: str, label: str,
                     value: int = 0, min_value: int = 0, max_value: int = 999999, step: int = 1) -> Tuple[int, bool]:
    dlg = IntInputDialog(parent, title, label, value=value, min_value=min_value, max_value=max_value, step=step)
    dlg.exec()
    return dlg.value, dlg.ok


# ===================== 4) 多行输入 =====================

class MultiLineInputDialog(BaseDialog):
    def __init__(self, parent, title: str, label: str, default: str = ""):
        super().__init__(parent, title=title)
        lbl = QLabel(label)
        lbl.setWordWrap(True)
        self.body.addWidget(lbl)

        self.edit = QTextEdit()
        self.edit.setPlainText(default or "")
        self.edit.setMinimumHeight(220)
        self.body.addWidget(self.edit)

        self._text = ""

    def _confirm(self):
        self._text = self.edit.toPlainText()
        super()._confirm()

    @property
    def text(self) -> str:
        return self._text


def multiline_input_dialog(parent, title: str, label: str, default: str = "") -> Tuple[str, bool]:
    dlg = MultiLineInputDialog(parent, title, label, default=default)
    dlg.exec()
    return dlg.text, dlg.ok


# ===================== 5) 三选一/多选一（替代 QMessageBox.addButton 那套） =====================

@dataclass
class ChoiceItem:
    text: str
    role: str = "normal"  # normal / destructive / cancel


class ChoiceDialog(BaseDialog):
    def __init__(self, parent, title: str, text: str, items: List[ChoiceItem]):
        super().__init__(parent, title=title)
        self._choice: Optional[str] = None

        lbl = QLabel(text)
        lbl.setWordWrap(True)
        self.body.addWidget(lbl)

        # 覆盖 footer：用多个按钮代替“取消/确认”
        # 这里把基类按钮隐藏掉
        self.btn_cancel.hide()
        self.btn_ok.hide()

        # 清空 footer，重新布局
        while self.footer.count():
            it = self.footer.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

        self.footer.addStretch(1)

        for item in items:
            b = QPushButton(item.text)
            if item.role == "cancel":
                b.setObjectName("BtnGhost")
                b.clicked.connect(self._cancel)
            elif item.role == "destructive":
                # 用主按钮样式但你也可以改成红色；先保持统一风格
                b.setObjectName("BtnPrimary")
                b.clicked.connect(lambda _=False, t=item.text: self._pick(t))
            else:
                b.setObjectName("BtnGhost")
                b.clicked.connect(lambda _=False, t=item.text: self._pick(t))
            self.footer.addWidget(b)

    def _pick(self, text: str):
        self._choice = text
        self._ok = True
        self.accept()

    @property
    def choice(self) -> Optional[str]:
        return self._choice


def choice_dialog(parent, title: str, text: str, items: List[ChoiceItem]) -> Tuple[Optional[str], bool]:
    dlg = ChoiceDialog(parent, title, text, items)
    dlg.exec()
    return dlg.choice, dlg.ok


# ===================== 6) AI优化关键词对话框 =====================

class _AIOptimizeWorker(QObject):
    """后台AI优化工作线程"""
    finished = Signal(bool, dict, str)  # success, data, error_msg
    
    def __init__(self, keywords_data: dict, api_key: str, model: str, additional_prompt: str = ""):
        super().__init__()
        self.keywords_data = keywords_data
        self.api_key = api_key
        self.model = model
        self.additional_prompt = additional_prompt
    
    def run(self):
        """在后台线程中运行"""
        import json
        import http.client
        
        try:
            if not self.additional_prompt:
                # 首次优化：根据必含词生成必含词+意图词
                keywords_str = json.dumps(self.keywords_data, ensure_ascii=False, indent=2)
                prompt = f"""请帮我优化以下关键词配置。这是一个直播助手的关键词匹配系统。

重要说明：
- must（必含词）：用户问题中必须包含的核心词汇（名词、主体）
- any（意图词）：用户问题中可能出现的修饰词、口语表达、同义词（形容词、动词、疑问词）
- reply（回复词）：如果原本有才需要生成更多；如果没有就不添加

优化规则：
1. 拆分复合词：如果必含词是"炉膛多少尺寸"，应该拆分为：
   - must: ["炉膛", "尺寸"]（核心词）
   - any: ["多少", "多大", "怎么样", "如何"]（修饰词/疑问词）

2. 对于每个分类的必含词，请：
   - 提取核心名词作为 must
   - 提取修饰词、形容词、疑问词作为 any
   - 生成相关的同义词和口语表达

3. 示例：
   - 原始: must: ["充电快不快"]
   - 优化后: must: ["充电"], any: ["快", "不快", "快吗", "快不快", "速度", "效率"]

4. 排除词（deny）可以不要

当前关键词配置：
{keywords_str}

请返回优化后的完整JSON格式，保持原有结构。"""
            else:
                # 继续优化
                optimized_str = json.dumps(self.keywords_data, ensure_ascii=False, indent=2)
                prompt = f"""基于用户的优化建议，继续改进关键词配置。

用户建议：{self.additional_prompt}

当前优化后的配置：
{optimized_str}

请根据用户建议进一步优化，返回完整的JSON格式。记住：
- must 应该是核心名词
- any 应该是修饰词、口语表达、同义词"""
            
            # 调用AI API
            conn = http.client.HTTPSConnection("ai.zhimengai.xyz", timeout=30)
            payload = json.dumps({
                "model": self.model,
                "max_tokens": 3000,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "stream": False
            })
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            conn.request("POST", "/v1/chat/completions", payload, headers)
            res = conn.getresponse()
            data = json.loads(res.read().decode("utf-8"))
            conn.close()
            
            if res.status == 200:
                # 提取AI返回的内容
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                # 尝试解析JSON
                try:
                    # 查找JSON部分
                    start = content.find("{")
                    end = content.rfind("}") + 1
                    if start >= 0 and end > start:
                        json_str = content[start:end]
                        parsed = json.loads(json_str)
                        
                        # 验证结构
                        if isinstance(parsed, dict):
                            self.finished.emit(True, parsed, "")
                        else:
                            self.finished.emit(False, {}, f"AI返回的JSON格式不正确（不是对象）：\n\n{content}")
                    else:
                        self.finished.emit(False, {}, f"无法从AI返回内容中提取JSON：\n\n{content}")
                except json.JSONDecodeError as je:
                    self.finished.emit(False, {}, f"JSON解析失败：{str(je)}\n\nAI返回内容：\n{content}")
            else:
                self.finished.emit(False, {}, f"API错误 ({res.status})：{data}")
                
        except Exception as e:
            import traceback
            self.finished.emit(False, {}, f"优化失败：{str(e)}\n\n{traceback.format_exc()}")


class AIOptimizeKeywordsDialog(BaseDialog):
    def __init__(self, parent, keywords_data: dict, api_key: str, model: str):
        super().__init__(parent, title="🤖 AI优化关键词")
        self.keywords_data = keywords_data
        self.api_key = api_key
        self.model = model
        self.optimized_data = {}
        self._worker_thread = None
        self._worker = None
        
        # 显示优化结果的文本框
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMinimumHeight(300)
        self.result_text.setPlaceholderText("正在调用AI优化关键词...")
        self.body.addWidget(self.result_text)
        
        # 继续优化的输入框
        self.optimize_input = QLineEdit()
        self.optimize_input.setPlaceholderText("输入优化建议（例如：添加更多同义词、增加回复词等），然后点击【继续优化】")
        self.optimize_input.setVisible(False)
        self.body.addWidget(self.optimize_input)
        
        # 修改按钮文本
        self.btn_ok.setText("✅ 确认添加")
        self.btn_cancel.setText("❌ 取消")
        
        # 添加"继续优化"按钮
        self.btn_continue = QPushButton("🔄 继续优化")
        self.btn_continue.setObjectName("BtnGhost")
        self.btn_continue.setVisible(False)
        self.btn_continue.clicked.connect(self._continue_optimize)
        
        # 在footer中插入继续优化按钮（在取消按钮之前）
        # footer 当前的顺序是: stretch, cancel, ok
        # 我们要改成: stretch, continue, cancel, ok
        self.footer.insertWidget(self.footer.count() - 2, self.btn_continue)
        
        # 使用QTimer延迟启动AI优化，确保UI完全初始化
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, self._call_ai_optimize)
    
    def _call_ai_optimize(self, additional_prompt: str = ""):
        """调用AI优化关键词"""
        # 停止之前的线程
        if self._worker_thread and self._worker_thread.isRunning():
            self._worker_thread.quit()
            self._worker_thread.wait()
        
        # 禁用所有按钮
        self.btn_ok.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.btn_continue.setEnabled(False)
        self.optimize_input.setEnabled(False)
        
        # 显示加载状态
        self.result_text.setText("⏳ 正在优化关键词，请稍候...")
        
        # 创建新的工作线程
        self._worker_thread = QThread()
        self._worker = _AIOptimizeWorker(self.optimized_data or self.keywords_data, self.api_key, self.model, additional_prompt)
        self._worker.moveToThread(self._worker_thread)
        
        # 连接信号
        self._worker_thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_optimize_finished)
        self._worker.finished.connect(self._worker_thread.quit)
        
        # 启动线程
        self._worker_thread.start()
    
    def _on_optimize_finished(self, success: bool, data: dict, error_msg: str):
        """优化完成的回调"""
        # 恢复按钮状态
        self.btn_cancel.setEnabled(True)
        self.optimize_input.setEnabled(True)
        
        if success:
            self.optimized_data = data
            self._display_result(data)
        else:
            self.result_text.setText(f"❌ {error_msg}")
            self.btn_ok.setEnabled(True)
    
    def _display_result(self, data: dict):
        """显示优化结果"""
        result_lines = ["✅ AI优化完成！以下是优化后的关键词：\n"]
        
        for prefix, cfg in data.items():
            result_lines.append(f"\n【{prefix}】")
            must = cfg.get('must', [])
            any_ = cfg.get('any', [])
            deny = cfg.get('deny', [])
            reply = cfg.get('reply', [])
            
            result_lines.append(f"  必含词: {', '.join(map(str, must)) if must else '(无)'}")
            result_lines.append(f"  意图词: {', '.join(map(str, any_)) if any_ else '(无)'}")
            if deny:
                result_lines.append(f"  排除词: {', '.join(map(str, deny))}")
            if reply:
                result_lines.append(f"  回复词: {'; '.join(map(str, reply))}")
        
        result_lines.append("\n\n" + "="*60)
        result_lines.append("如果满意，点击【✅ 确认添加】")
        result_lines.append("如需继续优化，输入建议后点击【🔄 继续优化】")
        
        self.result_text.setText("\n".join(result_lines))
        
        # 启用按钮
        self.btn_ok.setEnabled(True)
        self.btn_continue.setEnabled(True)
        self.optimize_input.setVisible(True)
        self.btn_continue.setVisible(True)
    
    def _continue_optimize(self):
        """继续优化"""
        suggestion = self.optimize_input.text().strip()
        if not suggestion:
            self.result_text.setText(self.result_text.toPlainText() + "\n❌ 请输入优化建议")
            return
        
        # 清空输入框
        self.optimize_input.clear()
        
        # 禁用按钮
        self.btn_ok.setEnabled(False)
        self.btn_continue.setEnabled(False)
        self.optimize_input.setEnabled(False)
        
        # 调用AI继续优化
        self._call_ai_optimize(suggestion)
    
    def _confirm(self):
        """确认添加"""
        if self.optimized_data:
            self._ok = True
            self.accept()
        else:
            self.result_text.setText("❌ 请等待AI优化完成")
    
    def closeEvent(self, event):
        """关闭对话框时清理线程"""
        if self._worker_thread and self._worker_thread.isRunning():
            self._worker_thread.quit()
            self._worker_thread.wait()
        super().closeEvent(event)


