"""
Mock LLM для тестирования и разработки.

Реализует интерфейс LLMClient без реальных API вызовов.
"""

import json

from tg_parser.processing.ports import LLMClient


class MockLLMClient(LLMClient):
    """
    Mock реализация LLMClient для тестирования.

    Возвращает предсказуемые ответы без реальных API вызовов.
    Можно настроить возвращаемые значения через конструктор.
    """

    def __init__(
        self,
        default_response: str | None = None,
        response_map: dict[str, str] | None = None,
    ):
        """
        Args:
            default_response: Ответ по умолчанию
            response_map: Маппинг prompt → response для специфичных ответов
        """
        self.default_response = default_response or "Mock LLM response"
        self.response_map = response_map or {}
        self.call_count = 0
        self.last_prompt = None
        self.last_params = {}

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> str:
        """
        Сгенерировать mock ответ.

        Сохраняет параметры вызова для тестирования.
        """
        self.call_count += 1
        self.last_prompt = prompt
        self.last_params = {
            "system_prompt": system_prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
        }

        # Проверяем маппинг для специфичных промптов
        for key, response in self.response_map.items():
            if key in prompt:
                return response

        # Если запрошен JSON формат, возвращаем валидный JSON
        if response_format and response_format.get("type") == "json_object":
            return json.dumps(
                {
                    "text_clean": "Cleaned text from mock LLM",
                    "summary": "Mock summary",
                    "topics": ["mock_topic_1", "mock_topic_2"],
                    "entities": [],
                    "language": "ru",
                }
            )

        return self.default_response


class DeterministicMockLLM(LLMClient):
    """
    Детерминированный mock LLM для тестирования идемпотентности.

    Всегда возвращает одинаковый ответ для одинакового промпта.
    """

    def __init__(self):
        self.responses: dict[str, str] = {}

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> str:
        """
        Генерация детерминированного ответа на основе хэша промпта.
        """
        # Создаём уникальный ключ из промпта и параметров
        key = f"{prompt}:{system_prompt}:{temperature}"

        if key not in self.responses:
            # Генерируем "уникальный" но детерминированный ответ
            hash_val = hash(key) % 1000

            if response_format and response_format.get("type") == "json_object":
                self.responses[key] = json.dumps(
                    {
                        "text_clean": f"Cleaned text {hash_val}",
                        "summary": f"Summary {hash_val}",
                        "topics": [f"topic_{hash_val}"],
                        "entities": [],
                        "language": "ru",
                    }
                )
            else:
                self.responses[key] = f"Deterministic response {hash_val}"

        return self.responses[key]


class ProcessingMockLLM(LLMClient):
    """
    Специализированный mock для processing pipeline.

    Возвращает реалистичные ProcessedDocument данные.
    """

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> str:
        """
        Генерация данных для ProcessedDocument.
        """
        # Извлекаем текст из промпта (простая эвристика)
        text_lines = [
            line for line in prompt.split("\n") if line.strip() and not line.startswith("#")
        ]
        original_text = " ".join(text_lines[:3]) if text_lines else "Mock text"

        # Генерируем реалистичный ответ
        response = {
            "text_clean": original_text[:200] + "...",  # Ограничиваем длину
            "summary": f"Краткое содержание: {original_text[:100]}",
            "topics": ["общая_информация", "обсуждение"],
            "entities": [{"type": "person", "value": "Автор", "confidence": 0.9}],
            "language": "ru",
        }

        return json.dumps(response, ensure_ascii=False)
