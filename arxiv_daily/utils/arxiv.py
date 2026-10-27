"""arXiv 标识与链接工具。"""

from __future__ import annotations

import re

# 形如 2401.12345 / 2401.12345v2 / 2401.12345v3 的 arXiv 编号
_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")

# 常见 URL 形态：
# https://arxiv.org/abs/2401.12345
# https://arxiv.org/pdf/2401.12345v2
# http://export.arxiv.org/abs/2401.12345
_URL_RE = re.compile(
    r"(?:arxiv\.org|export\.arxiv\.org)/(?:abs|pdf|html)/("
    r"\d{4}\.\d{4,5})(?:v\d+)?",
    re.IGNORECASE,
)


def extract_arxiv_id(url_or_text: str) -> str | None:
    """从 URL 或文本中提取形如 ``2401.12345`` 的 arXiv ID；无法识别返回 None。"""
    if not url_or_text:
        return None
    match = _URL_RE.search(url_or_text)
    if match:
        return match.group(1)
    # 兜底：裸 ID（如 snippet 里出现 arXiv:2401.12345）
    bare = re.search(r"arXiv[:\s](\d{4}\.\d{4,5})", url_or_text, re.IGNORECASE)
    if bare:
        return bare.group(1)
    return None


def arxiv_id_from_doi(doi: str) -> str | None:
    """从 DOI（10.48550/arXiv.2401.12345）提取 ID。"""
    if not doi:
        return None
    match = re.search(r"arXiv\.(\d{4}\.\d{4,5})", doi, re.IGNORECASE)
    return match.group(1) if match else None


def abs_url_for(arxiv_id: str) -> str:
    return f"https://arxiv.org/abs/{arxiv_id}"


def pdf_url_for(arxiv_id: str) -> str:
    return f"https://arxiv.org/pdf/{arxiv_id}"


def normalize_range(start: "date", end: "date", *, latest: "date | None" = None):
    """范围归一：起≤止、止不晚于昨天（arXiv 当日尚未放榜，昨日即最新）。"""
    from datetime import date as _date

    latest = latest or _date.today() - _timedelta(days=1)
    start, end = min(start, end), max(start, end)
    if end > latest:
        offset = (end - latest).days
        start -= _timedelta(days=offset)
        end = latest
    if start > end:
        start = end
    return start, end


def freshness_for_range(start: "date", end: "date") -> str:
    """元宝 Freshness：单日=yyyy-mm-dd；范围=A,B（实测逗号语法）。"""
    if start == end:
        return start.isoformat()
    return f"{start.isoformat()},{end.isoformat()}"


from datetime import timedelta as _timedelta  # noqa: E402
