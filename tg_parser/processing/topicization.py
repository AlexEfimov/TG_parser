"""
Topicization pipeline implementation.

Реализует TopicizationPipeline: кластеризация ProcessedDocument → TopicCard + TopicBundle.
Требования: TR-27..TR-37, TR-IF-4 (детерминизм anchors).
"""

import asyncio
import json
import logging
import re
from datetime import UTC, datetime

from tg_parser.config import settings
from tg_parser.domain.ids import make_topic_id
from tg_parser.domain.models import (
    Anchor,
    BundleItem,
    BundleItemRole,
    MessageType,
    TopicAssignment,
    TopicBundle,
    TopicCard,
    TopicType,
)
from tg_parser.processing.pipeline import extract_json_from_response
from tg_parser.processing.ports import LLMClient, TopicizationPipeline
from tg_parser.processing.topicization_prompts import (
    INCREMENTAL_DISCOVER_SYSTEM_PROMPT,
    TOPICIZATION_SYSTEM_PROMPT,
    build_incremental_discover_prompt,
    build_topicization_prompt,
    get_incremental_discover_prompt_name,
    get_supporting_items_prompt_name,
    get_topicization_prompt_name,
)
from tg_parser.storage.ports import ProcessedDocumentRepo, TopicBundleRepo, TopicCardRepo

logger = logging.getLogger(__name__)

# Quality criteria (TR-35) — wired from settings (Session 33)
MIN_SINGLETON_SCORE = settings.topicization_singleton_min_score
MIN_SINGLETON_LENGTH = settings.topicization_singleton_min_len
MIN_CLUSTER_ANCHORS = 2
MIN_CLUSTER_SCORE = settings.topicization_cluster_min_anchor_score
MIN_SUPPORTING_SCORE = settings.topicization_supporting_min_score
MAX_SUPPORTING_ITEMS = settings.topicization_max_supporting_items
MAX_ANCHORS_PER_CLUSTER = settings.topicization_top_n_anchors
MIN_TOKEN_LENGTH = settings.topicization_min_token_length
TEXT_CLEAN_MATCH_CHARS = settings.topicization_text_clean_match_chars


class TopicizationPipelineImpl(TopicizationPipeline):
    """
    Реализация pipeline тематизации.

    Требования:
    - TR-27..TR-37: формирование TopicCard и TopicBundle
    - TR-IF-4: детерminизм anchors (sort by score desc, anchor_ref asc)
    - TR-35: критерии качества тем
    - TR-32: детерминизм тематизации
    """

    def __init__(
        self,
        llm_client: LLMClient | None,
        processed_doc_repo: ProcessedDocumentRepo,
        topic_card_repo: TopicCardRepo,
        topic_bundle_repo: TopicBundleRepo,
        pipeline_version: str | None = None,
        model_id: str | None = None,
        batch_concurrency: int = 5,
    ):
        """
        Args:
            llm_client: LLM клиент для тематизации
            processed_doc_repo: Репозиторий processed документов
            topic_card_repo: Репозиторий topic cards
            topic_bundle_repo: Репозиторий topic bundles
            pipeline_version: Версия pipeline (default: "v1.0")
            model_id: Идентификатор модели (default из OpenAI client)
            batch_concurrency: Max concurrent LLM batches in topicize_channel
        """
        self.llm_client = llm_client
        self.processed_doc_repo = processed_doc_repo
        self.topic_card_repo = topic_card_repo
        self.topic_bundle_repo = topic_bundle_repo
        self._db_lock = asyncio.Lock()
        self.pipeline_version = pipeline_version or "v1.0"
        self.batch_concurrency = batch_concurrency

        if model_id:
            self.model_id = model_id
        elif hasattr(llm_client, "model"):
            self.model_id = llm_client.model
        else:
            self.model_id = "unknown"

        # Вычисляем prompt_id (TR-40)
        if hasattr(llm_client, "compute_prompt_id"):
            self.prompt_id = llm_client.compute_prompt_id(
                TOPICIZATION_SYSTEM_PROMPT,
                build_topicization_prompt(
                    [
                        {
                            "source_ref": "tg:ch:post:1",
                            "text_clean": "test",
                            "summary": "test",
                            "topics": [],
                        }
                    ]
                ),
            )
        else:
            self.prompt_id = "unknown"

        self.prompt_name = get_topicization_prompt_name()
        self.supporting_prompt_name = get_supporting_items_prompt_name()

    async def topicize_channel(
        self,
        channel_id: str,
        force: bool = False,
    ) -> list[TopicCard]:
        """
        Сформировать темы для канала.

        TR-30: все ProcessedDocument канала используются для тематизации.
        TR-32: детерминизм (при одинаковых входных данных результат стабилен).

        Алгоритм (docs/pipeline.md строки 114-163):
        1. Подготовка корпуса - все ProcessedDocument канала
        2. Выбор кандидатов в якоря
        3. Генерация тем через LLM
        4. Нормализация и детерминизация anchors (TR-IF-4)
        5. Применение критериев качества (TR-35)
        6. Сохранение TopicCard в репозиторий
        """
        logger.info("Starting topicization for channel_id=%s, force=%s", channel_id, force)

        if force:
            deleted_bundles = await self.topic_bundle_repo.delete_by_channel(channel_id)
            deleted_cards = await self.topic_card_repo.delete_by_channel(channel_id)
            logger.info(
                "Force mode: deleted %d old topic cards and %d bundles for channel_id=%s",
                deleted_cards, deleted_bundles, channel_id,
            )

        # Step 1: Подготовка корпуса (TR-30)
        documents = await self.processed_doc_repo.list_by_channel(channel_id)

        if not documents:
            logger.warning("No processed documents found for channel_id=%s", channel_id)
            return []

        logger.info("Found %d processed documents for channel_id=%s", len(documents), channel_id)

        # Step 2: Выбор кандидатов в якоря
        candidates = [
            {
                "source_ref": doc.source_ref,
                "text_clean": doc.text_clean,
                "summary": doc.summary,
                "topics": doc.topics or [],
                "channel_id": doc.channel_id,
                "message_id": doc.source_message_id,
            }
            for doc in documents
        ]

        # Step 3: Генерация тем через LLM (параллельный батчинг)
        BATCH_SIZE = 50
        batch_concurrency = self.batch_concurrency
        raw_topics = []

        if len(candidates) <= BATCH_SIZE:
            raw_topics = await self._generate_topics_batch(candidates)
        else:
            batches = [
                candidates[i:i + BATCH_SIZE]
                for i in range(0, len(candidates), BATCH_SIZE)
            ]
            logger.info(
                "Large channel (%d docs), %d batches of %d (concurrency=%d)",
                len(candidates), len(batches), BATCH_SIZE, batch_concurrency,
            )

            semaphore = asyncio.Semaphore(batch_concurrency)

            async def _gen_batch(idx: int, batch: list[dict]) -> list[dict]:
                async with semaphore:
                    logger.info("Processing batch %d/%d (%d candidates)", idx + 1, len(batches), len(batch))
                    topics = await self._generate_topics_batch(batch)
                    logger.info("Batch %d/%d generated %d topics", idx + 1, len(batches), len(topics))
                    return topics

            batch_results = await asyncio.gather(
                *(_gen_batch(i, b) for i, b in enumerate(batches)),
                return_exceptions=True,
            )

            all_batch_topics = []
            for i, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    logger.error("Batch %d/%d failed: %s", i + 1, len(batches), result)
                else:
                    all_batch_topics.extend(result)

            if all_batch_topics:
                raw_topics = await self._merge_topics(all_batch_topics, candidates)
                logger.info("Merged %d batch topics into %d final topics", len(all_batch_topics), len(raw_topics))

        # Step 4 & 5: Нормализация, детерминизация и применение критериев качества
        topic_cards = []

        for raw_topic in raw_topics:
            try:
                topic_card = self._build_topic_card(
                    raw_topic=raw_topic,
                    channel_id=channel_id,
                    documents=documents,
                )

                if topic_card:
                    topic_cards.append(topic_card)

            except Exception as e:
                logger.error("Failed to build topic card from raw_topic: %s", e, exc_info=True)
                continue

        logger.info("Created %d valid topic cards for channel_id=%s", len(topic_cards), channel_id)

        # Step 6: Сохранение TopicCard
        for card in topic_cards:
            try:
                await self.topic_card_repo.upsert(card)
                logger.info("Saved topic card: %s", card.id)
            except Exception as e:
                logger.error("Failed to save topic card %s: %s", card.id, e, exc_info=True)

        return topic_cards

    async def _generate_topics_batch(self, candidates: list[dict]) -> list[dict]:
        """Генерировать темы для одного батча кандидатов.

        429 retries handled by AnthropicClient rate limiter; only JSONDecodeError retried here.
        """
        prompt = build_topicization_prompt(candidates)
        max_json_retries = 3

        for attempt in range(1, max_json_retries + 1):
            try:
                response = await self.llm_client.generate(
                    prompt=prompt,
                    system_prompt=TOPICIZATION_SYSTEM_PROMPT,
                    temperature=0.0,
                    max_tokens=8192,
                    response_format={"type": "json_object"},
                )

                cleaned = extract_json_from_response(response)
                llm_result = json.loads(cleaned)
                raw_topics = llm_result.get("topics", [])

                logger.info("LLM generated %d raw topics from batch of %d", len(raw_topics), len(candidates))
                return raw_topics

            except json.JSONDecodeError as e:
                if attempt < max_json_retries:
                    logger.warning("JSON parse error (attempt %d/%d): %s, retrying", attempt, max_json_retries, e)
                    await asyncio.sleep(settings.llm_json_retry_delay)
                else:
                    logger.error("Failed to parse topics JSON after %d attempts", max_json_retries, exc_info=True)
                    raise RuntimeError(f"Topicization JSON parse failed: {e}") from e
            except Exception as e:
                logger.error("Failed to generate topics with LLM: %s", e, exc_info=True)
                raise RuntimeError(f"Topicization LLM call failed: {e}") from e
        return []

    async def _merge_topics(self, all_batch_topics: list[dict], candidates: list[dict]) -> list[dict]:
        """
        Объединить темы из нескольких батчей.

        LLM возвращает только группы ID дубликатов (минимальный output).
        Метаданные (title, summary, scope, anchors) собираются программно из первого члена группы.
        """
        logger.info("Merging %d topics from batches", len(all_batch_topics))

        topics_compact = [
            {
                "id": i,
                "title": topic.get("title", ""),
                "summary": topic.get("summary", "")[:60],
            }
            for i, topic in enumerate(all_batch_topics)
        ]

        merge_prompt = f"""You have {len(topics_compact)} topics extracted from different batches of messages from the same Telegram channel.
Many topics will overlap or cover the same subject — group them aggressively.

Topics:
{json.dumps(topics_compact, ensure_ascii=False)}

Return JSON:
{{"groups": [[0, 5, 12], [3], [1, 7]]}}

Rules:
- Each topic ID must appear in exactly one group
- Merge topics that cover the same subject even if titles differ slightly
- Be aggressive: prefer fewer, broader groups over many narrow ones
- Singletons: [3] (topic with truly no overlap)
- Merged: [0, 5, 12] (same or overlapping subjects grouped together)
- Return ONLY the "groups" array of arrays of integer IDs, nothing else"""

        max_merge_retries = 3
        groups = []

        for attempt in range(1, max_merge_retries + 1):
            try:
                response = await self.llm_client.generate(
                    prompt=merge_prompt,
                    system_prompt="You are a topic deduplication expert. Return compact JSON with only group ID arrays.",
                    temperature=0.0,
                    max_tokens=16384,
                    response_format={"type": "json_object"},
                )

                cleaned = extract_json_from_response(response)
                result = json.loads(cleaned)
                groups = result.get("groups", [])
                break
            except json.JSONDecodeError as e:
                if attempt < max_merge_retries:
                    logger.warning("Merge JSON parse error (attempt %d/%d): %s, retrying", attempt, max_merge_retries, e)
                    await asyncio.sleep(settings.llm_json_retry_delay)
                else:
                    logger.warning("Merge JSON parse failed after %d attempts, using all batch topics: %s", max_merge_retries, e)
                    return all_batch_topics
            except Exception as e:
                logger.warning("Failed to merge topics: %s", e, exc_info=True)
                return all_batch_topics

        if not groups:
            logger.warning("Merge returned empty groups, using all batch topics")
            return all_batch_topics

        merged_topics = []
        for group in groups:
            member_ids = group if isinstance(group, list) else group.get("member_ids", [])
            valid_ids = [mid for mid in member_ids if 0 <= mid < len(all_batch_topics)]
            if not valid_ids:
                continue

            primary = all_batch_topics[valid_ids[0]]

            combined_anchors = []
            seen_refs: set[str] = set()
            for mid in valid_ids:
                for anchor in all_batch_topics[mid].get("anchors", []):
                    ref = anchor.get("source_ref", "")
                    if ref and ref not in seen_refs:
                        combined_anchors.append(anchor)
                        seen_refs.add(ref)

            merged_topics.append({
                "title": primary.get("title", ""),
                "summary": primary.get("summary", ""),
                "type": primary.get("type", "cluster") if len(valid_ids) == 1 else "cluster",
                "scope_in": primary.get("scope_in", []),
                "scope_out": primary.get("scope_out", []),
                "anchors": combined_anchors,
            })

        logger.info(
            "Merged %d batch topics into %d unique topics",
            len(all_batch_topics), len(merged_topics),
        )
        return merged_topics

    def _build_topic_card(
        self,
        raw_topic: dict,
        channel_id: str,
        documents: list,
    ) -> TopicCard | None:
        """
        Построить и валидировать TopicCard из raw LLM output.

        TR-IF-4: детерминизация anchors (sort by score desc, anchor_ref asc).
        TR-35: критерии качества.

        Returns:
            TopicCard or None если не прошёл критерии качества
        """
        topic_type_str = raw_topic.get("type", "cluster")
        topic_type = TopicType.SINGLETON if topic_type_str == "singleton" else TopicType.CLUSTER

        # Parse anchors
        raw_anchors = raw_topic.get("anchors", [])

        if not raw_anchors:
            logger.warning("Topic has no anchors, skipping")
            return None

        # Build Anchor objects
        anchors = []
        for raw_anchor in raw_anchors:
            source_ref = raw_anchor.get("source_ref")
            score = raw_anchor.get("score", 0.0)

            if not source_ref:
                continue

            # Parse source_ref: tg:channel_id:message_type:message_id
            parts = source_ref.split(":")
            if len(parts) != 4:
                logger.warning("Invalid source_ref format: %s", source_ref)
                continue

            _, ch_id, msg_type, msg_id = parts

            anchors.append(
                Anchor(
                    channel_id=ch_id,
                    message_id=msg_id,
                    message_type=MessageType(msg_type),
                    anchor_ref=source_ref,
                    score=score,
                )
            )

        if not anchors:
            logger.warning("No valid anchors after parsing, skipping topic")
            return None

        # Step 4: Детерminизация anchors (TR-IF-4)
        anchors = self._determinize_anchors(anchors, topic_type)

        # Step 5: Применение критериев качества (TR-35)
        if not self._validate_quality(anchors, topic_type, documents):
            logger.info("Topic failed quality criteria, skipping")
            return None

        # Build TopicCard
        primary_anchor_ref = anchors[0].anchor_ref
        topic_id = make_topic_id(primary_anchor_ref)

        title = raw_topic.get("title", "Untitled Topic")
        summary = raw_topic.get("summary", "")
        scope_in = raw_topic.get("scope_in", [])
        scope_out = raw_topic.get("scope_out", [])
        tags = raw_topic.get("tags")

        if not scope_in:
            scope_in = ["General topic content"]
        if not scope_out:
            scope_out = ["Unrelated content"]

        metadata = {
            "topicization_run_id": f"run_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}",
            "pipeline_version": self.pipeline_version,
            "model_id": self.model_id,
            "prompt_id": self.prompt_id,
            "prompt_name": self.prompt_name,
            "algorithm": "llm_clustering",
            "parameters": {
                "temperature": 0.0,
                "min_singleton_score": MIN_SINGLETON_SCORE,
                "min_singleton_length": MIN_SINGLETON_LENGTH,
                "min_cluster_anchors": MIN_CLUSTER_ANCHORS,
                "min_cluster_score": MIN_CLUSTER_SCORE,
                "max_anchors": MAX_ANCHORS_PER_CLUSTER,
            },
            "input_scope": {
                "channel_id": channel_id,
                "mode": "full_history",
            },
        }

        topic_card = TopicCard(
            id=topic_id,
            title=title,
            summary=summary,
            scope_in=scope_in,
            scope_out=scope_out,
            type=topic_type,
            anchors=anchors,
            sources=[channel_id],
            updated_at=datetime.now(UTC),
            tags=tags,
            metadata=metadata,
        )

        return topic_card

    def _determinize_anchors(
        self,
        anchors: list[Anchor],
        topic_type: TopicType,
    ) -> list[Anchor]:
        """
        Детерминизация anchors (TR-IF-4).

        1. Удаление дубликатов по anchor_ref
        2. Сортировка по (score desc, anchor_ref asc)
        3. Top-N для cluster (N=3)
        """
        seen = set()
        unique_anchors = []
        for anchor in anchors:
            if anchor.anchor_ref not in seen:
                seen.add(anchor.anchor_ref)
                unique_anchors.append(anchor)

        sorted_anchors = sorted(
            unique_anchors,
            key=lambda a: (-a.score if a.score else 0.0, a.anchor_ref),
        )

        if topic_type == TopicType.CLUSTER:
            sorted_anchors = sorted_anchors[:MAX_ANCHORS_PER_CLUSTER]

        return sorted_anchors

    def _validate_quality(
        self,
        anchors: list[Anchor],
        topic_type: TopicType,
        documents: list,
    ) -> bool:
        """
        Проверить критерии качества темы (TR-35).

        Singleton: length >= 300, score >= 0.75
        Cluster: min 2 anchors, score >= 0.6
        """
        if topic_type == TopicType.SINGLETON:
            if not anchors:
                return False

            primary_anchor = anchors[0]

            if primary_anchor.score is None or primary_anchor.score < MIN_SINGLETON_SCORE:
                logger.debug("Singleton score too low: %s", primary_anchor.score)
                return False

            doc = next(
                (d for d in documents if d.source_ref == primary_anchor.anchor_ref),
                None,
            )

            if not doc:
                logger.warning("Document not found for anchor_ref: %s", primary_anchor.anchor_ref)
                return False

            if len(doc.text_clean) < MIN_SINGLETON_LENGTH:
                logger.debug(
                    "Singleton text too short: %d < %d",
                    len(doc.text_clean),
                    MIN_SINGLETON_LENGTH,
                )
                return False

        elif topic_type == TopicType.CLUSTER:
            if len(anchors) < MIN_CLUSTER_ANCHORS:
                logger.debug("Cluster has too few anchors: %d", len(anchors))
                return False

            for anchor in anchors:
                if anchor.score is None or anchor.score < MIN_CLUSTER_SCORE:
                    logger.debug("Cluster anchor score too low: %s", anchor.score)
                    return False

        return True

    async def build_topic_bundle(
        self,
        topic_card: TopicCard,
        channel_id: str,
        documents: list | None = None,
    ) -> TopicBundle:
        """
        Сформировать подборку материалов по теме (TR-36).

        Supporting items найдены программным keyword matching (без LLM).
        """
        logger.info(
            "Building topic bundle for topic_id=%s, channel_id=%s", topic_card.id, channel_id
        )

        items = []

        for anchor in topic_card.anchors:
            items.append(
                BundleItem(
                    channel_id=anchor.channel_id,
                    message_id=anchor.message_id,
                    message_type=anchor.message_type,
                    source_ref=anchor.anchor_ref,
                    role=BundleItemRole.ANCHOR,
                    parent_message_id=anchor.parent_message_id,
                    thread_id=anchor.thread_id,
                    score=anchor.score,
                )
            )

        anchor_refs = {anchor.anchor_ref for anchor in topic_card.anchors}

        if documents is None:
            documents = await self.processed_doc_repo.list_by_channel(channel_id)

        if len(documents) > len(anchor_refs):
            supporting_items = self._find_supporting_items_programmatic(
                topic_card=topic_card,
                anchor_refs=anchor_refs,
                documents=documents,
            )
            items.extend(supporting_items)

        # Дедупликация по source_ref (TR-36)
        seen = set()
        unique_items = []
        for item in items:
            if item.source_ref not in seen:
                seen.add(item.source_ref)
                unique_items.append(item)

        # Детерминированная сортировка (TR-63)
        unique_items.sort(
            key=lambda item: (
                0 if item.role == BundleItemRole.ANCHOR else 1,
                -(item.score if item.score else 0.0),
                item.source_ref,
            )
        )

        metadata = {
            "topicization_run_id": topic_card.metadata.get("topicization_run_id")
            if topic_card.metadata
            else None,
            "pipeline_version": self.pipeline_version,
            "model_id": self.model_id,
            "prompt_id": "keyword_matching_v2",
            "prompt_name": self.supporting_prompt_name,
            "algorithm": "keyword_matching",
            "parameters": {
                "min_supporting_score": MIN_SUPPORTING_SCORE,
                "max_supporting_items": MAX_SUPPORTING_ITEMS,
                "min_token_length": MIN_TOKEN_LENGTH,
                "text_clean_match_chars": TEXT_CLEAN_MATCH_CHARS,
            },
            "input_scope": {
                "channel_id": channel_id,
                "mode": "full_history",
            },
        }

        bundle = TopicBundle(
            topic_id=topic_card.id,
            items=unique_items,
            updated_at=datetime.now(UTC),
            channels=[channel_id],
            metadata=metadata,
        )

        async with self._db_lock:
            await self.topic_bundle_repo.upsert(bundle)
        logger.info("Saved topic bundle: %s with %d items", bundle.topic_id, len(bundle.items))

        return bundle

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Extract lowercase word tokens (MIN_TOKEN_LENGTH+ chars) for keyword matching.

        Session 33: lowered from 4 to 2 (configurable) to capture short medical
        abbreviations like СОЭ, ТТГ, ПЦР, IgE, IgG, ЛДГ, АЛТ, ДНК, РНК.
        """
        return {w for w in re.findall(
            rf"[a-zA-Zа-яА-ЯёЁ]{{{MIN_TOKEN_LENGTH},}}", text.lower(),
        )}

    @classmethod
    def _tokenize_topic_card(cls, topic_card: TopicCard) -> set[str]:
        """Build keyword token set from a TopicCard's title and scope_in."""
        tokens: set[str] = set()
        for kw in topic_card.scope_in:
            tokens |= cls._tokenize(kw)
        tokens |= cls._tokenize(topic_card.title)
        tokens.discard("")
        return tokens

    @classmethod
    def _tokenize_document(cls, doc) -> tuple[set[str], set[str]]:
        """Build strong (topics+summary) and weak (text_clean) token sets from a doc.

        Returns (strong_tokens, weak_tokens) where weak = text_clean-only tokens.
        """
        strong: set[str] = set()
        for t in (doc.topics or []):
            strong |= cls._tokenize(t)
        if doc.summary:
            strong |= cls._tokenize(doc.summary)

        weak: set[str] = set()
        if TEXT_CLEAN_MATCH_CHARS and doc.text_clean:
            weak = cls._tokenize(doc.text_clean[:TEXT_CLEAN_MATCH_CHARS]) - strong

        return strong, weak

    @staticmethod
    def _compute_match_score(
        topic_keywords: set[str],
        strong_tokens: set[str],
        weak_tokens: set[str],
    ) -> tuple[float, set[str]]:
        """Compute weighted keyword-overlap score between topic keywords and doc tokens.

        Strong tokens (topics/summary) count at 1.0x, weak tokens (text_clean) at 0.3x.
        Includes substring fallback for long tokens (>=5 chars).

        Returns (score, hit_keywords).
        """
        doc_tokens = strong_tokens | weak_tokens
        if not doc_tokens or not topic_keywords:
            return 0.0, set()

        hits = topic_keywords & doc_tokens
        if not hits:
            for kw in topic_keywords:
                for dt in doc_tokens:
                    if len(kw) >= 5 and len(dt) >= 5 and (kw in dt or dt in kw):
                        hits.add(kw)
                        break

        if not hits:
            return 0.0, set()

        strong_hits = hits & strong_tokens
        weak_hits = hits - strong_tokens
        weighted_hits = len(strong_hits) + len(weak_hits) * 0.3

        score = weighted_hits / max(len(topic_keywords), 1)
        return round(score, 3), hits

    def _find_supporting_items_programmatic(
        self,
        topic_card: TopicCard,
        anchor_refs: set[str],
        documents: list,
    ) -> list[BundleItem]:
        """
        Find supporting items by keyword matching against ProcessedDocument.topics.

        Uses scope_in keywords + title tokens to match against each document's
        pre-extracted topics list. No LLM calls — O(topics * docs) string comparisons.
        """
        topic_keywords = self._tokenize_topic_card(topic_card)
        if not topic_keywords:
            return []

        supporting_items: list[BundleItem] = []

        for doc in documents:
            if doc.source_ref in anchor_refs:
                continue

            strong_tokens, weak_tokens = self._tokenize_document(doc)
            score, hits = self._compute_match_score(topic_keywords, strong_tokens, weak_tokens)

            if score < MIN_SUPPORTING_SCORE:
                continue

            parts = doc.source_ref.split(":")
            if len(parts) != 4:
                continue

            _, ch_id, msg_type, msg_id = parts
            supporting_items.append(
                BundleItem(
                    channel_id=ch_id,
                    message_id=msg_id,
                    message_type=MessageType(msg_type),
                    source_ref=doc.source_ref,
                    role=BundleItemRole.SUPPORTING,
                    score=score,
                    justification=f"keyword overlap: {', '.join(sorted(hits)[:5])}",
                )
            )

        supporting_items.sort(key=lambda x: -(x.score or 0))
        supporting_items = supporting_items[:MAX_SUPPORTING_ITEMS]

        logger.info(
            "Programmatic matching found %d supporting items for topic '%s'",
            len(supporting_items), topic_card.title[:50],
        )
        return supporting_items

    async def assign_documents_to_topics(
        self,
        new_docs: list,
        channel_id: str,
    ) -> tuple[list[TopicAssignment], list[str]]:
        """
        Phase 1: Programmatic assignment of documents to existing topics.

        For each doc: tokenize fields -> match against topic keywords ->
        assign to best topic if score >= threshold.

        Returns:
            (assignments, unassigned_source_refs)
        """
        topic_cards = await self.topic_card_repo.list_by_channel(channel_id)
        if not topic_cards:
            logger.warning("No topic cards found for channel %s — all docs unassigned", channel_id)
            return [], [doc.source_ref for doc in new_docs]

        topic_keyword_sets: list[tuple[TopicCard, set[str]]] = [
            (card, self._tokenize_topic_card(card))
            for card in topic_cards
        ]
        topic_keyword_sets = [(card, kws) for card, kws in topic_keyword_sets if kws]

        assignments: list[TopicAssignment] = []
        unassigned: list[str] = []

        for doc in new_docs:
            strong_tokens, weak_tokens = self._tokenize_document(doc)

            best_score = 0.0
            best_topic_id: str | None = None

            for card, topic_keywords in topic_keyword_sets:
                score, _hits = self._compute_match_score(topic_keywords, strong_tokens, weak_tokens)
                if score > best_score:
                    best_score = score
                    best_topic_id = card.id

            if best_topic_id is not None and best_score >= MIN_SUPPORTING_SCORE:
                assignments.append(TopicAssignment(
                    source_ref=doc.source_ref,
                    topic_id=best_topic_id,
                    score=best_score,
                    method="keyword",
                ))
            else:
                unassigned.append(doc.source_ref)

        logger.info(
            "Phase 1 assign: %d assigned, %d unassigned out of %d new docs (channel=%s)",
            len(assignments), len(unassigned), len(new_docs), channel_id,
        )
        return assignments, unassigned

    async def discover_new_topics(
        self,
        channel_id: str,
        unassigned_docs: list,
        batch_size: int = 50,
    ) -> tuple[list[TopicAssignment], list[TopicCard], list[str], int]:
        """Phase 2: LLM discover — assign unassigned docs to existing topics or create new ones.

        When len(unassigned_docs) > batch_size the documents are split into
        sequential batches.  New topics discovered in batch N are added to the
        existing-topics context for batch N+1 to avoid duplicates.

        Returns:
            (llm_assignments, new_topic_cards, unassignable_refs, tokens_used)
        """
        if not unassigned_docs:
            return [], [], [], 0

        topic_cards = await self.topic_card_repo.list_by_channel(channel_id)
        existing_topics = [
            {"id": card.id, "title": card.title, "scope_in": card.scope_in}
            for card in topic_cards
        ]
        existing_topic_ids = {card.id for card in topic_cards}

        if len(unassigned_docs) <= batch_size:
            return await self._discover_single_batch(
                channel_id, unassigned_docs, existing_topics, existing_topic_ids,
            )

        all_assignments: list[TopicAssignment] = []
        all_new_cards: list[TopicCard] = []
        all_unassignable: list[str] = []
        total_tokens = 0
        total_batches = (len(unassigned_docs) + batch_size - 1) // batch_size

        for i in range(0, len(unassigned_docs), batch_size):
            batch_docs = unassigned_docs[i:i + batch_size]
            batch_num = i // batch_size + 1

            logger.info(
                "discover_new_topics batch %d/%d (%d docs, channel=%s)",
                batch_num, total_batches, len(batch_docs), channel_id,
            )

            assignments, new_cards, unassignable, tokens = \
                await self._discover_single_batch(
                    channel_id, batch_docs, existing_topics, existing_topic_ids,
                )

            all_assignments.extend(assignments)
            all_new_cards.extend(new_cards)
            all_unassignable.extend(unassignable)
            total_tokens += tokens

            for card in new_cards:
                existing_topics.append(
                    {"id": card.id, "title": card.title, "scope_in": card.scope_in}
                )
                existing_topic_ids.add(card.id)

        logger.info(
            "Phase 2 discover: %d batches, %d assigned, %d new topics, "
            "%d unassignable (channel=%s)",
            total_batches, len(all_assignments), len(all_new_cards),
            len(all_unassignable), channel_id,
        )

        return all_assignments, all_new_cards, all_unassignable, total_tokens

    async def _discover_single_batch(
        self,
        channel_id: str,
        batch_docs: list,
        existing_topics: list[dict],
        existing_topic_ids: set[str],
    ) -> tuple[list[TopicAssignment], list[TopicCard], list[str], int]:
        """Run a single LLM discover call for a batch of documents."""
        docs_payload = [
            {
                "source_ref": doc.source_ref,
                "summary": doc.summary or "",
                "topics": doc.topics or [],
                "text_clean": doc.text_clean,
            }
            for doc in batch_docs
        ]

        prompt = build_incremental_discover_prompt(existing_topics, docs_payload)

        max_json_retries = 3
        llm_result: dict | None = None
        tokens_used = 0

        for attempt in range(1, max_json_retries + 1):
            try:
                llm_response = await self.llm_client.generate_with_usage(
                    prompt=prompt,
                    system_prompt=INCREMENTAL_DISCOVER_SYSTEM_PROMPT,
                    temperature=0.0,
                    max_tokens=8192,
                    response_format={"type": "json_object"},
                )
                tokens_used += llm_response.total_tokens
                cleaned = extract_json_from_response(llm_response.text)
                llm_result = json.loads(cleaned)
                break
            except json.JSONDecodeError as e:
                if attempt < max_json_retries:
                    logger.warning(
                        "Phase 2 JSON parse error (attempt %d/%d): %s, retrying",
                        attempt, max_json_retries, e,
                    )
                    await asyncio.sleep(settings.llm_json_retry_delay)
                else:
                    logger.error(
                        "Phase 2 JSON parse failed after %d attempts, "
                        "marking batch docs as unassignable",
                        max_json_retries,
                    )
                    return [], [], [doc.source_ref for doc in batch_docs], tokens_used
            except Exception as e:
                logger.error("Phase 2 LLM call failed: %s", e, exc_info=True)
                return [], [], [doc.source_ref for doc in batch_docs], tokens_used

        if llm_result is None:
            return [], [], [doc.source_ref for doc in batch_docs], tokens_used

        llm_assignments: list[TopicAssignment] = []
        for raw_assign in llm_result.get("assignments", []):
            topic_id = raw_assign.get("topic_id", "")
            source_ref = raw_assign.get("source_ref", "")
            confidence = raw_assign.get("confidence", 0.0)
            if topic_id in existing_topic_ids and source_ref:
                llm_assignments.append(TopicAssignment(
                    source_ref=source_ref,
                    topic_id=topic_id,
                    score=min(max(confidence, 0.0), 1.0),
                    method="llm",
                ))

        new_topic_cards: list[TopicCard] = []
        for raw_topic in llm_result.get("new_topics", []):
            try:
                card = self._build_topic_card(
                    raw_topic=raw_topic,
                    channel_id=channel_id,
                    documents=batch_docs,
                )
                if card:
                    card.metadata = card.metadata or {}
                    card.metadata["origin"] = "discovered"
                    card.metadata["discovered_at"] = datetime.now(UTC).isoformat()
                    card.metadata["algorithm"] = "incremental_llm_discover"
                    card.metadata["prompt_name"] = get_incremental_discover_prompt_name()
                    new_topic_cards.append(card)
            except Exception as e:
                logger.error("Failed to build discovered topic card: %s", e, exc_info=True)

        unassignable = llm_result.get("unassignable", [])

        logger.info(
            "Phase 2 batch: %d assigned, %d new topics, %d unassignable (channel=%s)",
            len(llm_assignments), len(new_topic_cards), len(unassignable), channel_id,
        )

        return llm_assignments, new_topic_cards, unassignable, tokens_used
