"""收藏与导出：Markdown 日报 / BibTeX 文献条目。"""

from __future__ import annotations

import re

from ..storage.database import PaperRecord


def _bibtex_key(paper: PaperRecord) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", (paper.arxiv_id or paper.title or "paper"))[:24] or "paper"


def export_bibtex(papers: list[PaperRecord]) -> str:
    entries = []
    for paper in papers:
        year = paper.published_date[:4] if len(paper.published_date) >= 4 else ""
        entries.append(
            "@article{%s,\n"
            "  title   = {%s},\n"
            "  journal = {arXiv preprint arXiv:%s},\n"
            "  year    = {%s},\n"
            "  url     = {%s}\n"
            "}" % (
                _bibtex_key(paper),
                paper.title.replace("{", "").replace("}", ""),
                paper.arxiv_id or "",
                year,
                paper.url,
            )
        )
    return "\n\n".join(entries) + ("\n" if entries else "")


def export_markdown(
    papers: list[PaperRecord],
    title: str = "ArXiv Daily",
    sections: dict[str, list[PaperRecord]] | None = None,
) -> str:
    """导出 Markdown；支持整体列表或「主题 → 论文」分组的日报。"""
    from datetime import date

    lines = [f"# {title}", "", f"> 生成时间：{date.today().isoformat()}", ""]
    if sections:
        for topic_name, topic_papers in sections.items():
            lines += [f"## {topic_name}", ""]
            lines += _paper_list(topic_papers)
    else:
        lines += _paper_list(papers)
    return "\n".join(lines)


def _paper_list(papers: list[PaperRecord]) -> list[str]:
    out: list[str] = []
    for i, paper in enumerate(papers, 1):
        out.append(f"{i}. **{paper.title}**")
        meta = [f"arXiv:{paper.arxiv_id}"] if paper.arxiv_id else []
        if paper.published_date:
            meta.append(paper.published_date)
        if paper.url:
            meta.append(f"[链接]({paper.url})")
        if meta:
            out.append(f"   - {' · '.join(meta)}")
        if paper.one_line_summary:
            out.append(f"   - {paper.one_line_summary}")
        if paper.keywords:
            out.append(f"   - 关键词：{'、'.join(paper.keywords)}")
        out.append("")
    return out
