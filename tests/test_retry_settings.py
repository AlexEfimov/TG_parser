"""
Tests for RetrySettings integration (Session 23).

Tests:
- RetrySettings loading from ENV
- Validation of constraints (ge/le)
- Integration with pipeline retry logic
"""

import os

import pytest
from pydantic import ValidationError

from tg_parser.config.settings import RetrySettings


def test_retry_settings_defaults():
    """Test RetrySettings default values."""
    settings = RetrySettings()
    
    assert settings.max_attempts == 3
    assert settings.backoff_base == 1.0
    assert settings.backoff_max == 60.0
    assert settings.jitter == 0.3


def test_retry_settings_from_env(monkeypatch):
    """Test loading RetrySettings from environment variables."""
    # Set environment variables
    monkeypatch.setenv("RETRY_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("RETRY_BACKOFF_BASE", "2.0")
    monkeypatch.setenv("RETRY_BACKOFF_MAX", "120.0")
    monkeypatch.setenv("RETRY_JITTER", "0.5")
    
    # Reload settings
    settings = RetrySettings()
    
    assert settings.max_attempts == 5
    assert settings.backoff_base == 2.0
    assert settings.backoff_max == 120.0
    assert settings.jitter == 0.5


def test_retry_settings_max_attempts_validation():
    """Test max_attempts validation (ge=1, le=10)."""
    # Valid values
    settings = RetrySettings(max_attempts=1)
    assert settings.max_attempts == 1
    
    settings = RetrySettings(max_attempts=10)
    assert settings.max_attempts == 10
    
    # Invalid: less than 1
    with pytest.raises(ValidationError):
        RetrySettings(max_attempts=0)
    
    # Invalid: greater than 10
    with pytest.raises(ValidationError):
        RetrySettings(max_attempts=11)


def test_retry_settings_backoff_base_validation():
    """Test backoff_base validation (ge=0.1, le=60.0)."""
    # Valid values
    settings = RetrySettings(backoff_base=0.1)
    assert settings.backoff_base == 0.1
    
    settings = RetrySettings(backoff_base=60.0)
    assert settings.backoff_base == 60.0
    
    # Invalid: less than 0.1
    with pytest.raises(ValidationError):
        RetrySettings(backoff_base=0.05)
    
    # Invalid: greater than 60.0
    with pytest.raises(ValidationError):
        RetrySettings(backoff_base=61.0)


def test_retry_settings_backoff_max_validation():
    """Test backoff_max validation (ge=1.0, le=300.0)."""
    # Valid values
    settings = RetrySettings(backoff_max=1.0)
    assert settings.backoff_max == 1.0
    
    settings = RetrySettings(backoff_max=300.0)
    assert settings.backoff_max == 300.0
    
    # Invalid: less than 1.0
    with pytest.raises(ValidationError):
        RetrySettings(backoff_max=0.5)
    
    # Invalid: greater than 300.0
    with pytest.raises(ValidationError):
        RetrySettings(backoff_max=301.0)


def test_retry_settings_jitter_validation():
    """Test jitter validation (ge=0.0, le=1.0)."""
    # Valid values
    settings = RetrySettings(jitter=0.0)
    assert settings.jitter == 0.0
    
    settings = RetrySettings(jitter=1.0)
    assert settings.jitter == 1.0
    
    # Invalid: less than 0.0
    with pytest.raises(ValidationError):
        RetrySettings(jitter=-0.1)
    
    # Invalid: greater than 1.0
    with pytest.raises(ValidationError):
        RetrySettings(jitter=1.1)


@pytest.mark.asyncio
async def test_retry_settings_integration_with_pipeline():
    """Test that pipeline uses retry_settings for retry logic."""
    from unittest.mock import AsyncMock, Mock, patch
    from tg_parser.config import retry_settings
    from tg_parser.domain.models import RawTelegramMessage
    from tg_parser.processing.pipeline import ProcessingPipelineImpl
    
    # Create mock LLM client that always fails
    mock_llm = Mock()
    mock_llm.model = "test-model"
    mock_llm.compute_prompt_id = Mock(return_value="test-prompt-id")
    mock_llm.generate = AsyncMock(side_effect=Exception("LLM error"))
    
    # Create mock repos
    mock_doc_repo = Mock()
    mock_doc_repo.exists = AsyncMock(return_value=False)
    
    mock_failure_repo = Mock()
    mock_failure_repo.record_failure = AsyncMock()
    
    # Create pipeline
    pipeline = ProcessingPipelineImpl(
        llm_client=mock_llm,
        processed_doc_repo=mock_doc_repo,
        failure_repo=mock_failure_repo,
    )
    
    # Create test message
    from datetime import datetime, UTC
    message = RawTelegramMessage(
        id="msg_1",
        channel_id="test_channel",
        text="Test message",
        message_type="post",
        date=datetime.now(UTC),
        source_ref="tg:test_channel:post:1",
    )
    
    # Try to process (should fail after max_attempts)
    with pytest.raises(Exception, match="LLM error"):
        await pipeline.process_message(message)
    
    # Check that LLM was called retry_settings.max_attempts times
    assert mock_llm.generate.call_count == retry_settings.max_attempts
    
    # Check that failure was recorded
    mock_failure_repo.record_failure.assert_called_once()
    call_args = mock_failure_repo.record_failure.call_args[1]
    assert call_args["attempts"] == retry_settings.max_attempts


def test_retry_settings_env_prefix():
    """Test that RetrySettings uses RETRY_ prefix for env vars."""
    settings = RetrySettings()
    
    # Check that model_config has env_prefix
    assert settings.model_config.get("env_prefix") == "RETRY_"


def test_retry_settings_backoff_calculation():
    """Test exponential backoff calculation with settings."""
    settings = RetrySettings(
        backoff_base=1.0,
        backoff_max=10.0,
        jitter=0.0,  # No jitter for deterministic test
    )
    
    # Calculate backoff for different attempts
    # Formula: min(backoff_base * (2 ** (attempt - 1)), backoff_max)
    
    # Attempt 1: 1.0 * 2^0 = 1.0
    backoff_1 = min(settings.backoff_base * (2 ** 0), settings.backoff_max)
    assert backoff_1 == 1.0
    
    # Attempt 2: 1.0 * 2^1 = 2.0
    backoff_2 = min(settings.backoff_base * (2 ** 1), settings.backoff_max)
    assert backoff_2 == 2.0
    
    # Attempt 3: 1.0 * 2^2 = 4.0
    backoff_3 = min(settings.backoff_base * (2 ** 2), settings.backoff_max)
    assert backoff_3 == 4.0
    
    # Attempt 4: 1.0 * 2^3 = 8.0
    backoff_4 = min(settings.backoff_base * (2 ** 3), settings.backoff_max)
    assert backoff_4 == 8.0
    
    # Attempt 5: 1.0 * 2^4 = 16.0, but capped at backoff_max=10.0
    backoff_5 = min(settings.backoff_base * (2 ** 4), settings.backoff_max)
    assert backoff_5 == 10.0

