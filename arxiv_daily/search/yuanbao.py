"""元宝搜索（腾讯云 wsa）SearchPro 实现。

API KEY 方式接入：
- POST ``{base_url}/SearchPro``（默认 ``https://api.wsa.cloud.tencent.com``）
- Header ``Authorization: Bearer sk-xxx``
- 请求体 ``{"Query": "...", "Cnt": 20, "Mode": 2, "Industry": "acad",
  "Site": "arxiv.org", "Freshness": "d7"}``
- 响应 ``{"Response": {"Query", "Pages": ["<json 字符串>", ...],
  "Version", "Msg", "RequestId"}}``，错误时 ``Response.Error.{Code,Message}``

文档：https://cloud.tencent.com/document/product/1806/121811
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from ..config.settings import SearchSettings
from .base import PageItem, SearchProvider, SearchResponse, SearchError

_ERROR_MESSAGES: dict[str, str] = {
    "UnauthorizedOperation": "API Key 无效或未授权，请在「设置 → 联网搜索」检查。",
    "ResourceNotFound": "搜索服务未开通，请先在服务控制台开通。",
    "ResourceUnavailable": "服务不可用（账号可能欠费），请检查腾讯云账户状态。",
    "RequestLimitExceeded": "请求频率超限，请稍后重试或降低并发。",
    "InvalidParameter": "请求参数不合法，请检查设置中的搜索参数。",
    "InternalError": "搜索服务内部错误，请稍后重试。",
}


class YuanbaoSearchProvider(SearchProvider):
    name = "yuanbao"
    display_name = "联网搜索服务"

    def __init__(self, settings: SearchSettings, proxy: str = "", transport: httpx.BaseTransport | None = None):
        self._settings = settings
        self._proxy = proxy
        self._transport = transport  # 测试注入 MockTransport

    # ---- 内部 ----
    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self._settings.timeout,
            proxy=self._proxy or None,
            transport=self._transport,
            headers={
                "Authorization": f"Bearer {self._settings.api_key.strip()}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = self._settings.base_url.rstrip("/") + "/SearchPro"
        last_error: Exception | None = None
        for attempt in range(self._settings.max_retries + 1):
            try:
                with self._client() as client:
                    resp = client.post(url, json=payload)
                body = resp.json()
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self._settings.max_retries:
                    time.sleep(0.8 * (attempt + 1))
                    continue
                raise SearchError(
                    f"网络请求失败：{exc}", code="NetworkError", detail=str(exc)
                ) from exc
            except json.JSONDecodeError as exc:
                raise SearchError(
                    f"服务返回了无法解析的响应（HTTP {resp.status_code}）",
                    code="BadResponse",
                    detail=str(exc),
                ) from exc

            envelope = body.get("Response", {}) if isinstance(body, dict) else {}
            if not isinstance(envelope, dict):
                raise SearchError("服务响应格式异常", code="BadResponse")
            error = envelope.get("Error")
            if isinstance(error, dict):
                code = str(error.get("Code") or "")
                message = _ERROR_MESSAGES.get(
                    code, f"搜索失败：{error.get('Message') or code}"
                )
                # 限流做一次退避重试，其余直接失败
                if code == "RequestLimitExceeded" and attempt < self._settings.max_retries:
                    time.sleep(1.0 * (attempt + 1))
                    last_error = SearchError(message, code=code)
                    continue
                raise SearchError(message, code=code, detail=str(error.get("Message") or ""))
            return envelope
        raise SearchError(
            f"请求失败：{last_error}", code="NetworkError", detail=str(last_error)
        )

    # ---- 接口实现 ----
    def search(
        self,
        query: str,
        *,
        cnt: int = 20,
        mode: int = 2,
        industry: str = "acad",
        site: str = "",
        freshness: str = "",
    ) -> SearchResponse:
        payload: dict[str, Any] = {"Query": query, "Cnt": cnt, "Mode": mode}
        if industry:
            payload["Industry"] = industry
        if site:
            payload["Site"] = site
        if freshness:
            payload["Freshness"] = freshness

        envelope = self._post(payload)
        pages: list[PageItem] = []
        for item in envelope.get("Pages") or []:
            try:
                raw = json.loads(item) if isinstance(item, str) else item
            except json.JSONDecodeError:
                continue
            if isinstance(raw, dict):
                pages.append(PageItem.from_raw(raw))
        return SearchResponse(
            query=str(envelope.get("Query") or query),
            pages=pages,
            version=str(envelope.get("Version") or ""),
            request_id=str(envelope.get("RequestId") or ""),
            raw=envelope,
        )

    def test_connection(self) -> str:
        start = time.perf_counter()
        response = self.search("arxiv", cnt=10)
        latency = (time.perf_counter() - start) * 1000
        version = response.version or "未知版本"
        return f"连接成功：{self.display_name}（{version}，{latency:.0f} ms，返回 {len(response.pages)} 条结果）"


def get_provider(settings: SearchSettings, proxy: str = "") -> SearchProvider:
    """按设置返回搜索 Provider；v1 仅支持元宝搜索。"""
    if settings.provider != YuanbaoSearchProvider.name:
        raise SearchError(
            f"暂不支持的搜索提供商：{settings.provider}，当前仅支持内置搜索服务。",
            code="UnsupportedProvider",
        )
    return YuanbaoSearchProvider(settings, proxy=proxy)
