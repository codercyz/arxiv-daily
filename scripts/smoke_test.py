"""离屏冒烟测试：悬浮胶囊顶栏 + 日报按日归档 + 各页面截图。

用法：.venv/Scripts/python.exe scripts/smoke_test.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from arxiv_daily.storage.database import PaperRecord
from arxiv_daily.ui import apply_theme
from arxiv_daily.ui.components.calendar_popup import CalendarPopup
from arxiv_daily.ui.main_window import MainWindow

OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

SAMPLE_PAPERS = [
    PaperRecord(
        arxiv_id="2610.01234", title="DeepSeek-R3: Scaling Reinforced Reasoning with Adaptive Memory",
        url="https://arxiv.org/abs/2610.01234", pdf_url="https://arxiv.org/pdf/2610.01234",
        published_date="2026-10-26", one_line_summary="提出自适应记忆机制强化推理链训练，数学与代码基准平均提升 8.4%。",
        keywords=["推理强化", "LLM", "Adaptive Memory"], passage="We introduce...", score=0.95, enriched=True,
    ),
    PaperRecord(
        arxiv_id="2610.05678", title="LoRA-XS: Ultra-Low-Rank Adaptation for Edge Deployment",
        url="https://arxiv.org/abs/2610.05678", pdf_url="https://arxiv.org/pdf/2610.05678",
        published_date="2026-10-25", one_line_summary="将低秩适配的秩压到 4 以内，边缘设备微调显存占用降低 62%。",
        keywords=["LoRA", "边缘部署", "参数高效微调"], passage="Parameter-efficient...", score=0.91, enriched=True,
    ),
    PaperRecord(
        arxiv_id="2610.09999", title="A Survey of Multimodal Alignment",
        url="https://arxiv.org/abs/2610.09999", pdf_url="https://arxiv.org/pdf/2610.09999",
        published_date="2026-10-24", one_line_summary="A survey covering alignment methods. It reviews 300 papers.",
        keywords=["Multimodal", "Alignment", "Survey"], passage="A survey covering...", score=0.82,
    ),
]


def shot(window, name: str):
    from PySide6.QtTest import QTest

    QApplication.instance().processEvents()
    QTest.qWait(320)
    window.grab().save(str(OUT / f"{name}.png"))
    print("saved", name)


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)

    # 独立临时数据库，绝不污染用户真实历史；抹掉内存中的 Key 保持完全离线
    window = MainWindow(db_path=str(ROOT / ".smoke_db"))
    window.settings.search.api_key = ""
    window.settings.llm.enabled = False
    window.settings.network.use_direct_arxiv = False  # 配图/补全直连通道也离线
    window.resize(1600, 1000)
    window.show()
    app.processEvents()

    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    # 1. 日报空态（无主题）
    shot(window, "01_daily_empty")

    # 2. 订阅 + 今日已刷新但无论文 → 轻松空态
    window.db.add_topic("大模型推理")
    window.db.add_topic("多模态对齐")
    window.daily_view._refreshed_today = True
    window.daily_view.reload_topics()
    shot(window, "02_daily_relax")

    # 3. 今日归档（两方向 + 一篇置顶）
    t1, t2 = window.db.list_topics()
    window.db.save_digest_items(t1.id, today, SAMPLE_PAPERS[:2])
    window.db.save_digest_items(t2.id, today, SAMPLE_PAPERS[2:])
    window.db.save_digest_items(t1.id, yesterday, [SAMPLE_PAPERS[1]])
    window.db.set_digest_pinned(t1.id, today, "2610.05678", True)
    window.daily_view.render_day()
    shot(window, "03_daily_today")

    # 4. 新版极简月历（有内容日期加粗、今天描边、选中黑胶囊）
    popup = CalendarPopup(window.db.digest_days(), today)
    popup.show()
    shot(popup, "04_calendar")
    popup.close()

    # 5. 搜索页日期范围检索（上周五~昨天；日历范围选择）
    window.switch_main(1)
    window.search_view._set_range(date.today() - timedelta(days=4), date.today() - timedelta(days=1))
    window.search_view._render_papers(SAMPLE_PAPERS)
    window.search_view.status.setText("10-23 ~ 10-26 · 联网搜索完成：3 条结果 · 共 3 篇")
    shot(window, "05_search_dated")

    popup = CalendarPopup([], yesterday, range_mode=True,
                          initial_range=(yesterday, yesterday))
    popup.show()
    shot(popup, "05b_calendar_range")
    popup.close()

    # 6. 搜索结果（退出回看后渲染）
    window.switch_main(1)
    window.search_view._set_range(date.today(), date.today())
    window.search_view._render_papers(SAMPLE_PAPERS)
    window.search_view.status.setText("联网搜索完成：3 条结果（standard，812 ms）· 共 3 篇，已保存到历史")
    shot(window, "06_search_results")

    # 7. 详情页（含论文配图：方法示意 + 实验对比）
    sample = SAMPLE_PAPERS[0]
    sample.figures = [
        {"caption": "自适应记忆与推理链耦合的整体框架示意", "url": "https://arxiv.org/x1.png", "kind": "method", "path": str(ROOT / ".smoke_figs" / "method.png")},
        {"caption": "各基准准确率对比柱状图", "url": "https://arxiv.org/x2.png", "kind": "experiment", "path": str(ROOT / ".smoke_figs" / "exp.png")},
    ]
    window._open_detail(sample)
    shot(window, "07_detail")

    # 8. 收藏页
    window._back_from_detail()
    window.db.star("2610.01234")
    window.switch_main(2)
    shot(window, "08_library")

    # 9. 历史页（主从分栏：左列表 + 右卡片）
    window.db.save_search("多智能体框架", SAMPLE_PAPERS[:2], llm_used=True)
    window.db.save_search("RAG 检索增强", SAMPLE_PAPERS[2:], llm_used=False)
    window.switch_main(3)
    records = window.db.list_searches()
    window.history_view._view(records[0])
    shot(window, "09_history")

    # 10. 设置页
    window.switch_main(4)
    shot(window, "10_settings_search")

    window.close()
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
