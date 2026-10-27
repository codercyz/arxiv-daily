"""主窗口：顶栏分段导航（日报/搜索/收藏/历史/设置）+ 详情浮层。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..config.settings import load_settings
from ..storage.database import Database
from ..workers import DownloadWorker
from .components.top_bar import TopBar
from .transitions import fade_in
from .views import DailyView, DetailView, HistoryView, LibraryView, SearchView, SettingsView, WeeklyView

_TABS = ["昨日日报", "搜索", "收藏", "历史", "设置"]


class MainWindow(QMainWindow):
    def __init__(self, db_path: str | None = None):
        super().__init__()
        self.setWindowTitle("ArXiv Daily · 昨日日报")
        self.resize(1280, 840)
        self.setMinimumSize(960, 640)

        self.settings = load_settings()
        self.db = Database(db_path) if db_path else Database()
        self._download_worker: DownloadWorker | None = None
        self._last_main_index = 0

        self._setup_ui()

    # ---- 布局 ----
    def _setup_ui(self):
        root = QWidget()
        root.setObjectName("rootPanel")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(root)

        # 顶栏：悬浮胶囊 + 白色滑动选中段
        major, minor, *_ = __version__.split(".")
        self.nav = TopBar(_TABS, f"v{major}.{minor}")
        self.nav.navChanged.connect(self._on_nav_changed)
        layout.addWidget(self.nav)

        # 下区域：内嵌圆角内容面板
        host_layout = QVBoxLayout()
        host_layout.setContentsMargins(18, 12, 18, 18)
        panel = QWidget()
        panel.setObjectName("contentPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.addWidget(panel)
        layout.addLayout(host_layout, 1)

        # 页面栈：5 个一级页 + 详情浮层
        self.stack = QStackedWidget()
        self.daily_view = DailyView(self.settings, self.db)
        self.search_view = SearchView(self.settings)
        self.library_view = LibraryView(self.db)
        self.history_view = HistoryView(self.db)
        self.settings_view = SettingsView(self.settings)
        self.detail_view = DetailView(self.settings, self.db)
        self.stack.addWidget(self.daily_view)     # 0
        self.stack.addWidget(self.search_view)    # 1
        self.stack.addWidget(self.library_view)   # 2
        self.stack.addWidget(self.history_view)   # 3
        self.stack.addWidget(self.settings_view)  # 4
        self.stack.addWidget(self.detail_view)    # 5
        self.weekly_view = WeeklyView(self.settings, self.db)
        self.stack.addWidget(self.weekly_view)   # 6
        panel_layout.addWidget(self.stack)

        # 轻提示
        self.toast = QLabel("")
        self.toast.setAlignment(Qt.AlignCenter)
        self.toast.setStyleSheet(
            "background:#333331; color:#FDFDFC; border-radius:18px;"
            "padding:9px 22px; font-size:13px; font-weight:600;"
        )
        self.toast.hide()
        self.toast.setParent(root)

        self.nav.setCurrentIndex(1 if self.settings.general.start_page == "search" else 0)
        self._wire_views()

    def _wire_views(self):
        for view in (self.daily_view, self.search_view, self.library_view):
            view.openDetail.connect(self._open_detail)
            view.downloadRequested.connect(self.start_download)
            view.starToggled.connect(self._on_star_toggled)
            if hasattr(view, "toastRequested"):
                view.toastRequested.connect(self.show_toast)
        self.daily_view.gotoSettings.connect(lambda: self.switch_main(4))
        self.search_view.gotoSettings.connect(lambda: self.switch_main(4))
        self.history_view.openDetail.connect(self._open_detail)
        self.daily_view.openWeekly.connect(self._open_weekly)
        self.weekly_view.backRequested.connect(self._back_from_weekly)
        self.history_view.downloadRequested.connect(self.start_download)
        self.history_view.starToggled.connect(self._on_star_toggled)
        self.history_view.toastRequested.connect(self.show_toast)
        self.settings_view.settingsChanged.connect(self._on_settings_changed)
        self.detail_view.backRequested.connect(self._back_from_detail)
        self.detail_view.downloadRequested.connect(self.start_download)
        self.detail_view.starToggled.connect(self._on_star_toggled)

    # ---- 导航 ----
    def switch_main(self, index: int):
        self.nav.setCurrentIndex(index)
        self._set_page(index)

    def _on_nav_changed(self, index: int):
        self._last_main_index = index
        self._set_page(index)

    def _set_page(self, index: int):
        if self.stack.currentIndex() == index:
            return
        self.stack.setCurrentIndex(index)
        fade_in(self.stack.currentWidget(), duration=200)
        if index == 0:
            self.daily_view.reload_topics()
        elif index == 1:
            self.search_view.focus_input()
        elif index == 2:
            self.library_view.refresh()
        elif index == 3:
            self.history_view.refresh()

    def _open_detail(self, paper):
        self.detail_view.show_paper(paper)
        self._set_page(5)

    def _open_weekly(self):
        self.weekly_view.show_weekly()
        self._set_page(6)

    def _back_from_weekly(self):
        self._set_page(self._last_main_index)

    def _back_from_detail(self):
        self._set_page(self._last_main_index)

    def _on_settings_changed(self):
        # 设置对象被 SettingsView 原地修改并已保存，依赖方按引用即可见
        self.search_view.reload_settings(self.settings)

    # ---- 收藏 ----
    def _on_star_toggled(self, paper, starred: bool):
        if not paper.arxiv_id:
            self.show_toast("该结果没有 arXiv ID，暂不支持收藏")
            return
        if starred:
            self.db.star(paper.arxiv_id)
            self.show_toast("已收藏，到「收藏」页查看")
        else:
            self.db.unstar(paper.arxiv_id)
            self.show_toast("已取消收藏")
            if self.stack.currentIndex() == 2:  # 正在收藏页，立即移除该卡片
                self.library_view.refresh()

    # ---- 下载 ----
    def start_download(self, paper):
        if self._download_worker is not None and self._download_worker.isRunning():
            self.show_toast("已有下载任务进行中，请稍候…")
            return
        self.show_toast(f"开始下载：{paper.title[:40]}…")
        self._download_worker = DownloadWorker(
            paper,
            dest_dir=self.settings.general.download_dir,
            proxy=self.settings.network.live_proxy(),
        )
        self._download_worker.finished_ok.connect(self._on_download_ok)
        self._download_worker.failed.connect(self._on_download_failed)
        self._download_worker.start()

    def _on_download_ok(self, path: str):
        self.show_toast(f"已下载：{path}")
        if self.settings.general.open_folder_after_download:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def _on_download_failed(self, message: str):
        if message.startswith("__OPEN_URL__"):
            QDesktopServices.openUrl(QUrl(message[len("__OPEN_URL__"):]))
            self.show_toast("该结果无 PDF 链接，已在浏览器打开原文")
        else:
            self.show_toast(message)

    # ---- 轻提示 ----
    def show_toast(self, text: str):
        self.toast.setText(text)
        self.toast.adjustSize()
        root = self.centralWidget()
        self.toast.move(
            root.width() // 2 - self.toast.width() // 2,
            root.height() - self.toast.height() - 28,
        )
        self.toast.show()
        self.toast.raise_()
        QTimer.singleShot(3500, self.toast.hide)

    # ---- 生命周期 ----
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.toast.isVisible():
            root = self.centralWidget()
            self.toast.move(
                root.width() // 2 - self.toast.width() // 2,
                root.height() - self.toast.height() - 28,
            )

    def closeEvent(self, event):
        self.daily_view.stop_worker()
        self.search_view._stop_worker_if_any()
        self.db.close()
        super().closeEvent(event)
