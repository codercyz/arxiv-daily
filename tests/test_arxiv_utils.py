from arxiv_daily.utils.arxiv import extract_arxiv_id, pdf_url_for


def test_extract_from_common_urls():
    assert extract_arxiv_id("https://arxiv.org/abs/2401.12345") == "2401.12345"
    assert extract_arxiv_id("https://arxiv.org/abs/2401.12345v2") == "2401.12345"
    assert extract_arxiv_id("http://arxiv.org/pdf/2310.06692v3") == "2310.06692"
    assert (
        extract_arxiv_id("https://export.arxiv.org/abs/2503.09999")
        == "2503.09999"
    )


def test_extract_from_snippet_text():
    assert extract_arxiv_id("arXiv:2401.12345v1 [cs.CL] 22 Jan 2024") == "2401.12345"


def test_extract_negative():
    assert extract_arxiv_id("https://example.com/paper") is None
    assert extract_arxiv_id("") is None


def test_pdf_url():
    assert pdf_url_for("2401.12345") == "https://arxiv.org/pdf/2401.12345"
