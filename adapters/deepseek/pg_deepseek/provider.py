from __future__ import annotations

import json
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from pg_engine_contracts import LLMProvider

T = TypeVar("T", bound=BaseModel)


class DeepSeekProviderError(RuntimeError):
    pass


class DeepSeekProvider(LLMProvider):
    """OpenAI-compatible DeepSeek provider with schema validation + one repair pass."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())

    async def _complete(self, messages: list[dict], *, response_format: dict | None = None) -> str:
        if not self.configured:
            raise DeepSeekProviderError("DEEPSEEK_API_KEY is not configured")
        payload = {"model": self.model, "messages": messages, "temperature": 0.2}
        if response_format:
            payload["response_format"] = response_format
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
        if response.status_code >= 400:
            raise DeepSeekProviderError(f"DeepSeek HTTP {response.status_code}: {response.text[:500]}")
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DeepSeekProviderError("DeepSeek response shape is invalid") from exc

    async def text(self, prompt: str, *, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self._complete(messages)

    async def structured(self, prompt: str, schema: type[T], *, system: str | None = None) -> T:
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        full_prompt = (
            f"{prompt}\n\nReturn ONLY valid JSON matching this JSON Schema:\n{schema_json}"
        )
        raw = await self.text(full_prompt, system=system)
        for attempt in range(2):
            try:
                return schema.model_validate_json(raw)
            except ValidationError as exc:
                if attempt == 1:
                    raise DeepSeekProviderError(f"structured output invalid after repair: {exc}") from exc
                repair = (
                    "Repair the following output into ONLY valid JSON matching the schema. "
                    "Do not add facts.\n\nSCHEMA:\n"
                    + schema_json
                    + "\n\nINVALID OUTPUT:\n"
                    + raw
                )
                raw = await self.text(repair, system="You repair JSON strictly and conservatively.")
        raise DeepSeekProviderError("unreachable")
