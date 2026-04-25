from unittest.mock import AsyncMock

import httpx
import pytest

from tg_parser.processing.llm.anthropic_client import AnthropicClient
from tg_parser.processing.llm.errors import AnthropicBillingError


@pytest.mark.asyncio
async def test_anthropic_credit_balance_raises_billing_error():
    client = AnthropicClient(api_key="test", max_retries=1)
    response = httpx.Response(
        400,
        request=httpx.Request("POST", AnthropicClient.BASE_URL),
        headers={"request-id": "req_123"},
        json={
            "error": {
                "type": "invalid_request_error",
                "message": "Your credit balance is too low to access the API.",
            }
        },
    )
    client._client.post = AsyncMock(return_value=response)

    with pytest.raises(AnthropicBillingError) as exc:
        await client.generate_with_usage(prompt="{}", response_format={"type": "json_object"})

    assert "credit balance" in str(exc.value).lower()
    assert exc.value.request_id == "req_123"
    await client.close()


@pytest.mark.asyncio
async def test_anthropic_other_400_remains_http_error():
    client = AnthropicClient(api_key="test", max_retries=1)
    response = httpx.Response(
        400,
        request=httpx.Request("POST", AnthropicClient.BASE_URL),
        json={"error": {"type": "invalid_request_error", "message": "Some other request error"}},
    )
    client._client.post = AsyncMock(return_value=response)

    with pytest.raises(httpx.HTTPStatusError):
        await client.generate_with_usage(prompt="{}", response_format={"type": "json_object"})
    await client.close()
