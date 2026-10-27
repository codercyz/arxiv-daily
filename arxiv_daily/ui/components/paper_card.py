"""论文结果卡片：标题 / 时间 / 一句话摘要 / 关键词气泡 / 星标 / 下载。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ...storage.database import PaperRecord


class PaperCard(QFrame):
    opened = Signal(object)             # PaperRecord
    downloadRequested = Signal(object)  # PaperRecord
    starToggled = Signal(object, bool)  # (PaperRecord, starred)
    pinToggled = Signal(object, bool)   # (PaperRecord, pinned)  日报收藏夹模式
    removeRequested = Signal(object)    # PaperRecord            日报收藏夹模式

    def __init__(self, paper: PaperRecord, rank: int, starred: bool = False,
                 digest_mode: bool = False, pinned: bool = False, parent=None):
        super().__init__(parent)
        self._paper = paper
        self._digest_mode = digest_mode
        self.setCursor(Qt.PointingHandCursor)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(17, 17, 17, 22))
        self.setGraphicsEffect(shadow)
        self._shadow = shadow  # hover 动画目标

        root = QHBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 16)
        root.setSpacing(16)

        rank_label = QLabel(f"{rank:02d}")
        rank_label.setObjectName("cardRank")
        rank_label.setFixedWidth(54)
        root.addWidget(rank_label, 0, Qt.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(7)

        title_label = QLabel(PaperCard.truncate_title(paper.title or "(未命名)"))
        title_label.setObjectName("cardTitle")
        title_label.setWordWrap(True)
        title_label.setMaximumHeight(46)
        body.addWidget(title_label)

        meta_bits = []
        if paper.published_date:
            meta_bits.append(paper.published_date)
        if paper.arxiv_id:
            meta_bits.append(f"arXiv:{paper.arxiv_id}")
        if paper.enriched:
            meta_bits.append("AI 摘要")
        meta = QLabel("  ·  ".join(meta_bits) or "—")
        meta.setObjectName("cardMeta")
        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        meta_row.addWidget(meta)
        if digest_mode and pinned:
            badge = QLabel("📌 置顶")
            badge.setObjectName("historyBadge")
            meta_row.addWidget(badge)
        meta_row.addStretch(1)
        body.addLayout(meta_row)

        summary = QLabel(paper.one_line_summary or paper.passage or "暂无摘要（配置 LLM 可自动生成中文摘要）")
        summary.setObjectName("cardSummary")
        summary.setWordWrap(True)
        summary.setMaximumHeight(46)
        body.addWidget(summary)

        if paper.keywords:
            tags = QHBoxLayout()
            tags.setSpacing(8)
            for keyword in paper.keywords[:5]:
                chip = QLabel(keyword)
                chip.setObjectName("tagBubble")
                tags.addWidget(chip)
            tags.addStretch(1)
            body.addLayout(tags)

        body.addSpacing(2)
        actions = QHBoxLayout()
        self.star_button = QPushButton("★" if starred else "☆")
        self.star_button.setObjectName("starButton")
        self.star_button.setCheckable(True)
        self.star_button.setChecked(starred)
        self.star_button.setCursor(Qt.PointingHandCursor)
        self.star_button.setToolTip("收藏到「收藏」页")
        self.star_button.clicked.connect(
            lambda checked: self.starToggled.emit(self._paper, checked)
        )
        self.star_button.toggled.connect(
            lambda checked: self.star_button.setText("★" if checked else "☆")
        )
        actions.addWidget(self.star_button)

        if digest_mode:
            self.pin_button = QPushButton("已置顶" if pinned else "置顶")
            self.pin_button.setObjectName("ghostButton")
            self.pin_button.setCheckable(True)
            self.pin_button.setChecked(pinned)
            self.pin_button.setCursor(Qt.PointingHandCursor)
            self.pin_button.toggled.connect(
                lambda checked: self.pin_button.setText("已置顶" if checked else "置顶")
            )
            self.pin_button.clicked.connect(
                lambda checked: self.pinToggled.emit(self._paper, checked)
            )
            remove_button = QPushButton("移除")
            remove_button.setObjectName("ghostButton")
            remove_button.setCursor(Qt.PointingHandCursor)
            remove_button.setToolTip("从这一天的收藏夹移除（不影响其他日期）")
            remove_button.clicked.connect(lambda: self.removeRequested.emit(self._paper))
            actions.addWidget(remove_button)
            actions.addStretch(1)
            actions.addWidget(self.pin_button)
        else:
            actions.addStretch(1)

        download = QPushButton("下载 PDF")
        download.setObjectName("cardDownload")
        download.setCursor(Qt.PointingHandCursor)
        download.clicked.connect(lambda: self.downloadRequested.emit(self._paper))
        actions.addWidget(download)
        body.addLayout(actions)

        root.addLayout(body, 1)

    @staticmethod
    def truncate_title(text: str, limit: int = 110) -> str:
        """超长标题截断加省略号；阈值按卡片双行展示容量取 110 字符。"""
        text = text.strip()
        return text if len(text) <= limit else text[:limit].rstrip() + "…"

    def paper(self) -> PaperRecord:
        return self._paper

    def set_starred(self, starred: bool):
        self.star_button.blockSignals(True)
        self.star_button.setChecked(starred)
        self.star_button.setText("★" if starred else "☆")
        self.star_button.blockSignals(False)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.opened.emit(self._paper)
        super().mousePressEvent(event)

    # ---- hover 交互：阴影平滑抬升（150ms） ----
    def _animate_shadow(self, blur: int, dy: float):
        from PySide6.QtCore import (
            QEasingCurve,
            QPointF,
            QPropertyAnimation,
        )

        anim_blur = QPropertyAnimation(self._shadow, b"blurRadius", self)
        anim_blur.setDuration(150)
        anim_blur.setEndValue(blur)
        anim_blur.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim_blur.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

        anim_offset = QPropertyAnimation(self._shadow, b"offset", self)
        anim_offset.setDuration(150)
        anim_offset.setEndValue(QPointF(0, dy))
        anim_offset.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim_offset.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def enterEvent(self, event):
        self._animate_shadow(44, 16)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_shadow(32, 10)
        super().leaveEvent(event)
