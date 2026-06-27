"""
Порты (интерфейсы) для слоя обработки.

Реализует ADR-0004: порты не зависят от инфраструктуры.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from tg_parser.domain.models import ProcessedDocument, RawTelegramMessage, TopicBundle, TopicCard


@dataclass
class LLMResponse:
    """Result of an LLM generation call, including token usage metadata."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    # BUG-071 (Fix 1): provider stop reason (e.g. Anthropic ``stop_reason``).
    # ``"max_tokens"`` means the reply was TRUNCATED at the output cap — the
    # call was still charged but the body is cut off mid-token, so callers must
    # NOT blindly re-issue the identical oversized request (it just re-burns
    # tokens). Providers that don't surface a stop reason leave this ``None``.
    stop_reason: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMClient(ABC):
    """
    Порт для взаимодействия с LLM.

    Реализации: OpenAI, Anthropic, OpenAI-compatible и т.п.
    """

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> str:
        """
        Сгенерировать ответ LLM.

        Args:
            prompt: Основной промпт
            system_prompt: Системный промпт (опционально)
            temperature: Параметр стохастики (TR-38)
            max_tokens: Лимит токенов
            response_format: Формат ответа (например {"type": "json_object"})

        Returns:
            Текст ответа от LLM
        """
        pass

    async def generate_with_usage(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> LLMResponse:
        """Generate with token usage tracking. Default: delegates to generate()."""
        text = await self.generate(prompt, system_prompt, temperature, max_tokens, response_format)
        return LLMResponse(text=text)


class ProcessingPipeline(ABC):
    """
    Порт для пайплайна обработки сообщений.

    TR-21: 1 raw → 1 processed
    """

    @abstractmethod
    async def process_message(
        self,
        message: RawTelegramMessage,
        force: bool = False,
    ) -> ProcessedDocument:
        """
        Обработать одно сырое сообщение.

        Args:
            message: RawTelegramMessage
            force: Переобработать даже если уже есть processed (TR-46)

        Returns:
            ProcessedDocument
        """
        pass

    @abstractmethod
    async def process_batch(
        self,
        messages: list[RawTelegramMessage],
        force: bool = False,
    ) -> list[ProcessedDocument]:
        """
        Обработать батч сообщений.

        TR-47: ошибка на одном сообщении не должна ронять весь батч.

        Args:
            messages: Список RawTelegramMessage
            force: Переобработать даже если уже есть processed

        Returns:
            Список ProcessedDocument (могут быть пропуски при ошибках)
        """
        pass


class TopicizationPipeline(ABC):
    """
    Порт для пайплайна тематизации.

    TR-27..TR-37: формирование TopicCard и TopicBundle.
    """

    @abstractmethod
    async def topicize_channel(
        self,
        channel_id: str,
        force: bool = False,
    ) -> list[TopicCard]:
        """
        Сформировать темы для канала.

        TR-30: все ProcessedDocument канала используются для тематизации.
        TR-32: детерминизм (при одинаковых входных данных результат стабилен).

        Args:
            channel_id: Идентификатор канала
            force: Переформировать темы даже если уже есть

        Returns:
            Список TopicCard
        """
        pass

    @abstractmethod
    async def build_topic_bundle(
        self,
        topic_card: TopicCard,
        channel_id: str,
    ) -> TopicBundle:
        """
        Сформировать подборку материалов по теме.

        TR-36: формирование TopicBundle с anchor и supporting items.

        Args:
            topic_card: Карточка темы
            channel_id: Идентификатор канала

        Returns:
            TopicBundle
        """
        pass
