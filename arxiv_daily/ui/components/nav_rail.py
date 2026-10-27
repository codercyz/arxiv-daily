"""导航组件：带滑动指示器。

- 垂直模式：侧边栏（黑色圆角滑块纵向滑动）
- 水平模式：顶栏分段导航（无轨道底，白色滑动胶囊 + 细边线 + 柔影）
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
)


class NavRail(QFrame):
    """继承 QFrame 以绘制 QSS 样式盒。"""

    currentChanged = Signal(int)

    def __init__(
        self,
        items: list[str],
        button_height: int = 44,
        horizontal: bool = False,
        button_width: int = 78,
        parent=None,
    ):
        super().__init__(parent)
        self._index = -1
        self._horizontal = horizontal

        if horizontal:
            self.setObjectName("segmentBar")
            layout: QVBoxLayout | QHBoxLayout = QHBoxLayout(self)
            layout.setContentsMargins(2, 2, 2, 2)
            layout.setSpacing(2)
        else:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)

        # 指示器先创建并置底，按钮覆盖其上
        self._indicator = QFrame(self)
        self._indicator.setObjectName("navIndicator")
        self._indicator.hide()
        if horizontal:
            # 白胶囊在白顶栏上靠细边线 + 柔影呈现立体感
            shadow = QGraphicsDropShadowEffect(self._indicator)
            shadow.setBlurRadius(14)
            shadow.setOffset(0, 2)
            shadow.setColor(QColor(17, 17, 17, 38))
            self._indicator.setGraphicsEffect(shadow)

        self._buttons: list[QPushButton] = []
        for i, text in enumerate(items):
            button = QPushButton(text)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(button_height)
            if horizontal:
                button.setFixedWidth(button_width)
            button.clicked.connect(lambda _=False, idx=i: self.setCurrentIndex(idx))
            layout.addWidget(button)
            self._buttons.append(button)

        self._indicator.lower()

    # ---- 对外接口 ----
    def count(self) -> int:
        return len(self._buttons)

    def currentIndex(self) -> int:
        return self._index

    def setCurrentIndex(self, index: int):
        if not 0 <= index < len(self._buttons) or index == self._index:
            return
        self._index = index
        for i, button in enumerate(self._buttons):
            button.setChecked(i == index)
        self._move_indicator(animated=self.isVisible())
        self.currentChanged.emit(index)

    # ---- 内部 ----
    def _move_indicator(self, animated: bool):
        if self._index < 0:
            return
        target = self._buttons[self._index].geometry()
        if not animated or not self.isVisible():
            self._indicator.setGeometry(target)
            self._indicator.show()
            return
        anim = QPropertyAnimation(self._indicator, b"geometry", self)
        anim.setDuration(220)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(self._indicator.geometry())
        anim.setEndValue(target)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def showEvent(self, event):
        super().showEvent(event)
        self._move_indicator(animated=False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._move_indicator(animated=False)
