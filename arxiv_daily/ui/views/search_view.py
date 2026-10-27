"""搜索视图：方向关键词搜索 + 快捷方向 + 订阅为日报主题。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from datetime import date, timedelta

from ...config.settings import Settings
from ...storage.database import PaperRecord
from ...workers import SearchWorker
from ..components.calendar_popup import CalendarPopup
from ..components.icons import calendar_icon, chevron_icon
from ..components.empty_state import EmptyState
from ..components.paper_card import PaperCard

CONTENT_MAX_WIDTH = 960
QUICK_TOPICS = ["大模型推理", "RAG 检索增强", "多模态", "AI Agent", "强化学习", "代码生成"]


class SearchView(QWidget):
    openDetail = Signal(object)
    downloadRequested = Signal(object)
    starToggled = Signal(object, bool)
    toastRequested = Signal(str)
    gotoSettings = Signal()

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._worker: SearchWorker | None = None
        _yesterday = date.today() - timedelta(days=1)
        self._range = (_yesterday, _yesterday)  # (起, 止)，上界=昨天（今日未放榜）
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

        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel("论文搜索")
        title.setObjectName("pageTitle")
        subtitle = QLabel("输入研究方向关键词（中/英文），检索指定日期范围内放榜的 arXiv 论文")
        subtitle.setObjectName("pageSubtitle")
        header.addWidget(title)
        header.addWidget(subtitle)
        layout.addLayout(header)
        layout.addSpacing(4)

        search_row = QHBoxLayout()
        search_row.setSpacing(12)
        self.input = QLineEdit()
        self.input.setObjectName("searchInput")
        self.input.setPlaceholderText("例如：大模型推理优化 / RAG / 多模态对齐 …")
        self.input.returnPressed.connect(self._on_search)
        self.button = QPushButton("搜索")
        self.button.setObjectName("searchButton")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(self._on_search)
        search_row.addWidget(self.input, 1)
        search_row.addWidget(self.button)
        layout.addLayout(search_row)

        # 快捷方向 chips + 订阅当前关键词
        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)
        for topic in QUICK_TOPICS:
            chip = QPushButton(topic)
            chip.setObjectName("ghostButton")
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _=False, t=topic: self.input.setText(t))
            chips_row.addWidget(chip)
        chips_row.addStretch(1)
        subscribe = QPushButton("☆ 订阅为日报主题")
        subscribe.setObjectName("ghostButton")
        subscribe.setCursor(Qt.PointingHandCursor)
        subscribe.clicked.connect(self._subscribe_current)
        chips_row.addWidget(subscribe)
        layout.addLayout(chips_row)

        # 日期过滤（默认今天）：作为 Freshness 交给联网搜索 API
        date_row = QHBoxLayout()
        date_row.setSpacing(6)
        self.prev_day_btn = QPushButton()
        self.prev_day_btn.setIcon(chevron_icon("left", 12))
        self.prev_day_btn.setObjectName("dateNavButton")
        self.prev_day_btn.setCursor(Qt.PointingHandCursor)
        self.prev_day_btn.setFixedSize(36, 34)
        self.prev_day_btn.setToolTip("前一天")
        self.prev_day_btn.clicked.connect(lambda: self._shift_day(-1))
        self.date_btn = QPushButton()
        self.date_btn.setObjectName("secondaryButton")
        self.date_btn.setIcon(calendar_icon(16))
        self.date_btn.setCursor(Qt.PointingHandCursor)
        self.date_btn.setToolTip("选择日期范围：检索该范围内放榜的 arXiv 论文（上界=昨天）")
        self.date_btn.clicked.connect(self._open_calendar)
        self.next_day_btn = QPushButton()
        self.next_day_btn.setIcon(chevron_icon("right", 12))
        self.next_day_btn.setObjectName("dateNavButton")
        self.next_day_btn.setCursor(Qt.PointingHandCursor)
        self.next_day_btn.setFixedSize(36, 34)
        self.next_day_btn.setToolTip("后一天")
        self.next_day_btn.clicked.connect(lambda: self._shift_day(1))
        self.today_btn = QPushButton("回到昨天")
        self.today_btn.setObjectName("ghostButton")
        self.today_btn.setCursor(Qt.PointingHandCursor)
        self.today_btn.clicked.connect(
            lambda: self._set_range(date.today() - timedelta(days=1),
                                    date.today() - timedelta(days=1)))

        for widget in (self.prev_day_btn, self.date_btn, self.next_day_btn, self.today_btn):
            date_row.addWidget(widget)
        date_row.addStretch(1)
        layout.addLayout(date_row)
        self._sync_date_button()

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setObjectName("statusLabel")
        layout.addWidget(self.status)

        self.error = QLabel("")
        self.error.setObjectName("errorLabel")
        self.error.setWordWrap(True)
        self.error.hide()
        layout.addWidget(self.error)

        self.empty = EmptyState("arXiv", "输入方向关键词开始搜索 · 结果按日保存到「历史」")
        layout.addWidget(self.empty, 1)

        self.setup_hint = QWidget()
        setup_layout = QVBoxLayout(self.setup_hint)
        setup_layout.setAlignment(Qt.AlignCenter)
        setup_layout.setSpacing(14)
        hint_text = QLabel("尚未配置联网搜索 API")
        hint_text.setObjectName("hintLabel")
        hint_text.setAlignment(Qt.AlignCenter)
        go_settings = QPushButton("前往设置")
        go_settings.setObjectName("primaryButton")
        go_settings.setCursor(Qt.PointingHandCursor)
        go_settings.clicked.connect(self.gotoSettings.emit)
        setup_layout.addWidget(hint_text)
        setup_layout.addWidget(go_settings)
        self.setup_hint.hide()
        layout.addWidget(self.setup_hint, 1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.hide()
        container = QWidget()
        self.results_layout = QVBoxLayout(container)
        self.results_layout.setContentsMargins(0, 0, 8, 0)
        self.results_layout.setSpacing(14)
        self.results_layout.addStretch(1)
        self.scroll.setWidget(container)
        layout.addWidget(self.scroll, 3)

        self._update_setup_hint()

    # ---- 公共接口 ----
    def reload_settings(self, settings: Settings):
        self._settings = settings
        self._update_setup_hint()

    def focus_input(self):
        self.input.setFocus()

    # ---- 内部 ----
    def _update_setup_hint(self):
        ready = self._settings.search.ready
        self.setup_hint.setVisible(not ready)
        self.empty.setVisible(ready and self.scroll.isHidden())

    def _subscribe_current(self):
        query = self.input.text().strip()
        if not query:
            self.toastRequested.emit("先输入研究方向关键词，再订阅")
            return
        db = self.window().db
        if db.add_topic(query) is None:
            self.toastRequested.emit(f"主题「{query}」已在日报订阅中")
        else:
            self.toastRequested.emit(f"已订阅「{query}」，到「日报」页刷新生效")

    def _on_search(self):
        if not self.input.isEnabled():
            return
        if self._worker is not None and self._worker.isRunning():
            return
        query = self.input.text().strip()
        if not query:
            self._show_error("请输入搜索关键词")
            return
        if not self._settings.search.ready:
            self._show_error("尚未配置联网搜索 API，请先到「设置 → 联网搜索」填写 API Key")
            self.gotoSettings.emit()
            return

        self.error.hide()
        self.empty.hide()
        self.setup_hint.hide()
        self.progress.show()
        self.button.setEnabled(False)
        self.status.setText(f"正在检索 {self._range_label()} 的论文…")
        self._render_papers([])

        self._worker = SearchWorker(
            self._settings, self.window().db, query,
            freshness=self._range_freshness(),
        )
        self._worker.status.connect(self.status.setText)
        self._worker.plan.connect(self._on_plan)
        self._worker.searched.connect(self._on_searched)
        self._worker.paperUpdated.connect(self._on_paper_updated)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.start()

    def _on_plan(self, payload: dict):
        if isinstance(payload, str):
            payload = {"planned_query": payload, "variants": []}
        variants = payload.get("variants") or []
        text = f"LLM 检索式：{payload.get('planned_query', '')}"
        if variants:
            text += f"（+{len(variants)} 变体多路）"
        self.status.setText(text)


    # ---- 日期范围过滤 ----
    def _open_calendar(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self._calendar_popup = CalendarPopup(
            [], self._range[0].isoformat(), self,
            range_mode=True, initial_range=(self._range[0].isoformat(), self._range[1].isoformat()),
            max_date=yesterday,
        )
        self._calendar_popup.dateRangeSelected.connect(
            lambda a, b: self._set_range(date.fromisoformat(a), date.fromisoformat(b))
        )
        self._calendar_popup.show_below(self.date_btn)

    def _set_range(self, start: date, end: date):
        from ...utils.arxiv import normalize_range

        self._range = normalize_range(start, end)
        self._sync_date_button()
        if self.input.text().strip():
            self._on_search()  # 换日期范围即重新检索

    def _shift_day(self, delta: int):

        span = (self._range[1] - self._range[0]).days
        start = self._range[0] + timedelta(days=delta)
        end = start + timedelta(days=span)
        self._set_range(start, end)

    def _sync_date_button(self):
        start, end = self._range
        yesterday = date.today() - timedelta(days=1)
        if end == yesterday and start == yesterday:
            self.date_btn.setText("昨天 ▾")
            self.today_btn.hide()
        elif start == end:
            self.date_btn.setText(f"{start.strftime('%m-%d')} ▾")
            self.today_btn.show()
        else:
            self.date_btn.setText(f"{start.strftime('%m-%d')} ~ {end.strftime('%m-%d')} ▾")
            self.today_btn.show()

    def _range_freshness(self) -> str:
        from ...utils.arxiv import freshness_for_range

        return freshness_for_range(*self._range)

    def _range_label(self) -> str:
        start, end = self._range
        return start.isoformat() if start == end else f"{start.isoformat()} ~ {end.isoformat()}"

    def _stop_worker_if_any(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        self._worker = None

    def _show_error(self, message: str):
        self.error.setText(message)
        self.error.show()

    def _on_searched(self, info: dict):
        version = info.get("version") or ""
        routes = info.get("routes", 1)
        text = f"联网搜索完成：{info.get('count', 0)} 条去重结果"
        if routes > 1:
            text += f"（{routes} 路并发共 {info.get('raw_total', 0)} 条，去重合并）"
        if version:
            text += f" · {version} {info.get('latency_ms', 0)} ms"
        self.status.setText(text)

    def _on_paper_updated(self, rank: int, paper: PaperRecord):
        """LLM 摘要渐进刷新：该位置已有卡片则替换，没有则就地插入。"""
        count = self.results_layout.count()  # 末位是 stretch
        if 0 <= rank < count - 1:
            item = self.results_layout.takeAt(rank)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        card = PaperCard(paper, rank + 1, starred=self.window().db.is_starred(paper.arxiv_id))
        self._wire_card(card)
        self.results_layout.insertWidget(rank, card)
        self.scroll.show()

    def _on_done(self, search_id: int, papers: list):
        self.progress.hide()
        self.button.setEnabled(True)
        self._render_papers(papers)  # 搜索完成：结果直接展示在搜索栏下方
        self.status.setText(f"共 {len(papers)} 篇论文，已保存到历史记录")
        if not papers:
            self._show_error(
                f"{self._range_label()} 没有检索到论文。arXiv 每个工作日更新（北京时间早上），"
                "周末/节假日为空属正常；可扩大日期范围或更换关键词再试。"
            )

    def _on_failed(self, message: str):
        self.progress.hide()
        self.button.setEnabled(True)
        self.status.setText("搜索失败")
        self._show_error(message)

    def _on_cancelled(self):
        self.progress.hide()
        self.button.setEnabled(True)
        self.status.setText("已取消")

    def _render_papers(self, papers: list[PaperRecord]):
        while self.results_layout.count() > 1:
            item = self.results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if papers:
            self.scroll.show()
            self.empty.hide()
            self.setup_hint.hide()
            db = self.window().db
            for rank, paper in enumerate(papers, 1):
                card = PaperCard(paper, rank, starred=db.is_starred(paper.arxiv_id))
                self._wire_card(card)
                self.results_layout.insertWidget(rank - 1, card)
            self.results_layout.addStretch(1)
        else:
            self.scroll.hide()
            self._update_setup_hint()

    def _wire_card(self, card: PaperCard):
        card.opened.connect(self.openDetail.emit)
        card.downloadRequested.connect(self.downloadRequested.emit)
        card.starToggled.connect(self.starToggled.emit)
