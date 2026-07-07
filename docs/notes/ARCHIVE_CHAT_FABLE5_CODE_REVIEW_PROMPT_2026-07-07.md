# Archived Chat — Fable 5 Code-Review Prompt Preparation

- **Chat ID:** `a6d67d2b-69ac-4cab-9e92-7e2dd14e0245`
- **Date/time:** Jul 7, 2026, 13:00 (UTC+3)
- **Topic:** User asked the assistant to study Anthropic's prompting recommendations for "Fable 5" and to prepare a Fable 5 prompt for a detailed, READ-ONLY code review of the `tg_parser` project, focused on the information-processing algorithms extracted from Telegram channels. The assistant coordinated the work via two parallel subagents.
- **Participants:**
  - **User**
  - **Assistant** (coordinator)
  - **Subagent A — Anthropic/Fable 5 prompting research**
  - **Subagent B — tg_parser processing-algorithms map**

> **Note on the final prompt file:** The main transcript ends after the two subagents were launched (it does not contain the synthesis step). However, the resulting prompt file **`docs/notes/START_PROMPT_FABLE5_CODE_REVIEW_PROCESSING_ALGORITHMS_2026-07-07.md` DOES exist** in the workspace, indicating the assistant subsequently synthesized and wrote the final Fable 5 code-review prompt after the archived portion of the conversation.

---

## Turn 1 — User

**Timestamp:** Tuesday, Jul 7, 2026, 1:00 PM (UTC+3)

Full user query (verbatim):

> Ознакомься с рекомендациями Anthropic по написанию промптов для Fable 5.
> Подготовь промпт для Fable 5 для проведения подробного code-review проекта tg_parser.
>
> Главные Задачи code-review:
> - Выявить алгоритмы используемые для обработки информации извлекаемой из тг каналов. Оценить эффективность этих алгоритмов с точки зрения скорости, качества обработки, эффективности использования токенов (расхода денег), эффективности взаимодействия с другими частями проекта и тп.
> - Оценить правильность выбора именно этих алгоритмов и дать предложения по возможной оптимизации и/или альтернативным решениям.
> - Оценить качество программной реализации алгоритмов обработки информации из тг каналов. Дать свои предложения по оптимизации.
> - Для каждой из предложенных оптимизаций оценить стоимость ее реализации (рефакторинга кода) и ее целесообразность этого рефакторинга.
>
> Review - строго Read Only! Код не меняем. На выходе должен быть документ в формате .md Содержащий отчет и выводы.

---

## Turn 2 — Assistant

**Assistant message / reasoning (summary):**

The assistant framed the work as a coordination task with two independent workstreams: (1) researching Anthropic's prompt-engineering guidance relevant to Fable 5, and (2) mapping the `tg_parser` information-processing algorithms so the prompt could be concrete and targeted. It clarified the scope: the deliverable is the *prompt itself*, not the code review output. Since writing the final prompt requires combining insights from both research streams, the assistant decided to keep the synthesis in the foreground and launch two subagents in parallel, then save the final prompt as a Markdown file.

**Tool calls:**

- `Task` (subagent, background) — **"Research Fable 5 prompting guidance"** → generalPurpose subagent. Key instructions summarized: research Anthropic's official prompt-engineering recommendations focused on the newest "Fable 5" model family (fall back to latest general Claude guidance if no Fable-5-specific docs). Goal: enable writing a large, high-quality prompt for a READ-ONLY code review producing a Markdown report. Requested a synthesis covering: (1) Fable-5-specific/latest-model guidance (with release date/naming); (2) core techniques — role/system prompt, being clear/direct, XML tags, context/motivation ("why"), multishot examples, chain-of-thought/`<thinking>` and how it interacts with extended/interleaved thinking, prefilling/output-format control, long-context/long-document handling (placement, quote-first grounding), handling large codebases, clean Markdown output, reducing hallucination/grounding; (3) agentic/extended-thinking guidance on tool use, NOT modifying files, staying read-only; (4) concrete do's and don'ts for a code-review prompt. Cite URLs, no file changes, return Markdown.

- `Task` (subagent, background) — **"Map tg_parser processing algorithms"** → explore subagent, "very thorough". Key instructions summarized: explore `/Users/alexanderefimov/TG_parser` and produce a structured inventory feeding into the code-review prompt. Context provided about the system (Telegram ingestion → LLM processing → knowledge base → topicization → cross-channel linking → RAG/digests/watchlists/exports/evolving summaries; prompts in `prompts/`). Requested inventory: (1) high-level architecture/directory layout; (2) end-to-end pipeline with concrete files/modules/classes/functions per stage; (3) the specific information-processing algorithms (chunking, dedup, embedding/semantic search, hybrid keyword+semantic weighting, clustering/topicization, incremental discovery, merge, re-summarization N-threshold triggers, watchlist hybrid 0.4/0.6 scoring, batching/rate-limiting, retries, caching, token budgeting/truncation) and where they live; (4) LLM interaction layer (provider abstraction openai/anthropic/gemini/ollama, YAML prompt loading, batching, retries, token/cost management); (5) storage/DB layer (models, schemas, contracts, ADRs); (6) existing relevant docs; (7) ranked reviewer focus list. Read-only, return Markdown with concrete paths.

---

## Turn 3 — Assistant (status update)

The assistant reported (in Russian) that it launched two parallel tasks:

- [Исследование гайдов Anthropic по промптам для Fable 5](26db899d-6da3-40c3-ab24-6ad2b530051b) — collecting current Anthropic prompt-engineering recommendations applicable to Fable 5.
- [Разбор алгоритмов обработки в tg_parser](9f13aa00-eb67-4a24-9d79-6a1395c49960) — mapping the Telegram-channel information-processing pipeline so the prompt is concrete and targeted.

It stated that once both returned, it would synthesize the final Fable 5 prompt (read-only code review, output as a `.md` report) and save it to a file, continuing after the background tasks finished.

*(Main transcript ends here with `turn_ended: success`.)*

---

## Subagent A — Anthropic/Fable 5 prompting research

**Task timestamp:** Tuesday, Jul 7, 2026, 1:01 PM (UTC+3)

### Subagent A — reasoning & tool activity (summary)

1. Set current step to "Researching Anthropic prompt-engineering docs" and ran three web searches in parallel:
   - `WebSearch`: `Anthropic Claude "Fable 5" model prompt engineering` — check whether a Fable 5 model exists publicly and any specific guidance.
   - `WebSearch`: `Anthropic prompt engineering best practices docs.claude.com 2026` — find latest official docs.
   - `WebSearch`: `Claude extended thinking prompt engineering tool use best practices Anthropic` — find guidance on extended thinking and agentic tool use.
2. Found rich results, including Fable-5-specific documentation. Then it read a saved search-result tool file and fetched the Fable 5 prompting page directly:
   - `Read`: local agent-tools result file (`8c8bf82a-...txt`).
   - `WebFetch`: `https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5`.
3. Judged it had comprehensive material and moved to writing the synthesis (step "Writing research synthesis").

### Subagent A — FINAL OUTPUT (in full)

# Anthropic Prompt-Engineering Research — for a Read-Only Python Code-Review Prompt (Fable 5)

## TL;DR

"Fable 5" is real: **Claude Fable 5** (`claude-fable-5`) is Anthropic's newest, most capable generally-available model (a "Mythos-class" model; `claude-mythos-5` is the restricted sibling sharing the same weights). It has **its own dedicated prompting page** on Anthropic's docs. The single biggest shift for your use case: **give the model a goal, the "why", and hard constraints — not a long prescriptive step-by-step script.** Over-engineered, Opus-era prompts can *degrade* Fable 5's output. For a read-only code review, that means a tight role, explicit read-only boundaries, XML structure, quote-first grounding, and an anti-hallucination clause — while deliberately *avoiding* "show your reasoning / think step by step" instructions, which can trigger a refusal classifier on Fable 5.

---

## 1. Fable-5-Specific / Latest-Model Guidance

**Model identity & release.** Claude Fable 5 and Claude Mythos 5 were launched together. Fable 5 is "a Mythos-class model made safe for general use" and is "available everywhere today"; Mythos 5 is limited to approved orgs via "Project Glasswing." They share the same underlying model; `claude-fable-5` is GA with additional safety measures. It is described as state-of-the-art on nearly all capability benchmarks, especially software engineering, with the lead growing "the longer and more complex the task."

**Behavioral differences that matter for a code-review prompt:**

- **De-prescribe.** "Skills developed for prior models are often too prescriptive for Claude Fable 5 and can degrade output quality." Fable 5 plans better than hand-written step lists. Replace 20-step procedures with *goal + reason + constraints*.
- **Effort is the main dial, not prompt incantations.** Effort is an API parameter (`output_config.effort`) with levels `low | medium | high | xhigh` (default `high`). Use `high` as default, `xhigh` for the hardest agentic/coding runs, `medium`/`low` for routine work. "Think harder" style prompt tricks are replaced by this dial. (This is set at the API/harness level, not inside the prompt text.)
- **Strong instruction following.** A *brief* instruction now steers behavior as well as an exhaustive list. E.g., one brevity sentence replaces enumerating every verbosity anti-pattern.
- **Longer turns by default.** Hard tasks can run many minutes; autonomous runs can go hours. Adjust timeouts/streaming if you run this via API.
- **Adaptive thinking is always on.** On Fable 5, thinking is always on and *adaptive* is the only mode — you cannot set `budget_tokens` (returns 400). Thinking depth is governed by `effort` + query complexity.
- **`refusal` stop reason.** Fable 5 runs safety classifiers (offensive cyber, bio/life-sciences, and *extraction of its summarized thinking*). Requests can return `stop_reason: "refusal"`. Configure fallback to Claude Opus 4.8. Benign security/bio work can occasionally trip these — relevant if the Python project touches security tooling.
- **No prefilling.** Prefilled assistant turns are unsupported (400 error) on 4.6+ and Fable 5.
- **Code review is a named strength.** Anthropic explicitly notes "Code review and debugging. Bug-finding recall … is noticeably higher than Claude Opus 4.8, including search across codebases and repository history." Good news for your use case.

Sources: [Introducing Fable 5 / Mythos 5](https://www.anthropic.com/news/claude-fable-5-mythos-5), [Prompting Claude Fable 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5), [Prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices), [Rewriting prompts for Fable 5 (Developers Digest)](https://www.developersdigest.tech/blog/rewriting-prompts-and-skills-for-fable-5), [fable5-prompting (GitHub)](https://github.com/byhartvig/fable5-prompting).

---

## 2. Core Anthropic Prompt-Engineering Techniques

### Role / system prompt
Set a role in the **system prompt** to focus behavior and tone — "even a single sentence makes a difference." For your case: something like *"You are a senior Python engineer performing a rigorous, read-only code review."*

### Be clear, direct, and explicit
"Think of Claude as a brilliant but new employee who lacks context on your norms." Golden rule: *if a colleague with minimal context would be confused by your prompt, so will Claude.* Be specific about desired output and constraints; if you want "above and beyond," ask for it explicitly. Use numbered/bulleted steps **only when order or completeness genuinely matters** (don't over-script for Fable 5).

### XML tags to structure prompts (strongly recommended)
XML tags "help Claude parse complex prompts unambiguously, especially when your prompt mixes instructions, context, examples, and variable inputs." Best practices: consistent, descriptive tag names; nest tags for natural hierarchy (e.g., `<documents>` → `<document>` → `<document_content>`). Anthropic's context-engineering guidance adds that you can use XML tags *or* Markdown headers to delineate sections, and that exact formatting matters less as models get more capable — but structure still helps.

### Provide context and motivation ("why")
"Providing context or motivation behind your instructions … can help Claude better understand your goals." This is *amplified* on Fable 5: "Claude Fable 5 measurably uses intent to make micro-decisions you didn't specify." Recommended template:
> *"I'm working on [larger task] for [who]. They need [what the output enables]. With that in mind: [request]."*

### Multishot / examples
Examples are "one of the most reliable ways to steer Claude's output format, tone, and structure." Make them **relevant, diverse, and structured** (wrap in `<example>` tags). Aim for **3–5 examples**. Context-engineering guidance: curate *diverse canonical examples* rather than stuffing a laundry list of edge cases. For a code review, a short example of the exact finding format (severity, location, explanation, suggested fix) is high-leverage.

### Chain-of-thought / thinking scaffolding
- On **adaptive-thinking models (incl. Fable 5)**, thinking is handled internally; "prefer general instructions over prescriptive steps" — "think thoroughly" often beats a hand-written plan. You can still guide reflection *after tool use*: *"After receiving tool results, carefully reflect on their quality and determine optimal next steps."*
- **Multishot works with thinking** — showing a reasoning pattern in examples generalizes to its thinking blocks.
- **Manual CoT is only a fallback** for when thinking is off (older models). Use `<thinking>`/`<answer>` tags to separate reasoning from output.
- **Critical Fable-5 caveat:** Do **not** ask the model to "show its reasoning," "explain its internal reasoning in the response," or transcribe its thinking — this can fire the `reasoning_extraction` refusal classifier and cause elevated fallbacks. If you need reasoning visibility, read the structured summarized `thinking` blocks via the API (`thinking.display: "summarized"`) instead of asking for it in-response. (Note: when thinking is *disabled* on some older Opus models, the word "think" is sensitive — use "consider/evaluate/reason through". Not applicable to Fable 5 where thinking is always on, but worth knowing.)
- **Self-check** is endorsed: *"Before you finish, verify your answer against [criteria]."*

### Prefilling / controlling output format
Prefilling is **deprecated/unsupported** on Fable 5 (400 error). Migrate to: direct instructions ("Respond directly without preamble; do not start with 'Here is…'"), **XML output tags**, **Structured Outputs**, or **tool calling** to enforce shape. Effective formatting levers:
1. Say what **to do**, not what not to do ("Write in flowing prose paragraphs" > "Don't use markdown").
2. Use **XML format indicators** ("Write the report body inside `<report>` tags").
3. **Match prompt style to desired output** (a Markdown-styled prompt yields more Markdown; a prose-styled prompt yields more prose).
4. Give **detailed formatting rules** when you have specific preferences.

### Long-context / long-document handling
For 20k+ token inputs:
- **Put long data at the top**, above your query/instructions/examples — "queries at the end can improve response quality by up to ~30%," especially with multi-document inputs.
- **Wrap each document** in `<document>` with `<source>` and `<document_content>` subtags.
- **Quote-first grounding:** ask the model to *first* extract relevant quotes (into `<quotes>` tags) before analysis — "This helps Claude cut through the noise." This is directly useful for grounding a code review in actual source lines.

### Handling large codebases / many files
- Fable 5 is strong at **search across codebases and repository history** and demonstrated a codebase-wide migration on a 50M-line repo.
- If running agentically: **parallel tool calls** (read several files at once), **subagents** for independent workstreams (Fable 5 dispatches them readily — give explicit guidance on *when* delegation is warranted to avoid overuse), and **fresh-context verifier subagents** tend to outperform self-critique.
- For multi-context-window jobs: use **git and structured state files** (e.g., `progress.txt`, findings JSON) to track state across sessions.

### Output formatting control (clean Markdown)
You *want* Markdown here, so this is easy — but note current models can *over-*format. To keep clean, readable Markdown: specify the exact section structure (via headings and/or XML output tags), and if you find excessive bullets/bold, add explicit guidance (Anthropic provides an `<avoid_excessive_markdown_and_bullet_points>` snippet). For a review report, define the report skeleton explicitly (e.g., Summary → Findings-by-severity → File-by-file notes → Recommendations).

### Reducing hallucination / staying grounded
Anthropic's recommended anti-hallucination snippet (ideal for code review):
> `<investigate_before_answering>` *Never speculate about code you have not opened. If the user references a specific file, you MUST read the file before answering. Investigate and read relevant files BEFORE answering… Never make claims about code before investigating unless you are certain — give grounded, hallucination-free answers.* `</investigate_before_answering>`

Combine with **quote-first grounding** (cite file + line for each finding) and **audit-progress-against-tool-results** (below).

---

## 3. Agentic / Extended-Thinking Guidance: Tool Use & Staying Read-Only

- **Be explicit about action vs. suggestion.** Latest models follow instructions literally: "If you say 'can you suggest some changes,' Claude will sometimes provide suggestions rather than implementing them." For your read-only review this literalness works *in your favor* — but you must state it clearly.
- **Read-only boundary snippet (adapt from Anthropic's `<do_not_act_before_instructions>`):**
> *Do not modify, create, or delete any files. Do not run commands that change system state. When the user is asking a question or describing a problem rather than requesting a change, the deliverable is your assessment: report findings and stop. Default to research, reading, and recommendations only.*
  Anthropic's Fable-5 page reinforces this: *"When the user is describing a problem … the deliverable is your assessment. Report your findings and stop. Don't apply a fix until they ask for one."*
- **Ground progress claims (Fable 5):** *"Before reporting progress/findings, audit each claim against a tool result from this session. Only report work you can point to evidence for."* This "nearly eliminated fabricated status reports" in Anthropic's testing — directly applicable to eliminating hallucinated findings.
- **Extended thinking + tool use mechanics** (if building via API): tool use with thinking supports only `tool_choice: auto` or `none` (not `any`/forced); **preserve all `thinking`/`redacted_thinking` blocks and signatures** unchanged when passing tool results back; don't toggle thinking mid-turn.
- **Balancing autonomy & safety:** Anthropic provides a snippet telling the model to confirm before destructive/hard-to-reverse/shared-system actions and to *never* use destructive shortcuts (e.g., `--no-verify`). For a strictly read-only review you can go further and forbid *all* mutating actions.
- **Reduce file creation:** Latest models sometimes create scratch files. Instruct cleanup, or (for read-only) forbid file creation outright.

Sources: [Prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices), [Prompting Claude Fable 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5), [Extended thinking](https://platform.claude.com/docs/en/build-with-claude/extended-thinking), [Extended thinking with tool use (Cookbook)](https://platform.claude.com/cookbook/extended-thinking-extended-thinking-with-tool-use), [Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), [The "think" tool](https://www.anthropic.com/engineering/claude-think-tool).

---

## 4. Concrete Do's and Don'ts to Bake Into a Code-Review Prompt

**Do**
- **Set a clear role** in the system prompt ("senior Python reviewer, read-only").
- **State the goal + the "why"** (who the review is for, what it enables) — Fable 5 uses intent to make judgment calls.
- **Use XML tags** to separate `<role>`, `<task>`, `<constraints>`, `<code>`/`<documents>`, `<output_format>`, `<example>`.
- **Place the code/files near the top**, with the review instructions and output spec after them.
- **Require quote-first grounding**: cite `file:line` (or a quoted snippet) for every finding before commenting.
- **Add the anti-hallucination clause** ("never speculate about code you haven't opened").
- **Add the audit-against-evidence clause** for grounded findings.
- **Explicitly forbid modifications** (no edits, no new files, no state-changing commands; deliverable = assessment only).
- **Define the exact Markdown report structure** you want (e.g., Executive summary → Findings grouped by severity with location/impact/recommended fix → per-file notes → prioritized recommendations).
- **Give 1–3 examples** of a properly-formatted finding.
- **Ask for a final self-check** ("verify each finding points to real code before finalizing").
- **Keep instructions concise** — trust Fable 5's strong instruction following.

**Don't**
- **Don't ask it to "show/explain its reasoning" or "think step by step" in the response** — risks the `reasoning_extraction` refusal on Fable 5. (Let adaptive thinking handle reasoning internally.)
- **Don't over-script** with long rigid step-by-step procedures — this can degrade Fable 5 output. Give the goal and constraints instead.
- **Don't rely on prefilling** to force format — unsupported (use XML tags / structured outputs / direct instructions).
- **Don't set `budget_tokens`** or "think harder" incantations — use the `effort` parameter (`high` default; `xhigh` for the most rigorous review).
- **Don't use aggressive "CRITICAL: you MUST…" language** — modern models may over-trigger; normal phrasing suffices.
- **Don't phrase as "can you suggest…"** if you want a specific behavior — be literal about what you want (here: a full report, no code changes).
- **Don't pile on redundant edge-case rules** — prefer a few canonical examples over exhaustive lists.
- **Don't surface a token/context countdown** to the model in long runs (can make Fable 5 wrap up early); reassure it has ample context if needed.

---

## Sources (URLs)

- Introducing Claude Fable 5 and Claude Mythos 5 — https://www.anthropic.com/news/claude-fable-5-mythos-5
- Prompting Claude Fable 5 (official) — https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5
- Prompting best practices (official, latest models) — https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
- Extended thinking (official) — https://platform.claude.com/docs/en/build-with-claude/extended-thinking
- Extended thinking with tool use (Cookbook) — https://platform.claude.com/cookbook/extended-thinking-extended-thinking-with-tool-use
- Effective context engineering for AI agents (Anthropic Engineering) — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- The "think" tool (Anthropic Engineering) — https://www.anthropic.com/engineering/claude-think-tool
- Rewriting Your Prompts and Skills for Fable 5 (Developers Digest) — https://www.developersdigest.tech/blog/rewriting-prompts-and-skills-for-fable-5
- Claude Fable 5 Part 1 (Ken Huang, Substack) — https://kenhuangus.substack.com/p/claude-fable-5-what-changed-and-how
- fable5-prompting (community distillation of Anthropic's playbook, GitHub) — https://github.com/byhartvig/fable5-prompting

No files were read from or written to your project — this was web research only.

---

## Subagent B — tg_parser processing-algorithms map

**Task timestamp:** Tuesday, Jul 7, 2026, 1:02 PM (UTC+3)

### Subagent B — reasoning & tool activity (summary)

The explorer subagent worked through the repository in several batched passes (its detailed thinking was redacted in the transcript). The tool activity was:

- **Architecture discovery:** `Glob` for `*`, `**/*.py`, `docs/**/*`, `prompts/**/*`; `Shell` `ls -la` of the repo root and `find` of `tg_parser` subdirectories; `Grep` for orchestrator/pipeline/`process_message` symbols; `Glob` of `tg_parser/**/*.py`, `docs/adr/*.md`, `docs/contracts/*.json`.
- **Pipeline tracing:** `Read` of `README.md`, `docs/DATA_ARCHITECTURE.md`, `docs/notes/processing-implementation.md`, `tests/README.md`, `prompts/README.md`; `Grep` across the package for `chunk|dedup|embedding|hybrid|watchlist|resummar|incremental|merge|truncat|token|rate_limit|retry`.
- **Symbol enumeration:** `Grep` for `class`/`def`/`async def` in `pipeline.py`, `topicization*.py`, key `services/*.py` (retrieval, near-duplicate, resummarization, topic linking, watchlist, processing, scheduler, pipeline, `_ranking`, watchlist tokenizer), `processing/llm/*.py`, and `prompt_loader.py`.
- **Deep reads:** `topicization.py` (multiple offset windows), `watchlist_service.py`, `retrieval_service.py`, `near_duplicate_service.py`, `resummarization_service.py`, `topic_linking_service.py`, `embedding_service.py`, `processing/llm/factory.py`, `processing/llm/rate_limiter.py`, `processing/llm/response_cache.py`, `domain/hashing.py`, `services/_ranking.py`, `ingestion/orchestrator.py`, `scheduler_service.py`, `pipeline_service.py`, `processing_service.py`, `processing/pipeline.py`, `storage/sqlalchemy/embedding_repo.py`, `processing/prompt_loader.py`, `processing/ports.py`.
- **Config & docs:** `Grep` of `config/settings.py` for algorithm knobs and `LLMConfigManager`; `Read` of `docs/pipeline.md`, `docs/SERVER_ARCHITECTURE.md`, several ADRs (0003, 0006, 0010, 0016), `docs/quality/AGENT_PLAYBOOK.md`.

It concluded with step "Compiling structured inventory" and produced the following full inventory.

### Subagent B — FINAL OUTPUT (in full)

# TG_parser — Information Processing Algorithms: Code Review Inventory

Structured inventory for a detailed code review focused on **algorithms that process information extracted from Telegram channels**. All paths are absolute under `/Users/alexanderefimov/TG_parser`.

---

## 1. High-level architecture / directory layout

### Top-level directories

| Path | Purpose |
|------|---------|
| `/Users/alexanderefimov/TG_parser/tg_parser/` | Main Python package — ingestion, processing, services, storage, API, bot, MCP |
| `/Users/alexanderefimov/TG_parser/prompts/` | Runtime YAML prompts (`processing`, `topicization`, `rag`, `merge`, `incremental_discover`, `resummarize`, `digest`, `bot`) |
| `/Users/alexanderefimov/TG_parser/migrations/` | Alembic migrations (3 logical DB branches: `ingestion/`, `raw/`, `processing/`) |
| `/Users/alexanderefimov/TG_parser/tests/` | ~2800+ pytest tests; algorithm coverage in `test_processing_pipeline.py`, `test_f5a_hybrid_search.py`, `test_watchlist_score.py`, `test_topicization.py`, etc. |
| `/Users/alexanderefimov/TG_parser/docs/` | ADRs, contracts, pipeline docs, quality lifecycle, runbooks |
| `/Users/alexanderefimov/TG_parser/docker/` | Compose stack, Grafana/Prometheus |
| `/Users/alexanderefimov/TG_parser/scripts/` | Migration/backfill utilities |
| `/Users/alexanderefimov/TG_parser/benchmarks/` | Baseline benchmarks |

### `tg_parser/` package layout (processing-relevant)

| Subdir | Role |
|--------|------|
| `ingestion/` | Telethon fetch, orchestrator, raw persistence |
| `processing/` | LLM pipeline, topicization engine, prompt loading, LLM clients |
| `services/` | Orchestration: scheduler, processing/topicization/retrieval/embedding/watchlist/resummarize |
| `storage/sqlalchemy/` | Postgres repos (raw, processed, embeddings, topics, failures) |
| `domain/` | Pydantic models, content hashing, contract validation |
| `config/` | Settings, retry config, `LLMConfigManager` |
| `agents/` | Optional multi-agent processing path (orchestrator + specialized agents) |
| `export/` | KB export mapping (not core algorithms, but output of processing) |
| `api/`, `bot/`, `cli/`, `mcp_server.py` | Surfaces that trigger/read processing |

**Architectural pattern:** Hexagonal (ADR-0004) — ports in `tg_parser/processing/ports.py`, adapters in `processing/` + `storage/sqlalchemy/`, orchestration in `services/`.

**Living-KB principles (ADR-0006):** persistent entities, provenance, cheap retrieval cycles (keyword+embedding without per-doc LLM on hot path), incremental living loop.

---

## 2. End-to-end pipeline: raw message → KB → topics → links → summaries

### Flow diagram (scheduler incremental tick)

```
Telegram API
  → IngestionOrchestrator.ingest_source()
  → raw_messages (Postgres)
  → run_processing() → ProcessingPipelineImpl.process_message()
  → processed_documents (+ content_hash dedup)
  → run_incremental_embedding()
  → run_incremental_topicization() [Phase 1 keyword + Phase 2 LLM discover]
  → run_topic_embedding()
  → run_near_duplicate_check_for_channel() [observe-only]
  → run_resummarize_for_channel() [N-threshold + age trigger]
  → run_watchlist_check_for_channel() [hybrid 0.4/0.6]
  → run_full_topicization_resume_for_channel() [BUG-076 chunked full run]
  → run_reconciliation_for_channel() [BUG-075 coverage gap fill]
```

Manual/one-shot path: `run_full_pipeline()` = ingest → process → topicize → export.

---

### Stage I — Raw ingestion

| Component | Path | Key symbols | Description |
|-----------|------|-------------|-------------|
| Orchestrator | `/Users/alexanderefimov/TG_parser/tg_parser/ingestion/orchestrator.py` | `IngestionOrchestrator`, `ingest_source()`, `_ingest_posts()`, `_ingest_comments()` | Snapshot/incremental modes; retryable vs non-retryable errors; rate-limit deferral via `source.rate_limit_until` |
| Telethon client | `/Users/alexanderefimov/TG_parser/tg_parser/ingestion/telegram/telethon_client.py` | `TelethonClient` | MTProto fetch; session lock contention |
| Ingestion service | `/Users/alexanderefimov/TG_parser/tg_parser/services/ingestion_service.py` | `run_ingestion()` | CLI/scheduler wrapper around orchestrator |
| Raw repo | `/Users/alexanderefimov/TG_parser/tg_parser/storage/sqlalchemy/raw_message_repo.py` | `SQLAlchemyRawMessageRepo` | Idempotent insert by `source_ref` |
| State repo | `/Users/alexanderefimov/TG_parser/tg_parser/storage/sqlalchemy/ingestion_state_repo.py` | cursors, `record_attempt()` | High-watermarks, fail_count, poll intervals |

---

### Stage II — LLM processing (raw → ProcessedDocument)

| Component | Path | Key symbols | Description |
|-----------|------|-------------|-------------|
| Pipeline impl | `/Users/alexanderefimov/TG_parser/tg_parser/processing/pipeline.py` | `ProcessingPipelineImpl`, `process_message()`, `process_batch()`, `_process_single_message()`, `create_processing_pipeline()` | 1 raw → 1 processed; idempotency; parallel batch; JSON repair; dedup gate |
| Processing service | `/Users/alexanderefimov/TG_parser/tg_parser/services/processing_service.py` | `run_processing()`, `_run_processing_locked()`, `channel_pipeline_lock()` | Loads bounded unprocessed window; advisory lock 0x9C40; wires pipeline + repos |
| Processed repo | `/Users/alexanderefimov/TG_parser/tg_parser/storage/sqlalchemy/processed_document_repo.py` | `upsert()`, `find_by_content_hash()`, FTS `search_vector` | Persists `text_clean`, `summary`, `topics`, `content_hash` |
| Failure repo | `/Users/alexanderefimov/TG_parser/tg_parser/storage/sqlalchemy/processing_failure_repo.py` | cooldown / attempts | BUG-067 category-specific retry budgets |
| Built-in prompts | `/Users/alexanderefimov/TG_parser/tg_parser/processing/prompts.py` | `PROCESSING_SYSTEM_PROMPT`, `build_processing_prompt()` | Fallback if YAML missing |
| YAML prompts | `/Users/alexanderefimov/TG_parser/prompts/processing.yaml` | system/user/model sections | Primary processing extraction prompt |
| Agent path (alt) | `/Users/alexanderefimov/TG_parser/tg_parser/agents/processing_agent.py`, `agents/tools/pipeline_tool.py` | `process_message_with_agent()`, `process_with_pipeline()` | Optional agent-driven processing |

**Output model:** `ProcessedDocument` in `/Users/alexanderefimov/TG_parser/tg_parser/domain/models.py` — includes `content_hash` for exact dedup.

---

### Stage IIa — Embeddings (processed → vector index)

| Component | Path | Key symbols | Description |
|-----------|------|-------------|-------------|
| Embedding service | `/Users/alexanderefimov/TG_parser/tg_parser/services/embedding_service.py` | `run_embedding()`, `run_incremental_embedding()`, `run_topic_embedding()`, `_prepare_text()` | Batches OpenAI embeddings; text = summary + first 500 chars of `text_clean` |
| Embedding repo | `/Users/alexanderefimov/TG_parser/tg_parser/storage/sqlalchemy/embedding_repo.py` | `similarity_search()`, `keyword_search()`, `save_batch()` | pgvector cosine (`<=>`); FTS union over `processed_documents` + `topic_cards` |
| Settings | `/Users/alexanderefimov/TG_parser/tg_parser/config/settings.py` | `embedding_model`, `embedding_batch_size`, `embedding_dimension` | Default `text-embedding-3-small`, dim 1536 |

---

### Stage IIb — Topicization (ProcessedDocument → TopicCard + TopicBundle)

| Component | Path | Key symbols | Description |
|-----------|------|-------------|-------------|
| Topicization engine | `/Users/alexanderefimov/TG_parser/tg_parser/processing/topicization.py` | `TopicizationPipelineImpl`, `topicize_channel()`, `_topicize_channel_chunked()`, `_merge_topics()`, `assign_documents_to_topics()`, `discover_new_topics()` | Full LLM clustering, chunked resume, merge, incremental assign/discover |
| Checkpoint | `/Users/alexanderefimov/TG_parser/tg_parser/processing/topicization_checkpoint.py` | `FullRunCheckpoint`, `parse_checkpoint()`, `noprogress_circuit_open()` | BUG-076 resumable full runs; chunk pinning |
| Topicization service | `/Users/alexanderefimov/TG_parser/tg_parser/services/topicization_service.py` | `run_topicization()`, `run_incremental_topicization()`, `run_reconciliation_for_channel()`, `run_full_topicization_resume_for_channel()`, `_finalize_full_run()` | Locks 0x70C1/0x70C2; cross-chunk programmatic merge; auto-linking |
| Topic prompts | `/Users/alexanderefimov/TG_parser/tg_parser/processing/topicization_prompts.py` | `build_topicization_prompt()`, `build_incremental_discover_prompt()` | Built-in prompt builders |
| YAML | `/Users/alexanderefimov/TG_parser/prompts/topicization.yaml`, `incremental_discover.yaml`, `merge.yaml`, `supporting_items.yaml` | LLM stage configs | Topicization, discover, merge dedup groups |
| Topic repos | `/Users/alexanderefimov/TG_parser/tg_parser/storage/sqlalchemy/topic_card_repo.py`, `topic_bundle_repo.py` | upsert, `list_resummarize_candidates()` | Topic persistence + F5-C candidate selection |
| CLI | `/Users/alexanderefimov/TG_parser/tg_parser/cli/topicize_cmd.py`, `topic_cmd.py` | manual topicize | Operator entry points |

**Incremental algorithm (3 phases):**
1. **Phase 1** — `assign_documents_to_topics()`: programmatic keyword overlap (0 LLM tokens).
2. **Phase 2** — `discover_new_topics()`: LLM assigns/creates topics for unassigned docs (`incremental_discover.yaml`).
3. **Phase 3** — `_run_cross_channel_linking()`: auto `TopicLink` creation for touched topics.

**Full run (BUG-076):** `_topicize_channel_chunked()` → per-chunk generate+merge → atomic commit → `_finalize_full_run()` cross-chunk Jaccard+cosine consolidation.

---

### Stage IIc — Cross-channel topic linking

| Component | Path | Key symbols | Description |
|-----------|------|-------------|-------------|
| Linking service | `/Users/alexanderefimov/TG_parser/tg_parser/services/topic_linking_service.py` | `link_topics()`, `_jaccard_similarity()`, `_cosine_similarity()` | All-pairs across channels; weights 0.4 Jaccard + 0.6 cosine; threshold 0.3 |
| Link repo | `/Users/alexanderefimov/TG_parser/tg_parser/storage/sqlalchemy/topic_link_repo.py` | `upsert_batch()`, `delete_all()` | Full rebuild on each `link_topics()` run |
| Analytics keywords | `/Users/alexanderefimov/TG_parser/tg_parser/services/analytics_service.py` | `_extract_keywords()` | Keyword sets from tags + scope_in |

---

### Stage IId — Evolving topic summaries (F5-C)

| Component | Path | Key symbols | Description |
|-----------|------|-------------|-------------|
| Resummarize service | `/Users/alexanderefimov/TG_parser/tg_parser/services/resummarization_service.py` | `ResummarizationService.run_for_channel()`, `_classify_trigger()` | N-threshold (`resummarize_trigger_n`), age trigger (`resummarize_max_age_days`); caps per tick |
| Version repo | `/Users/alexanderefimov/TG_parser/tg_parser/storage/sqlalchemy/topic_card_version_repo.py` | audit trail | Previous summary snapshot before commit |
| YAML | `/Users/alexanderefimov/TG_parser/prompts/resummarize.yaml` | resummarize LLM prompt | Input window: top-N bundle items (anchor-first sort) |
| Scheduler hook | `/Users/alexanderefimov/TG_parser/tg_parser/services/scheduler_service.py` | `run_resummarize_for_channel()` | Runs every tick (not gated on new docs) |

---

### Stage III — Retrieval / RAG (KB query path)

| Component | Path | Key symbols | Description |
|-----------|------|-------------|-------------|
| Retrieval service | `/Users/alexanderefimov/TG_parser/tg_parser/services/retrieval_service.py` | `search()`, `answer()`, `_apply_type_quotas()`, `_build_context()` | Hybrid semantic+keyword via RRF; RAG answer with token-budgeted context |
| Ranking | `/Users/alexanderefimov/TG_parser/tg_parser/services/_ranking.py` | `rrf_fuse()` | Reciprocal Rank Fusion (k=`hybrid_rrf_k`, default 60) |
| API | `/Users/alexanderefimov/TG_parser/tg_parser/api/routes/rag.py` | HTTP search/ask | Surface for hybrid search |
| YAML | `/Users/alexanderefimov/TG_parser/prompts/rag.yaml` | RAG system/user prompts | Q&A generation |

---

### Post-processing hooks (same scheduler tick)

| Hook | Path | Trigger |
|------|------|---------|
| Near-duplicate observe | `/Users/alexanderefimov/TG_parser/tg_parser/services/near_duplicate_service.py` | After embedding new docs |
| Watchlist | `/Users/alexanderefimov/TG_parser/tg_parser/services/watchlist_service.py` | Every tick; scores new docs vs interests |
| Digest (F6) | `/Users/alexanderefimov/TG_parser/tg_parser/services/digest_service.py` | Separate cron; LLM summarization over channel window |

---

### Orchestration entry points

| Path | Symbol | Role |
|------|--------|------|
| `/Users/alexanderefimov/TG_parser/tg_parser/services/pipeline_service.py` | `run_full_pipeline()` | ingest → process → topicize → export |
| `/Users/alexanderefimov/TG_parser/tg_parser/services/scheduler_service.py` | `run_incremental_for_all_sources()`, `_process_source()`, `incremental_pipeline_task()` | Background incremental loop |
| `/Users/alexanderefimov/TG_parser/tg_parser/services/pipeline_dispatch_service.py` | `trigger_pipeline_job()` | MCP/API async jobs |
| `/Users/alexanderefimov/TG_parser/tg_parser/services/background_scheduler.py` | APScheduler setup | Periodic tasks |

---

## 3. Information processing algorithms — locations

### Chunking / batching

| Algorithm | Location | Details |
|-----------|----------|---------|
| Processing tick batch | `processing_service._run_processing_locked()` + `settings.processing_tick_batch_size` | Bounded unprocessed window per scheduler tick (BUG-069) |
| Processing parallel batch | `pipeline.py` → `process_batch()`, `_process_batch_parallel()` | Semaphore concurrency; `settings.processing_concurrency` |
| Topicization LLM batches | `topicization.py` → `topicize_channel()`, `_generate_topics_batch()` | Default `batch_size=50`, `batch_concurrency=5` |
| Full-run chunks | `topicization.py` → `_topicize_channel_chunked()` | Chunks of `topicization_full_chunk_batches` × 50 docs; pinned plan in checkpoint |
| Incremental discover batches | `topicization.py` → `discover_new_topics()` | Sequential batches; accumulates new topics into context |
| Embedding batches | `embedding_service.py` | `settings.embedding_batch_size` |
| Resummarize caps | `resummarization_service.py` | `max_topics`, `max_duration_s`, `max_tokens_per_tick` per tick |
| Near-dup cap | `near_duplicate_service.py` | `MAX_DOCS_PER_TICK = 100` |

### Deduplication

| Type | Location | Algorithm |
|------|----------|-----------|
| **Exact hash (F5-A Phase 3)** | `/Users/alexanderefimov/TG_parser/tg_parser/domain/hashing.py` — `normalize_for_hash()`, `compute_content_hash()` | SHA-256 of normalized `text_clean` (lowercase, whitespace collapse, optional URL query strip) |
| Exact dedup gate | `pipeline.py` ~474–492 | Under DB lock: `find_by_content_hash()` → return canonical doc, metric `tg_dedup_duplicates_detected_total` |
| **Near-duplicate observe (ADR-0016 Phase 0)** | `near_duplicate_service.py` | Max cosine vs sliding window: **intra** (same channel) + **cross** (sibling channels); threshold `near_dup_similarity_threshold` (0.92); observation-only |
| **Topic merge dedup** | `topicization.py` → `_merge_topics()` | LLM returns duplicate topic ID groups (`merge.yaml`); programmatic metadata assembly |
| **Cross-chunk merge** | `topicization_service.py` → `_finalize_full_run()` | Programmatic Jaccard+cosine over persisted cards; threshold `topicization_full_merge_threshold` |
| Ingestion dedup | `raw_message_repo` | `ON CONFLICT DO NOTHING` on `source_ref` |

### Embedding / semantic search

| Location | Mechanism |
|----------|-----------|
| `embedding_service._prepare_text()` | Embed: `summary + text_clean[:500]` |
| `embedding_repo.similarity_search()` | pgvector: `1 - (embedding <=> query)` ; IVFFlat probes=20 when channel-scoped |
| `retrieval_service.search(mode="semantic")` | Query embedding → similarity_search |
| Topic embeddings | `run_topic_embedding()` — text = `summary \| scope_in` |

### Hybrid search (keyword + semantic)

| Location | Mechanism |
|----------|-----------|
| `embedding_repo.keyword_search()` | FTS: `plainto_tsquery` on **simple \|\| russian \|\| english** configs; `ts_rank_cd` on `processed_documents.search_vector` ∪ `topic_cards.search_vector` |
| `retrieval_service.search(mode="hybrid")` | Parallel semantic + keyword branches → `rrf_fuse(sem, kw, k=hybrid_rrf_k)` |
| `settings.hybrid_enabled`, `hybrid_rrf_k`, `fts_min_rank` | Feature flag + RRF constant + keyword cutoff |
| `_ranking.py` | RRF: score = Σ 1/(k+rank) |

### Topicization / clustering logic

| Phase | Location | Algorithm |
|-------|----------|-----------|
| Full LLM clustering | `topicization.py` → `topicize_channel()` | LLM proposes topics+anchors from doc batches; quality gates (`MIN_SINGLETON_SCORE`, `MIN_CLUSTER_ANCHORS`, etc.) |
| Anchor determinism | `_determinize_anchors()` | Sort by score desc, `anchor_ref` asc (TR-IF-4) |
| Supporting items (programmatic) | `_find_supporting_items_programmatic()` | Keyword overlap; no LLM |
| Supporting items (LLM) | `build_topic_bundle()` + `supporting_items.yaml` | Optional LLM path for supports |
| Incremental Phase 1 | `assign_documents_to_topics()` | Weighted keyword overlap: strong tokens (topics+summary) 1.0×, weak (`text_clean` prefix) 0.3×; substring fallback for tokens ≥5 chars |
| Incremental Phase 2 | `discover_new_topics()` | LLM incremental discover with existing + cross-channel topic context |
| Re-escalation | `topicization_service._run_incremental_topicization_locked()` | 0 topic cards → full re-topicization (with cooldown marker) |
| Reconciliation (BUG-075) | `run_reconciliation_for_channel()` | Feeds uncovered docs once (`discover_attempted` marker); `reconcile_only=True` disables re-escalation |
| Full resume (BUG-076) | `run_full_topicization_resume_for_channel()` + checkpoint | Chunk-at-a-time with token budget + noprogress circuit breaker |

### Incremental discovery

| File | Symbols |
|------|---------|
| `topicization.py` | `discover_new_topics()`, `_discover_single_batch()`, `_discover_after_truncation()` |
| `topicization_prompts.py` | `build_incremental_discover_prompt()`, `INCREMENTAL_DISCOVER_SYSTEM_PROMPT` |
| `prompts/incremental_discover.yaml` | YAML override |

### Merge logic

| Merge type | Location |
|------------|----------|
| Within-batch / cross-batch (LLM) | `topicization.py` → `_merge_topics()` using `prompts/merge.yaml` |
| Cross-chunk (programmatic) | `topicization_service.py` → `_finalize_full_run()` — Jaccard 0.4 + cosine 0.6 |
| Export merge rules | `/Users/alexanderefimov/TG_parser/tg_parser/export/topics_export.py` |

### Re-summarization triggers (N-threshold)

| Location | Logic |
|----------|-------|
| `settings.resummarize_trigger_n` | Counter trigger: `new_items_since_last_summary >= N` |
| `settings.resummarize_max_age_days` | Age trigger: stale summary + ≥1 new item |
| `topic_card_repo.list_resummarize_candidates()` | DB query for candidates |
| `resummarization_service._classify_trigger()` | Observability: `"counter"` vs `"age"` |
| `TopicCard.new_items_since_last_summary` | Incremented on bundle updates; reset on successful resummarize |

### Watchlist hybrid scoring (0.4 / 0.6)

| Location | Logic |
|----------|-------|
| `watchlist_service.py` | `KEYWORD_WEIGHT=0.4`, `SEMANTIC_WEIGHT=0.6`; `compute_watch_score()` |
| Keyword component | `_aggregate_keyword_score()` — ADR-0010 **top-k** default (K=3) or **mean** rollback via `watchlist_keyword_aggregation` |
| Tokenization | `watchlist_tokenizer.py` — lemmatization (RU/EN), `normalize_token()` |
| Exclude filter | Any `exclude_keywords` token match → `combined=0` |
| Semantic fallback | No interest or doc embedding → keyword-only (`combined=keyword`) |
| Threshold | Per-interest `threshold`; calibration helpers in `suggest_threshold_from_scores()` |
| Settings override | `watchlist_keyword_weight`, `watchlist_semantic_weight` |

### Cross-channel topic linking scoring

| Location | Weights |
|----------|---------|
| `topic_linking_service.py` | Jaccard 0.4 + cosine 0.6; threshold 0.3 |
| `topicization_service._run_cross_channel_linking()` | Same weights for incremental auto-links |

### Batching / rate-limiting for LLM calls

| Mechanism | Location |
|-----------|----------|
| Anthropic token-bucket | `processing/llm/rate_limiter.py` → `LLMRateLimiter` (RPM/ITPM/OTPM; sync from response headers) |
| Factory wiring | `processing/llm/factory.py` → shared limiter per API key for Anthropic |
| Concurrency cap | `LLMRateLimiter.suggested_parallel_cap()` via `suggest_processing_concurrency` on Anthropic client |
| OpenAI/Gemini/Ollama retries | `openai_client.py`, `anthropic_client.py`, `gemini_client.py`, `ollama_client.py` — exponential backoff on 429/5xx |
| HTTP timeouts | `settings.anthropic_http_timeout_s`, `anthropic_call_timeout_s`, streaming options |
| Orchestrator rate limit | `/Users/alexanderefimov/TG_parser/tg_parser/agents/orchestrator.py` (agent batch orchestration) |

### Retry logic

| Layer | Location | Policy |
|-------|----------|--------|
| Per-message processing | `pipeline.py` → `process_message()` | `retry_settings`: max_attempts, backoff 1/2/4s + jitter; records `processing_failures` |
| Failure cooldown | `processing_service._run_processing_locked()` | Skip docs in cooldown unless `retry_failed` / `bypass_failure_cooldown` |
| JSON parse retry | `pipeline.py` → `apply_json_retry_hint()`, `repair_json()`; topicization mirrors in `_loads_topicization_json_with_repair()` | Inner JSON retry loop separate from HTTP retry |
| Ingestion | `ingestion/orchestrator.py` | `ingestion_max_attempts_per_run`; RetryableError vs NonRetryableError |
| LLM HTTP | Client `_request_with_retry()` / Anthropic `_compute_retry_delay()` | Up to 5 retries; respects `Retry-After` |

### Caching

| Cache | Location |
|-------|----------|
| LLM response cache (F8-A) | `processing/llm/response_cache.py` → `LLMResponseCache` (TTL 5min, 500 entries; key = hash of prompt+system+temp+max_tokens) |
| Prompt YAML cache | `prompt_loader.py` → `PromptLoader._cache` |
| Watchlist interest embedding | `WatchInterest.embedding` field — lazy cache in DB |
| Anthropic prompt caching | `anthropic_client.py` + `settings.anthropic_prompt_caching_enabled` |

### Token budgeting / truncation

| Location | Mechanism |
|----------|-----------|
| `topicization.py` | `_scaled_max_tokens()` cap 32768; shrink/split ladder on `stop_reason=="max_tokens"`; `TopicizationBatchTruncatedError` |
| `topicization.py` | `_TOPICIZATION_MAX_JSON_RETRIES = 2` |
| `settings.topicization_full_run_token_budget` | Per-invocation cap for chunked full runs |
| `resummarization_service.py` | `resummarize_max_tokens_per_tick`; input window `resummarize_input_window_n` |
| `retrieval_service._build_context()` | Char limit for RAG context assembly |
| `embedding_service._prepare_text()` | Truncates `text_clean` to 500 chars for embedding |
| `settings.topicization_text_clean_match_chars` | Limits weak-token extraction for assign/scoring |
| YAML `model.max_tokens` | Per-stage defaults in prompts/*.yaml |

### Advisory locks / concurrency control

| Lock | Namespace | File |
|------|-----------|------|
| Processing | 0x9C40 | `processing_service.channel_pipeline_lock()` |
| Full topicization | 0x70C1 | `topicization_service.channel_topicization_lock()` |
| Incremental topicization | 0x70C2 | `topicization_service.channel_incremental_topicization_lock()` |
| Resummarize per topic | 0xF5C | `resummarization_service` advisory lock |
| Scheduler per-source | 0x5C40 | `scheduler_service._source_processing_lock()` |

---

## 4. LLM interaction layer

### Provider abstraction

| File | Class | Provider |
|------|-------|----------|
| `/Users/alexanderefimov/TG_parser/tg_parser/processing/ports.py` | `LLMClient` (ABC), `LLMResponse` | Port interface |
| `/Users/alexanderefimov/TG_parser/tg_parser/processing/llm/openai_client.py` | `OpenAIClient` | OpenAI + compatible APIs; Chat Completions + Responses API |
| `/Users/alexanderefimov/TG_parser/tg_parser/processing/llm/anthropic_client.py` | `AnthropicClient` | Claude; rate limiter integration; streaming option |
| `/Users/alexanderefimov/TG_parser/tg_parser/processing/llm/gemini_client.py` | `GeminiClient` | Google Gemini |
| `/Users/alexanderefimov/TG_parser/tg_parser/processing/llm/ollama_client.py` | `OllamaClient` | Local Ollama |
| `/Users/alexanderefimov/TG_parser/tg_parser/processing/llm/instrumented.py` | `InstrumentedLLMClient` | Prometheus metrics wrapper |
| `/Users/alexanderefimov/TG_parser/tg_parser/processing/llm/factory.py` | `create_llm_client()`, `resolve_llm_config()` | Factory + stage resolution |
| `/Users/alexanderefimov/TG_parser/tg_parser/processing/mock_llm.py` | Test doubles | Deterministic test clients |

### Prompt loading

| File | Role |
|------|------|
| `/Users/alexanderefimov/TG_parser/tg_parser/processing/prompt_loader.py` | `PromptLoader.load()`, `get_system_prompt()`, `get_user_template()`, `get_model_settings()`; fail-loud for `REQUIRED_PROMPT_STAGES` |
| `/Users/alexanderefimov/TG_parser/prompts/*.yaml` | Runtime prompts |
| `/Users/alexanderefimov/TG_parser/prompts/README.md` | Format documentation |
| Env | `PROMPTS_DIR` → `settings.prompts_dir` |

### Stage → provider resolution

| File | Mechanism |
|------|-----------|
| `/Users/alexanderefimov/TG_parser/tg_parser/config/settings.py` | `LLMConfigManager` (class ~line 1520+); scopes: `global`, `processing`, `topicization`, `rag`, `digest`, `resummarize`, `bot` |
| Per-stage env | `PROCESSING_LLM_PROVIDER`, `TOPICIZATION_LLM_PROVIDER`, `RAG_LLM_PROVIDER`, etc. |
| Runtime override | API/MCP `set_llm_config` / `reset_llm_config` (not persisted) |
| `/Users/alexanderefimov/TG_parser/tg_parser/api/routes/llm_config.py` | HTTP surface for runtime switching |

### Request batching, retries, token/cost management

- **Batching:** processing parallelism via asyncio semaphore; topicization batch concurrency; embedding API batching.
- **Retries:** per-client HTTP retry loops; pipeline-level per-message retry; JSON repair before counting parse failures.
- **Token tracking:** `LLMResponse.input_tokens/output_tokens`; pipeline accumulators `_batch_input_tokens`; topicization `total_input_tokens`; resummarize tick token cap.
- **Cost guards:** Anthropic billing errors propagate to pause source (`_pause_source_for_billing`); degraded tick detection (BUG-067).
- **Determinism:** `temperature=0` default; `prompt_id` SHA-256 hash stored in metadata (TR-40).

---

## 5. Data storage / DB layer (processing-relevant)

### Logical databases (Postgres engines)

| Engine | Migrations | Key tables |
|--------|------------|------------|
| Ingestion | `migrations/versions/ingestion/` | `sources`, `source_attempts`, `digest_subscriptions`, `watch_interests`, `workspaces` |
| Raw | `migrations/versions/raw/` (if present) / raw branch | `raw_messages` |
| Processing | `migrations/versions/processing/` | `processed_documents`, `topic_cards`, `topic_bundles`, `document_embeddings`, `topic_links`, `topic_card_versions`, `processing_failures`, `watch_matches` |

### Schema / metadata definitions

| Path | Content |
|------|---------|
| `/Users/alexanderefimov/TG_parser/tg_parser/storage/sqlalchemy/_metadata.py` | SQLAlchemy table defs, FTS `search_vector` expressions, indexes (`idx_pd_channel_content_hash`) |
| `/Users/alexanderefimov/TG_parser/tg_parser/domain/models.py` | Pydantic domain models: `RawTelegramMessage`, `ProcessedDocument`, `TopicCard`, `TopicBundle`, `WatchInterest`, `WatchMatch`, `TopicCardVersion`, `IncrementalTopicizeResult` |
| `/Users/alexanderefimov/TG_parser/tg_parser/domain/contract_validation.py` | JSON Schema validation |
| `/Users/alexanderefimov/TG_parser/tg_parser/domain/ids.py` | Deterministic IDs: `doc:`, `topic:` |
| `/Users/alexanderefimov/TG_parser/tg_parser/storage/ports.py` | Repository interfaces + `SimilarityResult` |

### JSON contracts (`docs/contracts/`)

| Schema | Entity |
|--------|--------|
| `/Users/alexanderefimov/TG_parser/docs/contracts/raw_telegram_message.schema.json` | Raw ingestion |
| `/Users/alexanderefimov/TG_parser/docs/contracts/processed_document.schema.json` | LLM processing output |
| `/Users/alexanderefimov/TG_parser/docs/contracts/topic_card.schema.json` | Topic cards |
| `/Users/alexanderefimov/TG_parser/docs/contracts/topic_bundle.schema.json` | Topic bundles |
| `/Users/alexanderefimov/TG_parser/docs/contracts/topic_card_version.schema.json` | F5-C version audit |
| `/Users/alexanderefimov/TG_parser/docs/contracts/knowledge_base_entry.schema.json` | Export/RAG entry shape |
| `/Users/alexanderefimov/TG_parser/docs/contracts/workspace.schema.json` | F4-B scoping |
| `/Users/alexanderefimov/TG_parser/docs/contracts/subscription_target.schema.json` | Digest/watchlist targets |

### ADRs (processing-relevant)

| ADR | Topic |
|-----|-------|
| `/Users/alexanderefimov/TG_parser/docs/adr/0001-overall-architecture.md` | Overall system |
| `/Users/alexanderefimov/TG_parser/docs/adr/0002-telegram-ingestion-approach.md` | Telethon ingestion |
| `/Users/alexanderefimov/TG_parser/docs/adr/0003-storage-and-indexing.md` | Postgres + FTS + pgvector |
| `/Users/alexanderefimov/TG_parser/docs/adr/0004-hexagonal-architecture-and-module-boundaries.md` | Ports/adapters |
| `/Users/alexanderefimov/TG_parser/docs/adr/0006-karpathy-like-living-kb-principles.md` | 7 Living-KB invariants |
| `/Users/alexanderefimov/TG_parser/docs/adr/0009-idempotency.md` | Idempotent operations |
| `/Users/alexanderefimov/TG_parser/docs/adr/0010-watchlist-keyword-aggregation.md` | Top-k vs mean keyword scoring |
| `/Users/alexanderefimov/TG_parser/docs/adr/0011-watchlist-backfill-rework.md` | Watchlist backfill |
| `/Users/alexanderefimov/TG_parser/docs/adr/0012-watchlist-threshold-calibration.md` | Threshold calibration |
| `/Users/alexanderefimov/TG_parser/docs/adr/0013-watchlist-threshold-precision-floor.md` | Threshold precision |
| `/Users/alexanderefimov/TG_parser/docs/adr/0014-watchlist-batch-silent-delivery.md` | Batch delivery |
| `/Users/alexanderefimov/TG_parser/docs/adr/0015-watchlist-update-recalibration.md` | Update recalibration |
| `/Users/alexanderefimov/TG_parser/docs/adr/0016-near-duplicate-dedup.md` | Exact + near-dup strategy |

---

## 6. Existing docs relevant to the review

### Normative / architecture

| Path | Relevance |
|------|-----------|
| `/Users/alexanderefimov/TG_parser/docs/pipeline.md` | Canonical pipeline stages, topicization algorithm spec, idempotency semantics |
| `/Users/alexanderefimov/TG_parser/docs/DATA_ARCHITECTURE.md` | Table schemas, field descriptions (dated; some SQLite references superseded by Postgres) |
| `/Users/alexanderefimov/TG_parser/docs/SERVER_ARCHITECTURE.md` | Production topology, scheduler in API container |
| `/Users/alexanderefimov/TG_parser/docs/adr/*.md` | Accepted architectural decisions |
| `/Users/alexanderefimov/TG_parser/docs/contracts/*.json` | Data shape invariants reviewers must not violate |

### Quality / review lifecycle

| Path | Relevance |
|------|-----------|
| `/Users/alexanderefimov/TG_parser/docs/quality/AGENT_PLAYBOOK.md` | Quality lifecycle, incident vs inbox |
| `/Users/alexanderefimov/TG_parser/docs/quality/TAXONOMY.md` | Severity/category taxonomy |
| `/Users/alexanderefimov/TG_parser/docs/quality/INBOX.md` | Active quality signals |
| `/Users/alexanderefimov/TG_parser/docs/quality/TRIAGED.md` | Resolved items |
| `/Users/alexanderefimov/TG_parser/docs/quality/incidents/2026-04-20_genotek_topicization_silent_failure.md` | Historical topicization failure case |

### Implementation notes / bug context (high value for algorithm review)

| Path | Relevance |
|------|-----------|
| `/Users/alexanderefimov/TG_parser/docs/notes/processing-implementation.md` | Early processing pipeline TR mapping |
| `/Users/alexanderefimov/TG_parser/docs/notes/BUG_LOG.md` | BUG-067..079 processing/topicization fixes |
| `/Users/alexanderefimov/TG_parser/docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` | Living-KB feature waves |
| `/Users/alexanderefimov/TG_parser/docs/notes/START_PROMPT_SESSION_BUG071_TOPICIZATION_TOKEN_BURN_2026-06-27.md` | Token burn / truncation fixes |
| `/Users/alexanderefimov/TG_parser/docs/plans/F5A_PERSISTENT_KB_PLAN.md` | Hybrid search + dedup plan |

### Tests / entry docs

| Path | Relevance |
|------|-----------|
| `/Users/alexanderefimov/TG_parser/README.md` | Feature overview, Wave 1 scope |
| `/Users/alexanderefimov/TG_parser/tests/README.md` | Test modes; pointers to watchlist/hybrid tests |
| `/Users/alexanderefimov/TG_parser/ENV_VARIABLES_GUIDE.md` | All tuning knobs |
| `/Users/alexanderefimov/TG_parser/prompts/README.md` | Prompt YAML format |

### Key test files for algorithm behavior

- `/Users/alexanderefimov/TG_parser/tests/test_processing_pipeline.py`
- `/Users/alexanderefimov/TG_parser/tests/test_f5a_hybrid_search.py`
- `/Users/alexanderefimov/TG_parser/tests/test_f5a_phase3_dedup.py`
- `/Users/alexanderefimov/TG_parser/tests/test_topicization.py`
- `/Users/alexanderefimov/TG_parser/tests/test_incremental_topicization.py`
- `/Users/alexanderefimov/TG_parser/tests/test_watchlist_score.py`
- `/Users/alexanderefimov/TG_parser/tests/test_near_duplicate_observe.py`
- `/Users/alexanderefimov/TG_parser/tests/test_resummarize_metrics.py`
- `/Users/alexanderefimov/TG_parser/tests/test_retrieval_hybrid_session.py`

---

## 7. Ranked reviewer focus list (information processing algorithms)

Priority order for a detailed algorithm review:

| Rank | Path(s) | Why |
|------|---------|-----|
| **1** | `/Users/alexanderefimov/TG_parser/tg_parser/processing/pipeline.py` | Core per-message LLM extraction, dedup, retries, JSON repair, parallel batching, token accounting |
| **2** | `/Users/alexanderefimov/TG_parser/tg_parser/processing/topicization.py` | Largest algorithm surface: full clustering, chunked resume, merge, incremental assign/discover, truncation ladder, quality gates |
| **3** | `/Users/alexanderefimov/TG_parser/tg_parser/services/topicization_service.py` | Orchestrates incremental/full/reconcile/resume; locks; cross-chunk merge; auto-linking; re-escalation cooldown |
| **4** | `/Users/alexanderefimov/TG_parser/tg_parser/services/scheduler_service.py` | Defines tick ordering, degraded detection, hook coupling (embed → topicize → near-dup → resummarize → watchlist → reconcile) |
| **5** | `/Users/alexanderefimov/TG_parser/tg_parser/services/retrieval_service.py` + `/Users/alexanderefimov/TG_parser/tg_parser/services/_ranking.py` + `/Users/alexanderefimov/TG_parser/tg_parser/storage/sqlalchemy/embedding_repo.py` | Hybrid RRF search, FTS query construction, pgvector queries |
| **6** | `/Users/alexanderefimov/TG_parser/tg_parser/services/watchlist_service.py` + `/Users/alexanderefimov/TG_parser/tg_parser/services/watchlist_tokenizer.py` | Hybrid 0.4/0.6 scoring, keyword aggregation (ADR-0010), exclude hard-filter |
| **7** | `/Users/alexanderefimov/TG_parser/tg_parser/processing/topicization_checkpoint.py` | Chunk-plan pinning, noprogress circuit breaker — correctness under crash/resume |
| **8** | `/Users/alexanderefimov/TG_parser/tg_parser/services/resummarization_service.py` | N-threshold + age triggers, advisory locks, input window selection, token caps |
| **9** | `/Users/alexanderefimov/TG_parser/tg_parser/domain/hashing.py` + dedup sections of `pipeline.py` + `/Users/alexanderefimov/TG_parser/tg_parser/services/near_duplicate_service.py` | Exact + near-duplicate observation pipeline |
| **10** | `/Users/alexanderefimov/TG_parser/tg_parser/services/embedding_service.py` | Embedding text preparation (truncation), batching, channel_id persistence (BUG-064) |
| **11** | `/Users/alexanderefimov/TG_parser/tg_parser/services/topic_linking_service.py` | Cross-channel linking all-pairs algorithm (O(channels² × topics²)) |
| **12** | `/Users/alexanderefimov/TG_parser/tg_parser/processing/llm/` (factory, rate_limiter, anthropic/openai clients, response_cache) | Provider abstraction, rate limits, retries, caching |
| **13** | `/Users/alexanderefimov/TG_parser/tg_parser/processing/prompt_loader.py` + `/Users/alexanderefimov/TG_parser/prompts/` | Prompt contracts affecting extraction quality and token use |
| **14** | `/Users/alexanderefimov/TG_parser/tg_parser/services/processing_service.py` | Batch window, advisory locks, failure cooldown integration |
| **15** | `/Users/alexanderefimov/TG_parser/tg_parser/config/settings.py` | All tunables: concurrency, thresholds, budgets, hybrid flags |
| **16** | `/Users/alexanderefimov/TG_parser/tg_parser/domain/models.py` | Field semantics for counters (`new_items_since_last_summary`), watchlist models |
| **17** | `/Users/alexanderefimov/TG_parser/docs/pipeline.md` + `/Users/alexanderefimov/TG_parser/docs/adr/0006-karpathy-like-living-kb-principles.md` + `/Users/alexanderefimov/TG_parser/docs/adr/0016-near-duplicate-dedup.md` | Spec vs implementation alignment |
| **18** | `/Users/alexanderefimov/TG_parser/tests/test_*` (see §6) | Behavioral contracts and regression coverage |

---

### Review prompt hints (derived from inventory)

When writing the review prompt, emphasize these **cross-cutting review axes**:

1. **Token/cost efficiency** — truncation ladders, re-escalation storms, JSON retry multiplication, chunked full-run budgets vs incremental cheap paths.
2. **Correctness under concurrency** — advisory locks, TOCTOU on dedup, SQLAlchemy session parallelism in hybrid search, tick-local doc abandonment (BUG-073/075).
3. **Algorithm choice** — LLM-heavy full topicization vs programmatic Phase 1; RRF vs score normalization; top-k vs mean watchlist keywords; observation-only near-dup vs future consolidation.
4. **Retrieval quality** — embedding text truncation (500 chars), FTS tri-config tsquery, RRF k, topic/message quota in RAG.
5. **Living-loop invariants (ADR-0006)** — cheap hot path (watchlist, assign) vs expensive cold path (discover, full topicize, resummarize).
6. **Refactoring cost estimates** — flag-gated settings already exist for many knobs; highest-cost refactors likely in `topicization.py` chunk/merge state machine and `topic_linking_service.py` all-pairs scaling.

---

## Outcome

- The archived main transcript ends after Turn 3 (both subagents launched). It does **not** contain the assistant's final synthesis of the Fable 5 code-review prompt.
- The final prompt file **`docs/notes/START_PROMPT_FABLE5_CODE_REVIEW_PROCESSING_ALGORITHMS_2026-07-07.md` exists** in the workspace, indicating the assistant completed the synthesis (combining Subagent A's Fable 5 prompting guidance with Subagent B's algorithm inventory) and wrote the deliverable after the recorded portion of the chat.
