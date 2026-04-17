"""
Промпты для topicization pipeline.

Шаблоны промптов для LLM-based кластеризации и формирования тем.
Требования: TR-27..TR-37, TR-38 (детерminизм).
"""

# ============================================================================
# Topicization промпты (TR-27..TR-37)
# ============================================================================

TOPICIZATION_SYSTEM_PROMPT = """You are a topic analysis assistant that identifies and clusters messages into coherent topics.

Your task is to analyze a collection of messages and identify distinct topics. For each topic, you should:

1. Determine if it's a SINGLETON (one comprehensive anchor message) or CLUSTER (multiple related messages)
2. Identify anchor messages (the most representative messages for the topic)
3. Assign relevance scores (0.0-1.0) to each anchor
4. Create a descriptive title and summary
5. Define scope_in (what belongs to the topic) and scope_out (what doesn't)

IMPORTANT: Generate title, summary, scope_in, scope_out, and tags in the SAME LANGUAGE as the source messages.
Detect the dominant language of the input content and use it for all output fields. This applies to any language.

Output MUST be valid JSON matching this structure:
{
  "topics": [
    {
      "type": "singleton" or "cluster",
      "anchors": [
        {
          "source_ref": "tg:channel_id:post:message_id",
          "score": 0.0-1.0
        }
      ],
      "title": "Topic title",
      "summary": "Brief 1-3 sentence description",
      "scope_in": ["aspect 1", "aspect 2", ...],
      "scope_out": ["excluded aspect 1", "excluded aspect 2", ...],
      "tags": ["tag1", "tag2", ...] // optional
    }
  ]
}

Quality criteria:
- SINGLETON: requires score >= 0.75 and text length >= 300 characters
- CLUSTER: requires minimum 2 anchors with score >= 0.6
- Anchors should be deduplicated by source_ref
- Each topic must have clear boundaries (scope_in/scope_out)

Important:
- Be conservative: only create topics with clear coherence
- Assign meaningful scores based on message centrality to the topic
- Ensure anchor source_refs exactly match the provided message references"""

TOPICIZATION_USER_PROMPT_TEMPLATE = """Analyze these messages and identify distinct topics:

{messages_text}

For each topic, identify:
1. Type (singleton for comprehensive single message, cluster for related group)
2. Anchor messages with relevance scores
3. Descriptive title and summary
4. Clear scope boundaries (what's in/out)

Return structured JSON."""


SUPPORTING_ITEMS_SYSTEM_PROMPT = """You are an assistant that evaluates message relevance to a specific topic.

Your task is to review messages and determine which ones support or relate to the given topic. For each relevant message, assign:
1. A relevance score (0.0-1.0)
2. A brief justification explaining why it's relevant

IMPORTANT: Write justifications in the SAME LANGUAGE as the source messages.

Output MUST be valid JSON matching this structure:
{
  "supporting_items": [
    {
      "source_ref": "tg:channel_id:post:message_id",
      "score": 0.5-1.0,
      "justification": "Brief explanation of relevance"
    }
  ]
}

Quality criteria:
- Only include messages with score >= 0.5
- Exclude anchor messages (they're already in the topic)
- Be selective: not every message needs to be included
- Justifications should be concise (1 sentence)

Important:
- Focus on messages that genuinely add value to the topic
- Lower scores (0.5-0.6) for tangentially related content
- Higher scores (0.7-0.9) for directly relevant content
- Ensure source_refs exactly match the provided message references"""

SUPPORTING_ITEMS_USER_PROMPT_TEMPLATE = """Topic: {topic_title}

Summary: {topic_summary}

Scope (what's included): {scope_in}

Scope (what's excluded): {scope_out}

Anchor messages (already included):
{anchor_refs}

Evaluate these messages for relevance to the topic:

{messages_text}

Return supporting items with scores and justifications in JSON."""


# ============================================================================
# Вспомогательные функции
# ============================================================================


def build_topicization_prompt(messages: list[dict]) -> str:
    """
    Построить user промпт для topicization.

    Args:
        messages: Список словарей с полями source_ref, text_clean, summary, topics

    Returns:
        Форматированный промпт
    """
    messages_text = ""
    for i, msg in enumerate(messages, 1):
        summary = msg.get("summary", "")
        topics_str = ", ".join(msg.get("topics", []))

        messages_text += f"""
Message {i}:
Reference: {msg["source_ref"]}
Text: {msg["text_clean"][:500]}{"..." if len(msg["text_clean"]) > 500 else ""}
Summary: {summary if summary else "N/A"}
Topics: {topics_str if topics_str else "N/A"}
---
"""

    return TOPICIZATION_USER_PROMPT_TEMPLATE.format(messages_text=messages_text.strip())


def build_supporting_items_prompt(
    topic_title: str,
    topic_summary: str,
    scope_in: list[str],
    scope_out: list[str],
    anchor_refs: list[str],
    messages: list[dict],
) -> str:
    """
    Построить user промпт для поиска supporting items.

    Args:
        topic_title: Название темы
        topic_summary: Описание темы
        scope_in: Что относится к теме
        scope_out: Что не относится к теме
        anchor_refs: Ссылки на якорные сообщения (исключить из результата)
        messages: Список словарей с полями source_ref, text_clean, summary

    Returns:
        Форматированный промпт
    """
    scope_in_str = "\n".join(f"- {item}" for item in scope_in)
    scope_out_str = "\n".join(f"- {item}" for item in scope_out)
    anchor_refs_str = "\n".join(f"- {ref}" for ref in anchor_refs)

    messages_text = ""
    for i, msg in enumerate(messages, 1):
        # Skip anchor messages
        if msg["source_ref"] in anchor_refs:
            continue

        summary = msg.get("summary", "")

        messages_text += f"""
Message {i}:
Reference: {msg["source_ref"]}
Text: {msg["text_clean"][:300]}{"..." if len(msg["text_clean"]) > 300 else ""}
Summary: {summary if summary else "N/A"}
---
"""

    return SUPPORTING_ITEMS_USER_PROMPT_TEMPLATE.format(
        topic_title=topic_title,
        topic_summary=topic_summary,
        scope_in=scope_in_str,
        scope_out=scope_out_str,
        anchor_refs=anchor_refs_str,
        messages_text=messages_text.strip(),
    )


def get_topicization_prompt_name() -> str:
    """Имя промпта для metadata (TR-40)."""
    return "topicization_v1"


def get_supporting_items_prompt_name() -> str:
    """Имя промпта для supporting items (TR-40)."""
    return "supporting_items_v1"


# ============================================================================
# Incremental Discover промпт (Phase 2, Session 36)
# ============================================================================

INCREMENTAL_DISCOVER_SYSTEM_PROMPT = """You are a topic analysis assistant that assigns documents to existing topics or discovers new ones.

You receive:
1. A list of EXISTING topics (id, title, scope_in) — the current topic taxonomy
2. A batch of UNASSIGNED documents that did not match any topic by keyword

Your task for each document:
- If it clearly fits an existing topic → assign it (provide topic_id and confidence 0.0-1.0)
- If it does NOT fit any existing topic but is substantial enough → propose a NEW topic
- If it is too short, generic, or unrelated to form any topic → mark as unassignable

IMPORTANT: Generate title, summary, scope_in, scope_out for new topics in the SAME LANGUAGE as the source documents.
Detect the dominant language of the input content and use it for all output fields.

Rules for NEW topics:
- Do NOT create a topic that duplicates an existing one — check the existing topics list carefully
- Also check the CROSS-CHANNEL topics list (if provided) — do NOT create a topic that already exists in another channel
- SINGLETON topic: one document with score >= 0.75 and text length >= 300 characters
- CLUSTER topic: at least 2 documents from the unassigned batch with score >= 0.6
- Each new topic needs a clear title, summary, scope_in, scope_out

Rules for assignments:
- confidence reflects how well the document fits the topic (0.0-1.0)
- Only assign with confidence >= 0.5

Output MUST be valid JSON:
{
  "assignments": [
    {"source_ref": "tg:ch:post:123", "topic_id": "topic:tg:ch:post:100", "confidence": 0.85}
  ],
  "new_topics": [
    {
      "title": "Topic title",
      "summary": "1-3 sentence description",
      "scope_in": ["aspect 1", "aspect 2"],
      "scope_out": ["excluded aspect"],
      "type": "singleton" or "cluster",
      "anchors": [
        {"source_ref": "tg:ch:post:456", "score": 0.9}
      ]
    }
  ],
  "unassignable": ["tg:ch:post:789"]
}

Important:
- Every unassigned document must appear in exactly one of: assignments, new_topics anchors, or unassignable
- Be conservative with new topics — only create when clearly justified
- Prefer assigning to existing topics over creating new ones"""


def build_incremental_discover_prompt(
    existing_topics: list[dict],
    unassigned_docs: list[dict],
    cross_channel_topics: list[dict] | None = None,
) -> str:
    """Build user prompt for Phase 2 LLM discover.

    Args:
        existing_topics: [{id, title, scope_in}] — compact context of all channel topics
        unassigned_docs: [{source_ref, summary, topics, text_clean}] — docs to classify
        cross_channel_topics: [{id, title, scope_in, channel_id}] — topics from OTHER channels
            (used as context only — documents must still be assigned to this channel's topics)
    """
    topics_text = ""
    for t in existing_topics:
        scope = ", ".join(t.get("scope_in", []))
        topics_text += f"- id: {t['id']} | title: {t['title']} | scope: {scope}\n"

    cross_channel_section = ""
    if cross_channel_topics:
        cc_text = ""
        for t in cross_channel_topics:
            scope = ", ".join(t.get("scope_in", []))
            cc_text += (
                f"- channel: {t.get('channel_id', '?')} | title: {t['title']} | scope: {scope}\n"
            )
        cross_channel_section = f"""
---

Topics from OTHER channels (for deduplication context only — do NOT assign documents to these):

{cc_text.strip()}

IMPORTANT: If a new topic you would create is very similar to one already listed above from another channel,
still create it for THIS channel but make sure the title and scope are precise and non-redundant.
"""

    docs_text = ""
    for i, doc in enumerate(unassigned_docs, 1):
        summary = doc.get("summary") or "N/A"
        topics_str = ", ".join(doc.get("topics", []))
        text_preview = doc.get("text_clean", "")[:500]
        if len(doc.get("text_clean", "")) > 500:
            text_preview += "..."

        docs_text += f"""
Document {i}:
Reference: {doc["source_ref"]}
Summary: {summary}
Topics: {topics_str if topics_str else "N/A"}
Text: {text_preview}
---
"""

    return f"""Here are the existing topics in this channel:

{topics_text.strip()}
{cross_channel_section}
---

The following documents were NOT matched to any topic by keyword. Analyze each one and decide:
(a) assign to an existing topic, (b) propose a new topic, or (c) mark as unassignable.

{docs_text.strip()}

Return structured JSON with assignments, new_topics, and unassignable."""


def get_incremental_discover_prompt_name() -> str:
    """Prompt name for metadata."""
    return "incremental_discover_v1"
