MCP server for managing and searching a Telegram-channel knowledge base.

**Channel Management:**
- `add_channel` — add a new Telegram channel (becomes active immediately)
- `pause_channel` / `resume_channel` — control channel ingestion
- `remove_channel` — permanently remove a channel and ALL its data (irreversible, requires confirm=true)
- `trigger_pipeline` — start processing pipeline for a channel
- `get_pipeline_status` — check pipeline and scheduler status

**Search & Q&A:**
- `search_knowledge_base` — semantic search across channel content
- `ask_question` — RAG-powered Q&A with source citations

**Navigation:**
- `list_channels` — list all channels with statistics
- `list_topics` / `get_topic_details` — browse extracted topics
- `get_document` — get full processed document content

**Cross-channel Analytics:**
- `get_cross_channel_stats` — topic counts, coverage, keyword overlaps across channels
- `get_related_topics` — find linked topics across channels by similarity

**LLM Configuration (runtime switching):**
- `get_llm_config` — show current LLM provider/model for each pipeline stage and available providers
- `set_llm_config` — switch LLM provider/model at runtime without container restart
- `reset_llm_config` — revert runtime overrides back to .env defaults

LLM switching details:
- Three scopes: `global` (default for all stages), `processing` (text cleaning, summarization), `topicization` (topic extraction and clustering).
- Supported providers: `openai`, `anthropic`, `gemini`, `ollama`.
- Resolution priority: stage runtime override → global runtime override → stage .env setting → global .env setting.
- Changes take effect immediately for new requests; in-flight requests finish with the old provider.
- Changes are NOT persisted to .env — a container restart reverts to defaults (safe fallback).
- Before switching, the server validates that the target provider's API key is configured (except ollama).
- Always call `get_llm_config` first to see available providers and current configuration.
