# ui/switch_toggle.py
from PySide6.QtCore import Property, QPropertyAnimation, QEasingCurve, QSize, Qt
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QAbstractButton


class SwitchToggle(QAbstractButton):
    def __init__(self, parent=None, checked=False):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(bool(checked))
        self.setCursor(Qt.PointingHandCursor)

        self._margin = 3
        self._offset = 0.0

        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)

        self._sync_offset()

    def sizeHint(self):
        return QSize(54, 28)

    def _sync_offset(self):
        h = self.height() if self.height() > 0 else 28
        w = self.width() if self.width() > 0 else 54
        knob = h - self._margin * 2
        self._offset = (w - self._margin - knob) if self.isChecked() else self._margin
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_offset()

    # ✅ 关键修复：不要再调用 super().mouseReleaseEvent，避免二次 toggle
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.pos()):
            self.toggle()
            self._start_anim()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def _start_anim(self):
        h = self.height()
        w = self.width()
        knob = h - self._margin * 2
        end = (w - self._margin - knob) if self.isChecked() else self._margin
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(end)
        self._anim.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        r = h / 2.0

        # ✅ 开启改为绿色
        track_off = QColor(255, 255, 255, 40)
        track_on = QColor(46, 204, 113, 180)  # green
        p.setPen(Qt.NoPen)
        p.setBrush(track_on if self.isChecked() else track_off)
        p.drawRoundedRect(0, 0, w, h, r, r)

        knob_size = h - self._margin * 2
        knob_color = QColor(255, 255, 255, 235)
        p.setBrush(knob_color)
        p.drawEllipse(int(self._offset), self._margin, knob_size, knob_size)
        p.end()

    def getOffset(self):
        return self._offset

    def setOffset(self, v):
        self._offset = float(v)
        self.update()

    offset = Property(float, getOffset, setOffset)
