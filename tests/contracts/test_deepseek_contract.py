from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from pg_deepseek import DeepSeekProvider


class TinySchema(BaseModel):
    value: str


@pytest.mark.asyncio
async def test_deepseek_structured_output_repairs_once():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        payload = json.loads(request.content.decode())
        seen.append(payload)
        if len(seen) == 1:
            content = "not-json"
        else:
            content = '{"value":"fixed"}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    provider = DeepSeekProvider(
        "test-key",
        "https://api.deepseek.test",
        "deepseek-chat",
        transport=httpx.MockTransport(handler),
    )
    result = await provider.structured("return a tiny object", TinySchema)
    assert result.value == "fixed"
    assert len(seen) == 2
    assert "Repair the following output" in seen[1]["messages"][-1]["content"]
