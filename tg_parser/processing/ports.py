"""
Порты (интерфейсы) для слоя обработки.

Реализует ADR-0004: порты не зависят от инфраструктуры.
"""

from abc import ABC, abstractmethod

from tg_parser.domain.models import ProcessedDocument, RawTelegramMessage


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
