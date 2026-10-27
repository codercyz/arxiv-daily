"""流水线装配与执行。

图结构：

```
START → plan → search → extract → enrich → persist → END
                    \（搜索失败）→ END
```

- plan / enrich 在 LLM 未配置时内部自动降级，不改变图结构；
- search 失败置 ``error`` 并直接结束，由调用方（UI worker）展示错误。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from ..config.settings import Settings
from ..llm.client import LLMClient
from ..search.base import SearchProvider
from ..storage.database import Database
from .nodes import (
    enrich_node_factory,
    extract_node_factory,
    persist_node_factory,
    plan_node_factory,
    search_node_factory,
)
from .state import PipelineState

Listener = Callable[[str, Any], None]


class NullLLM:
    """LLM 未注入时的占位：所有能力均视为未配置，节点自动降级。"""

    configured = False

    def chat(self, system: str, user: str, *, temperature: float | None = None) -> str:  # pragma: no cover
        raise RuntimeError("LLM not configured")


@dataclass
class PipelineDeps:
    settings: Settings
    provider: SearchProvider
    llm: LLMClient | None = None
    db: Database | None = None
    listener: Listener | None = field(default=None)


def build_graph(deps: PipelineDeps):
    llm = deps.llm if deps.llm is not None else NullLLM()
    builder = StateGraph(PipelineState)

    builder.add_node(
        "plan",
        plan_node_factory(
            llm, deps.listener,
            use_plan=deps.settings.llm.use_plan,
            db=deps.db,
            multi_query=deps.settings.search.multi_query,
        ),
    )
    builder.add_node("search", search_node_factory(deps.provider, deps.settings, deps.listener))
    builder.add_node("extract", extract_node_factory(deps.settings.search.arxiv_only))
    builder.add_node(
        "enrich",
        enrich_node_factory(
            llm, deps.listener,
            language=deps.settings.llm.summary_language,
            max_papers=deps.settings.llm.enrich_max_papers,
        ),
    )
    builder.add_node("persist", persist_node_factory(deps.db, deps.settings, deps.listener))

    builder.add_edge(START, "plan")
    builder.add_edge("plan", "search")

    def route_after_search(state: PipelineState) -> str:
        return END if state.get("error") else "extract"

    builder.add_conditional_edges("search", route_after_search, {"extract": "extract", END: END})
    builder.add_edge("extract", "enrich")
    builder.add_edge("enrich", "persist")
    builder.add_edge("persist", END)

    return builder.compile()


def run_pipeline(deps: PipelineDeps, query: str, initial: dict | None = None) -> PipelineState:
    """同步执行整条流水线（在后台线程调用），返回最终 state。

    ``initial`` 可注入附加初始状态（如日报链路的 skip_history）。
    """
    graph = build_graph(deps)
    final: PipelineState = {"query": query}
    if initial:
        final.update(initial)
    payload: PipelineState = {"query": query}
    if initial:
        payload.update(initial)
    for chunk in graph.stream(payload):
        for node_state in chunk.values():
            if isinstance(node_state, dict):
                final.update(node_state)  # type: ignore[typeddict-item]
    return final
