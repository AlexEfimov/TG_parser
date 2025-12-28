"""
Тесты для Multi-LLM клиентов (v1.2).

Требования: TR-38 (детерминизм), v1.2 Multi-LLM Support.
"""

import pytest

from tg_parser.processing.llm import (
    AnthropicClient,
    GeminiClient,
    OllamaClient,
    OpenAIClient,
    create_llm_client,
    get_model_id_from_client,
    get_provider_from_client,
)


# =============================================================================
# Factory Tests
# =============================================================================


def test_factory_creates_openai_client():
    """Фабрика создаёт OpenAI клиент."""
    client = create_llm_client(
        provider="openai",
        api_key="test-key",
        model="gpt-4o-mini",
    )
    assert isinstance(client, OpenAIClient)
    assert client.model == "gpt-4o-mini"


def test_factory_creates_anthropic_client():
    """Фабрика создаёт Anthropic клиент."""
    client = create_llm_client(
        provider="anthropic",
        api_key="test-key",
        model="claude-sonnet-4-20250514",
    )
    assert isinstance(client, AnthropicClient)
    assert client.model == "claude-sonnet-4-20250514"


def test_factory_creates_gemini_client():
    """Фабрика создаёт Gemini клиент."""
    client = create_llm_client(
        provider="gemini",
        api_key="test-key",
        model="gemini-2.0-flash-exp",
    )
    assert isinstance(client, GeminiClient)
    assert client.model == "gemini-2.0-flash-exp"


def test_factory_creates_ollama_client():
    """Фабрика создаёт Ollama клиент."""
    client = create_llm_client(
        provider="ollama",
        model="llama3.2",
        base_url="http://localhost:11434",
    )
    assert isinstance(client, OllamaClient)
    assert client.model == "llama3.2"


def test_factory_uses_defaults():
    """Фабрика использует default модели."""
    openai_client = create_llm_client(provider="openai", api_key="test-key")
    assert openai_client.model == "gpt-4o-mini"

    anthropic_client = create_llm_client(provider="anthropic", api_key="test-key")
    assert anthropic_client.model == "claude-sonnet-4-20250514"

    gemini_client = create_llm_client(provider="gemini", api_key="test-key")
    assert gemini_client.model == "gemini-2.0-flash-exp"

    ollama_client = create_llm_client(provider="ollama")
    assert ollama_client.model == "llama3.2"


def test_factory_raises_on_unknown_provider():
    """Фабрика выбрасывает ошибку для неизвестного провайдера."""
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        create_llm_client(provider="unknown", api_key="test-key")


def test_factory_raises_on_missing_api_key():
    """Фабрика требует API key для провайдеров (кроме Ollama)."""
    with pytest.raises(ValueError, match="API key required"):
        create_llm_client(provider="openai")

    with pytest.raises(ValueError, match="API key required"):
        create_llm_client(provider="anthropic")

    with pytest.raises(ValueError, match="API key required"):
        create_llm_client(provider="gemini")


def test_factory_case_insensitive():
    """Фабрика работает с любым регистром провайдера."""
    client1 = create_llm_client(provider="OpenAI", api_key="test-key")
    assert isinstance(client1, OpenAIClient)

    client2 = create_llm_client(provider="ANTHROPIC", api_key="test-key")
    assert isinstance(client2, AnthropicClient)


# =============================================================================
# Helper Functions Tests
# =============================================================================


def test_get_model_id_from_client():
    """get_model_id_from_client извлекает model из клиента."""
    openai_client = create_llm_client(provider="openai", api_key="test-key", model="gpt-4")
    assert get_model_id_from_client(openai_client) == "gpt-4"

    anthropic_client = create_llm_client(provider="anthropic", api_key="test-key", model="claude-3")
    assert get_model_id_from_client(anthropic_client) == "claude-3"


def test_get_provider_from_client():
    """get_provider_from_client определяет провайдера по типу клиента."""
    openai_client = create_llm_client(provider="openai", api_key="test-key")
    assert get_provider_from_client(openai_client) == "openai"

    anthropic_client = create_llm_client(provider="anthropic", api_key="test-key")
    assert get_provider_from_client(anthropic_client) == "anthropic"

    gemini_client = create_llm_client(provider="gemini", api_key="test-key")
    assert get_provider_from_client(gemini_client) == "gemini"

    ollama_client = create_llm_client(provider="ollama")
    assert get_provider_from_client(ollama_client) == "ollama"


# =============================================================================
# Client-specific Tests
# =============================================================================


def test_openai_client_initialization():
    """OpenAI клиент инициализируется корректно."""
    client = OpenAIClient(api_key="test-key", model="gpt-4o-mini")
    assert client.api_key == "test-key"
    assert client.model == "gpt-4o-mini"
    assert client.base_url == "https://api.openai.com/v1"


def test_openai_client_custom_base_url():
    """OpenAI клиент поддерживает custom base URL."""
    client = OpenAIClient(api_key="test-key", base_url="http://localhost:8000/v1/")
    assert client.base_url == "http://localhost:8000/v1"  # trailing slash removed


def test_anthropic_client_initialization():
    """Anthropic клиент инициализируется корректно."""
    client = AnthropicClient(api_key="test-key", model="claude-sonnet-4-20250514")
    assert client.api_key == "test-key"
    assert client.model == "claude-sonnet-4-20250514"
    assert client.max_tokens == 4096


def test_gemini_client_initialization():
    """Gemini клиент инициализируется корректно."""
    client = GeminiClient(api_key="test-key", model="gemini-2.0-flash-exp")
    assert client.api_key == "test-key"
    assert client.model == "gemini-2.0-flash-exp"


def test_ollama_client_initialization():
    """Ollama клиент инициализируется корректно."""
    client = OllamaClient(model="llama3.2", base_url="http://localhost:11434")
    assert client.model == "llama3.2"
    assert client.base_url == "http://localhost:11434"


def test_ollama_client_default_base_url():
    """Ollama клиент использует default base URL."""
    client = OllamaClient(model="llama3.2")
    assert client.base_url == "http://localhost:11434"


# =============================================================================
# Prompt ID Tests (TR-40: детерминизм)
# =============================================================================


def test_compute_prompt_id_deterministic():
    """compute_prompt_id возвращает стабильный hash."""
    client = OpenAIClient(api_key="test-key")
    
    system_prompt = "You are a helpful assistant."
    user_template = "Process: {text}"
    
    prompt_id_1 = client.compute_prompt_id(system_prompt, user_template)
    prompt_id_2 = client.compute_prompt_id(system_prompt, user_template)
    
    assert prompt_id_1 == prompt_id_2
    assert prompt_id_1.startswith("sha256:")


def test_compute_prompt_id_different_prompts():
    """compute_prompt_id возвращает разные hash для разных промптов."""
    client = OpenAIClient(api_key="test-key")
    
    prompt_id_1 = client.compute_prompt_id("System 1", "User 1")
    prompt_id_2 = client.compute_prompt_id("System 2", "User 2")
    
    assert prompt_id_1 != prompt_id_2


def test_compute_prompt_id_same_across_clients():
    """compute_prompt_id одинаковый для всех клиентов (для одних промптов)."""
    system_prompt = "You are a helpful assistant."
    user_template = "Process: {text}"
    
    openai_client = OpenAIClient(api_key="test-key")
    anthropic_client = AnthropicClient(api_key="test-key")
    gemini_client = GeminiClient(api_key="test-key")
    ollama_client = OllamaClient()
    
    openai_id = openai_client.compute_prompt_id(system_prompt, user_template)
    anthropic_id = anthropic_client.compute_prompt_id(system_prompt, user_template)
    gemini_id = gemini_client.compute_prompt_id(system_prompt, user_template)
    ollama_id = ollama_client.compute_prompt_id(system_prompt, user_template)
    
    # Все должны возвращать одинаковый hash
    assert openai_id == anthropic_id == gemini_id == ollama_id


# =============================================================================
# Integration Tests (require mocking HTTP)
# =============================================================================


@pytest.mark.asyncio
async def test_openai_client_close():
    """OpenAI клиент корректно закрывает HTTP клиент."""
    client = OpenAIClient(api_key="test-key")
    await client.close()
    # Проверяем что клиент закрыт
    assert client.client.is_closed


@pytest.mark.asyncio
async def test_anthropic_client_close():
    """Anthropic клиент корректно закрывает HTTP клиент."""
    client = AnthropicClient(api_key="test-key")
    await client.close()
    assert client._client.is_closed


@pytest.mark.asyncio
async def test_gemini_client_close():
    """Gemini клиент корректно закрывает HTTP клиент."""
    client = GeminiClient(api_key="test-key")
    await client.close()
    assert client._client.is_closed


@pytest.mark.asyncio
async def test_ollama_client_close():
    """Ollama клиент корректно закрывает HTTP клиент."""
    client = OllamaClient()
    await client.close()
    assert client._client.is_closed

