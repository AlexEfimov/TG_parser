# Тесты TG_parser

Запуск тестов:

```bash
pytest
```

## Покрытие

Основные тесты покрывают ключевые инварианты из `docs/testing-strategy.md`:

- **test_ids.py**: канонизация идентификаторов (TR-IF-5, TR-41, TR-IF-4, TR-61)
- **test_telegram_url.py**: резолюция Telegram URL (TR-58/TR-65)
- **test_models.py**: валидация Pydantic моделей против контрактов (TR-IF-1)
