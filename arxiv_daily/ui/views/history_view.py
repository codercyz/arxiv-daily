"""历史视图（主从分栏）：左侧搜索历史列表，点击切换右侧论文卡片。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...storage.database import Database, SearchRecord
from ..components.empty_state import EmptyState
from ..components.paper_card import PaperCard
from ..transitions import fade_in


class HistoryView(QWidget):
    openDetail = Signal(object)
    downloadRequested = Signal(object)
    starToggled = Signal(object, bool)
    toastRequested = Signal(str)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self._db = db
        self._selected: SearchRecord | None = None
        self._setup_ui()

    def _setup_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(36, 28, 36, 24)
        outer.setSpacing(16)

        # ---- 左侧：历史列表 ----
        left = QFrame()
        left.setObjectName("historyPanel")
        left.setFixedWidth(300)
        left_col = QVBoxLayout(left)
        left_col.setContentsMargins(12, 12, 12, 12)
        left_col.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("搜索历史")
        title.setObjectName("groupTitle")
        head.addWidget(title)
        head.addStretch(1)
        refresh = QPushButton("刷新")
        refresh.setObjectName("ghostButton")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self.refresh)
        head.addWidget(refresh)
        left_col.addLayout(head)

        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QFrame.NoFrame)
        list_container = QWidget()
        self.list_layout = QVBoxLayout(list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(6)
        self.list_layout.addStretch(1)
        self.list_scroll.setWidget(list_container)
        left_col.addWidget(self.list_scroll, 1)
        outer.addWidget(left)

        # ---- 右侧：所选记录的论文卡片 ----
        right = QWidget()
        right_col = QVBoxLayout(right)
        right_col.setContentsMargins(4, 0, 0, 0)
        right_col.setSpacing(10)

        self.detail_head = QWidget()
        head_col = QVBoxLayout(self.detail_head)
        head_col.setSpacing(4)
        self.detail_query = QLabel("")
        self.detail_query.setObjectName("cardTitle")
        self.detail_query.setStyleSheet("font-size:17px; font-weight:600;")
        self.detail_query.setWordWrap(True)
        self.detail_meta = QLabel("")
        self.detail_meta.setObjectName("cardMeta")
        head_row = QHBoxLayout()
        head_row_col = QVBoxLayout()
        head_row_col.setSpacing(4)
        head_row_col.addWidget(self.detail_query)
        head_row_col.addWidget(self.detail_meta)
        head_row.addLayout(head_row_col, 1)
        self.delete_btn = QPushButton("删除此记录")
        self.delete_btn.setObjectName("ghostButton")
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.clicked.connect(self._delete_selected)
        head_row.addWidget(self.delete_btn, 0, Qt.AlignTop)
        head_col.addLayout(head_row)
        self.detail_head.hide()
        right_col.addWidget(self.detail_head)

        self.right_empty = EmptyState("History", "点击左侧任意一条记录，这里会展示当次的论文结果")
        right_col.addWidget(self.right_empty, 1)

        self.papers_scroll = QScrollArea()
        self.papers_scroll.setWidgetResizable(True)
        self.papers_scroll.setFrameShape(QFrame.NoFrame)
        self.papers_scroll.hide()
        papers_container = QWidget()
        self.papers_layout = QVBoxLayout(papers_container)
        self.papers_layout.setContentsMargins(0, 0, 8, 0)
        self.papers_layout.setSpacing(14)
        self.papers_layout.addStretch(1)
        self.papers_scroll.setWidget(papers_container)
        right_col.addWidget(self.papers_scroll, 4)

        outer.addWidget(right, 1)

        self.left_empty = EmptyState("Empty", "暂无搜索历史，去「搜索」页发起第一次搜索吧")
        self.left_empty.hide()
        outer.addWidget(self.left_empty, 1)
        left.hide()

    # ---- 数据 ----
    def refresh(self):
        records = self._db.list_searches()
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not records:
            self.left_empty.show()
            self.left_empty.setSizePolicy(self.left_empty.sizePolicy())
            self.list_scroll.parentWidget().hide()
            self.detail_head.hide()
            self.papers_scroll.hide()
            self.right_empty.set_texts("History", "暂无搜索历史")
            self.right_empty.show()
            self._selected = None
            return
        self.left_empty.hide()
        self.list_scroll.parentWidget().show()
        for record in records:
            row = HistoryRow(record, self)
            if self._selected is not None and record.id == self._selected.id:
                row.set_selected(True)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
        if self._selected is None or not any(r.id == (self._selected and self._selected.id) for r in records):
            if self._selected is not None:
                self._clear_right()
                self._selected = None

    def _view(self, record: SearchRecord):
        if self._selected is not None and record.id == self._selected.id:
            return
        self._selected = record
        for i in range(self.list_layout.count() - 1):
            item = self.list_layout.itemAt(i)
            row = item.widget() if item else None
            if isinstance(row, HistoryRow):
                row.set_selected(row.record.id == record.id)

        papers = self._db.get_papers(record.id)
        self.detail_query.setText(record.query)
        self.detail_meta.setText(
            f"{record.searched_at.replace('T', '  ')} · {record.result_count} 条结果"
            + (" · AI 摘要" if record.llm_used else "")
        )
        self.detail_head.show()
        self.right_empty.hide()
        self.delete_btn.setEnabled(True)

        while self.papers_layout.count() > 1:
            item = self.papers_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        db = self.window().db
        for rank, paper in enumerate(papers, 1):
            card = PaperCard(paper, rank, starred=db.is_starred(paper.arxiv_id))
            card.opened.connect(self.openDetail.emit)
            card.downloadRequested.connect(self.downloadRequested.emit)
            card.starToggled.connect(self.starToggled.emit)
            self.papers_layout.insertWidget(self.papers_layout.count() - 1, card)
        self.papers_scroll.show()
        fade_in(self.papers_scroll, duration=180)  # 切换记录时右侧淡入过渡

    def _clear_right(self):
        self.detail_head.hide()
        self.papers_scroll.hide()
        self.right_empty.set_texts("History", "点击左侧任意一条记录，这里会展示当次的论文结果")
        self.right_empty.show()

    def _delete_record(self, record: SearchRecord):
        self._db.delete_search(record.id)
        if self._selected is not None and record.id == self._selected.id:
            self._selected = None
            self._clear_right()
        self.toastRequested.emit("已删除该条历史记录")
        self.refresh()

    def _delete_selected(self):
        if self._selected is not None:
            self._delete_record(self._selected)


class HistoryRow(QFrame):
    def __init__(self, record: SearchRecord, page: HistoryView, parent=None):
        super().__init__(parent)
        self.record = record
        self._page = page
        self.setObjectName("histItem")
        self.setCursor(Qt.PointingHandCursor)
        self._selected = False

        col = QVBoxLayout(self)
        col.setContentsMargins(14, 10, 8, 10)
        col.setSpacing(3)
        _q = record.query.strip()
        query = QLabel(_q if len(_q) <= 40 else _q[:40].rstrip() + "…")
        query.setObjectName("histItemQuery")
        query.setWordWrap(True)
        col.addWidget(query)
        self._query_label = query

        self._meta_labels = []
        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        for text in ([record.searched_at.replace("T", " "), f"{record.result_count} 篇"]
                     + (["AI"] if record.llm_used else [])):
            label = QLabel(text)
            label.setObjectName("histItemMeta")
            meta_row.addWidget(label)
            self._meta_labels.append(label)
        meta_row.addStretch(1)
        self._delete_btn = QPushButton("✕")
        self._delete_btn.setObjectName("histItemDelete")
        self._delete_btn.setCursor(Qt.PointingHandCursor)
        self._delete_btn.setFixedSize(24, 24)
        self._delete_btn.setToolTip("删除这条记录")
        self._delete_btn.clicked.connect(lambda: page._delete_record(record))
        meta_row.addWidget(self._delete_btn)
        col.addLayout(meta_row)

    def set_selected(self, selected: bool):
        self._selected = selected
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        # 文字颜色代码直控：QSS 后代选择器在父属性变化时不会重刷子控件
        self._query_label.setStyleSheet(
            "color:#FDFDFC;" if selected else "color:#2E2E2C;"
        )
        meta_color = "#BDBDB8" if selected else "#ABABA6"
        for label in self._meta_labels:
            label.setStyleSheet(f"color:{meta_color};")
        self._delete_btn.setStyleSheet("color:#8A8A86;" if selected else "color:#B8B8B3;")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._page._view(self.record)
        super().mousePressEvent(event)
