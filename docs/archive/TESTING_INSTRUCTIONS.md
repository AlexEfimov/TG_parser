# Testing Instructions для v1.2.0

## 🧪 Готовые тестовые скрипты

### 1. **test_anthropic_gemini.py** — Базовое тестирование Anthropic и Gemini

**Что тестирует:**
- Anthropic Claude 3.5 Sonnet (10 сообщений)
- Google Gemini 2.0 Flash (10 сообщений)
- Performance метрики
- Quality метрики
- Сравнение с результатами OpenAI

**Запуск:**
```bash
cd /Users/alexanderefimov/TG_parser
source .venv/bin/activate
python test_anthropic_gemini.py
```

**Длительность:** ~5-10 минут

**Результат:** `test_results_all_cloud_providers.json`

---

### 2. **test_concurrency_cloud.py** — Performance тестирование с concurrency

**Что тестирует:**
- Все 3 провайдера (OpenAI, Anthropic, Gemini)
- Concurrency levels: 1, 3, 5
- 15 сообщений на каждый тест
- Speedup анализ

**Запуск:**
```bash
cd /Users/alexanderefimov/TG_parser
source .venv/bin/activate
python test_concurrency_cloud.py
```

**Длительность:** ~20-30 минут

**Результат:** `test_results_concurrency.json`

---

### 3. **test_cloud_providers_comparison.py** — Полное сравнение всех провайдеров

**Что тестирует:**
- OpenAI, Anthropic, Gemini (10 сообщений каждый)
- Детальные метрики качества
- Performance сравнение

**Запуск:**
```bash
cd /Users/alexanderefimov/TG_parser
source .venv/bin/activate
python test_cloud_providers_comparison.py
```

**Длительность:** ~10-15 минут

**Результат:** `test_results_cloud_providers.json`

---

## 📋 Рекомендуемая последовательность

### После пополнения баланса Anthropic и Gemini:

**Шаг 1: Проверка API ключей**
```bash
cd /Users/alexanderefimov/TG_parser
python3 << 'EOF'
from tg_parser.config import settings

print("API Keys Status:")
print(f"OpenAI: {'✅ OK' if settings.openai_api_key and settings.openai_api_key.startswith('sk-proj-') else '❌ INVALID'}")
print(f"Anthropic: {'✅ OK' if settings.anthropic_api_key and settings.anthropic_api_key.startswith('sk-ant-') else '❌ INVALID'}")
print(f"Gemini: {'✅ OK' if settings.gemini_api_key and settings.gemini_api_key.startswith('AIza') else '❌ INVALID'}")
EOF
```

**Шаг 2: Базовое тестирование (быстрое)**
```bash
source .venv/bin/activate
python test_anthropic_gemini.py
```

Это протестирует только Anthropic и Gemini, добавит результаты к уже имеющимся OpenAI.

**Шаг 3: Concurrency тестирование (опционально)**
```bash
python test_concurrency_cloud.py
```

Это покажет оптимальные значения concurrency для каждого провайдера.

---

## ✅ Критерии успеха

### Для каждого провайдера:
- [ ] Success rate: > 90% (9/10 или 10/10)
- [ ] Summary coverage: 100% (все документы имеют summary)
- [ ] Topics coverage: > 80% (большинство документов имеют темы)
- [ ] Language accuracy: 100% (язык определён правильно как 'ru')
- [ ] Нет критических ошибок (timeout, auth errors, quota errors)

### Performance:
- [ ] OpenAI: ~0.1-0.2 msg/sec
- [ ] Anthropic: ~0.15-0.3 msg/sec (ожидается быстрее OpenAI)
- [ ] Gemini: ~0.2-0.4 msg/sec (ожидается самый быстрый)

### Concurrency:
- [ ] Speedup при concurrency=3: ~2-2.5x
- [ ] Speedup при concurrency=5: ~3-4x
- [ ] Нет деградации success rate при высоком concurrency

---

## 🐛 Troubleshooting

### Anthropic: "credit balance too low"
```bash
# Решение: пополнить баланс
# https://console.anthropic.com/settings/billing
```

### Gemini: "429 quota exceeded"
```bash
# Решение 1: подождать сброса квоты (24 часа)
# Решение 2: перейти на платный план
# https://ai.google.dev/pricing
```

### OpenAI: "invalid API key"
```bash
# Проверить ключ в .env
grep OPENAI_API_KEY .env
# Ключ должен начинаться с sk-proj- (новый формат)
```

---

## 📊 Ожидаемые результаты

После успешного тестирования у вас будут:

1. **test_results_all_cloud_providers.json** — сравнение всех провайдеров
2. **test_results_concurrency.json** — оптимальный concurrency для каждого
3. Данные для создания **TESTING_RESULTS_v1.2.md**

---

## 💾 Результаты уже имеются

### OpenAI ✅
- Протестирован: 10/10 успешно
- Avg time: 8.3s per message
- Quality: отличное (100% summary, topics, language)

### Ollama ✅
- Протестирован: 848 сообщений успешно
- Avg time: ~42s per message (локально)
- Quality: хорошее (некоторые summary на английском)
- Concurrency: НЕ рекомендуется (негативный эффект)

### Anthropic ⏳
- Ожидает пополнения баланса

### Gemini ⏳
- Ожидает пополнения баланса или сброса квоты

---

**Готовы к запуску!** 🚀

После того как вы пополните баланс, просто запустите:
```bash
python test_anthropic_gemini.py
```

