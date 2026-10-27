"""极简月历弹层：锚定在触发按钮下方的下拉式小组件（非独立窗口）。

- Qt.Popup：无边框、不出现在任务栏、点击外部自动关闭
- 半透明背景承载卡片圆角与柔影
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]


class CalendarPopup(QWidget):
    dateSelected = Signal(str)          # yyyy-mm-dd（单日模式）
    dateRangeSelected = Signal(str, str)  # 起,止（范围模式，起==止 表示单日）


    def __init__(self, highlighted_days: list[str], initial: str, parent=None,
                 range_mode: bool = False, initial_range: tuple[str, str] | None = None,
                 max_date: str | None = None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("calendarCard")
        self.setFixedSize(324, 368)

        self._range_mode = range_mode
        from datetime import date as _date
        self._max_date = _date.fromisoformat(max_date) if max_date else None  # 可选上界（含）
        self._pick_start: date | None = None  # 范围模式第一步已选的起始日
        self._range: tuple[date, date] | None = None
        if initial_range:
            try:
                a = date.fromisoformat(initial_range[0])
                b = date.fromisoformat(initial_range[1])
                self._range = (min(a, b), max(a, b))
            except ValueError:
                pass

        self._highlight = set(highlighted_days)
        try:
            init = date.fromisoformat(initial)
        except ValueError:
            init = date.today()
        self._year, self._month = init.year, init.month
        self._selected_iso = init.isoformat()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 8)
        layout.setSpacing(2)

        # 标题行：‹ 2026年10月 › · 今天
        head = QHBoxLayout()
        prev_month = QPushButton("‹")
        prev_month.setObjectName("calNav")
        prev_month.setCursor(Qt.PointingHandCursor)
        prev_month.setFixedSize(32, 30)
        prev_month.clicked.connect(lambda: self._shift_month(-1))
        self.title = QLabel("")
        self.title.setObjectName("calTitle")
        self.title.setAlignment(Qt.AlignCenter)
        next_month = QPushButton("›")
        next_month.setObjectName("calNav")
        next_month.setCursor(Qt.PointingHandCursor)
        next_month.setFixedSize(32, 30)
        next_month.clicked.connect(lambda: self._shift_month(1))
        today_btn = QPushButton("昨天" if self._max_date else "今天")
        today_btn.setObjectName("ghostButton")
        today_btn.setCursor(Qt.PointingHandCursor)
        today_btn.clicked.connect(
            lambda: self._pick(self._max_date or date.today()))
        self.title.setMinimumWidth(96)
        center = QHBoxLayout()
        center.setSpacing(6)
        center.addWidget(prev_month)
        center.addWidget(self.title)
        center.addWidget(next_month)
        head.addStretch(1)
        head.addLayout(center)
        head.addStretch(1)
        head.addSpacing(6)
        head.addWidget(today_btn)
        layout.addLayout(head)
        self.hint = QLabel("")
        self.hint.setObjectName("calHint")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.hide()
        layout.addWidget(self.hint)

        # 星期色块带（浅灰圆角分区）
        week_bar = QFrame()
        week_bar.setObjectName("calWeekBar")
        week_bar.setFixedHeight(20)
        week_row = QHBoxLayout(week_bar)
        week_row.setContentsMargins(8, 0, 8, 0)
        week_row.setSpacing(0)
        for name in _WEEKDAYS:
            label = QLabel(name)
            label.setObjectName("calWeekday")
            label.setAlignment(Qt.AlignCenter)
            week_row.addWidget(label, 1)
        layout.addWidget(week_bar)

        # 日期网格
        self.grid = QGridLayout()
        self.grid.setSpacing(2)
        layout.addLayout(self.grid, 1)

        self._day_buttons: dict[str, QPushButton] = {}
        self._rebuild()

    # ---- 弹出位置：锚定在触发按钮正下方 ----
    def show_below(self, anchor: QWidget):
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 6))
        window = anchor.window()
        if window.windowHandle() is not None:
            avail = window.windowHandle().screen().availableGeometry()
            if pos.x() + self.width() > avail.right():
                pos.setX(max(avail.left(), avail.right() - self.width()))
            if pos.y() + self.height() > avail.bottom():
                pos.setY(anchor.mapToGlobal(QPoint(0, -self.height() - 6)).y())
        self.move(pos)
        self.show()

    # ---- 内部 ----
    def _shift_month(self, delta: int):
        month = self._month + delta
        year = self._year
        if month == 0:
            month, year = 12, year - 1
        elif month == 13:
            month, year = 1, year + 1
        self._year, self._month = year, month
        self._rebuild()

    def _rebuild(self):
        self.title.setText(f"{self._year} 年 {self._month} 月")
        self._day_buttons.clear()
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        first = date(self._year, self._month, 1)
        lead = first.weekday()  # 周一=0
        if first.month == 12:
            next_month = date(self._year + 1, 1, 1)
        else:
            next_month = date(self._year, self._month + 1, 1)
        days = (next_month - first).days
        today_iso = date.today().isoformat()

        for cell in range(lead):
            self.grid.addWidget(QLabel(""), 0, cell)
        from datetime import date as _d2

        for day in range(1, days + 1):
            _d_day = _d2(self._year, self._month, day)
            iso = _d_day.isoformat()
            button = QPushButton(str(day))
            button.setObjectName("calDay")
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(34)
            button.setProperty("iso", iso)
            beyond = self._max_date is not None and _d_day > self._max_date
            button.setProperty("beyond", beyond)
            button.setEnabled(not beyond)
            button.setProperty("hasData", iso in self._highlight)
            button.setProperty("isToday", iso == today_iso)
            if self._range_mode:
                start_iso = self._pick_start.isoformat() if self._pick_start else (
                    self._range[0].isoformat() if self._range else None)
                end_iso = self._pick_start.isoformat() if self._pick_start else (
                    self._range[1].isoformat() if self._range else None)
                button.setProperty("isSelected", start_iso is not None and iso in (start_iso, end_iso))
                in_range = start_iso is not None and start_iso <= iso <= end_iso
                button.setProperty("inRange", in_range)
                button.installEventFilter(self)  # 悬停预览范围
            else:
                button.setProperty("isSelected", iso == self._selected_iso)
            self._day_buttons[iso] = button
            button.clicked.connect(
                lambda _=False, d=day: self._pick(date(self._year, self._month, d))
            )
            self.grid.addWidget(button, (lead + day - 1) // 7, (lead + day - 1) % 7)

    def _pick(self, day: date):
        if not self._range_mode:
            self.dateSelected.emit(day.isoformat())
            self.close()
            return
        if self._pick_start is None:
            self._pick_start = day
            self.hint.setText(f"起始日 {day.isoformat()} · 请点结束日（点同一天 = 仅当天）")
            self.hint.show()
            self._rebuild()
            return
        start, end = sorted((self._pick_start, day))
        self._pick_start = None
        self.dateRangeSelected.emit(start.isoformat(), end.isoformat())
        self.close()

    # ---- 悬停实时预览范围 ----
    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent

        if (self._range_mode and self._pick_start is not None
                and event.type() in (QEvent.Type.HoverEnter, QEvent.Type.Enter)):
            iso = obj.property("iso")
            if isinstance(iso, str):
                lo, hi = sorted((iso, self._pick_start.isoformat()))
                self._apply_preview(lo, hi)
        return super().eventFilter(obj, event)

    def leaveEvent(self, event):
        if self._pick_start is not None:
            self._apply_preview(self._pick_start.isoformat(), self._pick_start.isoformat())
        super().leaveEvent(event)

    def _apply_preview(self, start_iso: str, end_iso: str):
        for iso, button in self._day_buttons.items():
            in_range = start_iso <= iso <= end_iso
            button.setProperty("inRange", in_range)
            button.style().unpolish(button)
            button.style().polish(button)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        super().keyPressEvent(event)
