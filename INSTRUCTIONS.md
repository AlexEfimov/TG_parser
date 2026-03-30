MCP server for navigating, searching, and managing a Telegram-channel knowledge base.

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
