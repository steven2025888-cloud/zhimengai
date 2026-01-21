from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from ui.pages.base_page import BasePage

class WorkbenchPage(BasePage):
    title = "AI工作台"
    desc  = "系统启动、开关、日志与测试"

    def __init__(self, mainwin):
        super().__init__(mainwin)
        self.mainwin = mainwin  # 需要 resource_path / license_key / 跳转等都从这取

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(self.title))

        # TODO: 把你原来 _build_workbench_page 里的控件/事件整体搬过来
        # - start_system / clear_log / append_log / set_report_interval
        # - sw_report / sw_auto_reply / sw_danmaku_reply / sw_zhuli
        # - stdout 重定向到 console
