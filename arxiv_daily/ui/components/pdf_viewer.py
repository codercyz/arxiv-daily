"""PDF 预览窗口：QtPdf 内嵌阅读（FitToWidth 滚动翻页）。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class PdfViewerDialog(QDialog):
    def __init__(self, pdf_path: str | Path, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{title[:60]} · PDF 预览")
        self.resize(980, 1000)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)

        self.document = QPdfDocument(self)
        self.document.load(str(pdf_path))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        self.page_label = QLabel("")
        self.page_label.setObjectName("statusLabel")
        bar.addWidget(self.page_label)
        bar.addStretch(1)
        zoom_in = QPushButton("放大 +")
        zoom_in.setObjectName("secondaryButton")
        zoom_in.clicked.connect(lambda: self._zoom(1.2))
        zoom_out = QPushButton("缩小 −")
        zoom_out.setObjectName("secondaryButton")
        zoom_out.clicked.connect(lambda: self._zoom(1 / 1.2))
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("secondaryButton")
        close_btn.clicked.connect(self.accept)
        bar.addWidget(zoom_out)
        bar.addWidget(zoom_in)
        bar.addWidget(close_btn)
        layout.addLayout(bar)

        self.view = QPdfView(self)
        self.view.setDocument(self.document)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        layout.addWidget(self.view, 1)

        # 本版 PySide6 的 QPdfView 无 currentPageChanged 信号，经 pageNavigator 接
        navigator = self.view.pageNavigator()
        navigator.currentPageChanged.connect(self._on_page_changed)
        self._on_page_changed(navigator.currentPage())

    def _on_page_changed(self, page: int):
        self.page_label.setText(f"第 {page + 1} / {self.document.pageCount()} 页")

    def _zoom(self, factor: float):
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(self.view.zoomFactor() * factor)
