"""流水线共享状态。"""

from __future__ import annotations

from typing import Any, TypedDict

from ..search.base import PageItem
from ..storage.database import PaperRecord


class PipelineState(TypedDict, total=False):
    query: str                    # 用户原始输入
    planned_query: str            # 主检索式（无 LLM 时等于 query）
    planned_queries: list         # 多路检索式（主 + 变体，多路召回用）
    plan_note: str                # 规划说明（供 UI 展示）
    raw_pages: list[PageItem]     # 搜索原始结果
    search_meta: dict[str, Any]   # version / request_id / latency_ms
    papers: list[PaperRecord]     # 规整后的论文（含摘要/关键词）
    enrich_done: int              # 已完成 LLM 摘要的论文数
    search_id: int                # 持久化后的搜索记录 ID
    skip_history: bool            # True 时 persist 不写入搜索历史（日报走 digest_items 归档）
    error: str                    # 非空则终止流水线
