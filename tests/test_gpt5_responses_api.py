"""
Tests for GPT-5 Responses API support (Session 23).

Tests:
- Routing to /responses for gpt-5.* models
- Routing to /chat/completions for other models
- Payload format for Responses API
- Response parsing from Responses API
"""

import json

import httpx
import pytest
from unittest.mock import AsyncMock, Mock, patch

from tg_parser.processing.llm.openai_client import OpenAIClient


@pytest.fixture
def openai_client_gpt5():
    """OpenAI client with GPT-5 model."""
    return OpenAIClient(
        api_key="sk-test-key",
        model="gpt-5.2",
        reasoning_effort="medium",
        verbosity="high",
    )


@pytest.fixture
def openai_client_gpt4():
    """OpenAI client with GPT-4 model."""
    return OpenAIClient(
        api_key="sk-test-key",
        model="gpt-4o-mini",
    )


def test_is_gpt5_model_detection(openai_client_gpt5, openai_client_gpt4):
    """Test GPT-5 model detection."""
    assert openai_client_gpt5._is_gpt5_model() is True
    assert openai_client_gpt4._is_gpt5_model() is False
    
    # Test other GPT-5 variants
    client_mini = OpenAIClient(api_key="sk-test", model="gpt-5-mini")
    assert client_mini._is_gpt5_model() is True
    
    client_nano = OpenAIClient(api_key="sk-test", model="gpt-5-nano")
    assert client_nano._is_gpt5_model() is True


@pytest.mark.asyncio
async def test_gpt5_uses_responses_api(openai_client_gpt5):
    """Test that GPT-5 models route to /responses endpoint."""
    # Mock the HTTP client
    mock_response = Mock()
    mock_response.json.return_value = {
        "output_text": "Test response",
        "finish_reason": "stop",
    }
    mock_response.raise_for_status = Mock()
    
    with patch.object(openai_client_gpt5.client, "post", new=AsyncMock(return_value=mock_response)) as mock_post:
        result = await openai_client_gpt5.generate(
            prompt="Test prompt",
            system_prompt="System prompt",
        )
        
        # Check that /responses was called
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0].endswith("/responses")
        
        # Check payload format
        payload = call_args[1]["json"]
        assert "reasoning" in payload
        assert payload["reasoning"]["effort"] == "medium"
        assert payload["verbosity"] == "high"
        assert payload["model"] == "gpt-5.2"
        
        # Check result
        assert result == "Test response"


@pytest.mark.asyncio
async def test_gpt4_uses_chat_completions(openai_client_gpt4):
    """Test that GPT-4 models route to /chat/completions endpoint."""
    # Mock the HTTP client
    mock_response = Mock()
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {"content": "Test response"},
                "finish_reason": "stop",
            }
        ]
    }
    mock_response.raise_for_status = Mock()
    
    with patch.object(openai_client_gpt4.client, "post", new=AsyncMock(return_value=mock_response)) as mock_post:
        result = await openai_client_gpt4.generate(
            prompt="Test prompt",
            system_prompt="System prompt",
        )
        
        # Check that /chat/completions was called
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0].endswith("/chat/completions")
        
        # Check payload format (should NOT have reasoning/verbosity)
        payload = call_args[1]["json"]
        assert "reasoning" not in payload
        assert "verbosity" not in payload
        assert "messages" in payload
        
        # Check result
        assert result == "Test response"


@pytest.mark.asyncio
async def test_responses_api_payload_format(openai_client_gpt5):
    """Test Responses API request payload format."""
    mock_response = Mock()
    mock_response.json.return_value = {"output_text": "Test"}
    mock_response.raise_for_status = Mock()
    
    with patch.object(openai_client_gpt5.client, "post", new=AsyncMock(return_value=mock_response)) as mock_post:
        await openai_client_gpt5.generate(
            prompt="User prompt",
            system_prompt="System prompt",
            temperature=0.5,
            max_tokens=2000,
        )
        
        payload = mock_post.call_args[1]["json"]
        
        # Check all required fields
        assert payload["model"] == "gpt-5.2"
        assert payload["temperature"] == 0.5
        assert payload["max_tokens"] == 2000
        assert len(payload["messages"]) == 2
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][0]["content"] == "System prompt"
        assert payload["messages"][1]["role"] == "user"
        assert payload["messages"][1]["content"] == "User prompt"
        assert payload["reasoning"]["effort"] == "medium"
        assert payload["verbosity"] == "high"


@pytest.mark.asyncio
async def test_responses_api_response_parsing_output_text(openai_client_gpt5):
    """Test parsing Responses API response with output_text field."""
    mock_response = Mock()
    mock_response.json.return_value = {
        "output_text": "This is the response text",
        "finish_reason": "stop",
    }
    mock_response.raise_for_status = Mock()
    
    with patch.object(openai_client_gpt5.client, "post", new=AsyncMock(return_value=mock_response)):
        result = await openai_client_gpt5.generate(prompt="Test")
        
        assert result == "This is the response text"


@pytest.mark.asyncio
async def test_responses_api_response_parsing_choices(openai_client_gpt5):
    """Test parsing Responses API response with choices structure."""
    mock_response = Mock()
    mock_response.json.return_value = {
        "choices": [
            {
                "output_text": "Response from choices",
                "finish_reason": "stop",
            }
        ]
    }
    mock_response.raise_for_status = Mock()
    
    with patch.object(openai_client_gpt5.client, "post", new=AsyncMock(return_value=mock_response)):
        result = await openai_client_gpt5.generate(prompt="Test")
        
        assert result == "Response from choices"


@pytest.mark.asyncio
async def test_responses_api_invalid_response(openai_client_gpt5):
    """Test error handling for invalid Responses API response."""
    mock_response = Mock()
    mock_response.json.return_value = {
        "invalid_field": "no output_text",
    }
    mock_response.raise_for_status = Mock()
    
    with patch.object(openai_client_gpt5.client, "post", new=AsyncMock(return_value=mock_response)):
        with pytest.raises(ValueError, match="Invalid Responses API format"):
            await openai_client_gpt5.generate(prompt="Test")


def test_gpt5_client_initialization():
    """Test GPT-5 client initialization with reasoning parameters."""
    client = OpenAIClient(
        api_key="sk-test",
        model="gpt-5.2",
        reasoning_effort="high",
        verbosity="medium",
    )
    
    assert client.model == "gpt-5.2"
    assert client.reasoning_effort == "high"
    assert client.verbosity == "medium"
    assert client._is_gpt5_model() is True


def test_default_reasoning_parameters():
    """Test default reasoning parameters for GPT-5."""
    client = OpenAIClient(
        api_key="sk-test",
        model="gpt-5-mini",
    )
    
    # Defaults from __init__
    assert client.reasoning_effort == "low"
    assert client.verbosity == "low"

