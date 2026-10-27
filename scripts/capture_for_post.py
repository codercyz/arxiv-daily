"""征文真实运行截图：真实 API/真实数据逐屏截取（post_XX_*.png）。"""

import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from arxiv_daily.config.settings import load_settings
from arxiv_daily.services.digest import DigestService
from arxiv_daily.storage.database import Database
from arxiv_daily.ui import apply_theme
from arxiv_daily.ui.components.calendar_popup import CalendarPopup
from arxiv_daily.ui.main_window import MainWindow

OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    window = MainWindow()  # 真实设置 + 真实数据库
    window.showMaximized()

    settings = load_settings()
    steps = []

    def grab(name):
        shot = app.primaryScreen().grabWindow(0)
        shot.save(str(OUT / f"{name}.png"))
        print("saved", name)

    def step_daily():
        window.switch_main(0)
        # 真实刷新一个主题（若无订阅则临时订阅 NLP）
        db = window.db
        if not db.list_topics():
            db.add_topic("NLP")
        for topic in db.list_topics():
            try:
                DigestService(settings, db).refresh_topic(topic)
            except Exception as exc:
                print("主题刷新失败:", exc)
        window.daily_view._refreshed_today = True
        window.daily_view.render_day()
        app.processEvents()
        grab("post_01_daily")
        QTimer.singleShot(400, step_search)

    def step_search():
        window.switch_main(1)
        # 真实搜索（同步跑流水线，渲染结果）
        from arxiv_daily.core.graph import PipelineDeps, run_pipeline
        from arxiv_daily.workers import build_deps

        deps = build_deps(load_settings(), window.db)
        final = run_pipeline(deps, "多智能体框架")
        papers = final.get("papers") or []
        window.search_view._set_range(date.today() - timedelta(days=1),
                                      date.today() - timedelta(days=1))
        window.search_view._render_papers(papers)
        routes = len(final.get("search_meta", {}).get("planned_queries") or [1])
        window.search_view.status.setText(
            f"联网搜索完成：{len(papers)} 条去重结果（{routes} 路并发，去重合并）· 已保存到历史记录")
        app.processEvents()
        grab("post_02_search")
        window._post_papers = papers
        QTimer.singleShot(400, step_detail)

    def step_detail():
        papers = getattr(window, "_post_papers", [])
        if papers:
            window._open_detail(papers[0])
            time.sleep(7)  # 等配图/信息自动补全（真实网络）
            app.processEvents()
            grab("post_03_detail")
            window._back_from_detail()
        QTimer.singleShot(300, step_calendar)

    def step_calendar():
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        popup = CalendarPopup([], yesterday, window.search_view, range_mode=True,
                              initial_range=(yesterday, yesterday),
                              max_date=yesterday)
        popup.show_below(window.search_view.date_btn)
        app.processEvents()
        grab("post_04_calendar")
        popup.close()
        QTimer.singleShot(300, step_history)

    def step_history():
        window.switch_main(3)
        records = window.db.list_searches()
        if records:
            window.history_view._view(records[0])
        app.processEvents()
        grab("post_05_history")
        QTimer.singleShot(300, step_library)

    def step_library():
        papers = getattr(window, "_post_papers", [])
        for paper in papers[:5]:
            if paper.arxiv_id:
                window.db.star(paper.arxiv_id)
        window.switch_main(2)
        app.processEvents()
        grab("post_06_library")
        QTimer.singleShot(300, step_settings)

    def step_settings():
        window.switch_main(4)
        app.processEvents()
        grab("post_07_settings")
        window.settings_view.nav.setCurrentIndex(1)  # 联网搜索分组
        app.processEvents()
        grab("post_08_settings_search")
        QTimer.singleShot(300, step_pdf)

    def step_pdf():
        cache = Path.home() / ".arxiv_daily" / "pdfcache"
        pdfs = sorted(cache.glob("*.pdf"), key=lambda p: p.stat().st_size, reverse=True)
        if pdfs:
            from arxiv_daily.ui.components.pdf_viewer import PdfViewerDialog

            viewer = PdfViewerDialog(str(pdfs[0]), "论文 PDF 在线预览")
            viewer.resize(1000, 1000)
            viewer.show()
            viewer.raise_()
            time.sleep(1.5)
            app.processEvents()
            grab("post_09_pdf_viewer")
            viewer.close()
        window.close()
        app.quit()

    QTimer.singleShot(900, step_daily)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
