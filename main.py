"""ArXiv Daily 入口：python main.py（或打包后的 ArXivDaily.exe）"""

import sys


def _install_crash_logger():
    """无控制台的 exe 崩溃时把 traceback 写到 ~/.arxiv_daily/crash.log。"""

    def hook(exc_type, exc, tb):
        import traceback

        from arxiv_daily.config.settings import APP_DIR

        APP_DIR.mkdir(parents=True, exist_ok=True)
        with open(APP_DIR / "crash.log", "a", encoding="utf-8") as fh:
            traceback.print_exception(exc_type, exc, tb, file=fh)
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from arxiv_daily import APP_NAME
    from arxiv_daily.ui import apply_theme
    from arxiv_daily.ui.components.icons import app_icon
    from arxiv_daily.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("ArxivDaily")
    apply_theme(app)

    window = MainWindow()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    _install_crash_logger()
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())
