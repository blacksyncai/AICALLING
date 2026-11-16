import asyncio

import httpx
import pytest


@pytest.mark.parametrize('body, expected', [
    ({'error': {'message': 'private-provider-message-' * 100, 'code': 'insufficient_quota'}}, 'insufficient_quota'),
    ({'error': {'type': 'invalid_api_key'}}, 'invalid_api_key'),
    ({'error': 'not an object'}, None),
])
def test_chat_preserves_error_code_without_retaining_provider_message(monkeypatch, body, expected):
    from app.config import settings
    from app.services import llm
    monkeypatch.setattr(settings, 'openai_api_key', 'unit-test-only')
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(429, json=body))
    monkeypatch.setattr(llm.httpx, 'AsyncClient', lambda **kwargs: original(transport=transport, **kwargs))
    async def run():
        with pytest.raises(llm.LLMRequestError) as caught:
            await llm._chat({'model': 'gpt-4.1-mini', 'messages': []})
        assert caught.value.status_code == 429
        assert caught.value.error_code == expected
        assert 'private-provider-message' not in str(caught.value)
        assert 'unit-test-only' not in str(caught.value)
    asyncio.run(run())
