"""plan 节点：LLM 规划英文检索式（主式 + 同义/缩写变体，多路召回），带 24h 缓存。"""

from __future__ import annotations

import json
import re

from ...llm.client import LLMClient, LLMError
from ..state import PipelineState

_SYSTEM = (
    "你是学术检索规划助手。用户给出一个研究方向（可能是中文或英文），"
    "请规划适合在学术搜索引擎检索最新 arXiv 论文的英文检索式：一个主检索式，"
    "外加最多 2 个变体（同义改写、缩写/全称互换、相邻子方向），用于多路召回。"
    "要求：使用领域标准术语，每条不超过 30 个词，不要引号和布尔运算符。"
    '只输出 JSON 对象，无其他文字：{"main": "…", "variants": ["…", "…"]}'
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_plan(reply: str) -> tuple[str, list[str]]:
    """容错解析规划回复 → (主检索式, 变体列表)。"""
    text = reply.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text, flags=re.DOTALL)
    main = ""
    variants: list[str] = []
    try:
        match = _JSON_RE.search(text)
        data = json.loads(match.group(0)) if match else {}
        main = str(data.get("main") or "").strip().strip('"')
        variants = [str(v).strip().strip('"') for v in (data.get("variants") or [])
                    if str(v).strip()]
    except (json.JSONDecodeError, AttributeError):
        pass
    if not main and text:
        # 模型没按 JSON 输出时，整行视为主检索式
        main = text.splitlines()[0].strip().strip('"')
    return main, variants[:2]


def _load_cached(raw: str) -> tuple[str, list[str]] | None:
    """缓存兼容：旧版存纯文本主式，新版存 {"main","variants"} JSON。"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("main"):
            return str(data["main"]), [str(v) for v in (data.get("variants") or [])][:2]
    except json.JSONDecodeError:
        pass
    return raw, []  # 旧格式：纯主式


def plan_node_factory(llm: LLMClient, listener=None, use_plan: bool = True,
                      db=None, multi_query: bool = True):
    def _apply(query: str, main: str, variants: list[str]):
        queries = [main] + [v for v in variants if v and v != main]
        if not multi_query:
            queries = [main]
        if listener and queries[0] != query:
            listener("plan", {"query": query, "planned_query": main, "variants": queries[1:]})
        return {
            "planned_query": main,
            "planned_queries": queries,
            "plan_note": f"检索式：{' / '.join(queries)}",
        }

    def plan_node(state: PipelineState) -> PipelineState:
        query = state["query"].strip()
        if not llm.configured or not use_plan:
            return {"planned_query": query, "planned_queries": [query], "plan_note": ""}

        # 24h 缓存：同查询的规划直接复用，省一次调用与延迟
        if db is not None:
            cached = _load_cached(db.get_cached_plan(query) or "")
            if cached:
                return _apply(query, cached[0], cached[1])

        try:
            reply = llm.chat(_SYSTEM, query, max_tokens=160)
        except LLMError:
            if listener:
                listener("status", "LLM 规划失败，使用原始关键词搜索")
            return {"planned_query": query, "planned_queries": [query],
                    "plan_note": "LLM 规划失败，已使用原始关键词"}
        main, variants = parse_plan(reply)
        if not main:
            main = query
        if db is not None:
            db.set_cached_plan(query, json.dumps({"main": main, "variants": variants},
                                                 ensure_ascii=False))
        return _apply(query, main, variants)

    return plan_node
