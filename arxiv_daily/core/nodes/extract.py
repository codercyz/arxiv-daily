"""extract 节点：原始搜索结果 → 规整论文记录（去重、提取 arXiv ID、兜底摘要/关键词）。"""

from __future__ import annotations

import re

from ...storage.database import PaperRecord
from ...utils.arxiv import extract_arxiv_id, pdf_url_for
from ..state import PipelineState

_STOPWORDS = {
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "with",
    "via", "from", "by", "using", "towards", "toward", "based", "its",
    "is", "are", "as", "at", "into", "over", "under", "new", "how", "why",
}


def one_sentence(text: str, limit: int = 90) -> str:
    """取第一句（或截断）作为无 LLM 时的兜底一句话摘要。"""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return ""
    for sep in (". ", ".\n", "? ", "! "):
        idx = text.find(sep)
        if 0 < idx < limit + 40:
            return text[: idx + 1].strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def fallback_keywords(title: str, max_keywords: int = 4) -> list[str]:
    """无 LLM 时从标题提取关键词（去停用词，保留术语/缩写，保持原顺序）。"""
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9\-]{1,}", title or "")
    keywords: list[str] = []
    for token in tokens:
        low = token.lower()
        if low in _STOPWORDS or len(low) < 3:
            continue
        # 全小写的普通词跳过首若干个，优先保留缩写（含大写）与长词
        if token.islower() and len(low) < 5:
            continue
        if token not in keywords:
            keywords.append(token)
        if len(keywords) >= max_keywords:
            break
    return keywords


def normalize_date(raw: str) -> str:
    """元宝返回形如 ``2026/10/22 00:00:00``，规范化为 ``2026-10-22``。"""
    if not raw:
        return ""
    head = raw.strip()[:10]
    if len(head) == 10 and head[4] in "/-" and head[7] in "/-":
        return head.replace("/", "-")
    return raw.strip()


def _fallback_summary(title: str, passage: str, content: str) -> str:
    """无 LLM 时的一句话摘要：优先 passage/content，跳过与标题复读的候选。"""
    title_head = (title or "").strip()[:24]
    for candidate in (passage, content):
        text = re.sub(r"\s+", " ", (candidate or "")).strip()
        if not text:
            continue
        if title_head and text.startswith(title_head):
            continue  # 元宝常把标题截断当摘要，复读无信息量
        return one_sentence(text)
    return ""


def extract_node_factory(arxiv_only: bool):
    def extract_node(state: PipelineState) -> PipelineState:
        pages = state.get("raw_pages") or []
        seen: set[str] = set()
        papers: list[PaperRecord] = []
        for page in pages:
            arxiv_id = extract_arxiv_id(page.url) or ""
            if arxiv_only and not arxiv_id:
                continue
            key = arxiv_id or page.url
            if key in seen:
                continue
            seen.add(key)
            papers.append(
                PaperRecord(
                    arxiv_id=arxiv_id,
                    title=page.title.strip(),
                    url=page.url,
                    pdf_url=pdf_url_for(arxiv_id) if arxiv_id else "",
                    published_date=normalize_date(page.date),
                    one_line_summary=_fallback_summary(page.title, page.passage, page.content),
                    keywords=fallback_keywords(page.title),
                    passage=page.passage,
                    content=page.content,
                    score=page.score,
                )
            )
        return {"papers": papers}

    return extract_node
