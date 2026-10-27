"""今日日报（首页）：主题订阅 + 每日自动归档 + 按日浏览（日历）+ 置顶/移除管理。"""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...config.settings import Settings
from ...services.digest import relax_message
from ...services.library import export_markdown
from ...storage.database import Database, PaperRecord
from ...workers import DigestWorker
from ..components.empty_state import EmptyState
from ..components.paper_card import PaperCard

CONTENT_MAX_WIDTH = 960


class DailyView(QWidget):
    openDetail = Signal(object)
    downloadRequested = Signal(object)
    starToggled = Signal(object, bool)
    toastRequested = Signal(str)
    gotoSettings = Signal()
    openWeekly = Signal()

    def __init__(self, settings: Settings, db: Database, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._db = db
        self._worker: DigestWorker | None = None
        self._refreshed_today = False  # 本次会话是否刷新过今天
        self._today_empty = False      # 今日确认无更新（周末/节假日）→ 禁用刷新
        self._topic_failures = 0
        self._setup_ui()
        self.reload_topics()

    # ---- UI ----
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
        title = QLabel("昨日日报")
        title.setObjectName("pageTitle")
        subtitle = QLabel("订阅研究方向，聚合昨天放榜的最新论文（arXiv 当日论文要等下午，昨日即最新）")
        subtitle.setObjectName("pageSubtitle")
        col.addWidget(title)
        col.addWidget(subtitle)
        header.addLayout(col)
        header.addStretch(1)
        self.weekly_btn = QPushButton("AI 周报")
        self.weekly_btn.setObjectName("secondaryButton")
        self.weekly_btn.setCursor(Qt.PointingHandCursor)
        self.weekly_btn.setToolTip("把近 7 天日报归档交给 LLM 写一篇研究者视角的综述")
        self.weekly_btn.clicked.connect(self._on_weekly)
        header.addWidget(self.weekly_btn)
        self.export_btn = QPushButton("导出昨日 Markdown")
        self.export_btn.setObjectName("secondaryButton")
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.clicked.connect(self._export)
        header.addWidget(self.export_btn)
        self.refresh_btn = QPushButton("刷新昨日日报")
        self.refresh_btn.setObjectName("primaryButton")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.clicked.connect(self._on_refresh)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        # 主题订阅条
        topics_bar = QHBoxLayout()
        topics_bar.setSpacing(8)
        self.chips_holder = QWidget()
        self.chips_layout = QHBoxLayout(self.chips_holder)
        self.chips_layout.setContentsMargins(0, 0, 0, 0)
        self.chips_layout.setSpacing(8)
        topics_bar.addWidget(self.chips_holder, 1)
        self.topic_input = QLineEdit()
        self.topic_input.setPlaceholderText("添加研究方向，如：多模态对齐")
        self.topic_input.setFixedWidth(240)
        self.topic_input.returnPressed.connect(self._add_topic)
        topics_bar.addWidget(self.topic_input)
        add_btn = QPushButton("订阅")
        add_btn.setObjectName("secondaryButton")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._add_topic)
        topics_bar.addWidget(add_btn)
        layout.addLayout(topics_bar)

        self.status = QLabel("")
        self.status.setObjectName("statusLabel")
        layout.addWidget(self.status)

        self.error = QLabel("")
        self.error.setObjectName("errorLabel")
        self.error.setWordWrap(True)
        self.error.hide()
        layout.addWidget(self.error)

        self.empty = QWidget()
        layout.addWidget(self.empty, 1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.hide()
        container = QWidget()
        self.sections = QVBoxLayout(container)
        self.sections.setContentsMargins(0, 0, 8, 0)
        self.sections.setSpacing(18)
        self.sections.addStretch(1)
        self.scroll.setWidget(container)
        layout.addWidget(self.scroll, 4)

    # ---- 主题管理 ----
    def reload_topics(self):
        self._clear_layout(self.chips_layout)
        for topic in self._db.list_topics():
            self.chips_layout.addWidget(self._make_chip(topic))
        self.render_day()

    def _make_chip(self, topic) -> QFrame:
        chip = QFrame()
        chip.setObjectName("topicChip")
        row = QHBoxLayout(chip)
        row.setContentsMargins(14, 5, 6, 5)
        row.setSpacing(2)
        name = QLabel(topic.name)
        name.setObjectName("topicChipName")
        row.addWidget(name)
        close = QPushButton("✕")
        close.setObjectName("topicChipClose")
        close.setCursor(Qt.PointingHandCursor)
        close.setFixedSize(20, 20)
        close.setToolTip("取消订阅（已有归档保留，可按日期回看）")
        close.clicked.connect(lambda _=False, t=topic: self._remove_topic(t))
        row.addWidget(close)
        return chip

    def _add_topic(self):
        name = self.topic_input.text().strip()
        if not name:
            return
        if self._db.add_topic(name) is None:
            self.toastRequested.emit(f"主题「{name}」已订阅过啦")
        else:
            # 新方向未知是否有更新，重新允许刷新尝试
            self._today_empty = False
            self.toastRequested.emit(f"已订阅「{name}」，点「刷新昨日日报」生效")
        self.topic_input.clear()
        self.reload_topics()

    def _remove_topic(self, topic):
        self._db.delete_topic(topic.id)
        self.toastRequested.emit(f"已取消订阅「{topic.name}」")
        self.reload_topics()

    # ---- 渲染当天归档 ----
    def render_day(self):
        # 日报固定展示昨天（最新完整放榜日）
        is_today = True

        # 昨日已确认无更新（周末/节假日）→ 刷新按钮禁用，避免无意义重试
        running = self._worker is not None and self._worker.isRunning()
        if is_today and self._today_empty:
            self.refresh_btn.setEnabled(False)
            self.refresh_btn.setText("昨日没有新论文")
            self.refresh_btn.setToolTip("arXiv 周末/节假日不更新，明天再来吧~")
        else:
            self.refresh_btn.setEnabled(not running)
            self.refresh_btn.setText("刷新中…" if running else "刷新今日日报")
            self.refresh_btn.setToolTip("")

        window = [(date.today() - timedelta(days=1)).isoformat()]
        topics = self._db.list_topics()
        sections = {}
        for t in topics:
            merged, seen = [], set()
            for day in window:
                for paper in self._db.list_digest_day(t.id, day):
                    key = paper.arxiv_id or paper.url
                    if key not in seen:
                        seen.add(key)
                        merged.append(paper)
            sections[t.id] = merged
        total = sum(len(p) for p in sections.values())

        # 重建主体
        self._clear_layout(self.sections)
        self.sections.addStretch(1)
        self._swap_empty()

        if not topics:
            self._set_empty(EmptyState("Daily", "先订阅几个研究方向，再点「刷新昨日日报」"))
            self.scroll.hide()
            return
        if total == 0:
            if is_today and self._refreshed_today:
                self._set_empty(EmptyState("Relax ~", relax_message(day)))
            elif is_today:
                self._set_empty(EmptyState("Daily", "点「刷新昨日日报」获取昨天放榜的新论文"))
            else:
                self._set_empty(EmptyState(day, "这一天没有收藏记录"))
            self.scroll.hide()
            return

        self.empty.hide()
        self.scroll.show()
        self.status.setText(f"昨日 · 共 {total} 篇 · 置顶优先展示")
        for topic in topics:
            papers = sections[topic.id]
            if not papers:
                continue
            header = QHBoxLayout()
            name = QLabel(topic.name)
            name.setObjectName("groupTitle")
            header.addWidget(name)
            meta = QLabel(f"{len(papers)} 篇 · 昨日放榜")
            meta.setObjectName("sectionMeta")
            header.addSpacing(10)
            header.addWidget(meta)
            header.addStretch(1)
            self.sections.addLayout(header)
            for rank, paper in enumerate(papers, 1):
                card = PaperCard(
                    paper, rank,
                    starred=self._db.is_starred(paper.arxiv_id),
                    digest_mode=True,
                    pinned=self._db.is_digest_pinned(topic.id, day, paper.arxiv_id),
                )
                self._wire_card(card, topic.id, day)
                self.sections.addWidget(card)
            self.sections.addSpacing(6)

    def _set_empty(self, widget: EmptyState):
        self._swap_empty(replacement=widget)
        self.status.setText("")

    def _swap_empty(self, replacement: QWidget | None = None):
        old = self.empty.layout()
        if old is not None:
            while old.count():
                item = old.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        if replacement is not None:
            if self.empty.layout() is None:
                self.empty.setLayout(QVBoxLayout(self.empty))
            self.empty.layout().addWidget(replacement)
            self.empty.show()
        else:
            self.empty.hide()

    def _wire_card(self, card: PaperCard, topic_id: int, day: str):
        card.opened.connect(self.openDetail.emit)
        card.downloadRequested.connect(self.downloadRequested.emit)
        card.starToggled.connect(self.starToggled.emit)
        card.pinToggled.connect(
            lambda paper, pinned: self._set_pinned(topic_id, day, paper, pinned)
        )
        card.removeRequested.connect(lambda paper: self._remove_item(topic_id, day, paper))

    def _set_pinned(self, topic_id: int, day: str, paper, pinned: bool):
        self._db.set_digest_pinned(topic_id, day, paper.arxiv_id, pinned)
        self.toastRequested.emit("已置顶" if pinned else "已取消置顶")
        self.render_day()

    def _remove_item(self, topic_id: int, day: str, paper):
        self._db.remove_digest_item(topic_id, day, paper.arxiv_id)
        self.toastRequested.emit(f"已从 {day} 的收藏夹移除「{paper.title[:24]}…」")
        self.render_day()

    # ---- 刷新今日 ----
    def _on_refresh(self):
        topics = self._db.list_topics()
        if not topics:
            self.toastRequested.emit("请先订阅至少一个研究方向")
            return
        if not self._settings.search.ready:
            self.error.setText("尚未配置联网搜索 API，请先到「设置 → 联网搜索」填写 API Key")
            self.error.show()
            self.gotoSettings.emit()
            return
        if self._worker is not None and self._worker.isRunning():
            return

        self.error.hide()
        self._topic_failures = 0
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("刷新中…")
        self.status.setText(f"正在获取 {len(topics)} 个主题昨日放榜的新论文…")

        self._worker = DigestWorker(self._settings, self._db, topics)
        self._worker.topicDone.connect(self._on_topic_done)
        self._worker.topicFailed.connect(self._on_topic_failed)
        self._worker.allDone.connect(self._on_all_done)
        self._worker.start()

    def _on_topic_done(self, topic, papers: list):
        self.status.setText(f"「{topic.name}」昨日 {len(papers)} 篇，已归档")

    def _on_topic_failed(self, topic, message: str):
        self._topic_failures += 1
        self.error.setText(f"「{topic.name}」刷新失败：{message}")
        self.error.show()

    def _on_all_done(self, done: int):
        self._refreshed_today = True
        window = [(date.today() - timedelta(days=1)).isoformat()]
        topics = self._db.list_topics()
        total = sum(
            len({p.arxiv_id or p.url for day in window
                 for p in self._db.list_digest_day(t.id, day)})
            for t in topics
        )
        # 所有主题都正常返回但今日无任何归档 → 确认"今日无更新"，禁用刷新按钮
        if total == 0 and self._topic_failures == 0:
            self._today_empty = True
        self.render_day()

    # ---- 导出 ----
    # ---- AI 周报 ----
    def _on_weekly(self):
        self.openWeekly.emit()

    def _export(self):
        day = date.today().isoformat()
        topics = self._db.list_topics()
        sections = {t.name: self._db.list_digest_day(t.id, day) for t in topics}
        total = sum(len(p) for p in sections.values())
        if not total:
            self.toastRequested.emit("昨天没有可导出的收藏")
            return
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self, "导出日报", f"arxiv-daily-{day}.md", "Markdown (*.md)"
        )
        if not path:
            return
        markdown = export_markdown([], title=f"ArXiv Daily · {day}", sections=sections)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(markdown)
        self.toastRequested.emit(f"已导出：{path}")

    # ---- 工具 ----
    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def stop_worker(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        self._worker = None
