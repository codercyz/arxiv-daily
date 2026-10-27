"""直连 arxiv.org 抓取论文 abs 页面，解析 meta 标签补全详情。

不消耗任何搜索/LLM 配额：arXiv 页面头部带有标准
``citation_*`` meta 标签，用 html.parser 即可稳定解析。
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from html.parser import HTMLParser

import httpx

from ..utils.arxiv import extract_arxiv_id


class _MetaParser(HTMLParser):
    """收集 <meta name="citation_*" content="..."> 与 primary_subject 分类。"""

    _WANTED = {
        "citation_title",
        "citation_author",
        "citation_date",
        "citation_online_date",
        "citation_pdf_url",
        "citation_abstract",
        "citation_doi",
        "citation_arxiv_id",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, list[str]] = {}
        self.in_title = False
        self.title_text = ""

    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            name = content = None
            for key, value in attrs:
                if key == "name" and value in self._WANTED:
                    name = value
                elif key == "content":
                    content = value
            if name and content is not None:
                self.meta.setdefault(name, []).append(html.unescape(content))
        elif tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title_text += data


@dataclass
class ArxivPageInfo:
    arxiv_id: str = ""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    published: str = ""          # citation_date，如 2026/10/24
    abstract: str = ""
    pdf_url: str = ""
    doi: str = ""
    page_title: str = ""


def fetch_arxiv_page(
    arxiv_id_or_url: str, *, timeout: float = 30.0, proxy: str = ""
) -> ArxivPageInfo:
    """抓取并解析一篇论文的 abs 页面；网络失败抛 httpx.HTTPError。"""
    arxiv_id = extract_arxiv_id(arxiv_id_or_url) or arxiv_id_or_url.strip()
    url = f"https://arxiv.org/abs/{arxiv_id}"
    headers = {"User-Agent": "ArXivDaily/0.1 (open-source paper digest app)"}
    with httpx.Client(timeout=timeout, proxy=proxy or None, follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()

    parser = _MetaParser()
    parser.feed(resp.text)

    def first(key: str) -> str:
        values = parser.meta.get(key) or []
        return values[0] if values else ""

    return ArxivPageInfo(
        arxiv_id=arxiv_id,
        title=first("citation_title") or parser.title_text.replace("[PDF] ...", "").strip(),
        authors=list(parser.meta.get("citation_author") or []),
        published=first("citation_date") or first("citation_online_date"),
        abstract=first("citation_abstract"),
        pdf_url=first("citation_pdf_url") or f"https://arxiv.org/pdf/{arxiv_id}",
        doi=first("citation_doi"),
        page_title=parser.title_text.strip(),
    )
