"""
Утилиты для стабильной JSON-сериализации.

Реализует требования детерминизма экспортов (TR-63) и тестов.
"""

import json
from datetime import datetime
from typing import Any


def stable_json_dumps(obj: Any, pretty: bool = False) -> str:
    """
    Сериализовать объект в JSON с стабильной сортировкой ключей.

    Требования:
    - TR-63: детерминизм экспортов и диффов
    - Стабильная сортировка ключей
    - Разделители без лишних пробелов (если не pretty)
    - Даты в ISO 8601 UTC

    Args:
        obj: Объект для сериализации
        pretty: Использовать отступы для читаемости

    Returns:
        JSON-строка
    """
    if pretty:
        return json.dumps(
            obj,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=_json_default,
        )
    else:
        return json.dumps(
            obj,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        )


def stable_json_loads(s: str) -> Any:
    """
    Десериализовать JSON-строку.

    Args:
        s: JSON-строка

    Returns:
        Объект Python
    """
    return json.loads(s)


def _json_default(obj: Any) -> Any:
    """
    Custom JSON encoder для datetime и других типов.

    Args:
        obj: Объект для сериализации

    Returns:
        JSON-serializable representation

    Raises:
        TypeError: если тип не поддерживается
    """
    if isinstance(obj, datetime):
        # ISO 8601 UTC format (docs/architecture.md)
        return obj.strftime("%Y-%m-%dT%H:%M:%SZ") if obj.tzinfo is None else obj.isoformat()

    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def parse_iso_datetime(s: str) -> datetime:
    """
    Парсить ISO 8601 datetime строку.

    Args:
        s: ISO datetime string (например "2025-12-13T10:00:00Z")

    Returns:
        datetime object (naive UTC)
    """
    # Убираем Z suffix если есть и парсим как naive UTC
    if s.endswith("Z"):
        s = s[:-1]

    return datetime.fromisoformat(s)
