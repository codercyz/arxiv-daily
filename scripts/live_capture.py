"""真实平台（windows QPA）启动验证：自动截图并退出。

用法：.venv/Scripts/python.exe scripts/live_capture.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from arxiv_daily.storage.database import PaperRecord
from arxiv_daily.ui.main_window import MainWindow


def main() -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from arxiv_daily.ui import apply_theme

    app = QApplication(sys.argv)
    apply_theme(app)

    window = MainWindow()
    window.resize(1200, 800)

    paper = PaperRecord(
        arxiv_id="2610.01234",
        title="DeepSeek-R3: Scaling Reinforced Reasoning with Adaptive Memory",
        url="https://arxiv.org/abs/2610.01234",
        pdf_url="https://arxiv.org/pdf/2610.01234",
        published_date="2026-10-26",
        one_line_summary="提出自适应记忆机制强化推理链训练，数学与代码基准平均提升 8.4%。",
        keywords=["推理强化", "LLM", "Adaptive Memory"],
        score=0.95,
        enriched=True,
    )

    def capture():
        out = ROOT / "docs" / "screenshots" / "10_live.png"
        window.grab().save(str(out))
        print("saved", out)
        window.close()
        app.quit()

    QTimer.singleShot(2500, capture)  # 等待渲染稳定
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
