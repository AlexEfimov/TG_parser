# INBOX — raw quality observations

**Purpose:** low-friction intake for anything that looks wrong, surprising, or
rough while using / testing `tg_parser`. Newest entries on top.

> **Для AI-агента:** полный алгоритм заполнения этого файла описан в
> [`AGENT_PLAYBOOK.md`](AGENT_PLAYBOOK.md). Пользователь даёт описание
> ситуации своими словами — агент читает playbook и производит правильный
> артефакт. Ручное заполнение человеком — по правилам ниже (короткая
> версия playbook'а §0–§3).

**Rules:**

1. **Write first, triage never-while-writing.** Your only job when adding an
   entry is to capture enough that tomorrow-you doesn't lose context. Do not
   stop to decide severity or component if it slows you down — guess, move on.
2. **One entry per observation.** If three things felt broken, write three
   entries. Cheap to merge later, expensive to split.
3. **Dated heading, taxonomy labels, then free-form body.** Follow the template
   in [`_TEMPLATE_OBSERVATION.md`](_TEMPLATE_OBSERVATION.md). Labels come from
   [`TAXONOMY.md`](TAXONOMY.md).
4. **After triage, entries move to [`TRIAGED.md`](TRIAGED.md)** with a
   disposition (→ sprint X.Y, duplicate, wontfix). Do not delete from INBOX —
   cut-paste so the git history preserves the note (see
   [`AGENT_PLAYBOOK.md`](AGENT_PLAYBOOK.md) §7 for exact mechanics).
5. **Bigger than 5 lines?** Create a file in `incidents/` using
   [`_TEMPLATE_INCIDENT.md`](_TEMPLATE_INCIDENT.md), and leave a one-line
   pointer in INBOX.

**Triage cadence:** batch-triage the full INBOX before planning each sprint
(i.e. when reading `ROADMAP_V3_PRODUCTION_FIRST.md` to pick the next scope).
Mid-sprint triage only for `P0`.

---

## Open entries

## 2026-08-28 16:00 UTC — topicization · perf · P2

→ [`incidents/2026-08-28_anthropic_spend_phase2_discover.md`](incidents/2026-08-28_anthropic_spend_phase2_discover.md)

Пустой баланс Anthropic сегодня — не TG_parser (~$1.80 / ~$9 за 7д). Остаётся Phase 2 discover: полный кросс-канальный каталог тем в каждый keyword-miss (~260k Sonnet ≈ $0.80). Вернуться до пополнения кредита.

---

<!--
Example entry (uncomment + edit when adding a real one):

## 2026-04-21 08:45 UTC — bot · ux · P2

**Что:** `/ask` в личке выдаёт "Нет данных" для вопроса про genotek, хотя
канал добавлен и видно ingest-активность.

**Как воспроизвести:** `/ask какие продукты у genotek?` в DM бота, user=admin.

**Ожидал:** либо осмысленный ответ, либо явный "ещё обрабатываем, канал только
что добавлен, подожди ~N минут".

**Контекст:** VPS production, main @ <commit>, канал добавлен 2026-04-20 ~18:00.

**Заметки:** вероятно связано с "topicization silent failure" —
→ incidents/2026-04-20_genotek_topicization_silent_failure.md
-->

---

## Reference

- Agent playbook (how AI fills this file): [`AGENT_PLAYBOOK.md`](AGENT_PLAYBOOK.md)
- Labels + severity: [`TAXONOMY.md`](TAXONOMY.md)
- Short-entry template: [`_TEMPLATE_OBSERVATION.md`](_TEMPLATE_OBSERVATION.md)
- Incident/RCA template: [`_TEMPLATE_INCIDENT.md`](_TEMPLATE_INCIDENT.md)
- Triaged history: [`TRIAGED.md`](TRIAGED.md)
- Known incidents: [`incidents/`](incidents/)
