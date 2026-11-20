"""R16 / BUG-105: rebuild a channel's topic bundles under decision G — no LLM.

``tg-parser topic rebuild-supporting --channel <ch> [--write]`` recomputes the
supporting part of every bundle of a channel with the current product formula
(``_compute_topic_bundle``: anchors + programmatic supporting, R16 decision G)
and writes it with ``upsert`` — never ``add_items``, so the F5-C resummarize
counter does not move (stage-B DoD).

What a rebuilt bundle keeps (owner decisions 2026-11-19 / 2026-11-20):

* anchors of the card and supporting by the formula — recomputed;
* items of the old bundle placed by LLM discover (``incremental llm assign``)
  whose document still exists — kept as they are (decision 5a: no LLM in R16);
  an anchor wins over an LLM item for the same ``source_ref``, an LLM item wins
  over a formula item; LLM items do not count against the supporting cap
  (same as ``add_items``);
* decision 4a — a document covered by the old bundles but by nothing new stays
  covered: Phase 1 (``assign_documents_with_cards``, unchanged selection) picks
  its best topic, the item is scored with the supporting K (§2 p. 6.1) and
  labelled ``rebuild coverage keep: …``; it may push a topic past the cap, as
  ``add_items`` can. Without a Phase-1 topic (or when the best topic is a card
  that is not rebuilt) — fallback to the old bundle with the highest new score
  (ties: old score, then ``topic_id``), label ``rebuild coverage keep (fallback): …``.

Everything else of the old bundle (``keyword overlap``, ``incremental keyword
assign``, earlier ``rebuild coverage keep``) is recomputed, so a second run on
the same data gives the same items (idempotent).

Only bundles whose channels are exactly ``[channel]`` are rebuilt. Any other
bundle ``list_by_channel`` returns (another channel's, or multi-channel even
with this channel first) is left alone and reported; a card whose stored bundle
is such a bundle is not rebuilt either. Bundles of this channel without a card
are left alone too. Documents in left-alone bundles stay covered, so 4a does
not add them anywhere and the coverage metrics count them.

The pure core (:func:`rebuild_channel_bundles`) has no DB access. The DB modes:

* dry-run (default) — :func:`run_dry` on its own engine with
  ``default_transaction_read_only=on`` in ``server_settings`` (asyncpg ignores
  ``PGOPTIONS``), checked with ``SHOW`` before anything else; no ``Database``
  singleton, no advisory locks, no writes;
* ``--write`` — :func:`run_write`: skips a channel with a live full-run
  checkpoint (a read error counts as live) or when either topicization lock
  (0x70C1 full, 0x70C2 incremental) is held; computes on a snapshot, then in
  one transaction re-reads the cards/bundles fingerprint (changed → rollback,
  ``bundles_changed``), stages ``upsert(commit=False)`` for every rebuilt
  bundle and commits once; afterwards re-reads the bundles and reports topics
  whose written content did not survive (``reverted_topics``).

The incremental tick does NOT stop on a held 0x70C2 lock (it proceeds without
it), so the protection against a concurrent tick is best effort: run right
after a tick; the fingerprint catches a tick write during the computation, the
post-commit check one that lands just after the commit. Re-running is safe.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from tg_parser.domain.models import (
    BundleItem,
    BundleItemRole,
    MessageType,
    TopicBundle,
    TopicCard,
)

REBUILD_TOOL = "rebuild-supporting"
LLM_JUSTIFICATION_PREFIX = "incremental llm assign"
COVERAGE_KEEP_LABEL = "rebuild coverage keep"
COVERAGE_FALLBACK_LABEL = "rebuild coverage keep (fallback)"
NO_MODEL_ID = "none (rebuild)"


@dataclass
class ChannelSnapshot:
    """Everything the rebuild reads for one channel.

    ``cards`` in ``TopicCardRepo.list_by_channel`` order (``updated_at DESC``):
    Phase 1's first-best argmax depends on it, exactly as in the product.
    ``bundles`` — everything ``TopicBundleRepo.list_by_channel`` returned.
    """

    channel_id: str
    docs: list
    cards: list[TopicCard]
    bundles: list[TopicBundle]


@dataclass
class RebuildResult:
    bundles: list[TopicBundle]  # one per rebuilt card, ready for upsert
    report: dict[str, Any]
    fingerprint: dict[str, Any] = field(default_factory=dict)


def effective_settings() -> dict[str, Any]:
    """Product scoring knobs the rebuild runs with (first line of every report)."""
    from tg_parser.processing import topicization as topi

    return {
        "min_supporting_score": topi.MIN_SUPPORTING_SCORE,
        "max_supporting_items": topi.MAX_SUPPORTING_ITEMS,
        "keyword_aggregation": topi.ASSIGN_KEYWORD_AGGREGATION,
        "assign_keyword_topk": topi.ASSIGN_KEYWORD_TOPK,
        "supporting_keyword_topk": topi.SUPPORTING_KEYWORD_TOPK,
        "supporting_score_cut": topi.SUPPORTING_SCORE_CUT,
        "min_token_length": topi.MIN_TOKEN_LENGTH,
        "text_clean_match_chars": topi.TEXT_CLEAN_MATCH_CHARS,
    }


def channel_fingerprint(
    channel_id: str, cards: Sequence[TopicCard], bundles: Sequence[TopicBundle]
):
    """What must not change between the snapshot and the write.

    Cards: id → (title, scope_in, anchor refs) — the inputs of the formula.
    Bundles: topic_id → sorted item refs, for every bundle of this channel.
    """
    card_fp = {
        c.id: (c.title, tuple(c.scope_in), tuple(sorted(a.anchor_ref for a in c.anchors)))
        for c in cards
    }
    bundle_fp = {
        b.topic_id: tuple(sorted(it.source_ref for it in b.items))
        for b in bundles
        if _is_own_bundle(b, channel_id)
    }
    foreign = tuple(sorted(b.topic_id for b in bundles if not _is_own_bundle(b, channel_id)))
    return {"cards": card_fp, "bundles": bundle_fp, "foreign": foreign}


def _is_own_bundle(bundle: TopicBundle, channel_id: str) -> bool:
    # The LIKE in list_by_channel is loose. Rebuild only bundles of exactly this
    # channel: a multi-channel bundle (even with this channel first) is skipped
    # and reported, so --write never drops another channel's items.
    return (bundle.channels or [channel_id]) == [channel_id]


def _is_llm_item(item: BundleItem) -> bool:
    return (item.justification or "").startswith(LLM_JUSTIFICATION_PREFIX)


def _supporting_item(source_ref: str, score: float, justification: str) -> BundleItem | None:
    parts = source_ref.split(":")
    if len(parts) != 4:
        return None
    _, ch_id, msg_type, msg_id = parts
    return BundleItem(
        channel_id=ch_id,
        message_id=msg_id,
        message_type=MessageType(msg_type),
        source_ref=source_ref,
        role=BundleItemRole.SUPPORTING,
        score=score,
        justification=justification,
    )


def _label(prefix: str, hits: set[str]) -> str:
    return f"{prefix}: {', '.join(sorted(hits)[:5])}" if hits else prefix


def _tr63_key(item: BundleItem):
    return (
        0 if item.role == BundleItemRole.ANCHOR else 1,
        -(item.score if item.score else 0.0),
        item.source_ref,
    )


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    m = len(s) // 2
    return float(s[m]) if len(s) % 2 else (s[m - 1] + s[m]) / 2


def rebuild_channel_bundles(
    snapshot: ChannelSnapshot,
    pipeline,
    *,
    now: datetime | None = None,
    with_base: bool = False,
) -> RebuildResult:
    """Pure core: new bundles for every card of the channel plus the report.

    ``pipeline`` is a ``TopicizationPipelineImpl`` (only its pure helpers are
    used: ``_compute_topic_bundle``, ``assign_documents_with_cards``,
    ``_find_supporting_items_programmatic``, ``_tokenize_*``,
    ``_compute_match_score``).
    """
    from tg_parser.processing import topicization as topi

    now = now or datetime.now(UTC)
    ch = snapshot.channel_id
    docs = snapshot.docs
    cards = snapshot.cards
    doc_by_ref = {d.source_ref: d for d in docs}
    doc_refs = set(doc_by_ref)
    n_docs = len(docs)
    cap = topi.MAX_SUPPORTING_ITEMS

    own = [b for b in snapshot.bundles if _is_own_bundle(b, ch)]
    foreign = [b for b in snapshot.bundles if not _is_own_bundle(b, ch)]
    foreign_ids = {b.topic_id for b in foreign}
    old_by_topic = {b.topic_id: b for b in own}
    card_ids = {c.id for c in cards}

    rebuilt_cards = [c for c in cards if c.id not in foreign_ids]
    skipped_cards = [c.id for c in cards if c.id in foreign_ids]
    untouched = [b for b in own if b.topic_id not in card_ids]  # bundles without a card

    # One tokenization per document for the whole channel (same result, R16 perf).
    doc_tokens = {d.source_ref: pipeline._tokenize_document(d) for d in docs}
    card_kws = {c.id: pipeline._tokenize_topic_card(c) for c in cards}

    # Bundles not rebuilt keep their items: they count as coverage before and after.
    left_alone = untouched + foreign
    stored_cov = {it.source_ref for b in snapshot.bundles for it in b.items} & doc_refs
    llm_refs_all = {
        it.source_ref
        for b in own
        for it in b.items
        if _is_llm_item(it) and it.source_ref in doc_refs
    }

    # --- formula (anchors + supporting by G) per card -----------------------
    formula: dict[str, TopicBundle] = {}
    for card in cards:
        formula[card.id] = pipeline._compute_topic_bundle(card, ch, docs, doc_tokens=doc_tokens)

    def _sup(b: TopicBundle) -> list[BundleItem]:
        return [it for it in b.items if it.role == BundleItemRole.SUPPORTING]

    # --- items per rebuilt card: formula + kept LLM ------------------------
    items_by_topic: dict[str, dict[str, BundleItem]] = {}
    llm_kept = Counter()
    llm_orphans = 0
    llm_replaced_formula = 0
    for card in rebuilt_cards:
        built = {it.source_ref: it for it in formula[card.id].items}
        old = old_by_topic.get(card.id)
        for it in old.items if old else []:
            if not _is_llm_item(it):
                continue
            if it.source_ref not in doc_refs:
                llm_orphans += 1
                continue
            prev = built.get(it.source_ref)
            if prev is not None and prev.role == BundleItemRole.ANCHOR:
                continue  # anchor wins
            if prev is not None:
                llm_replaced_formula += 1
            built[it.source_ref] = it
            llm_kept[card.id] += 1
        items_by_topic[card.id] = built

    # --- 4a: previously covered, not covered now ----------------------------
    new_cov = {r for built in items_by_topic.values() for r in built}
    new_cov |= {it.source_ref for b in left_alone for it in b.items}
    candidates = sorted((stored_cov - new_cov) & doc_refs)
    cand_docs = [doc_by_ref[r] for r in candidates]
    assignments, unassigned = pipeline.assign_documents_with_cards(
        cand_docs, cards, doc_tokens=doc_tokens
    )
    rebuilt_ids = {c.id for c in rebuilt_cards}
    coverage_kept = Counter()
    coverage_fallback = Counter()
    coverage_lost: list[str] = []
    fallback_refs = list(unassigned)
    for a in assignments:
        if a.topic_id not in rebuilt_ids:
            fallback_refs.append(a.source_ref)
            continue
        strong, weak = doc_tokens[a.source_ref]
        score, hits = pipeline._compute_match_score(
            card_kws[a.topic_id], strong, weak, topk=topi.SUPPORTING_KEYWORD_TOPK
        )
        item = _supporting_item(a.source_ref, score, _label(COVERAGE_KEEP_LABEL, hits))
        if item is None:
            coverage_lost.append(a.source_ref)
            continue
        items_by_topic[a.topic_id][a.source_ref] = item
        coverage_kept[a.topic_id] += 1

    # ref -> [(topic_id, old score)] over the old bundles that are rebuilt
    held_by: dict[str, list[tuple[str, float]]] = {}
    if fallback_refs:
        wanted = set(fallback_refs)
        for b in own:
            if b.topic_id not in rebuilt_ids:
                continue
            for it in b.items:
                if it.source_ref in wanted:
                    held_by.setdefault(it.source_ref, []).append((b.topic_id, it.score or 0.0))
    for ref in sorted(set(fallback_refs)):
        strong, weak = doc_tokens[ref]
        # (topic_id, new score, hits, old score)
        options = []
        for topic_id, old_score in held_by.get(ref, []):
            score, hits = pipeline._compute_match_score(
                card_kws[topic_id], strong, weak, topk=topi.SUPPORTING_KEYWORD_TOPK
            )
            options.append((topic_id, score, hits, old_score))
        if not options:
            coverage_lost.append(ref)
            continue
        # highest new score, then highest old score, then the smallest topic_id
        topic_id, score, hits, _old = min(options, key=lambda o: (-o[1], -o[3], o[0]))
        item = _supporting_item(ref, score, _label(COVERAGE_FALLBACK_LABEL, hits))
        if item is None:
            coverage_lost.append(ref)
            continue
        items_by_topic[topic_id][ref] = item
        coverage_fallback[topic_id] += 1

    # --- assemble bundles ---------------------------------------------------
    at = now.isoformat()
    new_bundles: list[TopicBundle] = []
    for card in rebuilt_cards:
        built = formula[card.id]
        items = sorted(items_by_topic[card.id].values(), key=_tr63_key)
        old = old_by_topic.get(card.id)
        md = dict(built.metadata or {})
        old_md = (old.metadata or {}) if old else {}
        md["model_id"] = old_md.get("model_id") or NO_MODEL_ID
        md["rebuild"] = {
            "tool": REBUILD_TOOL,
            "at": at,
            "llm_kept": llm_kept[card.id],
            "coverage_kept": coverage_kept[card.id],
            "coverage_fallback": coverage_fallback[card.id],
        }
        new_bundles.append(
            TopicBundle(
                topic_id=card.id,
                items=items,
                updated_at=now,
                time_range=None,
                channels=[ch],
                metadata=md,
            )
        )

    # --- report -------------------------------------------------------------
    anchors = {c.id: {a.anchor_ref for a in c.anchors} for c in cards}
    eligible = {c.id: bool(card_kws[c.id]) and n_docs > len(anchors[c.id]) for c in cards}
    formula_sz = {c.id: len(_sup(formula[c.id])) for c in cards}

    def _sim_block(sup_refs: dict[str, list[str]]) -> dict[str, Any]:
        """Definitions of scripts/r16_supporting_simulation.py simulate_channel."""
        items = [len(anchors[cid]) + len(sup_refs[cid]) for cid in sup_refs]
        members = 0
        covered: set[str] = set()
        for cid, refs in sup_refs.items():
            m = (anchors[cid] & doc_refs) | set(refs)
            members += len(m)
            covered |= m
        covered_b = covered | llm_refs_all
        uncovered_b = [r for r in doc_refs if r not in covered_b]
        return {
            "topics": len(items),
            "items_sum": sum(items),
            "median_items": _median(items),
            "sat_cap": sum(1 for refs in sup_refs.values() if len(refs) >= cap),
            "topics_per_doc": round(members / n_docs, 2) if n_docs else 0.0,
            "topics_per_doc_members": members,
            "topics_without_supporting": sum(1 for refs in sup_refs.values() if not refs),
            "uncovered_kw_only": n_docs - len(covered),
            "uncovered_previously_covered": sum(1 for r in uncovered_b if r in stored_cov),
        }

    def _emptied_halved(ref_sz: dict[str, int]) -> dict[str, int]:
        emptied = [
            cid
            for cid in formula_sz
            if eligible[cid] and ref_sz.get(cid, 0) > 0 and formula_sz[cid] == 0
        ]
        halved = [
            cid
            for cid in formula_sz
            if eligible[cid] and 0 < formula_sz[cid] < ref_sz.get(cid, 0) / 2
        ]
        return {"topics_emptied": len(emptied), "topics_halved": len(halved)}

    g_refs = {c.id: [it.source_ref for it in _sup(formula[c.id])] for c in cards}
    sim_g = _sim_block(g_refs)
    stored_sup_sz = {
        cid: sum(1 for it in old_by_topic[cid].items if it.role == BundleItemRole.SUPPORTING)
        for cid in card_ids
        if cid in old_by_topic
    }
    sim_g["vs_stored"] = _emptied_halved(stored_sup_sz)
    report: dict[str, Any] = {
        "type": "channel",
        "channel_id": ch,
        "docs": n_docs,
        "cards": len(cards),
    }
    if with_base:
        base_refs: dict[str, list[str]] = {}
        for card in cards:
            anc = anchors[card.id]
            sup = (
                pipeline._find_supporting_items_programmatic(
                    card,
                    anc,
                    docs,
                    topk=topi.ASSIGN_KEYWORD_TOPK,
                    cut="lt",
                    doc_tokens=doc_tokens,
                )
                if n_docs > len(anc)
                else []
            )
            base_refs[card.id] = [it.source_ref for it in sup]
        report["simulation_base_pre_r16"] = _sim_block(base_refs)
        sim_g["vs_base"] = _emptied_halved({cid: len(r) for cid, r in base_refs.items()})
    report["simulation_g"] = sim_g

    n_coverage_items = sum(coverage_kept.values()) + sum(coverage_fallback.values())
    final_members = 0
    final_cov: set[str] = set()
    for b in new_bundles:
        refs = {it.source_ref for it in b.items} & doc_refs
        final_members += len(refs)
        final_cov |= refs
    for b in left_alone:
        refs = {it.source_ref for it in b.items} & doc_refs
        final_members += len(refs)
        final_cov |= refs
    stored_members = sum(
        len({it.source_ref for it in b.items} & doc_refs) for b in snapshot.bundles
    )
    report["final"] = {
        "topics_per_doc_stored": round(stored_members / n_docs, 2) if n_docs else 0.0,
        "topics_per_doc_formula": sim_g["topics_per_doc"],
        # formula (simulation definition) + the 4a items; 4a items are never formula items
        "topics_per_doc_with_4a": round(
            (sim_g["topics_per_doc_members"] + n_coverage_items) / n_docs, 2
        )
        if n_docs
        else 0.0,
        "topics_per_doc_final": round(final_members / n_docs, 2) if n_docs else 0.0,
        "coverage_pct_stored": round(100.0 * len(stored_cov) / n_docs, 2) if n_docs else 0.0,
        "coverage_pct_final": round(100.0 * len(final_cov) / n_docs, 2) if n_docs else 0.0,
        "previously_covered_now_uncovered": len(stored_cov - final_cov),
        "coverage_candidates": len(candidates),
        "coverage_kept": sum(coverage_kept.values()),
        "coverage_fallback": sum(coverage_fallback.values()),
        "coverage_lost": len(coverage_lost),
        "llm_kept": sum(llm_kept.values()),
        "llm_orphans_dropped": llm_orphans,
        "llm_replaced_formula_item": llm_replaced_formula,
        "topics_over_cap": sum(
            1
            for b in new_bundles
            if sum(1 for it in b.items if it.role == BundleItemRole.SUPPORTING) > cap
        ),
        "bundles_rebuilt": len(new_bundles),
        "cards_without_bundle": sum(1 for c in rebuilt_cards if c.id not in old_by_topic),
        "bundles_without_card": len(untouched),
        "foreign_bundles_skipped": len(foreign),
        "cards_skipped_foreign_bundle": len(skipped_cards),
    }
    return RebuildResult(
        bundles=new_bundles,
        report=report,
        fingerprint=channel_fingerprint(ch, cards, snapshot.bundles),
    )


# ---------------------------------------------------------------------------
# DB modes
# ---------------------------------------------------------------------------


async def _load_bundles(bundle_repo, channel_id: str, cards: Sequence[TopicCard]):
    """Bundles of the channel plus the stored bundle of every card it misses.

    ``list_by_channel`` matches on the bundle's channels, so a card of this
    channel whose bundle (same ``topic_id``) lists only other channels is not
    returned. ``upsert`` replaces by ``topic_id``, so without this lookup the
    rebuild would overwrite another channel's bundle. Such a bundle is foreign
    (:func:`_is_own_bundle`): the card is skipped and reported.
    """
    bundles = list(await bundle_repo.list_by_channel(channel_id))
    have = {b.topic_id for b in bundles}
    for card in cards:
        if card.id in have:
            continue
        stored = await bundle_repo.get_by_topic_id(card.id)
        if stored is not None:
            bundles.append(stored)
            have.add(card.id)
    return bundles


async def load_snapshot(doc_repo, card_repo, bundle_repo, channel_id: str) -> ChannelSnapshot:
    docs = await doc_repo.list_by_channel(channel_id)
    cards = await card_repo.list_by_channel(channel_id)
    bundles = await _load_bundles(bundle_repo, channel_id, cards)
    return ChannelSnapshot(channel_id, docs, cards, bundles)


def _make_pipeline(doc_repo, card_repo, bundle_repo):
    from tg_parser.processing.topicization import TopicizationPipelineImpl

    return TopicizationPipelineImpl(
        llm_client=None,
        processed_doc_repo=doc_repo,
        topic_card_repo=card_repo,
        topic_bundle_repo=bundle_repo,
        model_id=NO_MODEL_ID,
    )


def make_read_only_engine(settings):
    """Own engine, every transaction read-only at the server (asyncpg ignores PGOPTIONS)."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from tg_parser.storage.engine_factory import create_postgres_engine_config

    cfg = create_postgres_engine_config(
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    return create_async_engine(
        cfg.url,
        pool_size=1,
        max_overflow=0,
        connect_args={"server_settings": {"default_transaction_read_only": "on"}},
    )


class RebuildRefused(RuntimeError):
    """A precondition for running at all failed (not a per-channel skip)."""


def _unknown(snapshot: ChannelSnapshot) -> bool:
    return not snapshot.docs and not snapshot.cards


async def run_dry(
    channels: Sequence[str],
    *,
    emit: Callable[[dict], None],
    with_base: bool = False,
    engine=None,
) -> int:
    """Dry-run on a read-only engine. Returns the exit code (0 ok, 2 unknown channel)."""
    import time

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    from tg_parser.config import settings
    from tg_parser.storage.sqlalchemy.processed_document_repo import SAProcessedDocumentRepo
    from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo
    from tg_parser.storage.sqlalchemy.topic_card_repo import SATopicCardRepo

    own_engine = engine is None
    engine = engine or make_read_only_engine(settings)
    rc = 0
    try:
        async with AsyncSession(engine) as session:
            ro = (await session.execute(text("SHOW default_transaction_read_only"))).scalar()
            emit({"type": "read_only_check", "default_transaction_read_only": ro})
            if ro != "on":
                raise RebuildRefused(f"default_transaction_read_only={ro!r}, expected 'on'")
            repos = (
                SAProcessedDocumentRepo(session),
                SATopicCardRepo(session),
                SATopicBundleRepo(session),
            )
            pipeline = _make_pipeline(*repos)
            for ch in channels:
                t0 = time.monotonic()
                snap = await load_snapshot(*repos, ch)
                if _unknown(snap):
                    emit({"type": "channel", "channel_id": ch, "error": "unknown_channel"})
                    rc = 2
                    continue
                result = rebuild_channel_bundles(snap, pipeline, with_base=with_base)
                result.report.update(
                    {
                        "mode": "dry-run",
                        "runtime_s": round(time.monotonic() - t0, 1),
                        "maxrss_mb": maxrss_mb(),
                    }
                )
                emit(result.report)
                del snap, result
    finally:
        if own_engine:
            await engine.dispose()
    return rc


async def run_write(
    channels: Sequence[str],
    *,
    emit: Callable[[dict], None],
    with_base: bool = False,
) -> int:
    """Write mode on the application ``Database``. Returns the exit code
    (0 ok, 2 unknown channel, 4 a channel skipped / rolled back / reverted)."""
    import time

    from tg_parser.processing.topicization_checkpoint import FullCheckpointReadError
    from tg_parser.services.db_context import processing_repos
    from tg_parser.services.topicization_service import (
        _read_full_checkpoint_liveness,
        channel_incremental_topicization_lock,
        channel_topicization_lock,
    )
    from tg_parser.storage.sqlalchemy.processing_failure_repo import SAProcessingFailureRepo

    rc = 0
    async with processing_repos() as (doc_repo, card_repo, bundle_repo, db):
        # The lock helpers degrade to "acquired" without an engine — never trust
        # that here: no engine means no protection at all.
        if not getattr(db, "_initialized", False) or db.processing_storage_engine is None:
            raise RebuildRefused("Database is not initialized — locks would be bypassed")
        if db.advisory_lock_engine is None:
            raise RebuildRefused("advisory_lock_engine missing — 0x70C2 would be bypassed")
        session = doc_repo.session
        failure_repo = SAProcessingFailureRepo(session)
        pipeline = _make_pipeline(doc_repo, card_repo, bundle_repo)
        for ch in channels:
            t0 = time.monotonic()
            base_line = {"type": "channel", "channel_id": ch, "mode": "write"}
            async with channel_topicization_lock(ch) as full_ok:
                if not full_ok:
                    emit({**base_line, "skipped": "full_topicization_lock_held"})
                    rc = rc or 4
                    continue
                async with channel_incremental_topicization_lock(ch) as inc_ok:
                    if not inc_ok:
                        emit({**base_line, "skipped": "incremental_topicization_lock_held"})
                        rc = rc or 4
                        continue
                    # Under both locks: a resumable full run that is not running right
                    # now must not have its checkpointed bundles rewritten either.
                    try:
                        live = await _read_full_checkpoint_liveness(failure_repo, ch)
                    except FullCheckpointReadError as e:  # unknown → treat as live
                        live, base_line["checkpoint_read_error"] = True, str(e)
                    await session.rollback()
                    if live:
                        emit({**base_line, "skipped": "live_full_checkpoint"})
                        rc = rc or 4
                        continue
                    outcome = await _write_channel(
                        session, doc_repo, card_repo, bundle_repo, pipeline, ch, with_base
                    )
            outcome.update(base_line)
            outcome["runtime_s"] = round(time.monotonic() - t0, 1)
            outcome["maxrss_mb"] = maxrss_mb()
            emit(outcome)
            if outcome.get("error") == "unknown_channel":
                rc = 2 if rc in (0, 2) else rc
            elif outcome.get("skipped") or outcome.get("reverted_topics"):
                rc = rc or 4
    return rc


async def _write_channel(
    session, doc_repo, card_repo, bundle_repo, pipeline, ch, with_base
) -> dict:
    snap = await load_snapshot(doc_repo, card_repo, bundle_repo, ch)
    await session.rollback()  # end the read transaction; compute outside any transaction
    if _unknown(snap):
        return {"error": "unknown_channel"}
    result = rebuild_channel_bundles(snap, pipeline, with_base=with_base)
    report = dict(result.report)
    del snap

    try:
        cards_now = await card_repo.list_by_channel(ch)
        bundles_now = await _load_bundles(bundle_repo, ch, cards_now)
        if channel_fingerprint(ch, cards_now, bundles_now) != result.fingerprint:
            await session.rollback()
            report["skipped"] = "bundles_changed"
            return report
        for bundle in result.bundles:
            # upsert replaces by topic_id: never over another channel's bundle.
            stored = await bundle_repo.get_by_topic_id(bundle.topic_id)
            if stored is not None and not _is_own_bundle(stored, ch):
                await session.rollback()
                report["skipped"] = "foreign_bundle"
                report["foreign_topic_id"] = bundle.topic_id
                return report
            await bundle_repo.upsert(bundle, commit=False)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    report["written"] = len(result.bundles)

    # Post-commit check: a tick that read before the commit and wrote after it
    # silently restores the old content of a topic (add_items is read-modify-write
    # and writes back the metadata it read). A tick that read AFTER the commit
    # keeps our metadata and only adds items — that is not a revert.
    after = {b.topic_id: b for b in await bundle_repo.list_by_channel(ch)}
    await session.rollback()
    reverted = []
    for b in result.bundles:
        got = after.get(b.topic_id)
        same = (
            got is not None
            and ((got.metadata or {}).get("rebuild") or {}).get("at") == b.metadata["rebuild"]["at"]
            and {it.source_ref for it in b.items} <= {it.source_ref for it in got.items}
        )
        if not same:
            reverted.append(b.topic_id)
    report["reverted_topics"] = reverted[:50]
    report["reverted_topics_count"] = len(reverted)
    return report


def maxrss_mb() -> int:
    import resource
    import sys

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss // (1024 * 1024) if sys.platform == "darwin" else rss // 1024
