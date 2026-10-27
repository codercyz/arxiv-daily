import json

from arxiv_daily.storage.database import Database, PaperRecord


def make_db(tmp_path):
    return Database(tmp_path / "data.db")


def paper(aid, title="T", summary="s"):
    return PaperRecord(
        arxiv_id=aid, title=title, url=f"https://arxiv.org/abs/{aid}",
        pdf_url=f"https://arxiv.org/pdf/{aid}", one_line_summary=summary,
        keywords=["LLM"], passage="p", score=0.9,
    )


def test_save_and_query(tmp_path):
    db = make_db(tmp_path)
    sid = db.save_search("大模型推理", [paper("2401.1", "A"), paper("2401.2", "B")], llm_used=True)
    searches = db.list_searches()
    assert len(searches) == 1
    assert searches[0].query == "大模型推理"
    assert searches[0].result_count == 2
    assert searches[0].llm_used

    papers = db.get_papers(sid)
    assert [p.title for p in papers] == ["A", "B"]

    single = db.get_paper("2401.1")
    assert single.keywords == ["LLM"]


def test_upsert_updates_existing_paper(tmp_path):
    db = make_db(tmp_path)
    db.save_search("q1", [paper("2401.1", "Old title", "old")], llm_used=False)
    sid2 = db.save_search("q2", [paper("2401.1", "New title", "new")], llm_used=False)
    assert db.get_paper("2401.1").title == "New title"
    assert len(db.list_searches()) == 2
    assert len(db.get_papers(sid2)) == 1


def test_prune_history(tmp_path):
    db = make_db(tmp_path)
    for i in range(5):
        db.save_search(f"q{i}", [paper(f"2401.{i}")], llm_used=False)
    db.prune_history(2)
    searches = db.list_searches()
    assert len(searches) == 2
    # 关联表已清理
    total_links = sum(len(db.get_papers(s.id)) for s in searches)
    assert total_links == 2


def test_delete_search(tmp_path):
    db = make_db(tmp_path)
    sid = db.save_search("q", [paper("2401.9")], llm_used=False)
    db.delete_search(sid)
    assert db.list_searches() == []
    # 论文本体保留（跨搜索去重复用）
    assert db.get_paper("2401.9") is not None
