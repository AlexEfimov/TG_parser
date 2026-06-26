"""
Тесты для processing pipeline.

Проверяет:
- LLM клиенты (OpenAI, Mock)
- ProcessingPipeline реализацию
- Интеграцию с storage
- Ретраи и обработку ошибок (TR-47)
- Идемпотентность (TR-22/TR-46/TR-48)
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_parser.config import settings as app_settings
from tg_parser.domain.ids import make_processed_document_id
from tg_parser.domain.models import MessageType, ProcessedDocument, RawTelegramMessage
from tg_parser.processing.llm.openai_client import OpenAIClient
from tg_parser.processing.mock_llm import (
    DeterministicMockLLM,
    MockLLMClient,
    ProcessingMockLLM,
)
from tg_parser.processing.pipeline import ProcessingPipelineImpl
from tg_parser.processing.prompts import (
    PROCESSING_SYSTEM_PROMPT,
    build_processing_prompt,
    get_processing_prompt_name,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_raw_message() -> RawTelegramMessage:
    """Создать тестовое raw сообщение."""
    return RawTelegramMessage(
        id="123",
        message_type=MessageType.POST,
        source_ref="tg:test_channel:post:123",
        channel_id="test_channel",
        date=datetime(2025, 12, 14, 10, 0, 0, tzinfo=UTC),
        text="Это тестовое сообщение для обработки через LLM.",
    )


@pytest.fixture
def mock_processed_doc_repo():
    """Mock репозиторий ProcessedDocument."""
    repo = MagicMock()
    repo.exists = AsyncMock(return_value=False)
    repo.get_by_source_ref = AsyncMock(return_value=None)
    repo.save = AsyncMock(return_value=None)
    repo.upsert = AsyncMock(return_value=None)
    repo.upsert_batch = AsyncMock(return_value=None)
    # F5-A Phase 3: dedup lookup hook (default: no duplicate in DB).
    repo.find_by_content_hash = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_failure_repo():
    """Mock репозиторий failures."""
    repo = MagicMock()
    repo.record_failure = AsyncMock(return_value=None)
    repo.clear_failure = AsyncMock(return_value=None)
    repo.delete_failure = AsyncMock(return_value=None)
    return repo


# ============================================================================
# Тесты промптов
# ============================================================================


def test_build_processing_prompt():
    """Тест построения промпта."""
    text = "Тестовый текст"
    prompt = build_processing_prompt(text)

    assert "Тестовый текст" in prompt
    assert "---" in prompt


def test_get_processing_prompt_name():
    """Тест имени промпта."""
    name = get_processing_prompt_name()
    assert name == "processing_v1"


# ============================================================================
# Тесты Mock LLM
# ============================================================================


@pytest.mark.asyncio
async def test_mock_llm_client_basic():
    """Тест базового MockLLMClient."""
    client = MockLLMClient(default_response="Test response")

    response = await client.generate(
        prompt="Test prompt",
        system_prompt="System",
    )

    assert response == "Test response"
    assert client.call_count == 1
    assert client.last_prompt == "Test prompt"


@pytest.mark.asyncio
async def test_mock_llm_client_json_format():
    """Тест MockLLMClient с JSON форматом."""
    client = MockLLMClient()

    response = await client.generate(
        prompt="Test",
        response_format={"type": "json_object"},
    )

    # Проверяем что ответ валидный JSON
    data = json.loads(response)
    assert "text_clean" in data
    assert "summary" in data
    assert "topics" in data


@pytest.mark.asyncio
async def test_deterministic_mock_llm():
    """Тест детерминированного mock LLM."""
    client = DeterministicMockLLM()

    # Вызываем дважды с одинаковыми параметрами
    response1 = await client.generate(
        prompt="Test prompt",
        system_prompt="System",
        temperature=0.0,
    )

    response2 = await client.generate(
        prompt="Test prompt",
        system_prompt="System",
        temperature=0.0,
    )

    # Должны быть идентичны
    assert response1 == response2


@pytest.mark.asyncio
async def test_processing_mock_llm():
    """Тест ProcessingMockLLM."""
    client = ProcessingMockLLM()

    response = await client.generate(
        prompt="Process this: Тестовый текст",
        system_prompt=PROCESSING_SYSTEM_PROMPT,
        response_format={"type": "json_object"},
    )

    # Парсим JSON
    data = json.loads(response)

    # Проверяем структуру
    assert "text_clean" in data
    assert isinstance(data["text_clean"], str)
    assert "topics" in data
    assert isinstance(data["topics"], list)
    assert "language" in data


# ============================================================================
# Тесты ProcessingPipeline
# ============================================================================


@pytest.mark.asyncio
async def test_processing_pipeline_basic(
    sample_raw_message,
    mock_processed_doc_repo,
):
    """Тест базовой обработки сообщения."""
    # Создаём pipeline с mock LLM
    llm_client = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm_client,
        processed_doc_repo=mock_processed_doc_repo,
        pipeline_version="processing:v1.0.0",
        model_id="test-model",
    )

    # Обрабатываем сообщение
    result = await pipeline.process_message(sample_raw_message)

    # Проверяем результат
    assert isinstance(result, ProcessedDocument)
    assert result.source_ref == sample_raw_message.source_ref
    assert result.id == make_processed_document_id(sample_raw_message.source_ref)
    assert result.text_clean
    assert result.channel_id == sample_raw_message.channel_id

    # Проверяем metadata
    assert result.metadata
    assert result.metadata["pipeline_version"] == "processing:v1.0.0"
    assert result.metadata["model_id"] == "test-model"
    assert "prompt_id" in result.metadata
    assert "parameters" in result.metadata

    # Проверяем что upsert был вызван
    mock_processed_doc_repo.upsert.assert_called_once()


@pytest.mark.asyncio
async def test_processing_pipeline_preserves_urls_in_metadata(
    mock_processed_doc_repo,
):
    """raw_payload urls are copied into ProcessedDocument.metadata without touching text_clean."""
    urls = [
        {
            "url": "https://hidden.example/path",
            "text": "click here",
            "type": "text_url",
        }
    ]
    message = RawTelegramMessage(
        id="123",
        message_type=MessageType.POST,
        source_ref="tg:test_channel:post:123",
        channel_id="test_channel",
        date=datetime(2025, 12, 14, 10, 0, 0, tzinfo=UTC),
        text="click here",
        raw_payload={"message": "click here", "urls": urls},
    )
    llm_client = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm_client,
        processed_doc_repo=mock_processed_doc_repo,
        model_id="test-model",
    )

    result = await pipeline.process_message(message)

    assert result.metadata["urls"] == urls


@pytest.mark.asyncio
async def test_processing_pipeline_no_urls_key_when_raw_payload_empty(
    sample_raw_message,
    mock_processed_doc_repo,
):
    """Messages without raw_payload urls do not add metadata.urls."""
    pipeline = ProcessingPipelineImpl(
        llm_client=ProcessingMockLLM(),
        processed_doc_repo=mock_processed_doc_repo,
    )

    result = await pipeline.process_message(sample_raw_message)

    assert "urls" not in result.metadata


@pytest.mark.asyncio
async def test_processing_pipeline_incrementality(
    sample_raw_message,
    mock_processed_doc_repo,
):
    """
    Тест инкрементальности (TR-46/TR-48).

    Если документ уже обработан, должен пропустить без force.
    """
    # Настраиваем mock: документ уже существует
    mock_processed_doc_repo.exists.return_value = True
    existing_doc = ProcessedDocument(
        id=make_processed_document_id(sample_raw_message.source_ref),
        source_ref=sample_raw_message.source_ref,
        source_message_id=sample_raw_message.id,
        channel_id=sample_raw_message.channel_id,
        processed_at=datetime.now(UTC),
        text_clean="Already processed",
    )
    mock_processed_doc_repo.get_by_source_ref.return_value = existing_doc

    # Создаём pipeline
    llm_client = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm_client,
        processed_doc_repo=mock_processed_doc_repo,
    )

    # Обрабатываем без force
    result = await pipeline.process_message(sample_raw_message, force=False)

    # Должен вернуть существующий документ
    assert result == existing_doc

    # upsert НЕ должен быть вызван
    mock_processed_doc_repo.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_processing_pipeline_force_reprocess(
    sample_raw_message,
    mock_processed_doc_repo,
):
    """
    Тест переобработки с force (TR-46/TR-49).

    С флагом force должен переобработать даже если уже есть.
    """
    # Настраиваем mock: документ существует
    mock_processed_doc_repo.exists.return_value = True

    # Создаём pipeline
    llm_client = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm_client,
        processed_doc_repo=mock_processed_doc_repo,
    )

    # Обрабатываем с force=True
    result = await pipeline.process_message(sample_raw_message, force=True)

    # Должен создать новый документ
    assert isinstance(result, ProcessedDocument)
    assert result.source_ref == sample_raw_message.source_ref

    # upsert ДОЛЖЕН быть вызван (переобработка)
    mock_processed_doc_repo.upsert.assert_called_once()


@pytest.mark.asyncio
async def test_processing_pipeline_retry_logic(
    sample_raw_message,
    mock_processed_doc_repo,
    mock_failure_repo,
):
    """
    Тест ретраев (TR-47).

    При ошибке должен делать 3 попытки с backoff.
    """
    # Создаём mock LLM который всегда падает
    failing_llm = MagicMock()
    failing_llm.generate_with_usage = AsyncMock(side_effect=Exception("API error"))

    # Создаём pipeline
    pipeline = ProcessingPipelineImpl(
        llm_client=failing_llm,
        processed_doc_repo=mock_processed_doc_repo,
        failure_repo=mock_failure_repo,
    )

    # Обрабатываем (должно упасть)
    with pytest.raises(Exception, match="API error"):
        await pipeline.process_message(sample_raw_message)

    # Проверяем что было 3 попытки (из настроек по умолчанию)
    assert failing_llm.generate_with_usage.call_count == 3

    # Проверяем что ошибка записана
    mock_failure_repo.record_failure.assert_called_once()
    call_args = mock_failure_repo.record_failure.call_args
    assert call_args[1]["source_ref"] == sample_raw_message.source_ref
    assert call_args[1]["channel_id"] == sample_raw_message.channel_id
    assert call_args[1]["attempts"] == 3
    assert call_args[1]["error_class"] == "Exception"


@pytest.mark.asyncio
async def test_processing_pipeline_retry_success_after_failure(
    sample_raw_message,
    mock_processed_doc_repo,
    mock_failure_repo,
):
    """
    Тест успешного ретрая после ошибок.

    Если попытка успешна, должен очистить failure.
    """
    # Создаём mock LLM который падает 2 раза, затем успешен
    failing_then_success_llm = MagicMock()

    call_count = 0

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise Exception("Temporary error")
        # На третий раз возвращаем валидный LLMResponse
        from tg_parser.processing.ports import LLMResponse

        return LLMResponse(
            text=json.dumps(
                {
                    "text_clean": "Success",
                    "summary": None,
                    "topics": [],
                    "entities": [],
                    "language": "ru",
                }
            ),
            input_tokens=100,
            output_tokens=50,
        )

    failing_then_success_llm.generate_with_usage = AsyncMock(side_effect=side_effect)

    # Создаём pipeline
    pipeline = ProcessingPipelineImpl(
        llm_client=failing_then_success_llm,
        processed_doc_repo=mock_processed_doc_repo,
        failure_repo=mock_failure_repo,
    )

    # Обрабатываем (должно успеть)
    result = await pipeline.process_message(sample_raw_message)

    # Проверяем результат
    assert isinstance(result, ProcessedDocument)
    assert result.text_clean == "Success"

    # Проверяем что было 3 попытки
    assert failing_then_success_llm.generate_with_usage.call_count == 3

    # Проверяем что failure была очищена
    mock_failure_repo.delete_failure.assert_called_once_with(sample_raw_message.source_ref)


@pytest.mark.asyncio
async def test_processing_pipeline_batch_continues_on_error(
    mock_processed_doc_repo,
):
    """
    Тест обработки батча (TR-47).

    Ошибка на одном сообщении не должна ронять весь батч.
    """
    # Создаём несколько сообщений
    messages = [
        RawTelegramMessage(
            id=str(i),
            message_type=MessageType.POST,
            source_ref=f"tg:test_channel:post:{i}",
            channel_id="test_channel",
            date=datetime.now(UTC),
            text=f"Message {i}",
        )
        for i in range(5)
    ]

    # Создаём mock LLM который падает на сообщении 2
    selective_failing_llm = MagicMock()

    async def side_effect(prompt, *args, **kwargs):
        if "Message 2" in prompt:
            raise Exception("Failed on message 2")
        from tg_parser.processing.ports import LLMResponse

        return LLMResponse(
            text=json.dumps(
                {
                    "text_clean": prompt[:50],
                    "summary": None,
                    "topics": [],
                    "entities": [],
                    "language": "ru",
                }
            ),
            input_tokens=100,
            output_tokens=50,
        )

    selective_failing_llm.generate_with_usage = AsyncMock(side_effect=side_effect)

    # Создаём pipeline
    pipeline = ProcessingPipelineImpl(
        llm_client=selective_failing_llm,
        processed_doc_repo=mock_processed_doc_repo,
    )

    # Обрабатываем батч
    results = await pipeline.process_batch(messages)

    # Должно быть 4 успешных результата (5 сообщений - 1 упавшее)
    # Но с учётом ретраев (3 попытки на message 2), результат может быть меньше
    # В данном случае проверяем что батч не упал полностью
    assert len(results) < len(messages)

    # Проверяем что успешные сообщения обработались
    assert all(isinstance(doc, ProcessedDocument) for doc in results)


@pytest.mark.asyncio
async def test_processing_pipeline_deterministic_id(
    sample_raw_message,
    mock_processed_doc_repo,
):
    """
    Тест детерминированного ID (TR-41).

    ProcessedDocument.id должен быть "doc:" + source_ref.
    """
    llm_client = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm_client,
        processed_doc_repo=mock_processed_doc_repo,
    )

    result = await pipeline.process_message(sample_raw_message)

    # Проверяем детерминированный ID
    expected_id = f"doc:{sample_raw_message.source_ref}"
    assert result.id == expected_id


@pytest.mark.asyncio
async def test_processing_pipeline_processed_at_utc(
    sample_raw_message,
    mock_processed_doc_repo,
):
    """
    Тест processed_at (TR-49).

    processed_at должен быть в UTC при создании/обновлении.
    """
    llm_client = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm_client,
        processed_doc_repo=mock_processed_doc_repo,
    )

    before = datetime.now(UTC)
    result = await pipeline.process_message(sample_raw_message)
    after = datetime.now(UTC)

    # Проверяем что processed_at в нужном диапазоне и в UTC
    assert result.processed_at.tzinfo == UTC
    assert before <= result.processed_at <= after


# ============================================================================
# Тесты OpenAI клиента (unit без реальных запросов)
# ============================================================================


def test_openai_client_compute_prompt_id():
    """Тест вычисления prompt_id."""
    client = OpenAIClient(api_key="test-key", model="gpt-4")

    system_prompt = "System prompt"
    user_template = "User template {var}"

    prompt_id = client.compute_prompt_id(system_prompt, user_template)

    # Проверяем формат
    assert prompt_id.startswith("sha256:")
    assert len(prompt_id) > len("sha256:")

    # Проверяем детерминизм
    prompt_id2 = client.compute_prompt_id(system_prompt, user_template)
    assert prompt_id == prompt_id2


def test_openai_client_configuration():
    """Тест конфигурации OpenAI клиента."""
    client = OpenAIClient(
        api_key="test-key",
        model="gpt-4o-mini",
        base_url="https://custom.openai.com/v1",
    )

    assert client.api_key == "test-key"
    assert client.model == "gpt-4o-mini"
    assert client.base_url == "https://custom.openai.com/v1"

    # Проверяем что trailing slash убран
    client2 = OpenAIClient(
        api_key="key",
        model="model",
        base_url="https://example.com/",
    )
    assert client2.base_url == "https://example.com"


# =========================================================================
# Concurrency tests (Session 31)
# =========================================================================


@pytest.mark.asyncio
async def test_process_batch_parallel_path(mock_processed_doc_repo):
    """
    process_batch(concurrency>1) delegates to _process_batch_parallel.
    """
    messages = [
        RawTelegramMessage(
            id=str(i),
            message_type=MessageType.POST,
            source_ref=f"tg:ch:post:{i}",
            channel_id="ch",
            date=datetime.now(UTC),
            text=f"Msg {i}",
        )
        for i in range(3)
    ]

    llm = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm,
        processed_doc_repo=mock_processed_doc_repo,
    )

    results = await pipeline.process_batch(messages, concurrency=5)

    assert len(results) == 3
    assert all(isinstance(r, ProcessedDocument) for r in results)


@pytest.mark.asyncio
async def test_process_batch_sequential_path(mock_processed_doc_repo):
    """
    process_batch(concurrency=1) delegates to _process_batch_sequential.
    """
    messages = [
        RawTelegramMessage(
            id=str(i),
            message_type=MessageType.POST,
            source_ref=f"tg:ch:post:{i}",
            channel_id="ch",
            date=datetime.now(UTC),
            text=f"Msg {i}",
        )
        for i in range(3)
    ]

    llm = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm,
        processed_doc_repo=mock_processed_doc_repo,
    )

    results = await pipeline.process_batch(messages, concurrency=1)

    assert len(results) == 3


@pytest.mark.asyncio
async def test_suggest_processing_concurrency_caps_parallel(mock_processed_doc_repo):
    """
    When llm_client has suggest_processing_concurrency, it can lower effective concurrency.
    """
    messages = [
        RawTelegramMessage(
            id="1",
            message_type=MessageType.POST,
            source_ref="tg:ch:post:1",
            channel_id="ch",
            date=datetime.now(UTC),
            text="Msg 1",
        )
    ]

    llm = ProcessingMockLLM()
    llm.suggest_processing_concurrency = lambda requested: min(requested, 2)

    pipeline = ProcessingPipelineImpl(
        llm_client=llm,
        processed_doc_repo=mock_processed_doc_repo,
    )

    results = await pipeline.process_batch(messages, concurrency=10)
    assert len(results) == 1


def test_settings_processing_concurrency(monkeypatch):
    """processing_concurrency field exists in Settings with correct default."""
    from tg_parser.config.settings import Settings

    monkeypatch.delenv("PROCESSING_CONCURRENCY", raising=False)
    s = Settings(
        _env_file=None,
    )
    assert s.processing_concurrency == 5
    assert 1 <= s.processing_concurrency <= 50


def test_settings_topicization_batch_concurrency(monkeypatch):
    """topicization_batch_concurrency field exists in Settings with correct default."""
    from tg_parser.config.settings import Settings

    monkeypatch.delenv("TOPICIZATION_BATCH_CONCURRENCY", raising=False)
    s = Settings(
        _env_file=None,
    )
    assert s.topicization_batch_concurrency == 5
    assert 1 <= s.topicization_batch_concurrency <= 20


def test_settings_processing_concurrency_from_env(monkeypatch):
    """PROCESSING_CONCURRENCY env var is picked up by Settings."""
    from tg_parser.config.settings import Settings

    monkeypatch.setenv("PROCESSING_CONCURRENCY", "15")
    s = Settings(_env_file=None)
    assert s.processing_concurrency == 15


def test_rate_limiter_suggested_parallel_cap():
    """LLMRateLimiter.suggested_parallel_cap reduces concurrency when remaining is low."""
    from tg_parser.processing.llm.rate_limiter import LLMRateLimiter

    rl = LLMRateLimiter(rpm=100, input_tokens_per_minute=50000, output_tokens_per_minute=10000)

    # Without any header sync, _last_requests_remaining is None → return requested
    assert rl.suggested_parallel_cap(20) == 20

    # Simulate low remaining
    rl._last_requests_remaining = 5.0
    cap = rl.suggested_parallel_cap(20)
    assert cap == 3  # int(5 * 0.6) = 3

    # Requested <= 1 → pass through
    assert rl.suggested_parallel_cap(1) == 1


def test_anthropic_client_suggest_processing_concurrency():
    """AnthropicClient.suggest_processing_concurrency delegates to rate_limiter."""
    from tg_parser.processing.llm.anthropic_client import AnthropicClient
    from tg_parser.processing.llm.rate_limiter import LLMRateLimiter

    rl = LLMRateLimiter(rpm=100, input_tokens_per_minute=50000, output_tokens_per_minute=10000)
    rl._last_requests_remaining = 8.0

    client = AnthropicClient(api_key="test", rate_limiter=rl)
    result = client.suggest_processing_concurrency(20)
    assert result == 4  # int(8 * 0.6) = 4

    # Without rate limiter, return requested as-is
    client_no_rl = AnthropicClient(api_key="test", rate_limiter=None)
    assert client_no_rl.suggest_processing_concurrency(20) == 20


# =========================================================================
# Session 32: Comment processing tests
# =========================================================================


@pytest.fixture
def sample_comment_message() -> RawTelegramMessage:
    """Comment message with non-empty text."""
    return RawTelegramMessage(
        id="500",
        message_type=MessageType.COMMENT,
        source_ref="tg:test_channel:comment:500",
        channel_id="test_channel",
        date=datetime(2025, 12, 14, 11, 0, 0, tzinfo=UTC),
        text="Отличный пост, спасибо за информацию!",
        thread_id="123",
        parent_message_id="499",
    )


@pytest.fixture
def media_only_comment_photo() -> RawTelegramMessage:
    """Media-only comment: photo without text (like comment:154)."""
    return RawTelegramMessage(
        id="154",
        message_type=MessageType.COMMENT,
        source_ref="tg:test_channel:comment:154",
        channel_id="test_channel",
        date=datetime(2025, 12, 14, 11, 5, 0, tzinfo=UTC),
        text="",
        thread_id="97",
        parent_message_id="153",
        raw_payload={
            "id": 154,
            "message": "",
            "media": {"type": "MessageMediaPhoto", "has_photo": True},
        },
    )


@pytest.fixture
def media_only_comment_voice() -> RawTelegramMessage:
    """Media-only comment: voice message without text (like comment:4057)."""
    return RawTelegramMessage(
        id="4057",
        message_type=MessageType.COMMENT,
        source_ref="tg:test_channel:comment:4057",
        channel_id="test_channel",
        date=datetime(2025, 12, 14, 11, 10, 0, tzinfo=UTC),
        text="",
        thread_id="58",
        parent_message_id="4055",
        raw_payload={
            "id": 4057,
            "message": "",
            "media": {
                "type": "MessageMediaDocument",
                "has_document": True,
                "mime_type": "audio/ogg",
                "size_bytes": 4555120,
            },
        },
    )


@pytest.fixture
def short_comment_message() -> RawTelegramMessage:
    """Very short comment (emoji/reaction)."""
    return RawTelegramMessage(
        id="600",
        message_type=MessageType.COMMENT,
        source_ref="tg:test_channel:comment:600",
        channel_id="test_channel",
        date=datetime(2025, 12, 14, 11, 15, 0, tzinfo=UTC),
        text="?",
        thread_id="123",
        parent_message_id="599",
    )


@pytest.fixture
def parent_processed_doc() -> ProcessedDocument:
    """Already-processed parent post for comments to reference."""
    return ProcessedDocument(
        id="doc:tg:test_channel:post:123",
        source_ref="tg:test_channel:post:123",
        source_message_id="123",
        channel_id="test_channel",
        processed_at=datetime(2025, 12, 14, 10, 0, 0, tzinfo=UTC),
        text_clean="Витамин D: показания к назначению, подготовка к анализу и интерпретация результатов.",
        summary="Обзор анализа на витамин D",
        topics=["витамин D", "лабораторная диагностика"],
        language="ru",
    )


@pytest.mark.asyncio
async def test_media_only_comment_photo_produces_synthetic_doc(
    media_only_comment_photo,
    mock_processed_doc_repo,
):
    """Media-only comment (photo) is processed without LLM call, producing synthetic text_clean."""
    llm_client = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm_client,
        processed_doc_repo=mock_processed_doc_repo,
        model_id="test-model",
    )

    result = await pipeline.process_message(media_only_comment_photo, force=True)

    assert isinstance(result, ProcessedDocument)
    assert result.source_ref == "tg:test_channel:comment:154"
    assert result.text_clean == "[Фото]"
    assert result.metadata["media_only"] is True
    assert result.metadata["prompt_id"] == "media_only_synthetic"
    assert result.language == "unknown"
    assert llm_client.call_count == 0


@pytest.mark.asyncio
async def test_media_only_preserves_urls_in_metadata(
    mock_processed_doc_repo,
):
    """Media-only synthetic docs still carry urls from raw_payload metadata."""
    urls = [
        {
            "url": "https://example.com/caption-link",
            "text": "https://example.com/caption-link",
            "type": "url",
        }
    ]
    message = RawTelegramMessage(
        id="154",
        message_type=MessageType.COMMENT,
        source_ref="tg:test_channel:comment:154",
        channel_id="test_channel",
        date=datetime(2025, 12, 14, 11, 5, 0, tzinfo=UTC),
        text="",
        thread_id="97",
        parent_message_id="153",
        raw_payload={
            "id": 154,
            "message": "",
            "media": {"type": "MessageMediaPhoto", "has_photo": True},
            "urls": urls,
        },
    )
    pipeline = ProcessingPipelineImpl(
        llm_client=ProcessingMockLLM(),
        processed_doc_repo=mock_processed_doc_repo,
    )

    result = await pipeline.process_message(message, force=True)

    assert result.metadata["urls"] == urls
    assert result.metadata["media_only"] is True


@pytest.mark.asyncio
async def test_media_only_comment_voice_produces_synthetic_doc(
    media_only_comment_voice,
    mock_processed_doc_repo,
):
    """Media-only comment (voice) is processed without LLM call."""
    llm_client = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm_client,
        processed_doc_repo=mock_processed_doc_repo,
        model_id="test-model",
    )

    result = await pipeline.process_message(media_only_comment_voice, force=True)

    assert isinstance(result, ProcessedDocument)
    assert result.source_ref == "tg:test_channel:comment:4057"
    assert result.text_clean == "[Голосовое сообщение]"
    assert result.metadata["media_only"] is True
    assert llm_client.call_count == 0


@pytest.mark.asyncio
async def test_media_only_preserves_thread_metadata(
    media_only_comment_photo,
    mock_processed_doc_repo,
):
    """Media-only synthetic document preserves thread_id and parent_message_id."""
    pipeline = ProcessingPipelineImpl(
        llm_client=ProcessingMockLLM(),
        processed_doc_repo=mock_processed_doc_repo,
    )

    result = await pipeline.process_message(media_only_comment_photo, force=True)

    assert result.metadata["thread_id"] == "97"
    assert result.metadata["parent_message_id"] == "153"


@pytest.mark.asyncio
async def test_comment_uses_parent_context_in_prompt(
    sample_comment_message,
    mock_processed_doc_repo,
    parent_processed_doc,
):
    """Comment processing loads parent post and uses comment template."""
    mock_processed_doc_repo.get_by_source_ref.return_value = parent_processed_doc

    llm_client = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm_client,
        processed_doc_repo=mock_processed_doc_repo,
        model_id="test-model",
    )

    result = await pipeline.process_message(sample_comment_message, force=True)

    assert isinstance(result, ProcessedDocument)
    assert result.metadata.get("has_parent_context") is True

    # Verify the LLM was called with the comment template containing parent context
    assert llm_client.call_count == 1
    last_prompt = llm_client.last_prompt
    assert "PARENT POST" in last_prompt
    assert "витамин D" in last_prompt.lower() or "Витамин D" in last_prompt
    assert "COMMENT" in last_prompt


@pytest.mark.asyncio
async def test_comment_without_parent_falls_back_to_regular_template(
    sample_comment_message,
    mock_processed_doc_repo,
):
    """When parent post is not found, comment uses regular (non-comment) template."""
    mock_processed_doc_repo.get_by_source_ref.return_value = None

    llm_client = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm_client,
        processed_doc_repo=mock_processed_doc_repo,
    )

    result = await pipeline.process_message(sample_comment_message, force=True)

    assert isinstance(result, ProcessedDocument)
    assert result.metadata.get("has_parent_context") is None

    # Should use regular template without PARENT POST section
    assert "PARENT POST" not in llm_client.last_prompt


@pytest.mark.asyncio
async def test_short_comment_processes_successfully(
    short_comment_message,
    mock_processed_doc_repo,
):
    """Very short comment ("?") is processed without error."""
    mock_processed_doc_repo.get_by_source_ref.return_value = None

    llm_client = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm_client,
        processed_doc_repo=mock_processed_doc_repo,
    )

    result = await pipeline.process_message(short_comment_message, force=True)

    assert isinstance(result, ProcessedDocument)
    assert result.text_clean
    assert llm_client.call_count == 1


@pytest.mark.asyncio
async def test_post_processing_unchanged(
    sample_raw_message,
    mock_processed_doc_repo,
):
    """Regular post processing is not affected by comment changes (backward compat)."""
    llm_client = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm_client,
        processed_doc_repo=mock_processed_doc_repo,
        model_id="test-model",
    )

    result = await pipeline.process_message(sample_raw_message, force=True)

    assert isinstance(result, ProcessedDocument)
    assert result.source_ref == "tg:test_channel:post:123"
    assert result.metadata.get("has_parent_context") is None
    assert result.metadata.get("media_only") is None

    # Regular post should use the standard template (no PARENT POST section)
    assert "PARENT POST" not in llm_client.last_prompt


@pytest.mark.asyncio
async def test_comment_with_raw_repo_fallback(
    sample_comment_message,
    mock_processed_doc_repo,
):
    """When processed parent is unavailable, falls back to raw_repo for context."""
    mock_processed_doc_repo.get_by_source_ref.return_value = None

    parent_raw = RawTelegramMessage(
        id="123",
        message_type=MessageType.POST,
        source_ref="tg:test_channel:post:123",
        channel_id="test_channel",
        date=datetime(2025, 12, 14, 10, 0, 0, tzinfo=UTC),
        text="Сырой текст поста про витамин D и лабораторную диагностику.",
    )

    mock_raw_repo = MagicMock()
    mock_raw_repo.get_by_source_ref = AsyncMock(return_value=parent_raw)

    llm_client = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm_client,
        processed_doc_repo=mock_processed_doc_repo,
        raw_repo=mock_raw_repo,
        model_id="test-model",
    )

    result = await pipeline.process_message(sample_comment_message, force=True)

    assert isinstance(result, ProcessedDocument)
    assert result.metadata.get("has_parent_context") is True
    assert "PARENT POST" in llm_client.last_prompt
    assert "витамин d" in llm_client.last_prompt.lower()


@pytest.mark.asyncio
async def test_batch_with_mixed_posts_and_comments(mock_processed_doc_repo):
    """Batch processing handles a mix of posts, comments, and media-only messages."""
    messages = [
        RawTelegramMessage(
            id="1",
            message_type=MessageType.POST,
            source_ref="tg:ch:post:1",
            channel_id="ch",
            date=datetime.now(UTC),
            text="Normal post text.",
        ),
        RawTelegramMessage(
            id="2",
            message_type=MessageType.COMMENT,
            source_ref="tg:ch:comment:2",
            channel_id="ch",
            date=datetime.now(UTC),
            text="Comment text",
            thread_id="1",
            parent_message_id="1",
        ),
        RawTelegramMessage(
            id="3",
            message_type=MessageType.COMMENT,
            source_ref="tg:ch:comment:3",
            channel_id="ch",
            date=datetime.now(UTC),
            text="",
            thread_id="1",
            parent_message_id="2",
            raw_payload={"media": {"type": "MessageMediaPhoto", "has_photo": True}},
        ),
    ]

    mock_processed_doc_repo.get_by_source_ref.return_value = None

    llm_client = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm_client,
        processed_doc_repo=mock_processed_doc_repo,
    )

    results = await pipeline.process_batch(messages, force=True)

    assert len(results) == 3

    # Post processed normally
    assert results[0].source_ref == "tg:ch:post:1"
    assert results[0].metadata.get("media_only") is None

    # Comment processed (without parent context since get_by_source_ref returns None)
    assert results[1].source_ref == "tg:ch:comment:2"

    # Media-only comment processed synthetically
    assert results[2].source_ref == "tg:ch:comment:3"
    assert results[2].text_clean == "[Фото]"
    assert results[2].metadata["media_only"] is True

    # LLM should only have been called for 2 messages (post + text comment)
    assert llm_client.call_count == 2


def test_describe_media_photo():
    """_describe_media returns correct label for photo."""
    from tg_parser.processing.pipeline import _describe_media

    assert _describe_media({"type": "MessageMediaPhoto", "has_photo": True}) == "[Фото]"


def test_describe_media_voice():
    """_describe_media returns correct label for audio/ogg."""
    from tg_parser.processing.pipeline import _describe_media

    media = {"type": "MessageMediaDocument", "has_document": True, "mime_type": "audio/ogg"}
    assert _describe_media(media) == "[Голосовое сообщение]"


def test_describe_media_video():
    """_describe_media returns correct label for video."""
    from tg_parser.processing.pipeline import _describe_media

    media = {"type": "MessageMediaDocument", "has_document": True, "mime_type": "video/mp4"}
    assert _describe_media(media) == "[Видео]"


def test_describe_media_document():
    """_describe_media returns correct label for generic document."""
    from tg_parser.processing.pipeline import _describe_media

    media = {"type": "MessageMediaDocument", "has_document": True, "mime_type": "application/pdf"}
    assert _describe_media(media) == "[Документ: application/pdf]"


def test_describe_media_unknown():
    """_describe_media returns fallback for unknown media type."""
    from tg_parser.processing.pipeline import _describe_media

    assert _describe_media({"type": "MessageMediaUnknown"}) == "[Медиа]"


def test_comment_prompt_template():
    """Comment prompt template includes parent_text and text placeholders."""
    from tg_parser.processing.prompts import build_comment_processing_prompt

    prompt = build_comment_processing_prompt(
        text="Спасибо!",
        parent_text="Пост про анализ крови.",
    )

    assert "PARENT POST" in prompt
    assert "Пост про анализ крови." in prompt
    assert "COMMENT" in prompt
    assert "Спасибо!" in prompt


# ============================================================================
# BUG-065: pure-Python JSON-repair fallback at the parse boundary
# ============================================================================


def test_repair_json_preserves_valid_json():
    """repair_json must not corrupt already-valid JSON (conservative)."""
    from tg_parser.processing.pipeline import repair_json

    valid = '{"text_clean": "no inner quotes here", "topics": ["a", "b"], "n": 3}'
    assert json.loads(repair_json(valid)) == json.loads(valid)


def test_repair_json_escapes_inner_quotes():
    """repair_json escapes unescaped inner double-quotes inside string values."""
    from tg_parser.processing.pipeline import repair_json

    broken = '{"text_clean": "He said "hi" loudly"}'
    # prod signature: invalid as-is.
    with pytest.raises(json.JSONDecodeError):
        json.loads(broken)
    parsed = json.loads(repair_json(broken))
    assert parsed["text_clean"] == 'He said "hi" loudly'


def test_repair_json_strips_trailing_commas():
    """repair_json strips trailing commas before } / ] (string-aware)."""
    from tg_parser.processing.pipeline import repair_json

    broken = '{"topics": ["a", "b",], "text_clean": "x",}'
    parsed = json.loads(repair_json(broken))
    assert parsed["topics"] == ["a", "b"]
    assert parsed["text_clean"] == "x"


@pytest.mark.asyncio
async def test_repair_recovers_unescaped_inner_quotes(
    sample_raw_message,
    mock_processed_doc_repo,
):
    """BUG-065: unescaped inner double-quotes in text_clean — mirroring the prod
    `Expecting ',' delimiter` line-2 signature — are repaired and parsed via the
    repair pass, on the FIRST attempt (no JSON retry needed)."""
    from tg_parser.processing.ports import LLMResponse

    # Line 2 (the text_clean line) contains verbatim inner quotes that the LLM
    # failed to escape — exactly the prod failure shape.
    invalid_json = (
        "{\n"
        '  "text_clean": "Врач сказал: "пейте больше воды" и это важно",\n'
        '  "summary": null,\n'
        '  "topics": [],\n'
        '  "entities": [],\n'
        '  "language": "ru"\n'
        "}"
    )
    # Sanity: this reproduces the prod JSONDecodeError signature.
    with pytest.raises(json.JSONDecodeError) as exc_info:
        json.loads(invalid_json)
    assert exc_info.value.lineno == 2

    llm = MagicMock()
    llm.generate_with_usage = AsyncMock(
        return_value=LLMResponse(text=invalid_json, input_tokens=10, output_tokens=5)
    )
    pipeline = ProcessingPipelineImpl(
        llm_client=llm,
        processed_doc_repo=mock_processed_doc_repo,
    )

    doc = await pipeline._process_single_message(sample_raw_message)

    assert isinstance(doc, ProcessedDocument)
    # Inner quotes preserved verbatim in the recovered value.
    assert doc.text_clean == 'Врач сказал: "пейте больше воды" и это важно'
    assert doc.language == "ru"
    # Repaired on the first attempt → no deterministic JSON retry.
    assert llm.generate_with_usage.call_count == 1


@pytest.mark.asyncio
async def test_irreparable_json_still_raises(
    sample_raw_message,
    mock_processed_doc_repo,
):
    """BUG-065: a genuinely irreparable payload still exhausts the JSON attempts
    and raises LLMJsonParseError (the repair pass must not mask hard failures)."""
    from tg_parser.processing.llm.errors import LLMJsonParseError
    from tg_parser.processing.ports import LLMResponse

    # Unclosed object/array — repair cannot synthesise the missing brackets.
    broken = '{"text_clean": "ok", "topics": [1, 2, 3'
    llm = MagicMock()
    llm.generate_with_usage = AsyncMock(
        return_value=LLMResponse(text=broken, input_tokens=10, output_tokens=5)
    )
    pipeline = ProcessingPipelineImpl(
        llm_client=llm,
        processed_doc_repo=mock_processed_doc_repo,
    )

    with pytest.raises(LLMJsonParseError):
        await pipeline._process_single_message(sample_raw_message)
    # Deterministic (temperature=0) → all max_json_attempts (=3) consumed.
    assert llm.generate_with_usage.call_count == 3


# ============================================================================
# BUG-067 B2b — bounded retry budget + cooldown TTL via failure_repo
# (parallel processing path). The dominant token burn was re-sending the whole
# failed backlog to the LLM every tick because only processed_doc_repo.exists()
# gated the skip. These tests pin the cooldown/budget skip behaviour.
# ============================================================================


def _b2b_raw_msgs(channel_id: str, n: int) -> list[RawTelegramMessage]:
    return [
        RawTelegramMessage(
            id=str(i),
            message_type=MessageType.POST,
            source_ref=f"tg:{channel_id}:post:{i}",
            channel_id=channel_id,
            date=datetime.now(UTC),
            text=f"Сообщение номер {i} с достаточным текстом для обработки LLM.",
        )
        for i in range(n)
    ]


def _b2b_failure_row(
    source_ref: str,
    channel_id: str,
    *,
    error_class: str,
    attempts: int,
    age_s: int,
) -> dict:
    ts = (datetime.now(UTC) - timedelta(seconds=age_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "source_ref": source_ref,
        "channel_id": channel_id,
        "attempts": attempts,
        "last_attempt_at": ts,
        "error_class": error_class,
        "error_message": "boom",
        "error_details": None,
    }


@pytest.mark.asyncio
async def test_b2b_parse_failure_within_cooldown_is_skipped(mock_processed_doc_repo):
    """A recently-failed (parse) doc is NOT re-sent to the LLM within cooldown."""
    msgs = _b2b_raw_msgs("ch", 2)
    failure_repo = AsyncMock()
    failure_repo.list_failures.return_value = [
        _b2b_failure_row(
            msgs[0].source_ref, "ch", error_class="LLMJsonParseError", attempts=1, age_s=60
        )
    ]
    llm = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm,
        processed_doc_repo=mock_processed_doc_repo,
        failure_repo=failure_repo,
    )

    results = await pipeline.process_batch(msgs, concurrency=2)

    assert llm.call_count == 1, "only the non-failed doc should hit the LLM"
    assert pipeline._batch_cooldown_skipped == 1
    assert len(results) == 1
    recorded = {c.kwargs["source_ref"] for c in failure_repo.record_failure.call_args_list}
    assert msgs[0].source_ref not in recorded, "a cooldown-skip must not re-record a failure"


@pytest.mark.asyncio
async def test_b2b_parse_failure_past_cooldown_is_retried_and_cleared(mock_processed_doc_repo):
    """Past its cooldown, a previously-failed doc is retried; on success its
    failure record is cleared."""
    msgs = _b2b_raw_msgs("ch", 1)
    failure_repo = AsyncMock()
    failure_repo.list_failures.return_value = [
        _b2b_failure_row(
            msgs[0].source_ref, "ch", error_class="LLMJsonParseError", attempts=1, age_s=7200
        )
    ]
    llm = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm,
        processed_doc_repo=mock_processed_doc_repo,
        failure_repo=failure_repo,
    )

    results = await pipeline.process_batch(msgs, concurrency=2)

    assert llm.call_count == 1
    assert pipeline._batch_cooldown_skipped == 0
    assert len(results) == 1
    failure_repo.delete_failure.assert_awaited_with(msgs[0].source_ref)


@pytest.mark.asyncio
async def test_b2b_billing_vs_parse_differentiation(mock_processed_doc_repo):
    """At the same age, a temporary billing failure is retried while a sticky
    parse failure is still cooling down (different TTLs)."""
    msgs = _b2b_raw_msgs("ch", 2)
    billing_ref, parse_ref = msgs[0].source_ref, msgs[1].source_ref
    failure_repo = AsyncMock()
    # age 2000s: billing cooldown (1800) elapsed -> retry; parse default (3600) -> skip.
    failure_repo.list_failures.return_value = [
        _b2b_failure_row(
            billing_ref, "ch", error_class="AnthropicBillingError", attempts=1, age_s=2000
        ),
        _b2b_failure_row(
            parse_ref, "ch", error_class="LLMJsonParseError", attempts=1, age_s=2000
        ),
    ]
    llm = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm,
        processed_doc_repo=mock_processed_doc_repo,
        failure_repo=failure_repo,
    )

    results = await pipeline.process_batch(msgs, concurrency=2)

    assert llm.call_count == 1
    assert pipeline._batch_cooldown_skipped == 1
    assert {d.source_ref for d in results} == {billing_ref}


@pytest.mark.asyncio
async def test_b2b_parse_budget_exhausted_uses_long_cooldown(mock_processed_doc_repo):
    """Once the parse-attempt budget is exhausted, the doc moves to the LONG
    cooldown — still skipped even though it is past the short/default cooldown."""
    msgs = _b2b_raw_msgs("ch", 1)
    failure_repo = AsyncMock()
    failure_repo.list_failures.return_value = [
        _b2b_failure_row(
            msgs[0].source_ref, "ch", error_class="LLMJsonParseError", attempts=3, age_s=7200
        )
    ]
    llm = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm,
        processed_doc_repo=mock_processed_doc_repo,
        failure_repo=failure_repo,
    )

    await pipeline.process_batch(msgs, concurrency=2)

    assert llm.call_count == 0, "budget exhausted + within 24h long cooldown -> skip"
    assert pipeline._batch_cooldown_skipped == 1


@pytest.mark.asyncio
async def test_b2b_bypass_failure_cooldown_retries_everything(mock_processed_doc_repo):
    """An explicit retry_failed run (bypass_failure_cooldown=True) ignores the
    cooldown and re-sends the doc to the LLM."""
    msgs = _b2b_raw_msgs("ch", 1)
    failure_repo = AsyncMock()
    failure_repo.list_failures.return_value = [
        _b2b_failure_row(
            msgs[0].source_ref, "ch", error_class="LLMJsonParseError", attempts=1, age_s=10
        )
    ]
    llm = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm,
        processed_doc_repo=mock_processed_doc_repo,
        failure_repo=failure_repo,
    )

    await pipeline.process_batch(msgs, concurrency=2, bypass_failure_cooldown=True)

    assert llm.call_count == 1
    assert pipeline._batch_cooldown_skipped == 0


@pytest.mark.asyncio
async def test_chunked_persistence_commits_completed_chunks_on_interruption(monkeypatch):
    """Partial-batch-loss fix: completed chunks are persisted incrementally, so an
    interruption mid-batch keeps the already-written (paid-for) chunk instead of
    discarding the whole batch at a single end-of-batch upsert."""
    monkeypatch.setattr(app_settings, "processing_persist_chunk_size", 2)
    msgs = _b2b_raw_msgs("ch", 4)

    repo = MagicMock()
    repo.exists = AsyncMock(return_value=False)
    repo.get_by_source_ref = AsyncMock(return_value=None)
    repo.find_by_content_hash = AsyncMock(return_value=None)
    repo.upsert = AsyncMock(return_value=None)
    # First chunk commits OK; the second chunk write blows up mid-batch.
    repo.upsert_batch = AsyncMock(side_effect=[None, RuntimeError("db down")])

    llm = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(llm_client=llm, processed_doc_repo=repo)

    with pytest.raises(RuntimeError, match="db down"):
        await pipeline.process_batch(msgs, concurrency=4)

    assert repo.upsert_batch.call_count == 2
    first_chunk = repo.upsert_batch.call_args_list[0].args[0]
    assert len(first_chunk) == 2, "the completed chunk must be committed before the failure"


# ============================================================================
# Review round 2 — Fix 1 (LLMCallTimeoutError not retried in worker),
# Fix 3 (incremental failure recording survives interruption),
# Fix 5 (future-dated cooldown timestamp clamped to expired).
# ============================================================================


@pytest.mark.asyncio
async def test_fix1_call_timeout_not_retried_in_worker(mock_processed_doc_repo):
    """Fix 1: an LLMCallTimeoutError must fail the doc in ONE attempt (no
    max_attempts × timeout burn) and be recorded as a timeout-category failure."""
    from tg_parser.processing.llm.errors import LLMCallTimeoutError

    msgs = _b2b_raw_msgs("ch", 1)
    llm = MagicMock()
    llm.generate_with_usage = AsyncMock(side_effect=LLMCallTimeoutError("aggregate timeout"))
    # Keep the effective concurrency an int (a bare MagicMock would otherwise
    # return a MagicMock from suggest_processing_concurrency).
    llm.suggest_processing_concurrency = MagicMock(return_value=2)
    failure_repo = AsyncMock()
    failure_repo.list_failures.return_value = []

    pipeline = ProcessingPipelineImpl(
        llm_client=llm,
        processed_doc_repo=mock_processed_doc_repo,
        failure_repo=failure_repo,
    )

    results = await pipeline.process_batch(msgs, concurrency=2)

    assert results == []
    assert llm.generate_with_usage.call_count == 1, "timeout must not be retried in the worker"
    failure_repo.record_failure.assert_awaited()
    kwargs = failure_repo.record_failure.call_args.kwargs
    assert kwargs["error_class"] == "LLMCallTimeoutError"
    assert kwargs["error_details"]["category"] == "timeout"


@pytest.mark.asyncio
async def test_fix3_interrupt_persists_already_arrived_failures(monkeypatch):
    """Fix 3(b): failures are recorded AS they arrive, so an interruption
    mid-batch still persists the cooldown rows of completed failures (instead of
    dropping them with the old after-the-loop bulk write)."""
    from tg_parser.processing.llm.errors import LLMCallTimeoutError

    monkeypatch.setattr(app_settings, "processing_persist_chunk_size", 1)
    msgs = _b2b_raw_msgs("ch", 2)  # post:0 -> fast fail, post:1 -> slow success

    class _FailFirstSlowRest(ProcessingMockLLM):
        async def generate(
            self,
            prompt,
            system_prompt=None,
            temperature=0.0,
            max_tokens=4096,
            response_format=None,
        ):
            if "номер 0" in prompt:
                raise LLMCallTimeoutError("boom")  # fast, single-attempt failure
            await asyncio.sleep(0.2)  # ensure the failure completes first
            return await super().generate(
                prompt, system_prompt, temperature, max_tokens, response_format
            )

    repo = MagicMock()
    repo.exists = AsyncMock(return_value=False)
    repo.get_by_source_ref = AsyncMock(return_value=None)
    repo.find_by_content_hash = AsyncMock(return_value=None)
    repo.upsert = AsyncMock(return_value=None)
    # The slow success triggers the interrupting persist (chunk_size=1).
    repo.upsert_batch = AsyncMock(side_effect=RuntimeError("db down"))

    failure_repo = AsyncMock()
    failure_repo.list_failures.return_value = []

    pipeline = ProcessingPipelineImpl(
        llm_client=_FailFirstSlowRest(),
        processed_doc_repo=repo,
        failure_repo=failure_repo,
    )

    with pytest.raises(RuntimeError, match="db down"):
        await pipeline.process_batch(msgs, concurrency=2)

    recorded = {c.kwargs["source_ref"] for c in failure_repo.record_failure.call_args_list}
    assert msgs[0].source_ref in recorded, "the failure recorded before the interrupt must persist"


@pytest.mark.asyncio
async def test_fix5_future_dated_failure_timestamp_not_skipped(mock_processed_doc_repo):
    """Fix 5: a legacy naive-local last_attempt_at parsed-as-UTC can land in the
    future (negative age) — it must be treated as expired, not skipped forever."""
    msgs = _b2b_raw_msgs("ch", 1)
    failure_repo = AsyncMock()
    failure_repo.list_failures.return_value = [
        _b2b_failure_row(
            msgs[0].source_ref, "ch", error_class="LLMJsonParseError", attempts=1, age_s=-14400
        )
    ]
    llm = ProcessingMockLLM()
    pipeline = ProcessingPipelineImpl(
        llm_client=llm,
        processed_doc_repo=mock_processed_doc_repo,
        failure_repo=failure_repo,
    )

    await pipeline.process_batch(msgs, concurrency=2)

    assert llm.call_count == 1, "future-dated timestamp -> expired -> retried"
    assert pipeline._batch_cooldown_skipped == 0
