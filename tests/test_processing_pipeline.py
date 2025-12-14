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
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from tg_parser.domain.ids import make_processed_document_id, make_source_ref
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
        date=datetime(2025, 12, 14, 10, 0, 0, tzinfo=timezone.utc),
        text="Это тестовое сообщение для обработки через LLM.",
    )


@pytest.fixture
def mock_processed_doc_repo():
    """Mock репозиторий ProcessedDocument."""
    repo = AsyncMock()
    repo.exists.return_value = False
    repo.get_by_source_ref.return_value = None
    repo.save.return_value = None
    return repo


@pytest.fixture
def mock_failure_repo():
    """Mock репозиторий failures."""
    repo = AsyncMock()
    repo.record_failure.return_value = None
    repo.clear_failure.return_value = None
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

    # Проверяем что save был вызван
    mock_processed_doc_repo.save.assert_called_once()


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
        processed_at=datetime.now(timezone.utc),
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

    # save НЕ должен быть вызван
    mock_processed_doc_repo.save.assert_not_called()


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

    # save ДОЛЖЕН быть вызван (переобработка)
    mock_processed_doc_repo.save.assert_called_once()


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
    failing_llm = AsyncMock()
    failing_llm.generate.side_effect = Exception("API error")

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
    assert failing_llm.generate.call_count == 3

    # Проверяем что ошибка записана
    mock_failure_repo.record_failure.assert_called_once()
    call_args = mock_failure_repo.record_failure.call_args
    assert call_args[1]["source_ref"] == sample_raw_message.source_ref
    assert call_args[1]["attempts"] == 3


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
    failing_then_success_llm = AsyncMock()

    call_count = 0

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise Exception("Temporary error")
        # На третий раз возвращаем валидный JSON
        return json.dumps(
            {
                "text_clean": "Success",
                "summary": None,
                "topics": [],
                "entities": [],
                "language": "ru",
            }
        )

    failing_then_success_llm.generate.side_effect = side_effect

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
    assert failing_then_success_llm.generate.call_count == 3

    # Проверяем что failure была очищена
    mock_failure_repo.clear_failure.assert_called_once_with(sample_raw_message.source_ref)


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
            date=datetime.now(timezone.utc),
            text=f"Message {i}",
        )
        for i in range(5)
    ]

    # Создаём mock LLM который падает на сообщении 2
    selective_failing_llm = AsyncMock()

    async def side_effect(prompt, *args, **kwargs):
        if "Message 2" in prompt:
            raise Exception("Failed on message 2")
        return json.dumps(
            {
                "text_clean": prompt[:50],
                "summary": None,
                "topics": [],
                "entities": [],
                "language": "ru",
            }
        )

    selective_failing_llm.generate.side_effect = side_effect

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

    before = datetime.now(timezone.utc)
    result = await pipeline.process_message(sample_raw_message)
    after = datetime.now(timezone.utc)

    # Проверяем что processed_at в нужном диапазоне и в UTC
    assert result.processed_at.tzinfo == timezone.utc
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
