from arxiv_daily.core.nodes import extract_node_factory, fallback_keywords, one_sentence
from arxiv_daily.core.nodes.extract import _fallback_summary, normalize_date
from arxiv_daily.search.base import PageItem
from arxiv_daily.core.state import PipelineState


def _state(pages):
    return {"raw_pages": pages}


def test_extract_filters_and_dedupes():
    extract = extract_node_factory(arxiv_only=True)
    pages = [
        PageItem(title="Paper A", url="https://arxiv.org/abs/2401.11111v1",
                 date="2026-10-25", passage="We propose X. It works well.", score=0.9),
        PageItem(title="Paper A duplicate", url="https://arxiv.org/abs/2401.11111",
                 date="2026-10-25", passage="dup", score=0.8),
        PageItem(title="Blog post", url="https://blog.example.com/ml", passage="not arxiv"),
        PageItem(title="Paper B", url="https://arxiv.org/pdf/2401.22222",
                 date="2026-10-24", passage="Second sentence follows. First is here."),
    ]
    result = extract(_state(pages))
    papers = result["papers"]
    assert len(papers) == 2
    assert papers[0].arxiv_id == "2401.11111"
    assert papers[1].arxiv_id == "2401.22222"
    assert papers[0].pdf_url == "https://arxiv.org/pdf/2401.11111"
    assert papers[0].one_line_summary == "We propose X."
    assert papers[0].published_date == "2026-10-25"


def test_extract_keeps_non_arxiv_when_disabled():
    extract = extract_node_factory(arxiv_only=False)
    pages = [PageItem(title="Blog", url="https://blog.example.com/ml", passage="p")]
    papers = extract(_state(pages))["papers"]
    assert len(papers) == 1
    assert papers[0].arxiv_id == ""
    assert papers[0].pdf_url == ""


def test_one_sentence_truncates_long():
    text = "word " * 60
    out = one_sentence(text, limit=90)
    assert out.endswith("…")
    assert len(out) <= 92


def test_normalize_date():
    assert normalize_date("2026/10/22 00:00:00") == "2026-10-22"   # 元宝真实格式
    assert normalize_date("2026-10-22") == "2026-10-22"
    assert normalize_date("") == ""


def test_fallback_summary_skips_title_echo():
    title = "Better Reasoning Not Just Bigger Models Framework"
    # passage 是标题复读时应跳过，取 content
    assert _fallback_summary(title, title[:30] + " extra", "Real abstract here. More.") == "Real abstract here."
    # 两个候选都复读/为空 → 空
    assert _fallback_summary("Title", "Title", "") == ""
    assert _fallback_summary("T", "", "") == ""
    # 正常 passage
    assert _fallback_summary("T", "A novel method. It works.", "") == "A novel method."


def test_fallback_keywords():
    title = "CoT-Valve: Length-Compressible Chain of Thought for the LLM Reasoning"
    kws = fallback_keywords(title)
    assert 0 < len(kws) <= 4
    assert "CoT-Valve" in kws
    assert "of" not in kws and "for" not in kws
    assert fallback_keywords("") == []
