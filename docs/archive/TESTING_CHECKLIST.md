# v1.2.0 Testing Checklist

## ✅ Completed

- [x] Unit тесты: 373/373 passed ✅ (v3.0.0)
- [x] OpenAI baseline test: 10/10 успешно ✅
- [x] Ollama baseline test: 848/848 успешно ✅
- [x] Ollama concurrency test: completed (негативный эффект обнаружен) ✅
- [x] API ключи сконфигурированы (все 3 провайдера) ✅

## ⏳ Pending (ждём пополнения баланса)

### Baseline тесты облачных провайдеров

- [ ] **Anthropic Claude 3.5 Sonnet** — 10 сообщений
  - Скрипт: `test_anthropic_gemini.py`
  - Статус: Ожидает пополнения баланса
  - Ожидаемое время: ~2-3 минуты

- [ ] **Google Gemini 2.0 Flash** — 10 сообщений
  - Скрипт: `test_anthropic_gemini.py`
  - Статус: Ожидает пополнения баланса
  - Ожидаемое время: ~1-2 минуты

### Concurrency тесты (опционально)

- [ ] **OpenAI** — concurrency [1, 3, 5]
  - Скрипт: `test_concurrency_cloud.py`
  - Ожидаемое время: ~8-10 минут

- [ ] **Anthropic** — concurrency [1, 3, 5]
  - Скрипт: `test_concurrency_cloud.py`
  - Ожидаемое время: ~6-8 минут

- [ ] **Gemini** — concurrency [1, 3, 5]
  - Скрипт: `test_concurrency_cloud.py`
  - Ожидаемое время: ~4-6 минут

## 🐳 Docker тестирование

- [ ] Docker build
- [ ] Docker run (basic commands)
- [ ] Docker compose (с Ollama)

## 📚 Документация

- [ ] Обновить README.md (Multi-LLM секция)
- [ ] Создать TESTING_RESULTS_v1.2.md
- [ ] Обновить docs/USER_GUIDE.md
- [ ] Создать MIGRATION_GUIDE_v1.1_to_v1.2.md
- [ ] Создать START_PROMPT_SESSION14.md (v2.0)

---

## 🚀 Next Steps

### Сразу после пополнения баланса:

1. **Проверить баланс активирован:**
   ```bash
   # Попробовать простой запрос к API
   curl -X POST https://api.anthropic.com/v1/messages \
     -H "x-api-key: $ANTHROPIC_API_KEY" \
     -H "anthropic-version: 2023-06-01" \
     -H "content-type: application/json" \
     -d '{"model":"claude-sonnet-4-20250514","max_tokens":10,"messages":[{"role":"user","content":"Hi"}]}'
   ```

2. **Запустить базовое тестирование:**
   ```bash
   cd /Users/alexanderefimov/TG_parser
   source .venv/bin/activate
   python test_anthropic_gemini.py
   ```

3. **Проверить результаты:**
   ```bash
   cat test_results_all_cloud_providers.json | python -m json.tool
   ```

4. **(Опционально) Запустить concurrency тесты:**
   ```bash
   python test_concurrency_cloud.py
   ```

---

## 📊 Success Criteria

### Must Have (для релиза v1.2.0):
- [x] Unit тесты: 325/325 ✅ (v3.0.0 Phase 3B)
- [ ] Минимум 2 облачных провайдера работают (OpenAI ✅, ждём Anthropic или Gemini)
- [ ] Docker build работает
- [ ] Документация обновлена (README, USER_GUIDE)
- [ ] TESTING_RESULTS_v1.2.md создан

### Nice to Have:
- [ ] Все 3 облачных провайдера протестированы
- [ ] Concurrency benchmarks для всех провайдеров
- [ ] Docker compose полностью протестирован
- [ ] MIGRATION_GUIDE создан

---

## 📝 Notes

### Обнаруженные особенности:

1. **Ollama concurrency:** Негативный эффект при параллелизации
   - Concurrency=1: 615s (baseline)
   - Concurrency=3: 697s (на 13% медленнее)
   - Concurrency=5: 744s (на 21% медленнее, + таймауты)
   - **Рекомендация:** Использовать concurrency=1 для Ollama

2. **OpenAI качество:** Отличное
   - 100% summary coverage
   - 100% topics coverage  
   - 100% language accuracy
   - 50% entities coverage (приемлемо)

3. **API Issues:**
   - Anthropic: "credit balance too low" (требует пополнения)
   - Gemini: "429 quota exceeded" (требует ожидания или upgrade)

---

**Status:** Ожидаем пополнения баланса Anthropic и Gemini для продолжения тестирования 🚀

