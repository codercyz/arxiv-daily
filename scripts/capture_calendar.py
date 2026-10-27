"""真实平台截取日历弹层（含主窗口上下文），用于视觉诊断。

用法：.venv/Scripts/python.exe scripts/capture_calendar.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from arxiv_daily.ui import apply_theme
from arxiv_daily.ui.components.calendar_popup import CalendarPopup
from arxiv_daily.ui.main_window import MainWindow

OUT = ROOT / "docs" / "screenshots"


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)

    window = MainWindow(db_path=str(ROOT / ".smoke_db"))
    window.settings.search.api_key = ""  # 离线，不触发网络
    window.settings.llm.enabled = False
    window.resize(1600, 1000)
    window.show()

    def capture():
        window.switch_main(1)  # 搜索页
        app.processEvents()
        popup = CalendarPopup(["2026-10-20", "2026-10-22", "2026-10-26"],
                              "2026-10-26", window)
        popup.show_below(window.search_view.date_btn)
        QTimer.singleShot(500, lambda: grab(popup))

    def grab(popup):
        screen = app.primaryScreen()
        shot = screen.grabWindow(0)
        out = OUT / "_calendar_live.png"
        shot.save(str(out))
        print("saved", out, shot.size())
        popup.close()
        window.close()
        app.quit()

    QTimer.singleShot(600, capture)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
