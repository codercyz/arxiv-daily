"""黑白极简 SVG 图标（内嵌绘制，圆角线条风）。"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# 日历：圆角外框 + 顶部圆头装订环 + 日期圆点阵
_CALENDAR_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
  <rect x="5" y="8" width="38" height="35" rx="9" fill="none" stroke="#2E2E2C" stroke-width="3.2"/>
  <path d="M5 18 H43" stroke="#2E2E2C" stroke-width="3.2" stroke-linecap="round"/>
  <path d="M15 4 V12" stroke="#2E2E2C" stroke-width="3.2" stroke-linecap="round"/>
  <path d="M33 4 V12" stroke="#2E2E2C" stroke-width="3.2" stroke-linecap="round"/>
  <circle cx="16" cy="27" r="2.6" fill="#2E2E2C"/>
  <circle cx="24" cy="27" r="2.6" fill="#2E2E2C"/>
  <circle cx="32" cy="27" r="2.6" fill="#2E2E2C"/>
  <circle cx="16" cy="34.5" r="2.6" fill="#ABABA6"/>
  <circle cx="24" cy="34.5" r="2.6" fill="#ABABA6"/>
</svg>"""


def svg_icon(svg: str, size: int = 18, dpr: float | None = None) -> QIcon:
    """按屏幕实际 DPR 渲染 1:1 物理像素，高分屏不糊。"""
    if dpr is None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        dpr = app.devicePixelRatio() if app else 2.0
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixels = int(size * dpr)
    image = QImage(pixels, pixels, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(dpr)
    return QIcon(pixmap)


def calendar_icon(size: int = 18) -> QIcon:
    return svg_icon(_CALENDAR_SVG, size)


_CHEVRON_LEFT = """<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
  <path d="M29 12 L19 24 L29 36" fill="none" stroke="#2E2E2C" stroke-width="5"
        stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

_CHEVRON_RIGHT = """<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
  <path d="M19 12 L29 24 L19 36" fill="none" stroke="#2E2E2C" stroke-width="5"
        stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""


def chevron_icon(direction: str, size: int = 12) -> QIcon:
    return svg_icon(_CHEVRON_LEFT if direction == "left" else _CHEVRON_RIGHT, size)


_APP_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <rect x="8" y="8" width="240" height="240" rx="56" fill="#333331"/>
  <rect x="56" y="52" width="144" height="18" rx="9" fill="#FDFDFC"/>
  <rect x="56" y="96" width="144" height="18" rx="9" fill="#FDFDFC" opacity="0.9"/>
  <rect x="56" y="140" width="96" height="18" rx="9" fill="#FDFDFC" opacity="0.75"/>
  <circle cx="176" cy="196" r="14" fill="#FDFDFC"/>
</svg>"""


def app_icon() -> QIcon:
    return svg_icon(_APP_ICON_SVG, 64)
