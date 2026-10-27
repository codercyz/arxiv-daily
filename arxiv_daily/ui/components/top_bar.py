"""悬浮胶囊顶栏：Linear/Notion 式——白色胶囊容器 + iOS 式白色滑动选中段。"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .nav_rail import NavRail

_BRAND = (
    '<span style="font-size:21px; font-weight:300; color:#2E2E2C;'
    'font-family:&quot;Microsoft YaHei UI&quot;;">ArXiv</span>'
    '&nbsp;'
    '<span style="font-size:12px; font-weight:400; color:#ABABA6;'
    'font-family:&quot;Microsoft YaHei UI&quot;;">Daily</span>'
)


class TopBar(QWidget):
    navChanged = Signal(int)

    def __init__(self, tabs: list[str], version_text: str = "", parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 6)
        outer.setSpacing(0)

        capsule = QFrame()
        capsule.setObjectName("topCapsule")
        capsule.setFixedHeight(56)
        shadow = QGraphicsDropShadowEffect(capsule)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(17, 17, 17, 26))
        capsule.setGraphicsEffect(shadow)

        row = QHBoxLayout(capsule)
        row.setContentsMargins(22, 0, 22, 0)
        row.setSpacing(16)

        brand = QLabel(_BRAND)
        brand.setObjectName("brandLabel")
        row.addWidget(brand)

        row.addStretch(1)
        self.rail = NavRail(tabs, button_height=32, horizontal=True, button_width=80)
        self.rail.currentChanged.connect(self.navChanged.emit)
        row.addWidget(self.rail)
        row.addStretch(1)

        version = QLabel(version_text)
        version.setObjectName("navVersion")
        row.addWidget(version)

        outer.addWidget(capsule)

    # ---- 转发导航接口 ----
    def setCurrentIndex(self, index: int):
        self.rail.setCurrentIndex(index)

    def currentIndex(self) -> int:
        return self.rail.currentIndex()
