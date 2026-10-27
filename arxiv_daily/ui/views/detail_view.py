"""论文详情视图：分区卡片（信息/摘要/链接）+ PDF 预览。

- 各分区独立圆角卡片包裹；链接为行式条目（点击整行跳转，规避富文本锚点转义问题）
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...storage.database import Database, PaperRecord
from ...workers import FetchDetailWorker, FuncWorker

CONTENT_MAX_WIDTH = 960


class LinkRow(QFrame):
    """行式链接条目：来源徽标 + 标题，点击整行用系统浏览器打开。"""

    def __init__(self, site: str, title: str, url: str, parent=None):
        super().__init__(parent)
        self._url = url
        self.setObjectName("linkRow")
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)
        badge = QLabel((site or "网页")[:10])
        badge.setObjectName("linkRowSite")
        row.addWidget(badge)
        text = QLabel(title)
        text.setObjectName("linkRowTitle")
        text.setWordWrap(True)
        row.addWidget(text, 1)
        arrow = QLabel("↗")
        arrow.setObjectName("linkRowArrow")
        row.addWidget(arrow)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._url:
            QDesktopServices.openUrl(QUrl(self._url))
        super().mousePressEvent(event)


class DetailView(QWidget):
    backRequested = Signal()
    downloadRequested = Signal(object)
    starToggled = Signal(object, bool)

    def __init__(self, settings, db: Database, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._db = db
        self._paper: PaperRecord | None = None
        self._fetch_worker: FetchDetailWorker | None = None
        self._pdf_download_worker = None
        self._show_zh = False
        self._translate_worker = None
        self._setup_ui()

    # ---------- UI ----------
    def _setup_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        content = QWidget()
        content.setMaximumWidth(CONTENT_MAX_WIDTH)
        outer.addWidget(content, 100)
        outer.addStretch(1)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(36, 24, 36, 22)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(10)
        back = QPushButton("←  返回")
        back.setObjectName("secondaryButton")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.backRequested.emit)
        top.addWidget(back)
        top.addStretch(1)
        self.star_btn = QPushButton("☆")
        self.star_btn.setObjectName("starButton")
        self.star_btn.setCheckable(True)
        self.star_btn.setCursor(Qt.PointingHandCursor)
        self.star_btn.setToolTip("收藏")
        self.star_btn.toggled.connect(lambda c: self.star_btn.setText("★" if c else "☆"))
        self.star_btn.clicked.connect(
            lambda: self.starToggled.emit(self._paper, self.star_btn.isChecked())
        )
        top.addWidget(self.star_btn)
        self.fetch_btn = QPushButton("获取完整信息")
        self.fetch_btn.setObjectName("secondaryButton")
        self.fetch_btn.setCursor(Qt.PointingHandCursor)
        self.fetch_btn.clicked.connect(self._on_fetch)
        top.addWidget(self.fetch_btn)
        self.pdf_btn = QPushButton("预览 PDF")
        self.pdf_btn.setObjectName("secondaryButton")
        self.pdf_btn.setCursor(Qt.PointingHandCursor)
        self.pdf_btn.clicked.connect(self._on_preview_pdf)
        top.addWidget(self.pdf_btn)
        self.download_btn = QPushButton("下载 PDF")
        self.download_btn.setObjectName("primaryButton")
        self.download_btn.setCursor(Qt.PointingHandCursor)
        self.download_btn.clicked.connect(self._on_download)
        top.addWidget(self.download_btn)
        layout.addLayout(top)

        self.status = QLabel("")
        self.status.setObjectName("statusLabel")
        layout.addWidget(self.status)

        body_host = QWidget()
        body = QVBoxLayout(body_host)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)

        # 卡 1：标题与元信息
        info_card = QFrame()
        info_card.setObjectName("detailCard")
        info = QVBoxLayout(info_card)
        info.setContentsMargins(22, 18, 22, 16)
        info.setSpacing(8)
        self.title = QLabel("")
        self.title.setObjectName("cardTitle")
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size:19px; font-weight:600;")
        info.addWidget(self.title)
        self.meta = QLabel("")
        self.meta.setObjectName("cardMeta")
        self.meta.setWordWrap(True)
        info.addWidget(self.meta)
        self.tags_row = QHBoxLayout()
        self.tags_row.setSpacing(8)
        info.addLayout(self.tags_row)
        body.addWidget(info_card)

        # 卡 2：摘要（中英切换，译文按篇持久化）
        abstract_card, abstract_layout = self._section_card()
        head_row = QHBoxLayout()
        head_label = QLabel("摘要")
        head_label.setObjectName("groupTitle")
        head_row.addWidget(head_label)
        head_row.addStretch(1)
        self.translate_btn = QPushButton("中文")
        self.translate_btn.setObjectName("secondaryButton")
        self.translate_btn.setCursor(Qt.PointingHandCursor)
        self.translate_btn.setToolTip("LLM 翻译为中文（翻译一次即缓存，之后随时切换）")
        self.translate_btn.clicked.connect(self._on_toggle_abstract)
        head_row.addWidget(self.translate_btn)
        abstract_layout.addLayout(head_row)
        self.abstract = QLabel("")
        self.abstract.setObjectName("cardSummary")
        self.abstract.setWordWrap(True)
        self.abstract.setTextInteractionFlags(Qt.TextSelectableByMouse)
        from PySide6.QtWidgets import QSizePolicy

        self.abstract.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
        self.abstract.setAlignment(Qt.AlignTop)
        abstract_layout.addWidget(self.abstract)
        body.addWidget(abstract_card)

        # 卡 4：代码仓库（元宝 Site=github.com 召回 + LLM 精判官方实现）
        repo_card, repo_layout = self._section_card("代码仓库")
        self.repo_card = repo_card
        self.repo_status = QLabel("")
        self.repo_status.setObjectName("statusLabel")
        repo_layout.addWidget(self.repo_status)
        self.repo_box = QVBoxLayout()
        repo_layout.addLayout(self.repo_box)
        body.addWidget(repo_card)
        repo_card.hide()

        # 卡 5：链接
        links_card, links_layout = self._section_card("链接")
        self.links_box = QVBoxLayout()
        links_layout.addLayout(self.links_box)
        body.addWidget(links_card)

        body.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidget(body_host)
        layout.addWidget(self.scroll, 1)

    def _section_card(self, title: str | None = None):
        card = QFrame()
        card.setObjectName("detailCard")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(22, 16, 22, 14)
        inner.setSpacing(8)
        if title:
            label = QLabel(title)
            label.setObjectName("groupTitle")
            inner.addWidget(label)
        return card, inner

    # ---------- 展示 ----------
    def show_paper(self, paper: PaperRecord):
        self._paper = paper
        _t = (paper.title or "(未命名)").strip()
        self.title.setText(_t if len(_t) <= 160 else _t[:160].rstrip() + "…")
        meta_bits = []
        if paper.published_date:
            meta_bits.append(f"发布时间：{paper.published_date}")
        if paper.arxiv_id:
            meta_bits.append(f"arXiv:{paper.arxiv_id}")
        if paper.authors:
            meta_bits.append("作者：" + ", ".join(paper.authors[:12]) + (" 等" if len(paper.authors) > 12 else ""))
        meta_bits.append("AI 摘要" if paper.enriched else "搜索摘要")
        self.meta.setText("  ·  ".join(meta_bits))

        while self.tags_row.count():
            item = self.tags_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for keyword in (paper.keywords or [])[:6]:
            chip = QLabel(keyword)
            chip.setObjectName("tagBubble")
            self.tags_row.addWidget(chip)
        self.tags_row.addStretch(1)

        abstract_text = (
            paper.full_abstract
            or paper.passage
            or paper.content
            or paper.one_line_summary
            or "暂无摘要，可点击「获取完整信息」从 arXiv 拉取。"
        )
        self.abstract.setText(abstract_text)

        while self.links_box.count():
            item = self.links_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if paper.url:
            self.links_box.addWidget(LinkRow("arXiv", "论文页面（abstract）", paper.url))
        if paper.pdf_url:
            self.links_box.addWidget(LinkRow("PDF", "PDF 全文下载页", paper.pdf_url))

        starred = self._db.is_starred(paper.arxiv_id)
        self.star_btn.blockSignals(True)
        self.star_btn.setChecked(starred)
        self.star_btn.setText("★" if starred else "☆")
        self.star_btn.blockSignals(False)
        self.download_btn.setEnabled(bool(paper.pdf_url))
        self.pdf_btn.setEnabled(bool(paper.pdf_url or paper.url))
        if paper.detail_fetched:
            self.fetch_btn.setText("已获取完整信息")
            self.fetch_btn.setEnabled(False)
        else:
            self.fetch_btn.setText("获取完整信息")
            self.fetch_btn.setEnabled(bool(paper.arxiv_id))
        self.status.setText("")

        self._render_repos()
        self._maybe_fetch_repo()
        self._maybe_autofetch_detail()  # 默认展示完整摘要：无全文时自动直连 arXiv 拉取

    # ---------- 代码仓库发现 ----------
    def _render_repos(self):
        while self.repo_box.count():
            item = self.repo_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        paper = self._paper
        if paper is None or paper.repo is None:
            self.repo_card.hide()
            self.repo_status.setText("")
            return
        self.repo_card.show()
        if not paper.repo:
            self.repo_status.setText("未找到相关代码仓库")
            return
        self.repo_status.setText("")
        for repo in paper.repo:
            site = "★ 可能官方" if repo.get("official") else "GitHub"
            title = repo["name"] + (f" · {repo['desc']}" if repo.get("desc") else "")
            self.repo_box.addWidget(LinkRow(site, title, repo["url"]))

    def _maybe_fetch_repo(self):
        paper = self._paper
        if paper is None or not paper.arxiv_id or paper.repo is not None:
            return  # 已有结果（含"搜过没有"）不再消耗配额
        if not self._settings.search.ready or not getattr(self._settings.search, "find_repo", True):
            return
        if getattr(self, "_repo_worker", None) is not None:
            old, self._repo_worker = self._repo_worker, None
            if old.isRunning():
                for sig in (old.finished_ok, old.failed):
                    try:
                        sig.disconnect()
                    except (RuntimeError, TypeError):
                        pass
        self.repo_card.show()
        self.repo_status.setText("正在查找官方代码仓库…")
        pid = paper.arxiv_id

        def job():
            from ...search.yuanbao import get_provider
            from ...services.repo import find_repos

            provider = get_provider(self._settings.search, proxy=self._settings.network.live_proxy())
            return find_repos(provider, paper)

        self._repo_worker = FuncWorker(job)
        self._repo_worker.finished_ok.connect(lambda repos: self._on_repos(repos, pid))
        self._repo_worker.failed.connect(lambda _msg: self._on_repo_failed(pid))
        self._repo_worker.start()

    def _on_repos(self, repos: list, pid: str):
        if self._paper is None or self._paper.arxiv_id != pid:
            return  # 论文已切换，迟到结果丢弃
        self._paper.repo = repos or []
        if self._db.get_paper(self._paper.arxiv_id) is None:
            self._db.upsert_papers([self._paper])
        else:
            self._db.update_paper(self._paper)
        self._render_repos()

    def _on_repo_failed(self, pid: str):
        if self._paper is None or self._paper.arxiv_id != pid:
            return
        self.repo_status.setText("代码仓库查找失败，稍后再进此页重试")

    # ---------- 摘要中英切换 ----------
    def _displayed_abstract_en(self) -> str:
        paper = self._paper
        return (
            paper.full_abstract
            or paper.passage
            or paper.content
            or paper.one_line_summary
            or ""
        )

    def _on_toggle_abstract(self):
        if self._paper is None:
            return
        if self._show_zh:
            self._show_zh = False
            self.translate_btn.setText("中文")
            self.abstract.setText(self._displayed_abstract_en())
            return
        # → 中文：有缓存直接切；无缓存且 LLM 可用则按需翻译并持久化
        if self._paper.abstract_zh:
            self._show_zh = True
            self.translate_btn.setText("原文")
            self.abstract.setText(self._paper.abstract_zh)
            return
        if not (self._settings.llm.ready and self._settings.llm.enabled):
            self.status.setText("未配置 LLM，无法翻译摘要（可在「设置 → LLM 增强」配置）")
            return
        if getattr(self, "_translate_worker", None) is not None and self._translate_worker.isRunning():
            return
        self.translate_btn.setEnabled(False)
        self.translate_btn.setText("翻译中…")
        paper = self._paper
        text = self._displayed_abstract_en()

        from ...llm.client import LLMClient
        from ...workers import FuncWorker

        client = LLMClient(self._settings.llm, proxy=self._settings.network.live_proxy())

        def translate() -> str:
            return client.chat(
                "你是学术翻译。把给出的论文摘要忠实流畅地翻译为中文："
                "保留专业术语的英文缩写（如 LLM/RAG），其余译为中文，"
                "不增删内容，不添加解释，只输出译文正文。",
                text,
                max_tokens=1200,
            )

        self._translate_worker = FuncWorker(translate)
        self._translate_worker.finished_ok.connect(self._on_translated)
        self._translate_worker.failed.connect(self._on_translate_failed)
        self._translate_worker.start()

    def _on_translated(self, zh: str):
        self.translate_btn.setEnabled(True)
        zh = (zh or "").strip()
        if not zh or self._paper is None:
            self.translate_btn.setText("中文")
            self.status.setText("翻译失败，请重试")
            return
        self._paper.abstract_zh = zh
        # 持久化（行不存在则补插，保证关软件不丢）
        if self._paper.arxiv_id:
            if self._db.get_paper(self._paper.arxiv_id) is None:
                self._db.upsert_papers([self._paper])
            else:
                self._db.update_paper(self._paper)
        self._show_zh = True
        self.translate_btn.setText("原文")
        self.abstract.setText(zh)
        self.status.setText("已翻译并保存，之后可随时切换")

    def _on_translate_failed(self, message: str):
        self.translate_btn.setEnabled(True)
        self.translate_btn.setText("中文")
        self.status.setText(f"翻译失败：{message[:60]}")

    # ---------- PDF 预览 ----------
    def _on_preview_pdf(self):
        if self._paper is None:
            return
        cache_dir = Path.home() / ".arxiv_daily" / "pdfcache"
        pdf_path = cache_dir / f"{self._paper.arxiv_id or 'paper'}.pdf"
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            self._open_pdf_viewer(pdf_path)
            return
        self.status.setText("正在下载 PDF 以供预览…")
        from ...downloader import download_pdf
        from ...workers import FuncWorker
        paper = self._paper
        proxy = self._settings.network.live_proxy()

        def fetch_pdf() -> Path:
            url = paper.pdf_url or f"https://arxiv.org/pdf/{paper.arxiv_id}"
            return download_pdf(
                url,
                arxiv_id=paper.arxiv_id or "paper",
                title=paper.title,
                dest_dir=cache_dir,
                filename=pdf_path.name,
                timeout=180,
                proxy=proxy,
            )

        self._pdf_download_worker = FuncWorker(fetch_pdf)
        self._pdf_download_worker.finished_ok.connect(self._open_pdf_viewer)
        self._pdf_download_worker.failed.connect(
            lambda msg: self.status.setText(f"PDF 下载失败：{msg}")
        )
        self._pdf_download_worker.start()

    def _open_pdf_viewer(self, pdf_path: Path):
        if not pdf_path.exists():
            self.status.setText("PDF 预览不可用")
            return
        self.status.setText("")
        try:
            from ..components.pdf_viewer import PdfViewerDialog
        except Exception as exc:
            self.status.setText(f"PDF 组件不可用：{exc}")
            return
        # 关键：保存引用并挂父窗口，否则无引用的对话框会被 Python GC 回收，
        # 窗口刚创建就消失（用户看不到任何预览）
        if getattr(self, "_pdf_viewer", None) is not None:
            self._pdf_viewer.close()
            self._pdf_viewer = None
        self._pdf_viewer = PdfViewerDialog(
            str(pdf_path), self._paper.title if self._paper else "", parent=self.window()
        )
        self._pdf_viewer.setAttribute(Qt.WA_DeleteOnClose, False)
        self._pdf_viewer.show()
        self._pdf_viewer.raise_()
        self._pdf_viewer.activateWindow()

    # ---------- 补全 / 下载 ----------
    def _maybe_autofetch_detail(self):
        """打开详情页即自动补全完整摘要（直连 arXiv，一次成功永久缓存）。"""
        if self._paper is None or not self._paper.arxiv_id:
            return
        if self._paper.full_abstract or self._paper.detail_fetched:
            return
        if not self._settings.network.use_direct_arxiv:
            return
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            return
        paper_id = self._paper.arxiv_id
        self.status.setText("正在自动获取完整摘要…")
        self._fetch_worker = FetchDetailWorker(
            self._paper.arxiv_id, proxy=self._settings.network.live_proxy()
        )
        self._fetch_worker.finished_ok.connect(
            lambda info: self._auto_fetched(paper_id, info)
        )
        self._fetch_worker.failed.connect(
            lambda _msg: self.status.setText("")  # 静默失败，保留搜索摘要与手动按钮
        )
        self._fetch_worker.start()

    def _auto_fetched(self, paper_id: str, info):
        if self._paper is None or self._paper.arxiv_id != paper_id:
            return
        paper = self._paper
        paper.detail_fetched = True
        if info.title:
            paper.title = info.title
        if info.authors:
            paper.authors = info.authors
        if info.published:
            paper.published_date = info.published.replace("/", "-")
        if info.abstract:
            paper.full_abstract = info.abstract
        if info.pdf_url:
            paper.pdf_url = info.pdf_url
        if paper.arxiv_id:
            if self._db.get_paper(paper.arxiv_id) is None:
                self._db.upsert_papers([paper])
            else:
                self._db.update_paper(paper)
        # 就地刷新显示（保持当前中/英状态不重启）
        self.title.setText(paper.title or "(未命名)")
        meta_bits = []
        if paper.published_date:
            meta_bits.append(f"发布时间：{paper.published_date}")
        if paper.arxiv_id:
            meta_bits.append(f"arXiv:{paper.arxiv_id}")
        if paper.authors:
            meta_bits.append("作者：" + ", ".join(paper.authors[:12]) + (" 等" if len(paper.authors) > 12 else ""))
        meta_bits.append("AI 摘要" if paper.enriched else "搜索摘要")
        self.meta.setText("  ·  ".join(meta_bits))
        if self._show_zh and paper.abstract_zh:
            self.abstract.setText(paper.abstract_zh)
        else:
            self.abstract.setText(
                paper.full_abstract or paper.passage or paper.content
                or paper.one_line_summary or "暂无摘要"
            )
        self.fetch_btn.setText("已获取完整信息")
        self.fetch_btn.setEnabled(False)
        self.status.setText("已自动补全完整信息")

    def _on_fetch(self):
        if self._paper is None or not self._paper.arxiv_id:
            return
        if not self._settings.network.use_direct_arxiv:
            self.status.setText("已在设置中关闭直连 arxiv.org，无法补全")
            return
        self.fetch_btn.setEnabled(False)
        self.status.setText("正在从 arxiv.org 抓取完整信息…")
        self._fetch_worker = FetchDetailWorker(self._paper.arxiv_id, proxy=self._settings.network.live_proxy())
        self._fetch_worker.finished_ok.connect(self._on_fetched)
        self._fetch_worker.failed.connect(self._on_fetch_failed)
        self._fetch_worker.start()

    def _on_fetched(self, info):
        if self._paper is None:
            return
        paper = self._paper
        paper.detail_fetched = True
        if info.title:
            paper.title = info.title
        if info.authors:
            paper.authors = info.authors
        if info.published:
            paper.published_date = info.published.replace("/", "-")
        if info.abstract:
            paper.full_abstract = info.abstract
        if info.pdf_url:
            paper.pdf_url = info.pdf_url
        self._db.update_paper(paper)
        self.show_paper(paper)
        self.status.setText("已从 arxiv.org 补全信息")

    def _on_fetch_failed(self, message: str):
        self.status.setText(message)
        self.fetch_btn.setEnabled(True)

    def _on_download(self):
        if self._paper is not None:
            self.downloadRequested.emit(self._paper)
