"""官方代码仓库发现：元宝搜索 Site=github.com 召回 + 本地规则标记官方实现。

同一个 API 换 Site 参数即变代码搜索；官方判定用零成本硬规则——
仓库名与论文项目名（标题首词）完全一致（近形名如 ForgeCAD≠CADForge 天然区分），
其余按相关性分数排序展示为相关仓库。
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..search.base import SearchProvider
from ..storage.database import PaperRecord

_REPO_PATH = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+)")

_GENERIC_HEADS = {
    "a", "an", "the", "on", "of", "for", "towards", "toward", "learning",
    "understanding", "exploring", "unified", "generalizing", "improving",
    "benchmark", "survey", "study", "notes", "rethinking", "enhancing",
    "adaptive", "efficient", "scalable", "deep", "simple", "fast",
}


def _project_token(title: str) -> str:
    """论文项目名启发：标题首词（CADForge: … → cadforge）。
    首词是通用词（a/the/learning…）时不可靠，返回空。"""
    first = re.split(r"[\s:，,（(—-]", (title or "").strip(), 1)[0]
    token = re.sub(r"[^0-9a-zA-Z]", "", first).lower()
    if len(token) < 3 or token in _GENERIC_HEADS:
        return ""
    return token


def find_repos(provider: SearchProvider, paper: PaperRecord, *, cnt: int = 10) -> list[dict]:
    """召回论文相关仓库：仅收 github.com 结果，归一化到 owner/repo 去重，score 降序。"""
    title = (paper.title or "").strip()
    if not title:
        return []
    response = provider.search(
        title[:110], cnt=cnt, mode=2, industry="", site="github.com", freshness=""
    )
    seen: set[str] = set()
    repos: list[dict] = []
    for page in response.pages:
        url = (page.url or "").split("?")[0]
        if "github.com" not in urlparse(url).netloc:
            continue
        m = _REPO_PATH.match(url)
        if not m:
            continue
        full = m.group(1).rstrip("/.")
        if full.lower() in seen:
            continue
        seen.add(full.lower())
        desc = (page.passage or page.content or "").strip().split("\n")[0][:120]
        repos.append({
            "name": full,
            "url": f"https://github.com/{full}",
            "desc": desc,
            "score": float(page.score or 0),
        })
    repos.sort(key=lambda r: r["score"], reverse=True)

    # 硬规则标记官方：仓库名 == 论文项目名（完全一致，不模糊匹配）
    proj = _project_token(paper.title or "")
    marked: list[dict] = []
    for r in repos:
        repo = re.sub(r"[^0-9a-z]", "", r["name"].rsplit("/", 1)[-1].lower())
        marked.append(dict(r, official=bool(proj) and repo == proj))
    if any(r["official"] for r in marked):  # 官方仓库置顶
        marked.sort(key=lambda r: not r["official"])
    return marked[:5]
