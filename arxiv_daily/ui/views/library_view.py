"""收藏视图：星标论文列表 + BibTeX / Markdown 导出。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...services.library import export_bibtex, export_markdown
from ...storage.database import Database
from ..components.empty_state import EmptyState
from ..components.paper_card import PaperCard

CONTENT_MAX_WIDTH = 960


class LibraryView(QWidget):
    openDetail = Signal(object)
    downloadRequested = Signal(object)
    starToggled = Signal(object, bool)
    toastRequested = Signal(str)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self._db = db
        self._setup_ui()

    def _setup_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        content = QWidget()
        content.setMaximumWidth(CONTENT_MAX_WIDTH)
        outer.addWidget(content, 100)
        outer.addStretch(1)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(36, 28, 36, 24)
        layout.setSpacing(12)

        header = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(4)
        title = QLabel("我的收藏")
        title.setObjectName("pageTitle")
        subtitle = QLabel("星标论文集中管理，可导出 BibTeX（文献管理）或 Markdown（日报分享）")
        subtitle.setObjectName("pageSubtitle")
        col.addWidget(title)
        col.addWidget(subtitle)
        header.addLayout(col)
        header.addStretch(1)
        export_bib = QPushButton("导出 BibTeX")
        export_bib.setObjectName("secondaryButton")
        export_bib.setCursor(Qt.PointingHandCursor)
        export_bib.clicked.connect(lambda: self._export("bibtex"))
        header.addWidget(export_bib)
        export_md = QPushButton("导出 Markdown")
        export_md.setObjectName("secondaryButton")
        export_md.setCursor(Qt.PointingHandCursor)
        export_md.clicked.connect(lambda: self._export("markdown"))
        header.addWidget(export_md)
        layout.addLayout(header)

        self.status = QLabel("")
        self.status.setObjectName("statusLabel")
        layout.addWidget(self.status)

        self.empty = EmptyState("Starred", "在论文卡片或详情页点 ☆ 收藏，这里会集中出现")
        layout.addWidget(self.empty, 1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.hide()
        container = QWidget()
        self.rows = QVBoxLayout(container)
        self.rows.setContentsMargins(0, 0, 8, 0)
        self.rows.setSpacing(14)
        self.rows.addStretch(1)
        self.scroll.setWidget(container)
        layout.addWidget(self.scroll, 4)

    def refresh(self):
        papers = self._db.list_starred()
        while self.rows.count() > 1:
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not papers:
            self.empty.show()
            self.scroll.hide()
            self.status.setText("")
            return
        self.empty.hide()
        self.scroll.show()
        self.status.setText(f"共 {len(papers)} 篇收藏")
        for rank, paper in enumerate(papers, 1):
            card = PaperCard(paper, rank, starred=True)
            card.opened.connect(self.openDetail.emit)
            card.downloadRequested.connect(self.downloadRequested.emit)
            card.starToggled.connect(self.starToggled.emit)
            self.rows.insertWidget(self.rows.count() - 1, card)

    def _export(self, kind: str):
        papers = self._db.list_starred()
        if not papers:
            self.toastRequested.emit("收藏夹是空的，先去星标几篇论文吧")
            return
        if kind == "bibtex":
            path, _ = QFileDialog.getSaveFileName(self, "导出 BibTeX", "arxiv-daily.bib", "BibTeX (*.bib)")
            content = export_bibtex(papers)
        else:
            path, _ = QFileDialog.getSaveFileName(self, "导出 Markdown", "arxiv-daily-starred.md", "Markdown (*.md)")
            content = export_markdown(papers, title="ArXiv Daily · 我的收藏")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        self.toastRequested.emit(f"已导出 {len(papers)} 篇到：{path}")
