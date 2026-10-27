"""search 节点：多路检索式并发调用联网搜索 API，按 arXiv ID 去重合并。

严格按指定日期/范围检索（Freshness 原样透传，不放宽）。
多路召回：LLM 规划的主式 + 变体各查一次（并发 3 路），展示元宝 API
的并发调用与去重合并能力——单路 10 条的中文词经规划+多路可达 50+ 条。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from ...config.settings import Settings
from ...search.base import PageItem, SearchProvider, SearchResponse
from ...utils.arxiv import extract_arxiv_id
from ..state import PipelineState

FANOUT_WORKERS = 3


def _dedupe(pages: list[PageItem]) -> list[PageItem]:
    seen: set[str] = set()
    out = []
    for page in pages:
        key = extract_arxiv_id(page.url) or page.url
        if key in seen:
            continue
        seen.add(key)
        out.append(page)
    return out


def search_node_factory(provider: SearchProvider, settings: Settings, listener):
    s = settings.search

    def _call(query: str, freshness: str) -> SearchResponse:
        return provider.search(
            query,
            cnt=s.cnt,
            mode=s.mode,
            industry=s.industry,
            site=s.site_filter,
            freshness=freshness,
        )

    def search_node(state: PipelineState) -> PipelineState:
        queries = state.get("planned_queries") or [state.get("planned_query") or state["query"]]
        freshness = s.freshness
        if len(queries) > 1:
            if listener:
                listener("status", f"多路检索并发中（{len(queries)} 路 · {provider.display_name}）…")
        else:
            if listener:
                listener("status", f"正在调用联网搜索（{provider.display_name}）…")

        start = time.perf_counter()
        if len(queries) == 1:
            try:
                response = _call(queries[0], freshness)
            except Exception as exc:
                message = getattr(exc, "message", None) or f"搜索失败：{exc}"
                if listener:
                    listener("error", {"message": message})
                return {"error": message}
            responses = [(queries[0], response)]
        else:
            responses = []
            errors: list[str] = []
            with ThreadPoolExecutor(max_workers=FANOUT_WORKERS) as pool:
                futures = {pool.submit(_call, q, freshness): q for q in queries}
                for future, q in futures.items():
                    try:
                        responses.append((q, future.result()))
                    except Exception as exc:
                        errors.append(getattr(exc, "message", None) or str(exc))
            if not responses:
                message = errors[0] if errors else "搜索失败"
                if listener:
                    listener("error", {"message": message})
                return {"error": message}
            if errors and listener:
                listener("status", f"{len(errors)} 路检索失败（其余 {len(responses)} 路正常）")

        # 按路序合并（主式优先）+ arXiv ID 去重
        merged: list[PageItem] = []
        per_query_counts = []
        for q, resp in responses:
            pages = _dedupe(resp.pages)
            per_query_counts.append({"query": q, "count": len(resp.pages)})
            merged.extend(pages)
        merged = _dedupe(merged)

        latency_ms = (time.perf_counter() - start) * 1000
        last = responses[-1][1]
        meta = {
            "version": last.version,
            "request_id": last.request_id,
            "latency_ms": round(latency_ms),
            "provider": provider.name,
            "planned_query": queries[0],
            "planned_queries": queries,
            "per_query_counts": per_query_counts,
            "freshness": freshness,
        }
        if listener:
            listener(
                "searched",
                {
                    "count": len(merged),
                    "raw_total": sum(c["count"] for c in per_query_counts),
                    "routes": len(responses),
                    "version": last.version,
                    "latency_ms": meta["latency_ms"],
                },
            )
        return {"raw_pages": merged, "search_meta": meta, "error": ""}

    return search_node
