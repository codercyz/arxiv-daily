"""最终实验：调用成本与效果硬数据（真实 API）。

产出：
- docs/实验数据.md 之「成本核算」与汇总表
- docs/figures/*.png 黑白风图表（PIL 绘制）
"""

import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont

from arxiv_daily.config.settings import load_settings
from arxiv_daily.core.graph import PipelineDeps, run_pipeline
from arxiv_daily.llm.client import LLMClient
from arxiv_daily.search.yuanbao import YuanbaoSearchProvider
from arxiv_daily.storage.database import Database
from arxiv_daily.utils.arxiv import extract_arxiv_id

FIG = ROOT / "docs" / "figures"
FIG.mkdir(parents=True, exist_ok=True)
FONT = "C:/Windows/Fonts/msyh.ttc"

INK, SOFT, FAINT, LINE = (30, 30, 28), (110, 110, 105), (200, 200, 195), (228, 228, 223)


def _font(size):
    return ImageFont.truetype(FONT, size)


def bar_chart(path, title, rows, unit, note=""):
    """极简黑白柱状图：rows=[(label, value, highlight)]"""
    w, h = 860, 460
    img = Image.new("RGB", (w, h), (253, 253, 252))
    d = ImageDraw.Draw(img)
    d.text((40, 28), title, fill=INK, font=_font(24))
    if note:
        d.text((40, 62), note, fill=SOFT, font=_font(15))
    n = len(rows)
    max_v = max(v for _, v, _ in rows) or 1
    bar_w = min(120, (w - 120) // n - 40)
    x0, base_y, top_y = 60, h - 70, 130
    for i, (label, value, hl) in enumerate(rows):
        x = x0 + i * ((w - 100) // n) + 20
        bh = int((base_y - top_y) * value / max_v)
        color = INK if hl else (176, 176, 170)
        d.rounded_rectangle([x, base_y - bh, x + bar_w, base_y], radius=8, fill=color)
        d.text((x + bar_w // 2 - len(str(value)) * 7, base_y - bh - 30),
               str(value), fill=INK, font=_font(20))
        d.text((x + bar_w // 2 - len(label) * 8, base_y + 14), label,
               fill=INK if hl else SOFT, font=_font(15))
    d.line([40, base_y, w - 30, base_y], fill=LINE, width=2)
    d.text((w - 30 - len(unit) * 9, 96), unit, fill=SOFT, font=_font(14))
    img.save(path)
    print("chart:", path.name)


def main() -> int:
    settings = load_settings()
    assert settings.search.ready and settings.llm.ready
    db = Database(ROOT / ".final_exp_db")
    results = {}

    # ---- 成本 1：单次手动搜索（3 路并发）----
    provider = YuanbaoSearchProvider(settings.search, proxy=settings.network.live_proxy())
    llm = LLMClient(settings.llm, proxy=settings.network.live_proxy())
    search_calls = [0]
    real_search = provider.search
    def counting_search(*a, **kw):
        search_calls[0] += 1
        return real_search(*a, **kw)
    provider.search = counting_search

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    deps = PipelineDeps(settings=settings, provider=provider, llm=llm, db=db)
    t0 = time.perf_counter()
    final = run_pipeline(deps, "多智能体框架", initial={"skip_history": True})
    manual_ms = (time.perf_counter() - t0) * 1000
    n_papers = len(final.get("papers") or [])
    manual = {
        "search_calls": search_calls[0],
        "llm_calls": llm.total_usage["calls"],
        "tokens": dict(llm.total_usage),
        "papers": n_papers,
        "ms": int(manual_ms),
    }
    results["manual"] = manual
    print("手动搜索:", manual)

    # ---- 成本 2：日报单主题刷新 ----
    llm2 = LLMClient(settings.llm, proxy=settings.network.live_proxy())
    search_calls[0] = 0
    provider.search = counting_search
    s2 = load_settings()
    s2.search.freshness = yesterday
    deps2 = PipelineDeps(settings=s2, provider=provider, llm=llm2, db=db)
    t0 = time.perf_counter()
    final2 = run_pipeline(deps2, "NLP", initial={"skip_history": True})
    digest_ms = (time.perf_counter() - t0) * 1000
    digest = {
        "search_calls": search_calls[0],
        "llm_calls": llm2.total_usage["calls"],
        "tokens": dict(llm2.total_usage),
        "papers": len(final2.get("papers") or []),
        "ms": int(digest_ms),
    }
    results["digest"] = digest
    print("日报单主题:", digest)

    # ---- 月度额度占用估算 ----
    # 假设典型用户：5 个主题 × 每日 1 次日报 + 每日 5 次手动搜索
    monthly_searches = 5 * digest["search_calls"] + 5 * manual["search_calls"]
    quota = 6000
    monthly = {
        "searches_per_day": 5 * digest["search_calls"] + 5 * manual["search_calls"],
        "monthly": monthly_searches * 30,
        "quota": quota,
        "coverage": monthly_searches * 30 / quota * 100,
    }
    results["monthly"] = monthly
    print("月度估算:", monthly)

    # ---- 图表 ----
    bar_chart(FIG / "cost_search_calls.png", "单次任务搜索 API 调用次数",
              [("手动搜索(3路)", manual["search_calls"], False),
               ("日报单主题", digest["search_calls"], True)], "次",
              note="多路召回增强 = 3 路并发检索一次任务")
    bar_chart(FIG / "cost_tokens.png", "单次任务 LLM token 消耗",
              [("手动搜索", manual["tokens"]["prompt"] + manual["tokens"]["completion"], False),
               ("日报单主题", digest["tokens"]["prompt"] + digest["tokens"]["completion"], True)], "tokens")
    bar_chart(FIG / "latency.png", "端到端延迟",
              [("v0.3 串行(38篇)", 129064, False),
               ("v0.4 批量+并发", 18800, True),
               (f"本次日报({digest['papers']}篇)", digest["ms"], False)], "ms",
              note="批量摘要+关思维链+并发 → 6.9x")

    # ---- 汇总 markdown ----
    lines = [
        "# 实验数据（征文素材 · 最终版）", "",
        f"采集：{date.today().isoformat()} · 真实联网搜索 API + LLM（{settings.llm.model}）", "",
        "## 一、效果", "",
        "### E1 召回消融（5 个中文方向词 · d30 · 去重 arXiv 命中）",
        "| 配置 | 合计 |",
        "|---|---|",
        "| A 中文原词直搜 | 243 |",
        "| B LLM 规划单路 | 238 |",
        "| **C 规划+多路召回** | **483（2.0×）** |",
        "",
        "### E2 日期范围严格性：3 组范围查询，越界 0 条", "",
        "## 二、成本（今日实测）", "",
        "| 任务 | 搜索调用 | LLM 调用 | tokens(p+c) | 得到论文 | 耗时 |",
        "|---|---|---|---|---|---|",
        f"| 手动搜索（3 路召回） | {manual['search_calls']} | {manual['llm_calls']} | "
        f"{manual['tokens']['prompt']}+{manual['tokens']['completion']} | {manual['papers']} 篇 | {manual['ms']/1000:.1f}s |",
        f"| 日报单主题 | {digest['search_calls']} | {digest['llm_calls']} | "
        f"{digest['tokens']['prompt']}+{digest['tokens']['completion']} | {digest['papers']} 篇 | {digest['ms']/1000:.1f}s |",
        "",
        "### 月度额度估算（典型：5 主题日报 + 日 5 次搜索）",
        f"- 每日搜索调用 ≈ {monthly['searches_per_day']} 次",
        f"- 月度 ≈ {monthly['monthly']} 次，**占免费额度 6000 次/月的 {monthly['coverage']:.0f}%**",
        "",
        "## 三、延迟优化（v0.3 → v0.4）",
        "| 阶段 | 38 篇全摘要耗时 |",
        "|---|---|",
        "| v0.3 逐篇串行 | 129.1 s |",
        "| v0.4 批量+并发+关思维链 | **18.8 s（6.9×）** |",
    ]
    (ROOT / "docs" / "实验数据.md").write_text("\n".join(lines), encoding="utf-8")
    print("docs/实验数据.md 更新完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
