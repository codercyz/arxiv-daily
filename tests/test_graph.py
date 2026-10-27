"""流水线集成测试：mock Provider + 假 LLM，全程离线。"""

import json

import pytest

from arxiv_daily.config.settings import Settings
from arxiv_daily.core.graph import PipelineDeps, run_pipeline
from arxiv_daily.llm.client import LLMError
from arxiv_daily.search.base import (
    PageItem,
    SearchProvider,
    SearchResponse,
    SearchError,
)
from arxiv_daily.storage.database import Database


class FakeProvider(SearchProvider):
    name = "fake"
    display_name = "Fake"

    def __init__(self, pages=None, error: str = ""):
        self.pages = pages or []
        self.error = error
        self.calls: list[dict] = []

    def search(self, query, *, cnt=20, mode=2, industry="acad", site="", freshness=""):
        if self.error:
            raise SearchError(self.error, code="UnauthorizedOperation")
        self.calls.append({"query": query, "cnt": cnt, "site": site})
        return SearchResponse(query=query, pages=self.pages, version="standard")

    def test_connection(self) -> str:  # pragma: no cover - 流水线不使用
        return "ok"


class FakeLLM:
    """脚本化 LLM：规划返回固定查询；批量摘要按编号回数组，单篇回对象。"""

    def __init__(self):
        self.configured = True
        self.chat_calls = 0

    def chat(self, system, user, *, temperature=None, max_tokens=None):
        self.chat_calls += 1
        if "检索" in system or "学术检索" in system:
            return "large language model reasoning"
        if "【1】" in user:  # 批量提示：覆盖全部编号
            count = user.count("【")
            items = [
                {"i": i, "summary": f"第{i}篇的中文摘要", "keywords": ["推理", "LLM"]}
                for i in range(1, count + 1)
            ]
            return json.dumps(items, ensure_ascii=False)
        return json.dumps({"summary": f"关于{user[:6]}的一句话摘要", "keywords": ["推理", "LLM"]}, ensure_ascii=False)


def _pages():
    return [
        PageItem(title="DeepSeek-R2 Pushes Reasoning", url="https://arxiv.org/abs/2610.00001",
                 date="2026-10-26", passage="A new model. It improves math.", score=0.95),
        PageItem(title="Non arxiv news", url="https://news.example.com/x", passage="skip me"),
    ]


def _deps(tmp_path, provider, llm=None):
    settings = Settings()
    return (
        PipelineDeps(
            settings=settings,
            provider=provider,
            llm=llm,
            db=Database(tmp_path / "data.db"),
        ),
        settings,
    )


def test_full_flow_with_llm(tmp_path):
    provider = FakeProvider(_pages())
    deps, settings = _deps(tmp_path, provider, FakeLLM())
    events = []
    deps.listener = lambda e, p: events.append(e)

    final = run_pipeline(deps, "大模型推理")

    # plan 生效：搜索用的是规划后的查询
    assert provider.calls[0]["query"] == "large language model reasoning"
    assert provider.calls[0]["site"] == "arxiv.org"
    # 非 arxiv 结果被过滤
    papers = final["papers"]
    assert len(papers) == 1
    assert papers[0].arxiv_id == "2610.00001"
    assert papers[0].enriched
    assert papers[0].one_line_summary == "第1篇的中文摘要"
    assert papers[0].keywords == ["推理", "LLM"]
    # 已入库
    searches = deps.db.list_searches()
    assert len(searches) == 1 and searches[0].result_count == 1
    assert searches[0].llm_used
    # 事件顺序合理
    assert "searched" in events and "paper" in events and events[-1] == "done"


def test_flow_degrades_without_llm(tmp_path):
    provider = FakeProvider(_pages())
    deps, _ = _deps(tmp_path, provider, llm=None)
    final = run_pipeline(deps, "LLM reasoning")
    # 用原始查询搜索；摘要/关键词走 extract 兜底
    assert provider.calls[0]["query"] == "LLM reasoning"
    papers = final["papers"]
    assert papers[0].one_line_summary == "A new model."
    assert not papers[0].enriched
    assert papers[0].keywords  # 标题提取的兜底关键词


def test_search_error_stops_pipeline(tmp_path):
    provider = FakeProvider(error="API Key 无效")
    deps, _ = _deps(tmp_path, provider, llm=None)
    final = run_pipeline(deps, "anything")
    assert "API Key 无效" in final.get("error", "")
    # 未产生任何历史
    assert deps.db.list_searches() == []


def test_llm_enrich_failure_keeps_fallback(tmp_path):
    class BadLLM(FakeLLM):
        def chat(self, system, user, *, temperature=None, max_tokens=None):
            if "检索" in system:
                return "ok query"
            raise LLMError("boom")

    provider = FakeProvider(_pages())
    deps, _ = _deps(tmp_path, provider, BadLLM())
    final = run_pipeline(deps, "q")
    paper = final["papers"][0]
    assert not paper.enriched
    assert paper.one_line_summary == "A new model."  # 兜底摘要仍在


def test_skip_history_keeps_searches_clean(tmp_path):
    """日报链路（skip_history）不写搜索历史；手动搜索仍写。"""
    db = Database(tmp_path / "d.db")
    provider = FakeProvider([])  # 空结果
    settings = Settings()
    deps = PipelineDeps(settings=settings, provider=provider, db=db)
    final = run_pipeline(deps, "daily topic", initial={"skip_history": True})

    assert final["papers"] == []
    assert db.list_searches() == []                       # 未污染搜索历史

    # 手动搜索（默认）依旧写历史
    run_pipeline(PipelineDeps(settings=settings, provider=FakeProvider(_pages()), db=db), "manual")
    assert len(db.list_searches()) == 1



def test_plan_disabled_by_setting(tmp_path):
    """use_plan=False 时即使 LLM 可用也用原始查询。"""
    settings = Settings()
    settings.llm.use_plan = False
    provider = FakeProvider(_pages())
    deps = PipelineDeps(settings=settings, provider=provider, llm=FakeLLM(), db=Database(tmp_path / "d.db"))
    run_pipeline(deps, "中文方向词")
    assert provider.calls[0]["query"] == "中文方向词"


def test_enrich_max_papers_limits_but_keeps_all(tmp_path):
    """enrich_max_papers=N 只为前 N 篇生成摘要，结果全量保留。"""

    class CountingLLM(FakeLLM):
        def __init__(self):
            super().__init__()
            self.summary_calls = 0

        def chat(self, system, user, *, temperature=None, max_tokens=None):
            if "检索" in system:
                return "ok query"
            if "【" in user:  # 批量请求：只回第一篇（制造缺漏，触发单篇重试）
                self.summary_calls += 1
                return json.dumps([{"i": 1, "summary": "摘要", "keywords": ["K"]}], ensure_ascii=False)
            self.summary_calls += 1
            return json.dumps({"summary": "单篇摘要", "keywords": ["K"]}, ensure_ascii=False)

    pages = [
        PageItem(title=f"P{i}", url=f"https://arxiv.org/abs/2610.0000{i}", passage=f"paper {i}. good")
        for i in range(1, 4)
    ]
    settings = Settings()
    settings.llm.enrich_max_papers = 1
    llm = CountingLLM()
    deps = PipelineDeps(settings=settings, provider=FakeProvider(pages), llm=llm,
                        db=Database(tmp_path / "d.db"))
    final = run_pipeline(deps, "q")
    papers = final["papers"]
    assert len(papers) == 3                       # 全量保留
    assert llm.summary_calls == 1                 # 只摘要了 1 篇
    assert papers[0].enriched and not papers[1].enriched
    assert final["enrich_done"] == 1


def test_save_history_disabled(tmp_path):
    settings = Settings()
    settings.search.save_history = False
    db = Database(tmp_path / "d.db")
    deps = PipelineDeps(settings=settings, provider=FakeProvider(_pages()), db=db)
    run_pipeline(deps, "q")
    assert db.list_searches() == []               # 不写历史
    assert db.get_paper("2610.00001") is not None  # 论文本体仍在库（收藏/配图可用）


def test_parse_batch_tolerant():
    from arxiv_daily.core.nodes.enrich import parse_batch, parse_single

    text = '[{"i": 1, "summary": "甲", "keywords": ["a"]}, {"i": 2, "summary": "乙", "keywords": []}]'
    parsed = parse_batch(text)
    assert parsed[1][0] == "甲" and parsed[2][0] == "乙"
    fenced = "```json\n" + '[{"i": 3, "summary": "丙"}]' + "\n```"
    assert parse_batch(fenced)[3][0] == "丙"
    assert parse_single('{"summary": "s", "keywords": ["k"]}') == ("s", ["k"])


def test_enrich_batch_missing_retries_single(tmp_path):
    """批量回复缺篇 → 缺漏篇走单篇重试并被补齐。"""
    pages = [
        PageItem(title=f"P{i}", url=f"https://arxiv.org/abs/2610.0000{i}", passage=f"paper {i}. good")
        for i in range(1, 4)
    ]
    db = Database(tmp_path / "d.db")
    deps = PipelineDeps(settings=Settings(), provider=FakeProvider(pages), llm=CountingRetryLLM(), db=db)
    final = run_pipeline(deps, "q")
    papers = final["papers"]
    assert all(p.enriched for p in papers)            # 全部补齐
    assert papers[1].one_line_summary == "单篇摘要"    # 第 2 篇经重试路径


class CountingRetryLLM(FakeLLM):
    """批量只回第 1、3 篇（缺第 2 篇），单篇正常。"""

    def chat(self, system, user, *, temperature=None, max_tokens=None):
        if "检索" in system:
            return "ok"
        if "【1】" in user:
            return json.dumps(
                [{"i": 1, "summary": "批量一", "keywords": ["K"]},
                 {"i": 3, "summary": "批量三", "keywords": ["K"]}],
                ensure_ascii=False,
            )
        return json.dumps({"summary": "单篇摘要", "keywords": ["K"]}, ensure_ascii=False)


def test_plan_cache_roundtrip(tmp_path):
    db = Database(tmp_path / "d.db")
    db.set_cached_plan("多智能体", "multi-agent")
    assert db.get_cached_plan("多智能体") == "multi-agent"
    assert db.get_cached_plan("别的") is None


def test_plan_node_uses_cache(tmp_path):
    from arxiv_daily.core.nodes import plan_node_factory

    db = Database(tmp_path / "d.db")
    db.set_cached_plan("多智能体框架", "cached query")
    llm = FakeLLM()
    plan = plan_node_factory(llm, use_plan=True, db=db)
    state = plan({"query": "多智能体框架"})
    assert state["planned_query"] == "cached query"
    assert llm.chat_calls == 0                       # 未真正调用 LLM


def test_search_range_freshness_utils():
    from datetime import date, timedelta

    from arxiv_daily.utils.arxiv import freshness_for_range, normalize_range

    today = date.today()
    assert freshness_for_range(today, today) == today.isoformat()          # 单日
    a, b = today - timedelta(days=6), today - timedelta(days=1)
    assert freshness_for_range(a, b) == f"{a.isoformat()},{b.isoformat()}"  # 范围（逗号语法）

    yesterday = today - timedelta(days=1)
    # 归一：颠倒交换
    s, e = normalize_range(b, a)
    assert s == a and e == b
    # 止越过昨天（上界）整体平移，绝不包含今天
    s2, e2 = normalize_range(today - timedelta(days=2), today + timedelta(days=3))
    assert e2 == yesterday and s2 == yesterday - timedelta(days=5)


def test_freshness_passed_through_strictly(tmp_path):
    """搜索严格按传入 Freshness 检索：一次调用、原样透传、空就是空。"""

    class StrictProbe(FakeProvider):
        def search(self, query, **kw):
            self.calls.append(dict(kw))
            return SearchResponse(query=query, pages=[], version="standard")

    settings = Settings()
    settings.search.freshness = "2026-10-20,2026-10-24"
    provider = StrictProbe([])
    deps = PipelineDeps(settings=settings, provider=provider, db=Database(tmp_path / "d.db"))
    final = run_pipeline(deps, "q")
    assert len(provider.calls) == 1                          # 不重试不放宽
    assert provider.calls[0]["freshness"] == "2026-10-20,2026-10-24"
    assert final["search_meta"]["freshness"] == "2026-10-20,2026-10-24"
    assert final["papers"] == []


def test_parse_plan_json_variants():
    from arxiv_daily.core.nodes.plan import parse_plan

    main, variants = parse_plan('{"main": "multi agent framework", "variants": ["LLM agents", "agent collaboration"]}')
    assert main == "multi agent framework"
    assert variants == ["LLM agents", "agent collaboration"]
    # 非 JSON 回复回退为整行主式
    main2, variants2 = parse_plan("pure text query")
    assert main2 == "pure text query" and variants2 == []


def test_multiquery_fanout_dedupes(tmp_path):
    """多路检索：两路并发 → 按 arXiv ID 去重合并，meta 记录每路命中。"""

    class MultiLLM(FakeLLM):
        def chat(self, system, user, *, temperature=None, max_tokens=None):
            if "检索" in system:
                return json.dumps(
                    {"main": "main query", "variants": ["variant query"]},
                    ensure_ascii=False)
            return json.dumps([{"i": 1, "summary": "s", "keywords": ["k"]}], ensure_ascii=False)

    overlap_pages = [
        PageItem(title="Paper A", url="https://arxiv.org/abs/2610.00001",
                 passage="A. Works.", score=0.9),
        PageItem(title="Paper B", url="https://arxiv.org/html/2610.00002v1",
                 passage="B. Works too.", score=0.8),
        PageItem(title="News", url="https://news.example.com/x", passage="n"),
    ]

    class OverlapProvider(FakeProvider):
        """两路返回相同论文集（模拟重叠召回）。"""

        def search(self, query, **kw):
            self.calls.append({"query": query})
            return SearchResponse(query=query, pages=overlap_pages, version="standard")

    settings = Settings()
    provider = OverlapProvider([])
    deps = PipelineDeps(settings=settings, provider=provider, llm=MultiLLM(),
                        db=Database(tmp_path / "d.db"))
    final = run_pipeline(deps, "中文方向")

    assert [c["query"] for c in provider.calls] == ["main query", "variant query"]  # 两路
    assert len(final["papers"]) == 2                    # 去重后仍只有 2 篇（重叠召回）
    meta = final["search_meta"]
    assert meta["planned_queries"] == ["main query", "variant query"]
    assert meta["per_query_counts"][0]["count"] == 3   # 每路原始 3 条（含非 arXiv 页）
    assert meta["version"] == "standard"


def test_multiquery_disabled_single_route(tmp_path):
    settings = Settings()
    settings.search.multi_query = False

    class MultiLLM(FakeLLM):
        def chat(self, system, user, *, temperature=None, max_tokens=None):
            if "检索" in system:
                return json.dumps({"main": "m", "variants": ["v"]}, ensure_ascii=False)
            return json.dumps([{"i": 1, "summary": "s", "keywords": ["k"]}], ensure_ascii=False)

    provider = FakeProvider(_pages())
    provider.calls.clear()
    deps = PipelineDeps(settings=settings, provider=provider, llm=MultiLLM(),
                        db=Database(tmp_path / "d.db"))
    final = run_pipeline(deps, "q")
    assert len(provider.calls) == 1                     # 关闭后单路
    assert final["search_meta"]["planned_queries"] == ["m"]


def test_enrich_fails_fast_on_connection_error(tmp_path):
    """LLM 端点不可达：批量+首篇重试失败即整体降级，不再串行放大等待。"""

    class DownLLM(FakeLLM):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def chat(self, system, user, *, temperature=None, max_tokens=None):
            self.calls += 1
            if "检索" in system:
                return "ok query"
            raise LLMError("无法连接 LLM 服务：connection refused")

    pages = [
        PageItem(title=f"P{i}", url=f"https://arxiv.org/abs/2610.0000{i}", passage=f"paper {i}. good")
        for i in range(1, 4)
    ]
    llm = DownLLM()
    deps = PipelineDeps(settings=Settings(), provider=FakeProvider(pages), llm=llm,
                        db=Database(tmp_path / "d.db"))
    final = run_pipeline(deps, "q")
    papers = final["papers"]
    assert len(papers) == 3 and all(not p.enriched for p in papers)  # 全部降级保兜底
    assert llm.calls == 3  # 1 plan + 1 批量 + 1 单篇重试后快速失败（而非 3+3 次）
