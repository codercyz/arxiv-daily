from pathlib import Path

from PySide6.QtWidgets import QApplication

_QSS_NAME = "style.qss"


def _qss_path() -> Path:
    """QSS 路径：源码运行取包目录；冻结运行取 _MEIPASS（--add-data 保持原目录结构）。"""
    import sys

    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "arxiv_daily" / "ui" / _QSS_NAME
    return Path(__file__).with_name(_QSS_NAME)


def apply_theme(app: QApplication) -> None:
    """加载黑白极简 QSS；缺失时记日志并终止——绝不静默回退成系统默认样式。"""
    qss = _qss_path()
    if not qss.exists():
        from ..config.settings import APP_DIR

        APP_DIR.mkdir(parents=True, exist_ok=True)
        message = f"[theme] style.qss 未找到: {qss}（打包需 --add-data \"arxiv_daily/ui/style.qss;arxiv_daily/ui\"）\n"
        with open(APP_DIR / "crash.log", "a", encoding="utf-8") as fh:
            fh.write(message)
        raise SystemExit(message)
    app.setStyleSheet(qss.read_text(encoding="utf-8"))
