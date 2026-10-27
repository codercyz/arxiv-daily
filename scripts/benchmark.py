"""v0.4 优化基线测试：记录各节点延迟、总耗时、token 消耗（真实 API）。

用法：.venv/Scripts/python.exe scripts/benchmark.py
输出：docs/v0.4-基线数据.md（Markdown 表格）
"""

import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from arxiv_daily.config.settings import load_settings
from arxiv_daily.core.graph import PipelineDeps, run_pipeline
from arxiv_daily.llm.client import LLMClient
from arxiv_daily.search.yuanbao import YuanbaoSearchProvider
from arxiv_daily.storage.database import Database

OUT = ROOT / "docs" / "v0.4-基线数据.md"
QUERY = "多智能体框架"
PAPERS_FOR_ENRICH = 3


def main() -> int:
    settings = load_settings()
    assert settings.search.ready, "需先配置元宝搜索 Key"
    assert settings.llm.ready, "需先配置 LLM"
    db = Database(ROOT / ".benchmark_db")

    provider = YuanbaoSearchProvider(settings.search, proxy=settings.network.live_proxy())
    llm = LLMClient(settings.llm, proxy=settings.network.live_proxy())
    rows: list[tuple[str, str, str]] = []  # (指标, 数值, 说明)

    def add(metric, value, note=""):
        rows.append((metric, value, note))
        print(f"{metric:32s} {value:>14s}   {note}")

    print(f"== ArXiv Daily v0.4 基线 @ {datetime.now().isoformat(timespec='seconds')} ==\n")

    # ---- 1. SearchAPI 裸调用 ----
    lat = []
    for i in range(3):
        t0 = time.perf_counter()
        resp = provider.search("large language model", cnt=10, mode=2,
                               industry="acad", site="arxiv.org", freshness="d7")
        lat.append((time.perf_counter() - t0) * 1000)
    add("SearchAPI 单次延迟(3次均值)", f"{sum(lat)/len(lat):.0f} ms", f"Cnt=10, 返回{len(resp.pages)}条, 版本{resp.version}")
    add("SearchAPI 单次延迟(最大)", f"{max(lat):.0f} ms", "")

    # ---- 2. plan 节点（LLM 检索词规划）----
    from arxiv_daily.core.nodes.plan import _SYSTEM as PLAN_SYSTEM
    t0 = time.perf_counter()
    llm.chat(PLAN_SYSTEM, QUERY)
    plan_ms = (time.perf_counter() - t0) * 1000
    u = llm.last_usage
    add("LLM plan 单次延迟", f"{plan_ms:.0f} ms", f"tokens: {u.get('prompt','?')}+{u.get('completion','?')}")

    # ---- 3. enrich 单篇（用真实论文，单篇提示词作对照）----
    import json
    from arxiv_daily.core.nodes.enrich import _SYSTEM_SINGLE as ENRICH_SYSTEM
    papers = [p for p in resp.pages if p.url and "arxiv.org" in p.url][:PAPERS_FOR_ENRICH]
    per_lat, per_tok = [], []
    for page in papers:
        snippet = (page.passage or page.content or "")[:900]
        t0 = time.perf_counter()
        try:
            llm.chat(ENRICH_SYSTEM.format(language="中文"),
                     f"标题：{page.title}\n摘要片段：{snippet or '（无）'}")
        except Exception as exc:
            add("enrich 单篇失败", "-", str(exc)[:40])
            break
        per_lat.append((time.perf_counter() - t0) * 1000)
        per_tok.append(llm.last_usage)
    if per_lat:
        avg = sum(per_lat) / len(per_lat)
        p_tok = sum(t.get("prompt", 0) for t in per_tok) / len(per_tok)
        c_tok = sum(t.get("completion", 0) for t in per_tok) / len(per_tok)
        add("LLM enrich 单篇延迟(均值)", f"{avg:.0f} ms", f"n={len(per_lat)}")
        add("LLM enrich 单篇 tokens(均值)", f"{p_tok:.0f}+{c_tok:.0f}", "prompt+completion")

    # ---- 4. 完整流水线（串行现状，Cnt=10）----
    deps = PipelineDeps(settings=settings, provider=provider, llm=llm, db=db)
    t0 = time.perf_counter()
    final = run_pipeline(deps, QUERY)
    total = (time.perf_counter() - t0) * 1000
    n = len(final.get("papers") or [])
    add("流水线总耗时(Cnt=10)", f"{total:.0f} ms", f"{n} 篇, planned={final.get('planned_query','')!r}")
    if n:
        add("流水线单篇均摊", f"{total/n:.0f} ms/篇", "")
        add("折算 50 篇耗时(线性外推)", f"{total/n*50/1000:.1f} s", "日报多主题场景")

    # ---- 5. 全网解读 / 配图（详情页触发型）----
    t0 = time.perf_counter()
    try:
        from arxiv_daily.services.insights import fetch_insights
        pages = fetch_insights(provider, papers[0].title if papers else "attention is all you need")
        add("全网解读单次延迟", f"{(time.perf_counter()-t0)*1000:.0f} ms", f"{len(pages)} 条解读")
    except Exception as exc:
        add("全网解读失败", "-", str(exc)[:40])

    # ---- 写文档 ----
    lines = [
        "# v0.4 优化基线数据", "",
        f"采集时间：{datetime.now().isoformat(timespec='seconds')} · 查询词：{QUERY} · LLM：{settings.llm.model}", "",
        "| 指标 | 数值 | 说明 |", "|---|---|---|",
    ]
    lines += [f"| {m} | {v} | {n} |" for m, v, n in rows]
    lines += ["", "> 优化目标在需求文档中对照本表设定。"]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n已写入 {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
