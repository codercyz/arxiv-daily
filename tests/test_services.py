"""服务层测试：订阅/收藏/导出/日报编排/全网解读（离线 mock）。"""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arxiv_daily.config.settings import Settings
from arxiv_daily.core.graph import PipelineDeps
from arxiv_daily.search.base import PageItem, SearchProvider, SearchResponse
from arxiv_daily.services.digest import DigestService
from arxiv_daily.services.library import export_bibtex, export_markdown
from arxiv_daily.storage.database import Database, PaperRecord

from test_graph import FakeLLM, FakeProvider  # 复用测试替身


def _paper(aid, title="T", summary="s"):
    return PaperRecord(
        arxiv_id=aid, title=title, url=f"https://arxiv.org/abs/{aid}",
        pdf_url=f"https://arxiv.org/pdf/{aid}", published_date="2026-10-26",
        one_line_summary=summary, keywords=["LLM"], passage="p", score=0.9,
    )


# ---- 主题与收藏 ----
def test_topics_crud(tmp_path):
    db = Database(tmp_path / "d.db")
    assert db.add_topic("多模态") is not None
    assert db.add_topic("多模态") is None          # 重名拒绝
    db.add_topic("RAG", query="retrieval augmented generation")
    topics = db.list_topics()
    assert [t.name for t in topics] == ["多模态", "RAG"]
    assert topics[1].query == "retrieval augmented generation"
    db.touch_topic(topics[0].id)
    assert db.list_topics()[0].last_run_at != ""
    db.delete_topic(topics[0].id)
    assert [t.name for t in db.list_topics()] == ["RAG"]


def test_star_roundtrip(tmp_path):
    db = Database(tmp_path / "d.db")
    db.save_search("q", [_paper("2401.1", "A")], llm_used=False)
    db.star("2401.1")
    assert db.is_starred("2401.1")
    assert not db.is_starred("2401.2")
    assert db.is_starred("") is False
    starred = db.list_starred()
    assert len(starred) == 1 and starred[0].title == "A"
    db.unstar("2401.1")
    assert db.list_starred() == []


# ---- 导出 ----
def test_export_bibtex():
    text = export_bibtex([_paper("2401.12345", "A Study {on} LLMs")])
    assert text.startswith("@article{240112345")
    assert "arXiv preprint arXiv:2401.12345" in text
    assert "A Study on LLMs" in text  # 花括号转义
    assert "year    = {2026}" in text


def test_export_markdown_sections():
    md = export_markdown([], title="日报", sections={"多模态": [_paper("2401.1", "P1")]})
    assert "# 日报" in md and "## 多模态" in md and "**P1**" in md


# ---- 日报编排 ----
def test_digest_refresh_topic_archives_today(tmp_path):
    from datetime import date

    db = Database(tmp_path / "d.db")
    settings = Settings()
    settings.search.freshness = "d7"  # 服务内部应固定为 d1 且关闭放宽
    topic = db.add_topic("推理")

    calls = []

    class FreshnessProbe(FakeProvider):
        def search(self, query, **kwargs):
            calls.append({"freshness": kwargs.get("freshness")})
            return SearchResponse(query=query, pages=[
                PageItem(title="Reasoning Paper", url="https://arxiv.org/abs/2610.00001",
                         date="2026/10/26 00:00:00", passage="Good paper. It works.", score=2.0),
            ])

    provider = FreshnessProbe([])
    service = DigestService(settings, db)
    captured = {}

    def builder():
        # 模拟真实链路：build_deps 使用服务改写后的 settings（d1 + 不放宽）
        cloned = captured["settings"]
        return PipelineDeps(settings=cloned, provider=provider, db=db)

    # 通过服务内部逻辑验证：直接调用并检查归档（builder 使用原 settings 时仅验证归档）
    deps = PipelineDeps(settings=settings, provider=provider, db=db)
    papers = service.refresh_topic(topic, deps_builder=lambda: deps)

    assert len(papers) == 1
    assert db.list_topics()[0].last_run_at != ""
    # 自动按论文自身日期分桶归档（2026-10-26 不落"今天"桶）
    archived = db.list_digest_day(topic.id, "2026-10-26")
    assert len(archived) == 1 and archived[0].arxiv_id == "2610.00001"
    assert db.list_digest_day(topic.id, date.today().isoformat()) == []


def test_digest_service_pins_settings_to_today(tmp_path):
    """服务的默认 deps_builder 应使用 d1 的克隆设置（日报固定当天）。"""
    import copy as _copy

    db = Database(tmp_path / "d.db")
    settings = Settings()
    settings.search.freshness = "d30"

    probe = {}

    class ProbeDeps:
        pass

    # 不真正跑流水线，只截获 build_deps 的 settings 参数
    import arxiv_daily.services.digest as digest_mod

    original_build = digest_mod.build_deps

    def fake_build(s, db, listener=None):
        probe["freshness"] = s.search.freshness
        raise _StopProbe()

    class _StopProbe(Exception):
        pass

    digest_mod.build_deps = fake_build
    try:
        DigestService(settings, db).refresh_topic(db.add_topic("t"))
    except _StopProbe:
        pass
    finally:
        digest_mod.build_deps = original_build

    from datetime import date as _d, timedelta as _td
    y = (_d.today() - _td(days=1)).isoformat()
    assert probe["freshness"] == y  # 日报=昨日单日


def test_digest_day_sorted_by_score(tmp_path):
    """日报展示排序：置顶优先，其余按相关度降序。"""
    from datetime import date

    db = Database(tmp_path / "d.db")
    topic = db.add_topic("方向S")
    day = date.today().isoformat()
    low = _paper("2401.1", "低相关"); low.score = 0.5
    mid = _paper("2401.2", "中相关"); mid.score = 1.2
    high = _paper("2401.3", "高相关"); high.score = 2.4
    pin_me = _paper("2401.4", "置顶但低分"); pin_me.score = 0.3
    db.save_digest_items(topic.id, day, [low, mid, high, pin_me])
    db.set_digest_pinned(topic.id, day, "2401.4", True)
    titles = [p.title for p in db.list_digest_day(topic.id, day)]
    assert titles == ["置顶但低分", "高相关", "中相关", "低相关"]


def test_digest_items_pin_remove_and_days(tmp_path):
    from datetime import date

    db = Database(tmp_path / "d.db")
    topic = db.add_topic("方向A")
    today = date.today().isoformat()
    papers = [_paper("2401.1", "A"), _paper("2401.2", "B"), _paper("2401.3", "C")]

    assert db.save_digest_items(topic.id, today, papers) == 3
    assert db.save_digest_items(topic.id, today, papers) == 0  # 幂等

    listed = db.list_digest_day(topic.id, today)
    assert [p.title for p in listed] == ["A", "B", "C"]

    # 置顶 B 后排最前
    db.set_digest_pinned(topic.id, today, "2401.2", True)
    assert db.is_digest_pinned(topic.id, today, "2401.2")
    assert [p.title for p in db.list_digest_day(topic.id, today)] == ["B", "A", "C"]

    # 移除 A
    db.remove_digest_item(topic.id, today, "2401.1")
    assert [p.title for p in db.list_digest_day(topic.id, today)] == ["B", "C"]
    assert db.digest_days(topic.id) == [today]
    assert db.digest_days() == [today]


def test_relax_message_stable():
    from arxiv_daily.services.digest import relax_message

    assert relax_message("2026-10-26") == relax_message("2026-10-26")
    assert all(isinstance(relax_message(d), str) for d in ("2026-10-25", "2026-10-26", "2026-10-27"))


def test_digest_raises_on_error(tmp_path):
    db = Database(tmp_path / "d.db")
    settings = Settings()
    topic = db.add_topic("x")
    service = DigestService(settings, db)
    deps = PipelineDeps(settings=settings, provider=FakeProvider(error="API Key 无效"), db=db)
    with pytest.raises(RuntimeError):
        service.refresh_topic(topic, deps_builder=lambda: deps)


# ---- papers 表 figures 字段持久化（配图功能已下线，字段保留做老库兼容） ----
def test_figures_persisted_in_db(tmp_path):
    db = Database(tmp_path / "d.db")
    paper = _paper("2505.20223", "CoT for Autonomous Driving")
    paper.figures = [{"caption": "框架图", "url": "https://arxiv.org/x.png", "kind": "method"}]
    db.save_search("q", [paper], llm_used=False)
    loaded = db.get_paper("2505.20223")
    assert loaded.figures and loaded.figures[0]["kind"] == "method"

def test_download_pdf_fallback_endpoints(tmp_path, monkeypatch):
    import arxiv_daily.downloader as dl
    from arxiv_daily.downloader import download_pdf

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "export.arxiv.org" in str(request.url):
            return httpx.Response(200, content=b"%PDF-1.4 " + b"x" * 20000)
        raise httpx.ConnectError("远程主机强迫关闭了一个现有的连接")

    real_client = httpx.Client

    def factory(**kwargs):
        kwargs.pop("proxy", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(dl.httpx, "Client", factory)
    target = download_pdf(
        "https://arxiv.org/pdf/2401.1", arxiv_id="2401.1", title="T",
        dest_dir=tmp_path, filename="2401.1.pdf",
    )
    assert target.exists() and target.stat().st_size > 10240
    assert any("export.arxiv.org" in c for c in calls)   # 已切换镜像
    assert calls[0].startswith("https://arxiv.org/pdf/2401.1")  # 先试原链


def test_digest_worker_matches_service_signature():
    """护栏：DigestWorker 对 refresh_topic 的调用不得传服务已删除的参数。"""
    import inspect

    from arxiv_daily.services.digest import DigestService
    from arxiv_daily.workers import DigestWorker

    params = set(inspect.signature(DigestService.refresh_topic).parameters)
    assert "freshness" not in params                    # 服务内部固定 d1
    call_src = inspect.getsource(DigestWorker.run)
    assert "freshness=" not in call_src                 # worker 不得再传


def test_title_truncation_rule():
    from arxiv_daily.ui.components.paper_card import PaperCard

    short = "A Short Title"
    assert PaperCard.truncate_title(short) == short
    long_title = "Word " * 40  # 200 字符
    out = PaperCard.truncate_title(long_title)
    assert 108 <= len(out) <= 111 and out.endswith("…") and not out.endswith(" …")


def test_abstract_zh_persisted(tmp_path):
    """中文摘要按篇持久化，重启（重开 DB）后仍在。"""
    db = Database(tmp_path / "d.db")
    paper = _paper("2401.7", "P")
    paper.abstract_zh = "这是翻译好的中文摘要。"
    db.save_search("q", [paper], llm_used=False)
    db.close()

    db2 = Database(tmp_path / "d.db")  # 模拟重启
    loaded = db2.get_paper("2401.7")
    assert loaded.abstract_zh == "这是翻译好的中文摘要。"


# ---- 论文配图去重 ----



# ---- 代码仓库发现（召回 + LLM 精判） ----
def _paper_repo():
    return _paper("2505.20223", "RA-CAD: Learning Post-Execution Critique")


def test_find_repos_filters_dedupes_and_sorts():
    from arxiv_daily.services.repo import find_repos

    provider = FakeProvider([
        PageItem(title="a", url="https://github.com/owner/ra-cad?tab=readme",
                 passage="official implementation", score=0.9),
        PageItem(title="b", url="https://github.com/owner/ra-cad/blob/main/x.py",
                 passage="dup of same repo", score=0.5),
        PageItem(title="c", url="https://zhihu.com/question/1", passage="解读", score=0.99),
        PageItem(title="d", url="https://github.com/other/text2cad",
                 passage="related repo", score=0.7),
    ])
    repos = find_repos(provider, _paper_repo())
    assert [r["name"] for r in repos] == ["owner/ra-cad", "other/text2cad"]  # 深层路径归一并去重
    assert repos[0]["url"] == "https://github.com/owner/ra-cad"
    assert repos[0]["score"] >= repos[1]["score"]  # score 降序
    assert provider.calls[0]["site"] == "github.com"


def test_find_repos_marks_official_by_name_rule():
    """硬规则：仓库名 == 论文项目名 → 官方并置顶；近形名不算。"""
    from arxiv_daily.services.repo import find_repos

    provider = FakeProvider([
        PageItem(title="a", url="https://github.com/other/awesome-cad-list",
                 passage="awesome list", score=0.95),
        PageItem(title="b", url="https://github.com/forgecad/forgecad-public-kit",
                 passage="ForgeCAD 官方技能包（另一个项目）", score=0.9),
        PageItem(title="c", url="https://github.com/owner/cadforge",
                 passage="CADForge is a full-stack AI tool", score=0.8),
    ])
    cad = _paper("2610.04262", "CADForge: Agentic Single-View CAD Reconstruction")
    repos = find_repos(provider, cad)
    assert repos[0]["name"] == "owner/cadforge" and repos[0]["official"] is True
    assert all(r["official"] is False for r in repos[1:])  # forgecad 近形不算

    # 首词是通用词（Learning…）时不做官方标记，只按 score 排
    generic = _paper("2505.20223", "Learning to Reason in Agents")
    repos2 = find_repos(provider, generic)
    assert all(r["official"] is False for r in repos2)
    assert repos2 == sorted(repos2, key=lambda r: -r["score"])


def test_repo_persist_and_upsert_keeps_value(tmp_path):
    db = Database(tmp_path / "d.db")
    paper = _paper_repo()
    paper.repo = [{"name": "owner/ra-cad", "url": "https://github.com/owner/ra-cad",
                   "desc": "official", "score": 0.9, "official": True}]
    db.save_search("q", [paper], llm_used=False)
    assert db.get_paper("2505.20223").repo[0]["name"] == "owner/ra-cad"

    # 搜索链路再次 upsert（repo=None）不得冲掉已发现结果
    again = _paper_repo()
    again.repo = None
    db.upsert_papers([again])
    assert db.get_paper("2505.20223").repo[0]["name"] == "owner/ra-cad"

    # 搜过没有（[]）的语义也要保留
    empty = _paper("2610.08647", "SquidAgent")
    empty.repo = []
    db.save_search("q2", [empty], llm_used=False)
    db.upsert_papers([_paper("2610.08647", "SquidAgent")])  # repo=None 覆盖尝试
    assert db.get_paper("2610.08647").repo == []


# ---- AI 周报 ----
def test_weekly_material_and_cache(tmp_path):
    from datetime import date, timedelta

    from arxiv_daily.services.weekly import build_material, generate_weekly, week_start

    db = Database(tmp_path / "d.db")
    topic = db.add_topic("多智能体框架")
    papers = [_paper(f"2610.05{i:03d}", f"Agent Paper {i}") for i in range(10)]
    for i, p in enumerate(papers):
        p.one_line_summary = f"摘要{i}"
        p.keywords = ["agent", f"kw{i}"]
        p.score = 0.9 - i * 0.01
    db.save_digest_items(topic.id, date.today().isoformat(), papers)

    total, material = build_material(db)
    assert total == 10
    assert "方向：多智能体框架" in material
    assert "[1] Agent Paper 0" in material          # score 最高者编号 1
    assert "关键词：agent、kw0" in material

    # 生成 + 缓存命中（FakeLLM 直接透传 user 长度作标记）
    class _EchoLLM:
        configured = True
        def chat(self, system, user, *, temperature=None, max_tokens=None):
            assert "硬性约束" in user and "细分方向" in user   # 提示词结构完整
            return "# 本周看点\n" + "很热闹。" * 150

    ws = week_start()
    content1 = generate_weekly(db, _EchoLLM())
    assert db.get_weekly_report(ws) == content1
    content2 = generate_weekly(db, None)             # 缓存命中，不碰 LLM
    assert content2 == content1


def test_weekly_insufficient_material(tmp_path):
    from datetime import date

    from arxiv_daily.services.weekly import WeeklyError, generate_weekly

    db = Database(tmp_path / "d.db")
    topic = db.add_topic("冷门方向")
    db.save_digest_items(topic.id, date.today().isoformat(), [_paper("2610.00001", "Only One")])
    with pytest.raises(WeeklyError, match="仅 1 篇"):
        generate_weekly(db, object())
