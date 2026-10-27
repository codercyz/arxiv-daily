"""enrich 节点：LLM 批量生成中文摘要与关键词（并发批次 + 缺漏重试 + 降级）。

性能设计（v0.4）：
- 批量提示：一次调用处理一个批次（默认 12 篇），编号列表进、JSON 数列出
- 并发：批次间线程池并发（默认 5），SearchAPI 不受影响
- 容错：批次解析失败/缺篇 → 对缺失篇用单篇提示串行重试；再失败保留搜索摘要
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

from ...llm.client import LLMClient, LLMError
from ...storage.database import PaperRecord
from ..state import PipelineState

# 延迟瓶颈是模型输出速度（~40 tok/s）：小批量 × 高并发 = 更多并行生成流
BATCH_SIZE = 4
BATCH_WORKERS = 8

_SYSTEM_SINGLE = (
    "你是论文阅读助手。根据给出的论文标题与摘要片段，输出严格的 JSON 对象，"
    "不要输出任何其他文字或代码块标记："
    '{{"summary": "用{language}写的一句话摘要，不超过 60 个字，说清做了什么、有什么价值", '
    '"keywords": ["3 到 5 个关键词，保留通用英文术语缩写，其余用{language}，每个不超过 12 字"]}}'
)

_SYSTEM_BATCH = (
    "你是论文阅读助手。下面给出编号的多篇论文（标题与摘要片段）。"
    "对每一篇用{language}写一句话摘要（不超过 60 个字，说清做了什么、有什么价值），"
    "并给出 3 到 5 个关键词（保留通用英文术语缩写，其余用{language}，每个不超过 12 字）。"
    "只输出 JSON 数组，不要任何解释或代码块标记，格式："
    '[{{"i": 1, "summary": "…", "keywords": ["…", "…"]}}, {{"i": 2, "summary": "…", "keywords": ["…"]}}]'
    "；i 必须与输入编号一一对应，不得遗漏任何一篇。"
)

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _clean(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text, flags=re.DOTALL)
    return text.strip()


def parse_single(text: str) -> tuple[str, list[str]]:
    match = _JSON_OBJ_RE.search(_clean(text))
    if not match:
        raise ValueError("no json object")
    data = json.loads(match.group(0))
    summary = str(data.get("summary") or "").strip()
    keywords = [str(k).strip() for k in (data.get("keywords") or []) if str(k).strip()]
    return summary, keywords[:5]


def parse_batch(text: str) -> dict[int, tuple[str, list[str]]]:
    """解析批量回复 → {编号: (summary, keywords)}。"""
    match = _JSON_ARRAY_RE.search(_clean(text))
    if not match:
        raise ValueError("no json array")
    items = json.loads(match.group(0))
    if isinstance(items, dict):
        items = [items]
    out: dict[int, tuple[str, list[str]]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("i"))
        except (TypeError, ValueError):
            continue
        summary = str(item.get("summary") or "").strip()
        keywords = [str(k).strip() for k in (item.get("keywords") or []) if str(k).strip()]
        if summary:
            out[index] = (summary, keywords[:5])
    return out


def _batch_user_message(batch: list[PaperRecord]) -> str:
    parts = []
    for i, paper in enumerate(batch, 1):
        snippet = (paper.passage or paper.content or paper.full_abstract or "")[:500]
        snippet = re.sub(r"\s+", " ", snippet).strip()
        parts.append(f"【{i}】标题：{paper.title}\n摘要片段：{snippet or '（无，请根据标题概括）'}")
    return "\n\n".join(parts)


def enrich_node_factory(llm: LLMClient, listener, language: str = "中文", max_papers: int = 0):
    single_system = _SYSTEM_SINGLE.format(language=language)
    batch_system = _SYSTEM_BATCH.format(language=language)

    def enrich_node(state: PipelineState) -> PipelineState:
        papers: list[PaperRecord] = list(state.get("papers") or [])
        if not llm.configured or not papers:
            return {"papers": papers, "enrich_done": 0}
        # 只为前 N 篇生成 LLM 摘要，其余保留搜索摘要（结果全量保留）
        targets = papers[:max_papers] if max_papers else papers
        rank_of = {id(p): i for i, p in enumerate(papers)}
        batches = [targets[i:i + BATCH_SIZE] for i in range(0, len(targets), BATCH_SIZE)]

        if listener:
            listener("status", f"正在生成{language}摘要（{len(targets)} 篇 · {len(batches)} 批并发）…")

        def run_batch(batch: list[PaperRecord]):
            try:
                reply = llm.chat(
                    batch_system,
                    _batch_user_message(batch),
                    max_tokens=min(4096, 220 + 170 * len(batch)),
                )
                return batch, parse_batch(reply)
            except Exception:  # 批次失败：整批进入缺漏重试
                return batch, {}

        missing: list[PaperRecord] = []
        with ThreadPoolExecutor(max_workers=BATCH_WORKERS) as pool:
            for batch, parsed in pool.map(run_batch, batches):
                for i, paper in enumerate(batch, 1):
                    item = parsed.get(i)
                    if item:
                        paper.one_line_summary, paper.keywords = item
                        paper.enriched = True
                    else:
                        missing.append(paper)
                    if listener:
                        listener("paper", {"paper": paper, "rank": rank_of[id(paper)]})

        # 缺漏篇用单篇提示串行重试；连接类错误快速失败 + 上限 5 篇，
        # 避免 LLM 端点不可达时 N 篇 × 请求超时的串行放大（最坏等待 N×60s）
        for paper in missing[:5]:
            snippet = (paper.passage or paper.content or paper.full_abstract or "")[:900]
            try:
                reply = llm.chat(
                    single_system,
                    f"标题：{paper.title}\n摘要片段：{snippet or '（无摘要，请根据标题概括）'}",
                )
                summary, keywords = parse_single(reply)
                if summary:
                    paper.one_line_summary = summary
                if keywords:
                    paper.keywords = keywords
                paper.enriched = True
            except (LLMError, ValueError, json.JSONDecodeError, AttributeError) as exc:
                if isinstance(exc, LLMError) and (
                    "连接" in exc.message or "connect" in exc.message.lower()
                ):
                    break  # 端点不可达：后续重试必然同样失败，整体降级
            if listener:
                listener("paper", {"paper": paper, "rank": rank_of[id(paper)]})

        done = sum(1 for p in targets if p.enriched)
        usage = getattr(llm, "total_usage", None)
        if listener and usage:
            tokens = usage.get("prompt", 0) + usage.get("completion", 0)
            listener("status", f"LLM 摘要完成：{done}/{len(targets)} 篇 · 累计 {tokens} tokens")
        return {"papers": papers, "enrich_done": done}

    return enrich_node
