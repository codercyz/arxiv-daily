"""AI 周报视图：独立页面（全页文档模式）。

渲染链路：LLM 输出 Markdown → markdown 库解析为 HTML → 注入排版 CSS →
QTextBrowser 富文本渲染。CSS 数值刻意比 Qt 默认段距（12px）拉开明显差距。
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

from ...config.settings import Settings
from ...storage.database import Database

CONTENT_MAX_WIDTH = 960

DOC_CSS = """
    p { color: #2E2E2C; margin: 0 0 18px 0; }
    h1 { color: #111110; font-size: 20px; font-weight: 700; margin: 6px 0 16px 0; }
    h2 { color: #111110; font-size: 18px; font-weight: 700; margin: 34px 0 14px 0; }
    h3 { color: #111110; font-size: 17px; font-weight: 700; margin: 34px 0 14px 0; }
    h4 { color: #55554F; font-size: 14px; font-weight: 600; margin: 20px 0 10px 0; }
    strong { color: #111110; }
    em { color: #55554F; }
    ul { margin: 0 0 18px 0; }
    li { color: #2E2E2C; margin: 0 0 10px 0; }
    blockquote { color: #6B6B66; margin: 0 0 18px 10px; }
    code { color: #44443F; background-color: #F4F4F2; font-family: Consolas, monospace; }
    a { color: #111110; }
"""


class WeeklyView(QWidget):
    backRequested = Signal()

    def __init__(self, settings: Settings, db: Database, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._db = db
        self._worker = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        content = QWidget()
        content.setMaximumWidth(CONTENT_MAX_WIDTH)
        outer.addWidget(content, 100)
        outer.addStretch(1)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(36, 28, 36, 24)
        layout.setSpacing(10)

        header = QHBoxLayout()
        back = QPushButton("← 返回日报")
        back.setObjectName("secondaryButton")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.backRequested.emit)
        header.addWidget(back)
        header.addStretch(1)
        self.regen_btn = QPushButton("重新生成")
        self.regen_btn.setObjectName("secondaryButton")
        self.regen_btn.setCursor(Qt.PointingHandCursor)
        self.regen_btn.clicked.connect(lambda: self._generate(force=True))
        header.addWidget(self.regen_btn)
        layout.addLayout(header)

        self.title = QLabel("AI 周报 · 近 7 天论文综述")
        self.title.setObjectName("pageTitle")
        layout.addWidget(self.title)
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("pageSubtitle")
        layout.addWidget(self.subtitle)

        self.status = QLabel("")
        self.status.setObjectName("statusLabel")
        layout.addWidget(self.status)

        # QTextBrowser 自带滚动，直接铺满即全页文档
        self.body = QTextBrowser()
        self.body.setObjectName("weeklyBody")
        self.body.setOpenExternalLinks(True)
        layout.addWidget(self.body, 1)

    # ---- 展示与生成 ----
    def show_weekly(self):
        """进入页面：缓存命中直接渲染，否则自动生成。"""
        from ...services.weekly import week_start

        cached = self._db.get_weekly_report(week_start())
        if cached:
            self._render(cached)
            self.status.setText("本周已生成过，直接展示缓存")
            return
        self._generate(force=False)

    def _render(self, content: str):
        import markdown as md_lib

        from ...services.weekly import week_start

        ws = week_start()
        end = (date.fromisoformat(ws) + timedelta(days=6)).isoformat()
        self.subtitle.setText(f"{ws} ~ {end} · 订阅方向 7 天归档 · LLM 综述，按周缓存")
        html = md_lib.markdown(content, extensions=["tables", "sane_lists"])
        # 节标题注入黑白风装饰符；首个标题压掉顶部大间距
        html = re.sub(r"<h([34])>", r"<h\1>▍ ", html)
        html = re.sub(r"<h3>", "<h3 style='margin-top:4px'>", html, count=1)
        self.body.document().setDefaultStyleSheet(DOC_CSS.strip())
        self.body.setHtml(html)
        self.body.verticalScrollBar().setValue(0)

    def _generate(self, *, force: bool):
        if self._worker is not None and self._worker.isRunning():
            return
        if not (self._settings.llm.ready and self._settings.llm.enabled):
            self.status.setText("")
            self.body.setHtml(
                "<p><strong>未配置 LLM，无法生成周报。</strong></p>"
                "<p>到「设置 → LLM 增强」填好 API 信息，再从日报页点「AI 周报」进来。"
                "生成一次即缓存，本周内随时可看。</p>")
            return
        self.status.setText("正在阅读近 7 天的论文归档…通常 20~40 秒")
        self.body.setHtml(
            "<p>正在阅读近 7 天的论文归档…</p>"
            "<p>综合判断本周的创新点与细分方向中，通常需要 20~40 秒。</p>")
        settings = self._settings
        db = self._db

        def job():
            from ...llm.client import LLMClient
            from ...services.weekly import generate_weekly

            client = LLMClient(settings.llm, proxy=settings.network.live_proxy())
            return generate_weekly(db, client, force=force)

        from ...workers import FuncWorker

        self._worker = FuncWorker(job)
        self._worker.finished_ok.connect(self._on_ok)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_ok(self, content: str):
        self.status.setText("")
        self._render(content)

    def _on_failed(self, message: str):
        self.status.setText("")
        self.body.setHtml(f"<p><strong>周报生成失败</strong></p><p>{message}</p>")
