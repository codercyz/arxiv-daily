"""元宝搜索客户端：响应解析与错误映射（httpx.MockTransport，全程离线）。"""

import json

import httpx
import pytest

from arxiv_daily.config.settings import SearchSettings
from arxiv_daily.search.base import SearchError
from arxiv_daily.search.yuanbao import YuanbaoSearchProvider, get_provider


def _envelope(pages=None, error=None):
    response = {"Query": "q", "Version": "standard", "RequestId": "req-1"}
    if pages is not None:
        response["Pages"] = [json.dumps(p, ensure_ascii=False) for p in pages]
    if error:
        response["Error"] = error
    return {"Response": response}


def _mock(body: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/SearchPro"
        assert request.headers["Authorization"] == "Bearer sk-test"
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


def _provider(body: dict, retries: int = 0) -> YuanbaoSearchProvider:
    return YuanbaoSearchProvider(
        SearchSettings(api_key="sk-test", max_retries=retries),
        transport=_mock(body),
    )


def test_search_parses_pages():
    provider = _provider(
        _envelope(
            pages=[
                {"title": "P1", "url": "https://arxiv.org/abs/2401.1", "date": "2026-10-26",
                 "passage": "摘要甲", "content": "动态摘要", "site": "arxiv.org", "score": 0.9},
                {"title": "P2", "url": "https://arxiv.org/abs/2401.2", "passage": "摘要乙", "score": 0.5},
                "not-a-json",
            ]
        )
    )
    resp = provider.search("q", cnt=20)
    assert resp.version == "standard"
    assert len(resp.pages) == 2  # 坏条目被跳过
    assert resp.pages[0].passage == "摘要甲"
    assert resp.pages[0].score == 0.9


def test_search_sends_expected_payload():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json=_envelope(pages=[]))

    provider = YuanbaoSearchProvider(
        SearchSettings(api_key="sk-test"), transport=httpx.MockTransport(handler)
    )
    provider.search("LLM reasoning", cnt=30, site="arxiv.org", freshness="d7")
    assert captured["json"] == {
        "Query": "LLM reasoning",
        "Cnt": 30,
        "Mode": 2,
        "Industry": "acad",
        "Site": "arxiv.org",
        "Freshness": "d7",
    }


def test_error_mapping_unauthorized():
    provider = _provider(
        _envelope(error={"Code": "UnauthorizedOperation", "Message": "auth fail"})
    )
    with pytest.raises(SearchError) as ei:
        provider.search("q")
    assert "API Key" in ei.value.message
    assert ei.value.code == "UnauthorizedOperation"


def test_error_mapping_service_unavailable():
    provider = _provider(_envelope(error={"Code": "ResourceUnavailable", "Message": "x"}))
    with pytest.raises(SearchError) as ei:
        provider.search("q")
    assert "不可用" in ei.value.message


def test_get_provider_rejects_unknown():
    with pytest.raises(SearchError):
        get_provider(SearchSettings(provider="nope"))
