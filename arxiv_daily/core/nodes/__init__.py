"""LangGraph 流水线节点。

节点通过 :class:`~arxiv_daily.core.graph.PipelineDeps` 闭包注入依赖
（搜索 Provider / LLM 客户端 / 数据库 / 事件监听器），便于单测替换。
事件约定（listener(event, payload)）：
- ``status``  阶段提示文本
- ``plan``    {query, planned_query}
- ``paper``   单篇论文更新（PaperRecord，含 rank）
- ``searched`` {count, version, latency_ms}
- ``done``    {search_id, papers}
- ``error``   {message}
"""

from .enrich import enrich_node_factory
from .extract import extract_node_factory, fallback_keywords, one_sentence
from .persist import persist_node_factory
from .plan import plan_node_factory
from .search import search_node_factory

__all__ = [
    "plan_node_factory",
    "search_node_factory",
    "extract_node_factory",
    "enrich_node_factory",
    "persist_node_factory",
    "fallback_keywords",
    "one_sentence",
]
