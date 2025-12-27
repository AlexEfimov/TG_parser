# Session 13 — Quick Start Checklist

**Mission**: Extended Testing & Documentation для v1.2.0

---

## ⚡ Quick Commands

### 1. Проверка окружения (2 мин)
```bash
cd /Users/alexanderefimov/TG_parser
source .venv/bin/activate
python --version  # Должно быть 3.12.0
pytest --tb=short -q  # Должно быть 126 passed
```

### 2. Проверка данных (1 мин)
```bash
sqlite3 raw_storage.sqlite "SELECT COUNT(*) FROM raw_telegram_messages;"
sqlite3 processing_storage.sqlite "SELECT COUNT(*) FROM processed_documents;"
sqlite3 processing_storage.sqlite "SELECT DISTINCT channel_id FROM processed_documents;"
```

### 3. Проверка API ключей (1 мин)
```bash
cat .env | grep API_KEY
# Если нужны реальные ключи:
# - OpenAI: platform.openai.com
# - Anthropic: console.anthropic.com
# - Gemini: aistudio.google.com
```

---

## 🧪 Test Plan (Summary)

### Этап 1: Baseline (30 мин)
- [ ] OpenAI: process 10 messages
- [ ] Anthropic: process 10 messages
- [ ] Ollama: process 10 messages
- [ ] Все успешно? → Этап 2

### Этап 2: Performance (45 мин)
- [ ] concurrency=1 (baseline)
- [ ] concurrency=3 (ожидается 2-3x ускорение)
- [ ] concurrency=5 (ожидается 3-5x ускорение)

### Этап 3: Integration (30 мин)
- [ ] Full pipeline OpenAI
- [ ] Full pipeline Anthropic

### Этап 4: Docker (20 мин)
- [ ] docker build
- [ ] docker run --help
- [ ] docker-compose test

---

## 📚 Documentation Plan (Summary)

- [ ] README.md — Multi-LLM examples
- [ ] TESTING_RESULTS_v1.2.md — create
- [ ] docs/USER_GUIDE.md — Multi-LLM section
- [ ] MIGRATION_GUIDE_v1.1_to_v1.2.md — create
- [ ] SESSION_HANDOFF_v1.2.md — finalize

---

## 🎯 Success Criteria

### Must Have
- [ ] ✅ 126 unit тестов
- [ ] ✅ 1+ провайдер работает на реальных данных
- [ ] ✅ Concurrency работает
- [ ] ✅ Docker build + run
- [ ] ✅ README обновлён
- [ ] ✅ CHANGELOG обновлён
- [ ] ✅ SESSION_HANDOFF завершён

### Release Ready
- [ ] git tag v1.2.0
- [ ] GitHub Release
- [ ] START_PROMPT_SESSION14.md (v2.0)

---

## 📄 Key Files

### Read First
1. `docs/notes/START_PROMPT_SESSION13.md` — детальный план
2. `docs/notes/SESSION12_SUMMARY.md` — что сделано
3. `docs/notes/SESSION_HANDOFF_v1.2.md` — технические детали

### Test Scripts
- `test_multi_llm.py` — unit тесты
- `test_llm_comparison.py` — качество
- `test_comprehensive_benchmark.py` — benchmark

### Documentation
- `LLM_SETUP_GUIDE.md` — настройка провайдеров
- `QUICKSTART_v1.2.md` — быстрый старт
- `.env.example` — конфигурация

---

## 💬 Questions to Clarify

1. **Какие провайдеры тестировать?**
   - Все 4 (OpenAI, Anthropic, Gemini, Ollama)?
   - Или только доступные (с API ключами)?

2. **Сколько сообщений?**
   - 10 для быстрого теста?
   - 100 для полного теста?
   - Все 846?

3. **Stress test нужен?**
   - Протестировать на большом объёме?
   - Или достаточно baseline?

4. **Документация — уровень детализации?**
   - Полная (примеры для всех провайдеров)?
   - Минимальная (только основное)?

---

**Ready to start Session 13?** 🚀

**First Action**: Утвердить план тестирования из `START_PROMPT_SESSION13.md`

