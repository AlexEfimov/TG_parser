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
    post_mock = AsyncMock(return_value=response)
    client._client.post = post_mock

    with pytest.raises(AnthropicBillingError) as exc:
        await client.generate_with_usage(prompt="{}", response_format={"type": "json_object"})

    assert "credit balance" in str(exc.value).lower()
    assert exc.value.request_id == "req_123"
    # Contract: AnthropicBillingError MUST short-circuit the retry loop. A retry
    # would mean wasted requests against an already-exhausted credit pool.
    assert post_mock.await_count == 1, (
        f"AnthropicBillingError must not be retried; got {post_mock.await_count} POSTs"
    )
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


@pytest.mark.asyncio
async def test_anthropic_400_with_malformed_body_falls_back_to_http_error():
    """If body isn't JSON we must still raise — never silently swallow a 400."""
    client = AnthropicClient(api_key="test", max_retries=1)
    response = httpx.Response(
        400,
        request=httpx.Request("POST", AnthropicClient.BASE_URL),
        text="<html>gateway error</html>",
    )
    client._client.post = AsyncMock(return_value=response)

    with pytest.raises(httpx.HTTPStatusError):
        await client.generate_with_usage(prompt="{}", response_format={"type": "json_object"})
    await client.close()


@pytest.mark.asyncio
async def test_anthropic_credit_balance_case_insensitive():
    """Billing detection must be case-insensitive — Anthropic may change copy."""
    client = AnthropicClient(api_key="test", max_retries=1)
    response = httpx.Response(
        400,
        request=httpx.Request("POST", AnthropicClient.BASE_URL),
        json={
            "error": {
                "type": "invalid_request_error",
                "message": "Your CREDIT BALANCE is too low.",
            }
        },
    )
    client._client.post = AsyncMock(return_value=response)

    with pytest.raises(AnthropicBillingError):
        await client.generate_with_usage(prompt="{}", response_format={"type": "json_object"})
    await client.close()
