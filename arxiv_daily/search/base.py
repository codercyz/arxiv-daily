"""联网搜索 Provider 抽象层。

v1 内置「元宝搜索（腾讯云 wsa）」实现；新增提供商时继承
:class:`SearchProvider` 并在 :func:`arxiv_daily.search.yuanbao.get_provider`
中注册即可，UI 与流水线无需改动。
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class SearchError(Exception):
    """搜索失败（网络/鉴权/配额等），message 面向用户可直接展示。"""

    def __init__(self, message: str, *, code: str = "", detail: str = ""):
        super().__init__(message)
        self.message = message
        self.code = code
        self.detail = detail


@dataclass
class PageItem:
    """单条搜索结果（对应元宝搜索 Pages 中的一条）。"""

    title: str = ""
    url: str = ""
    date: str = ""
    passage: str = ""      # 标准摘要
    content: str = ""      # 动态摘要（部分版本无）
    site: str = ""
    favicon: str = ""
    score: float = 0.0
    pics: list = field(default_factory=list)  # [{"caption","origin_url"}] 元宝提取的页面插图

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "PageItem":
        return cls(
            title=str(raw.get("title") or ""),
            url=str(raw.get("url") or ""),
            date=str(raw.get("date") or ""),
            passage=str(raw.get("passage") or ""),
            content=str(raw.get("content") or ""),
            site=str(raw.get("site") or ""),
            favicon=str(raw.get("favicon") or ""),
            score=float(raw.get("score") or 0.0),
            pics=parse_pics(raw.get("pics")),
        )


def parse_pics(value) -> list[dict]:
    """容错解析 pics：元宝可能返回 JSON 串、Python repr 串或已是列表。"""
    if not value:
        return []
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        try:
            items = json.loads(value)
        except json.JSONDecodeError:
            try:
                import ast

                items = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return []
    else:
        return []
    out = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get("origin_url"):
            out.append({
                "caption": str(item.get("caption") or ""),
                "origin_url": str(item.get("origin_url")),
            })
    return out


@dataclass
class SearchResponse:
    query: str = ""
    pages: list[PageItem] = field(default_factory=list)
    version: str = ""      # lite / standard / flagship
    request_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class SearchProvider(ABC):
    """联网搜索提供商接口。"""

    name: str = "base"
    display_name: str = "未命名提供商"

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        cnt: int = 20,
        mode: int = 2,
        industry: str = "acad",
        site: str = "",
        freshness: str = "",
    ) -> SearchResponse:
        """执行一次搜索并返回规整后的结果。失败抛 :class:`SearchError`。"""

    @abstractmethod
    def test_connection(self) -> str:
        """发送一次最小请求验证凭据，返回面向用户的描述文本。"""
