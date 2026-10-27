"""后台线程封装：搜索流水线 / 详情抓取 / PDF 下载。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .config.settings import Settings
from .core.graph import PipelineDeps, run_pipeline
from .downloader import download_pdf
from .fetcher.arxiv_page import ArxivPageInfo, fetch_arxiv_page
from .llm.client import LLMClient
from .search.yuanbao import get_provider
from .storage.database import Database, PaperRecord

class PipelineCancelled(Exception):
    pass

def build_deps(settings: Settings, db: Database, listener=None) -> PipelineDeps:
    """按当前设置装配流水线依赖（设置变更后重建即可生效）。"""
    provider = get_provider(settings.search, proxy=settings.network.live_proxy())
    llm = LLMClient(settings.llm, proxy=settings.network.live_proxy()) if settings.llm.ready else None
    return PipelineDeps(settings=settings, provider=provider, llm=llm, db=db, listener=listener)

class SearchWorker(QThread):
    """在后台线程执行 plan→search→extract→enrich→persist 流水线。

    ``freshness`` 指定时（如 yyyy-mm-dd），该日期作为 Freshness 传给
    联网搜索 API——检索"那一天更新"的论文。
    """

    status = Signal(str)                 # 阶段提示
    plan = Signal(object)                # {planned_query, variants}
    searched = Signal(dict)              # {count, version, latency_ms}
    paperUpdated = Signal(int, object)   # (rank, PaperRecord) 逐篇刷新
    finished_ok = Signal(int, list)      # (search_id, papers)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, settings: Settings, db: Database, query: str,
                 freshness: str | None = None, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._db = db
        self._query = query
        self._freshness = freshness
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    # listener 在流水线线程内被调用，把事件转发为 Qt 信号；
    # 用户取消时通过抛异常中断图执行。
    def _listener(self, event: str, payload):
        if self._cancelled:
            raise PipelineCancelled()
        if event == "status":
            self.status.emit(str(payload))
        elif event == "plan":
            self.plan.emit(payload)
        elif event == "searched":
            self.searched.emit(payload)
        elif event == "paper":
            self.paperUpdated.emit(payload["rank"], payload["paper"])
        elif event == "error":
            self.failed.emit(payload["message"])

    def run(self):
        import copy

        settings = self._settings
        if self._freshness:
            settings = copy.deepcopy(self._settings)
            settings.search.freshness = self._freshness
        try:
            deps = build_deps(settings, self._db, listener=self._listener)
            final = run_pipeline(deps, self._query)
        except PipelineCancelled:
            self.cancelled.emit()
            return
        except Exception as exc:  # 未预期异常兜底
            self.failed.emit(f"搜索失败：{exc}")
            return
        if final.get("error"):
            # failed 信号已在 search 节点的 listener("error") 发出
            return
        self.finished_ok.emit(final.get("search_id", 0), final.get("papers") or [])

class FuncWorker(QThread):
    """通用后台函数执行器（用于设置页的测试连接/拉取模型列表）。"""

    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            result = self._fn()
        except Exception as exc:
            message = getattr(exc, "message", None) or str(exc)
            self.failed.emit(message)
            return
        self.finished_ok.emit(result)

class FetchDetailWorker(QThread):
    """直连 arxiv.org 抓取论文完整信息（不消耗搜索/LLM 配额）。"""

    finished_ok = Signal(object)         # ArxivPageInfo
    failed = Signal(str)

    def __init__(self, arxiv_id: str, proxy: str = "", parent=None):
        super().__init__(parent)
        self._arxiv_id = arxiv_id
        self._proxy = proxy

    def run(self):
        try:
            info = fetch_arxiv_page(self._arxiv_id, proxy=self._proxy)
        except Exception as exc:
            self.failed.emit(f"抓取 arxiv 页面失败：{exc}")
            return
        self.finished_ok.emit(info)

class DownloadWorker(QThread):
    """后台下载论文 PDF。"""

    finished_ok = Signal(str)            # 本地文件路径
    failed = Signal(str)

    def __init__(self, paper: PaperRecord, dest_dir: str, proxy: str = "", parent=None):
        super().__init__(parent)
        self._paper = paper
        self._dest = dest_dir
        self._proxy = proxy

    def run(self):
        url = self._paper.pdf_url
        if not url:
            if self._paper.url:
                self.failed.emit("__OPEN_URL__" + self._paper.url)
            else:
                self.failed.emit("该结果没有可下载的 PDF 链接")
            return
        try:
            path = download_pdf(
                url,
                arxiv_id=self._paper.arxiv_id or "paper",
                title=self._paper.title,
                dest_dir=Path(self._dest),
                proxy=self._proxy,
            )
        except Exception as exc:
            self.failed.emit(f"下载失败：{exc}")
            return
        self.finished_ok.emit(str(path))

class DigestWorker(QThread):
    """今日日报：逐主题执行搜索流水线，分组渐次回传。"""

    topicStarted = Signal(object)            # TopicRecord
    topicDone = Signal(object, list)         # TopicRecord, papers
    topicFailed = Signal(object, str)
    allDone = Signal(int)                    # 完成主题数

    def __init__(self, settings: Settings, db: Database, topics, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._db = db
        self._topics = topics
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        from .services.digest import DigestService

        service = DigestService(self._settings, self._db)
        done = 0
        for topic in self._topics:
            if self._cancelled:
                break
            self.topicStarted.emit(topic)
            try:
                # 日报固定「今日新增」，由服务内部钉住 d1
                papers = service.refresh_topic(topic)
            except Exception as exc:
                self.topicFailed.emit(topic, str(exc))
                continue
            done += 1
            self.topicDone.emit(topic, papers)
        self.allDone.emit(done)

