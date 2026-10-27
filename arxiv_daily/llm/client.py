"""OpenAI 兼容 LLM 客户端（火山方舟 / DeepSeek / OpenAI 等均可）。

仅依赖 ``base_url + api_key + model`` 三项用户配置，
用于检索词规划与论文中文摘要生成；未配置或调用失败时流水线自动降级。
"""

from __future__ import annotations

import httpx
from openai import APIConnectionError, OpenAI

from ..config.settings import LLMSettings


class LLMError(Exception):
    def __init__(self, message: str, *, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail


class LLMClient:
    def __init__(self, settings: LLMSettings, proxy: str = ""):
        self._settings = settings
        self._proxy = proxy
        self.last_usage: dict = {}   # 最近一次调用的 {prompt, completion}
        self.total_usage: dict = {"prompt": 0, "completion": 0, "calls": 0}  # 实例累计
        self._client: OpenAI | None = None

    @property
    def configured(self) -> bool:
        return self._settings.ready

    def _openai(self) -> OpenAI:
        # 复用连接：线程安全，省去每次调用的 TLS 握手
        if self._client is None:
            http_client = httpx.Client(
                timeout=self._settings.timeout, proxy=self._proxy or None
            )
            self._client = OpenAI(
                base_url=self._settings.base_url.strip(),
                api_key=self._settings.api_key.strip(),
                http_client=http_client,
            )
        return self._client

    def chat(self, system: str, user: str, *, temperature: float | None = None,
             max_tokens: int | None = None) -> str:
        """一次对话补全，失败抛 :class:`LLMError`。

        ``max_tokens`` 可按调用覆写（批量摘要需要更大的输出窗口）。
        """
        kwargs = dict(
            model=self._settings.model.strip(),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=(
                self._settings.temperature if temperature is None else temperature
            ),
            max_tokens=max_tokens or self._settings.max_tokens,
        )
        if self._settings.disable_thinking:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        try:
            try:
                completion = self._openai().chat.completions.create(**kwargs)
            except Exception as exc:
                if "thinking" not in str(exc).lower() and "parameter" not in str(exc).lower():
                    raise
                kwargs.pop("extra_body", None)  # 端点不支持该参数时回退
                completion = self._openai().chat.completions.create(**kwargs)
        except APIConnectionError as exc:
            raise LLMError(
                f"无法连接 LLM 服务：{exc}", detail=str(exc)
            ) from exc
        except Exception as exc:
            raise LLMError(f"LLM 调用失败：{exc}", detail=str(exc)) from exc
        content = completion.choices[0].message.content if completion.choices else ""
        usage = getattr(completion, "usage", None)
        if usage is not None:
            self.last_usage = {
                "prompt": getattr(usage, "prompt_tokens", 0) or 0,
                "completion": getattr(usage, "completion_tokens", 0) or 0,
            }
            self.total_usage["prompt"] += self.last_usage["prompt"]
            self.total_usage["completion"] += self.last_usage["completion"]
            self.total_usage["calls"] += 1
        return (content or "").strip()

    def list_models(self) -> list[str]:
        try:
            page = self._openai().models.list()
            return sorted(m.id for m in page.data)
        except Exception as exc:
            raise LLMError(f"获取模型列表失败：{exc}", detail=str(exc)) from exc

    def test_connection(self) -> str:
        try:
            models = self.list_models()
        except LLMError as exc:
            raise LLMError(f"连接失败：{exc.message}", detail=exc.detail) from exc
        hint = f"连接成功，可见 {len(models)} 个模型"
        if self._settings.model.strip():
            try:
                reply = self.chat(
                    "You are a connectivity probe.", "Reply with the single word: ok"
                )
                hint += f"；模型 {self._settings.model.strip()} 可用（回复：{reply[:20]}）"
            except LLMError as exc:
                hint += f"；但模型对话失败：{exc.message}"
        else:
            hint += "；尚未选择模型，请从下拉列表选择"
        return hint
