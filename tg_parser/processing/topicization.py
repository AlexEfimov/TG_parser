"""
Topicization pipeline implementation.

Реализует TopicizationPipeline: кластеризация ProcessedDocument → TopicCard + TopicBundle.
Требования: TR-27..TR-37, TR-IF-4 (детерминизм anchors).
"""

import json
import logging
from datetime import UTC, datetime

from tg_parser.config import settings
from tg_parser.domain.ids import make_topic_id
from tg_parser.domain.models import (
    Anchor,
    BundleItem,
    BundleItemRole,
    MessageType,
    TopicBundle,
    TopicCard,
    TopicType,
)
from tg_parser.processing.llm.openai_client import OpenAIClient
from tg_parser.processing.ports import LLMClient, TopicizationPipeline
from tg_parser.processing.topicization_prompts import (
    SUPPORTING_ITEMS_SYSTEM_PROMPT,
    TOPICIZATION_SYSTEM_PROMPT,
    build_supporting_items_prompt,
    build_topicization_prompt,
    get_supporting_items_prompt_name,
    get_topicization_prompt_name,
)
from tg_parser.storage.ports import ProcessedDocumentRepo, TopicBundleRepo, TopicCardRepo

logger = logging.getLogger(__name__)

# Quality criteria (TR-35)
MIN_SINGLETON_SCORE = 0.75
MIN_SINGLETON_LENGTH = 300
MIN_CLUSTER_ANCHORS = 2
MIN_CLUSTER_SCORE = 0.6
MIN_SUPPORTING_SCORE = 0.5
MAX_ANCHORS_PER_CLUSTER = 3


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
        llm_client: LLMClient,
        processed_doc_repo: ProcessedDocumentRepo,
        topic_card_repo: TopicCardRepo,
        topic_bundle_repo: TopicBundleRepo,
        pipeline_version: str | None = None,
        model_id: str | None = None,
    ):
        """
        Args:
            llm_client: LLM клиент для тематизации
            processed_doc_repo: Репозиторий processed документов
            topic_card_repo: Репозиторий topic cards
            topic_bundle_repo: Репозиторий topic bundles
            pipeline_version: Версия pipeline (default из settings)
            model_id: Идентификатор модели (default из OpenAI client)
        """
        self.llm_client = llm_client
        self.processed_doc_repo = processed_doc_repo
        self.topic_card_repo = topic_card_repo
        self.topic_bundle_repo = topic_bundle_repo
        self.pipeline_version = pipeline_version or settings.pipeline_version_topicization

        # Model ID извлекаем из OpenAI client если доступен
        if model_id:
            self.model_id = model_id
        elif isinstance(llm_client, OpenAIClient):
            self.model_id = llm_client.model
        else:
            self.model_id = "unknown"

        # Вычисляем prompt_id (TR-40)
        if isinstance(llm_client, OpenAIClient):
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
            self.supporting_prompt_id = llm_client.compute_prompt_id(
                SUPPORTING_ITEMS_SYSTEM_PROMPT,
                build_supporting_items_prompt("test", "test", [], [], [], []),
            )
        else:
            self.prompt_id = "unknown"
            self.supporting_prompt_id = "unknown"

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

        # Step 1: Подготовка корпуса (TR-30)
        documents = await self.processed_doc_repo.list_by_channel(channel_id)

        if not documents:
            logger.warning("No processed documents found for channel_id=%s", channel_id)
            return []

        logger.info("Found %d processed documents for channel_id=%s", len(documents), channel_id)

        # Step 2: Выбор кандидатов в якоря
        # Для MVP используем все документы как кандидатов
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

        # Step 3: Генерация тем через LLM
        logger.info("Generating topics with LLM for %d candidates", len(candidates))

        prompt = build_topicization_prompt(candidates)

        try:
            response = await self.llm_client.generate(
                prompt=prompt,
                system_prompt=TOPICIZATION_SYSTEM_PROMPT,
                temperature=0.0,  # TR-38: детерminизм
                response_format={"type": "json_object"},
            )

            llm_result = json.loads(response)
            raw_topics = llm_result.get("topics", [])

            logger.info("LLM generated %d raw topics", len(raw_topics))

        except Exception as e:
            logger.error("Failed to generate topics with LLM: %s", e, exc_info=True)
            raise RuntimeError(f"Topicization LLM call failed: {e}") from e

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
        # Sort by (score desc, anchor_ref asc) and take top-N
        anchors = self._determinize_anchors(anchors, topic_type)

        # Step 5: Применение критериев качества (TR-35)
        if not self._validate_quality(anchors, topic_type, documents):
            logger.info("Topic failed quality criteria, skipping")
            return None

        # Build TopicCard
        primary_anchor_ref = anchors[0].anchor_ref
        topic_id = make_topic_id(primary_anchor_ref)

        # Extract metadata
        title = raw_topic.get("title", "Untitled Topic")
        summary = raw_topic.get("summary", "")
        scope_in = raw_topic.get("scope_in", [])
        scope_out = raw_topic.get("scope_out", [])
        tags = raw_topic.get("tags")

        # Ensure scope_in/scope_out have at least 1 item (contract requirement)
        if not scope_in:
            scope_in = ["General topic content"]
        if not scope_out:
            scope_out = ["Unrelated content"]

        # Build metadata (TR-35, TR-40)
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

        Returns:
            Детерminированный список anchors
        """
        # Dedup by anchor_ref
        seen = set()
        unique_anchors = []
        for anchor in anchors:
            if anchor.anchor_ref not in seen:
                seen.add(anchor.anchor_ref)
                unique_anchors.append(anchor)

        # Sort by (score desc, anchor_ref asc)
        sorted_anchors = sorted(
            unique_anchors,
            key=lambda a: (-a.score if a.score else 0.0, a.anchor_ref),
        )

        # Take top-N for cluster
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

        Singleton:
        - length >= 300 символов
        - score >= 0.75

        Cluster:
        - минимум 2 anchors
        - score >= 0.6 для всех anchors

        Returns:
            True если критерии соблюдены
        """
        if topic_type == TopicType.SINGLETON:
            # TR-35: singleton требует score >= 0.75 и length >= 300
            if not anchors:
                return False

            primary_anchor = anchors[0]

            if primary_anchor.score is None or primary_anchor.score < MIN_SINGLETON_SCORE:
                logger.debug("Singleton score too low: %s", primary_anchor.score)
                return False

            # Find document for length check
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
            # TR-35: cluster требует минимум 2 anchors с score >= 0.6
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
    ) -> TopicBundle:
        """
        Сформировать подборку материалов по теме (TR-36).

        Алгоритм:
        1. Добавить anchors как items с role="anchor"
        2. Найти supporting items через LLM (score >= 0.5)
        3. Дедупликация по source_ref
        4. Детерминированная сортировка (TR-63)
        """
        logger.info(
            "Building topic bundle for topic_id=%s, channel_id=%s", topic_card.id, channel_id
        )

        # Step 1: Начинаем с anchors (TR-36)
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

        # Step 2: Найти supporting items
        anchor_refs = [anchor.anchor_ref for anchor in topic_card.anchors]

        # Get all documents for channel
        documents = await self.processed_doc_repo.list_by_channel(channel_id)

        if len(documents) > len(anchor_refs):
            # Есть документы помимо anchors - ищем supporting
            supporting_items = await self._find_supporting_items(
                topic_card=topic_card,
                anchor_refs=anchor_refs,
                documents=documents,
            )

            items.extend(supporting_items)

        # Step 3: Дедупликация по source_ref (TR-36)
        seen = set()
        unique_items = []
        for item in items:
            if item.source_ref not in seen:
                seen.add(item.source_ref)
                unique_items.append(item)

        # Step 4: Детерминированная сортировка (TR-63)
        # Сортируем по (role, score desc, source_ref asc)
        # Anchors идут первыми, потом supporting
        unique_items.sort(
            key=lambda item: (
                0 if item.role == BundleItemRole.ANCHOR else 1,
                -(item.score if item.score else 0.0),
                item.source_ref,
            )
        )

        # Build metadata
        metadata = {
            "topicization_run_id": topic_card.metadata.get("topicization_run_id")
            if topic_card.metadata
            else None,
            "pipeline_version": self.pipeline_version,
            "model_id": self.model_id,
            "prompt_id": self.supporting_prompt_id,
            "prompt_name": self.supporting_prompt_name,
            "algorithm": "llm_relevance",
            "parameters": {
                "temperature": 0.0,
                "min_supporting_score": MIN_SUPPORTING_SCORE,
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

        # Save bundle
        await self.topic_bundle_repo.upsert(bundle)
        logger.info("Saved topic bundle: %s with %d items", bundle.topic_id, len(bundle.items))

        return bundle

    async def _find_supporting_items(
        self,
        topic_card: TopicCard,
        anchor_refs: list[str],
        documents: list,
    ) -> list[BundleItem]:
        """
        Найти supporting items для темы через LLM.

        TR-36: включаем supporting при score >= 0.5.

        Returns:
            Список BundleItem с role="supporting"
        """
        # Prepare documents for LLM (exclude anchors)
        candidate_docs = [
            {
                "source_ref": doc.source_ref,
                "text_clean": doc.text_clean,
                "summary": doc.summary,
            }
            for doc in documents
            if doc.source_ref not in anchor_refs
        ]

        if not candidate_docs:
            return []

        # Build prompt
        prompt = build_supporting_items_prompt(
            topic_title=topic_card.title,
            topic_summary=topic_card.summary,
            scope_in=topic_card.scope_in,
            scope_out=topic_card.scope_out,
            anchor_refs=anchor_refs,
            messages=candidate_docs,
        )

        try:
            response = await self.llm_client.generate(
                prompt=prompt,
                system_prompt=SUPPORTING_ITEMS_SYSTEM_PROMPT,
                temperature=0.0,  # TR-38: детерminизм
                response_format={"type": "json_object"},
            )

            llm_result = json.loads(response)
            raw_supporting = llm_result.get("supporting_items", [])

            logger.info("LLM identified %d supporting items", len(raw_supporting))

        except Exception as e:
            logger.error("Failed to find supporting items with LLM: %s", e, exc_info=True)
            return []

        # Build BundleItem objects
        supporting_items = []

        for raw_item in raw_supporting:
            source_ref = raw_item.get("source_ref")
            score = raw_item.get("score", 0.0)
            justification = raw_item.get("justification")

            # Validate score threshold (TR-36)
            if score < MIN_SUPPORTING_SCORE:
                continue

            # Parse source_ref
            parts = source_ref.split(":")
            if len(parts) != 4:
                continue

            _, ch_id, msg_type, msg_id = parts

            supporting_items.append(
                BundleItem(
                    channel_id=ch_id,
                    message_id=msg_id,
                    message_type=MessageType(msg_type),
                    source_ref=source_ref,
                    role=BundleItemRole.SUPPORTING,
                    score=score,
                    justification=justification,
                )
            )

        logger.info("Filtered to %d valid supporting items", len(supporting_items))

        return supporting_items
