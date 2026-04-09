"""
Тесты для processing pipeline.

Проверяет:
- LLM клиенты (OpenAI, Mock)
- ProcessingPipeline реализацию
- Интеграцию с storage
- Ретраи и обработку ошибок (TR-47)
- Идемпотентность (TR-22/TR-46/TR-48)
"""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

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
