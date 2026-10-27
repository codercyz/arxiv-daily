"""离屏渲染单张论文卡片，放大验证标题换行与按钮渲染。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from arxiv_daily.storage.database import PaperRecord
from arxiv_daily.ui import apply_theme
from arxiv_daily.ui.widgets.paper_card import PaperCard

OUT = ROOT / "docs" / "screenshots"

PAPER = PaperRecord(
    arxiv_id="2610.01234",
    title="DeepSeek-R3: Scaling Reinforced Reasoning with Adaptive Memory for Very Long Contexts",
    url="https://arxiv.org/abs/2610.01234",
    pdf_url="https://arxiv.org/pdf/2610.01234",
    published_date="2026-10-26",
    one_line_summary="提出自适应记忆机制强化推理链训练，数学与代码基准平均提升 8.4%。",
    keywords=["推理强化", "LLM", "Adaptive Memory", "长上下文"],
    passage="We introduce...",
    score=0.95,
    enriched=True,
)


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)

    host = QWidget()
    host.resize(900, 640)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(40, 40, 40, 40)

    card = PaperCard(PAPER, 1)
    card.setFixedWidth(800)
    layout.addWidget(card)

    # 对照组：同参数的裸 QLabel
    plain = QLabel(PAPER.title)
    plain.setObjectName("cardTitle")
    plain.setWordWrap(True)
    plain.setMaximumHeight(46)
    plain.setFixedWidth(800)
    layout.addWidget(plain)

    info = QLabel(f"card sizeHint={card.sizeHint()} plain sizeHint={plain.sizeHint()}")
    layout.addWidget(info)

    host.show()
    app.processEvents()
    OUT.joinpath("_card_probe.png").write_bytes(b"")
    host.grab().save(str(OUT / "_card_probe.png"))
    print("hint:", card.sizeHint(), plain.sizeHint(), "title label h:",
          card.findChild(QLabel, "cardTitle").height())
    return 0


if __name__ == "__main__":
    sys.exit(main())
