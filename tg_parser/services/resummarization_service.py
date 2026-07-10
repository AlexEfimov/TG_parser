"""F5-C Evolving Topic Summaries (a4b5c6d7e8f9) — re-summarize service.

Triggered by the scheduler hook in ``scheduler_service._process_source``
once per channel-tick.  Walks topics whose
``new_items_since_last_summary`` crossed the threshold, takes a Postgres
advisory lock per topic, runs the ``resummarize`` LLM prompt against the
top-N items in the topic's bundle, snapshots the *previous* summary
into ``topic_card_versions``, atomically commits the new summary via
``topic_card_repo.commit_resummary`` (single UPDATE with optimistic
version check), and best-effort re-embeds the topic.

Critical invariants (see START_PROMPT_SPRINT_F5C.md):

* **Decision #13 / Gotcha #16** — ``AnthropicBillingError`` must NOT be
  swallowed inside this service.  It propagates to the scheduler hook,
  which adds it to ``stage_errors`` so ``_pause_source_for_billing``
  fires.  All other LLM exceptions are converted to
  ``status='llm_error'`` so per-channel work continues.
* **Gotcha #5** — advisory lock uses the two-key form
  ``pg_try_advisory_xact_lock(0xF5C, hashtext(topic_id))`` to reduce
  cross-feature collisions (other code paths may also hash topic_id).
  Held only for the lifetime of the transaction; commit_resummary's
  ``self.session.commit()`` releases it.
* **Gotcha #6** — input window selects ``bundle.items[:N]``, NOT
  ``[-N:]``.  ``topic_bundle_repo.add_items`` already sorts items as
  (role anchor-first, ``-score``, ``source_ref``); top-N therefore yields
  anchors plus the highest-score supports, which is what we want.
* **Real-bug #2** — version snapshot is appended BEFORE
  ``commit_resummary``, so audit trail provenance survives even if the
  optimistic version check loses the race.
"""

from __future__ import annotations

import contextlib
import json
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import text as sa_text

from tg_parser.api.metrics import record_resummarize_outcome
from tg_parser.config import settings
from tg_parser.domain.models import TopicCardVersion
from tg_parser.processing.llm.errors import AnthropicBillingError
from tg_parser.processing.llm.factory import create_llm_client, resolve_llm_config
from tg_parser.processing.pipeline import extract_json_from_response
from tg_parser.processing.prompt_loader import (
    PromptLoader,
    PromptLoaderError,
    get_prompt_loader,
)
from tg_parser.services.embedding_service import run_topic_embedding

if TYPE_CHECKING:
    from tg_parser.processing.ports import LLMClient
    from tg_parser.storage.ports import (
        ProcessedDocumentRepo,
        TopicBundleRepo,
        TopicCardRepo,
        TopicCardVersionRepo,
    )

logger = structlog.get_logger(__name__)


RESUMMARIZE_ITEM_TEXT_MAX_CHARS = 500
"""Upper bound (chars) for the per-item ``text_clean`` snippet placed into the
re-summarize prompt (O-1 / F-02).

Each window item now carries the document ``summary`` plus a truncated
``text_clean`` so the LLM actually sees the material it is asked to summarize.
Truncating per item keeps the prompt-token growth bounded (≈window_n items ×
this cap) well within ``resummarize_max_tokens_per_tick``. Covered by a
dedicated truncation test.
"""


F5C_LOCK_NS = 0xF5C
"""Magic constant for the F5-C namespace of ``pg_try_advisory_xact_lock``.

Two-key form (``pg_try_advisory_xact_lock(:ns, hashtext(:tid))``) reduces
the chance of a false collision against other code paths that also use
``hashtext(topic_id)`` for advisory locking (Gotcha #5).
"""


def _classify_trigger(card: Any) -> str:
    """Classify why ``card`` qualified for re-summarize (Wave 2 observability).

    Mirrors the OR predicate in ``TopicCardRepo.list_resummarize_candidates``
    using the card data already in hand, so we never re-query:

    * ``"counter"`` — ``new_items_since_last_summary >= RESUMMARIZE_TRIGGER_N``.
    * ``"age"`` — counter not crossed, but the time-based
      ``RESUMMARIZE_MAX_AGE_DAYS`` branch matched (last_summarized_at older than
      the cutoff, with >= 1 new item, and the feature enabled).
    * ``"-"`` — neither predicate applies (e.g. a direct ``force_resummarize``
      that bypasses candidate selection).
    """
    new_items = card.new_items_since_last_summary
    if new_items >= settings.resummarize_trigger_n:
        return "counter"
    max_age_days = settings.resummarize_max_age_days
    if (
        max_age_days > 0
        and new_items > 0
        and card.last_summarized_at is not None
        and card.last_summarized_at < datetime.now(UTC) - timedelta(days=max_age_days)
    ):
        return "age"
    return "-"


class ResummarizationService:
    """Stateless service: short-lived, owns no engines.

    All persistence repositories share the same processing session
    (provided by ``resummarization_repos`` context manager) so the
    advisory lock taken on ``topic_card_repo.session`` covers the
    ``commit_resummary`` UPDATE on the same connection.
    """

    def __init__(
        self,
        *,
        topic_card_repo: TopicCardRepo,
        topic_bundle_repo: TopicBundleRepo,
        topic_card_version_repo: TopicCardVersionRepo,
        processed_document_repo: ProcessedDocumentRepo | None = None,
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        self.topic_card_repo = topic_card_repo
        self.topic_bundle_repo = topic_bundle_repo
        self.topic_card_version_repo = topic_card_version_repo
        # O-1 (F-02): source of window-document text/summary for the prompt.
        # Optional so standalone callers that only need the audit-trail repos
        # (or legacy tests) keep working — a missing repo yields empty content
        # rather than a crash.
        self.processed_document_repo = processed_document_repo
        self.prompt_loader = prompt_loader or get_prompt_loader()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_for_channel(
        self,
        channel_id: str,
        *,
        n_threshold: int | None = None,
        max_topics: int | None = None,
        max_duration_s: int | None = None,
        max_tokens_per_tick: int | None = None,
    ) -> dict[str, Any]:
        """Find candidates and re-summarize each, respecting all caps.

        Returns a summary dict with counters used by the scheduler-hook
        log line and downstream observability.
        """
        if not settings.resummarize_enabled:
            return {
                "candidates": 0,
                "resummarized": 0,
                "skipped": 0,
                "skipped_breakdown": {"disabled": 1},
                "tokens": 0,
            }

        n = n_threshold if n_threshold is not None else settings.resummarize_trigger_n
        cap_topics = max_topics if max_topics is not None else settings.resummarize_max_per_tick
        cap_duration = (
            max_duration_s if max_duration_s is not None else settings.resummarize_max_duration_s
        )
        cap_tokens = (
            max_tokens_per_tick
            if max_tokens_per_tick is not None
            else settings.resummarize_max_tokens_per_tick
        )

        candidates = await self.topic_card_repo.list_resummarize_candidates(
            channel_id=channel_id,
            threshold=n,
            max_age_days=settings.resummarize_max_age_days,
        )
        if not candidates:
            return {
                "candidates": 0,
                "resummarized": 0,
                "skipped": 0,
                "skipped_breakdown": {},
                "tokens": 0,
            }

        start_at = time.time()
        tokens_used = 0
        done = 0
        skipped: dict[str, int] = {}

        # O-9a (F-11): one LLM client per tick. Created only AFTER the
        # candidate check above so the disabled / no-candidate early returns
        # never pay for a handshake. Closed once in the finally below,
        # regardless of how the loop exits (cap break / billing raise / error).
        provider, api_key, model = resolve_llm_config("resummarize")
        client = create_llm_client(provider=provider, api_key=api_key, model=model)
        try:
            for card in candidates[:cap_topics]:
                elapsed = time.time() - start_at
                if elapsed >= cap_duration:
                    skipped["cap_duration"] = skipped.get("cap_duration", 0) + 1
                    logger.info(
                        "f5c_cap_duration_reached",
                        channel_id=channel_id,
                        elapsed=elapsed,
                    )
                    break
                if tokens_used >= cap_tokens:
                    skipped["cap_tokens"] = skipped.get("cap_tokens", 0) + 1
                    logger.info(
                        "f5c_cap_tokens_reached",
                        channel_id=channel_id,
                        tokens_used=tokens_used,
                    )
                    break
                try:
                    outcome = await self.resummarize_topic(card.id, llm=(client, provider, model))
                except AnthropicBillingError:
                    # Decision #13 + Gotcha #16: propagate so scheduler hook
                    # adds to stage_errors and _pause_source_for_billing fires.
                    # Without this re-raise, every tick would re-incur a billing
                    # error until manual intervention.
                    raise
                except Exception as exc:
                    logger.exception(
                        "f5c_resummarize_topic_failed",
                        topic_id=card.id,
                        channel_id=channel_id,
                        error=str(exc),
                    )
                    skipped["llm_error"] = skipped.get("llm_error", 0) + 1
                    continue

                status = outcome.get("status", "unknown")
                if status == "ok":
                    done += 1
                    tokens_used += int(outcome.get("tokens", 0))
                else:
                    skipped[status] = skipped.get(status, 0) + 1
        finally:
            with contextlib.suppress(Exception):
                # best-effort: an instrumented client's close() may raise.
                await client.close()

        return {
            "candidates": len(candidates),
            "resummarized": done,
            "skipped": sum(skipped.values()),
            "skipped_breakdown": skipped,
            "tokens": tokens_used,
        }

    async def resummarize_topic(
        self,
        topic_id: str,
        *,
        llm: tuple[LLMClient, str, str] | None = None,
    ) -> dict[str, Any]:
        """Re-summarize a single topic with full F5-C contract.

        Outcome status values:
          ``ok`` | ``locked`` | ``no_card`` | ``no_bundle`` |
          ``empty_scope`` | ``llm_error`` | ``version_raced``

        ``AnthropicBillingError`` is NOT caught here — it propagates so
        the scheduler hook can pause the source.

        O-9a (F-11): ``run_for_channel`` creates one LLM client per tick and
        passes it in as ``llm = (client, provider, model)`` so we don't
        re-handshake per topic. Standalone callers (MCP ``force_resummarize``,
        CLI) omit ``llm``; this method then resolves config + creates a client
        in-place and closes it in its own ``finally``. When a client is
        injected, its lifecycle is owned by the caller (closed once per tick).
        """
        # 1. Advisory lock (Gotcha #5: two-key form).  Taken on the
        # topic_card_repo session — same connection as commit_resummary's
        # UPDATE, so xact-lock auto-releases on the same commit.
        locked_row = await self.topic_card_repo.session.execute(
            sa_text("SELECT pg_try_advisory_xact_lock(:ns, hashtext(:tid))"),
            {"ns": F5C_LOCK_NS, "tid": topic_id},
        )
        if not locked_row.scalar():
            record_resummarize_outcome(topic_id=topic_id, status="locked", duration_s=0.0)
            return {"status": "locked"}

        card = await self.topic_card_repo.get_by_id(topic_id)
        if card is None:
            record_resummarize_outcome(topic_id=topic_id, status="no_card", duration_s=0.0)
            return {"status": "no_card"}

        # F5-C P2 / #15 item #10: primary source channel for the per-channel
        # re-summarize metric label. Once the card is loaded the channel is
        # known; the early paths above (locked / no_card) keep the "-" fallback.
        metric_channel = card.sources[0] if card.sources else "-"
        # Wave 2 observability: classify counter-vs-age selection from the
        # loaded card data. Early paths (locked / no_card / no_bundle) keep the
        # "-" fallback because the card is unavailable there.
        metric_trigger = _classify_trigger(card)

        # BUG-083 poison-pill guard: a topic whose resummarize was previously
        # refused by the LLM safety classifier (deterministic per model+content)
        # is quarantined for an escalating cooldown. Skip BEFORE the bundle fetch
        # + LLM call so we neither re-pay for the guaranteed-refusal call nor keep
        # skewing the ResummarizeLLMErrorRate tripwire every tick.
        if settings.resummarize_refusal_backoff_s > 0 and self._in_refusal_cooldown(card):
            record_resummarize_outcome(
                topic_id=topic_id,
                status="refusal_cooldown",
                channel_id=metric_channel,
                trigger=metric_trigger,
                duration_s=0.0,
            )
            return {
                "status": "refusal_cooldown",
                "cooldown_until": (card.metadata or {}).get("resummarize_refusal_until"),
            }

        bundle = await self.topic_bundle_repo.get_by_topic_id(topic_id)
        if bundle is None or not bundle.items:
            record_resummarize_outcome(topic_id=topic_id, status="no_bundle", duration_s=0.0)
            return {"status": "no_bundle"}

        # 2. Input window — Gotcha #6: top-N (anchors + highest-score
        # supports) NOT [-N:] which would give alphabetical tail items.
        window_n = settings.resummarize_input_window_n
        input_items = bundle.items[:window_n] if window_n > 0 else list(bundle.items)

        # O-1 (F-02): batch-fetch the window documents so each item carries the
        # actual material (summary + truncated text_clean). One query, not N+1.
        # A ref with no processed_documents row simply yields empty content.
        docs_by_ref: dict[str, Any] = {}
        if self.processed_document_repo is not None:
            window_refs = [it.source_ref for it in input_items]
            docs_by_ref = await self.processed_document_repo.get_by_source_refs(window_refs)

        items_payload = []
        for it in input_items:
            item: dict[str, Any] = {
                "source_ref": it.source_ref,
                "role": it.role.value,
                "score": it.score if it.score is not None else 0.0,
                "justification": it.justification or "",
            }
            doc = docs_by_ref.get(it.source_ref)
            if doc is not None:
                if doc.summary:
                    item["summary"] = doc.summary[:RESUMMARIZE_ITEM_TEXT_MAX_CHARS]
                text_clean = doc.text_clean or ""
                if text_clean:
                    item["text"] = text_clean[:RESUMMARIZE_ITEM_TEXT_MAX_CHARS]
            items_payload.append(item)
        items_json = json.dumps(items_payload, ensure_ascii=False, indent=2)

        # 3. Build LLM prompt.
        sys_prompt = self.prompt_loader.get_system_prompt("resummarize")
        user_template = self.prompt_loader.get_user_template("resummarize")
        prompt_meta = self.prompt_loader.get_metadata("resummarize")
        prompt_version = prompt_meta.get("version") if prompt_meta else None
        if not user_template:
            # Defense-in-depth: PromptLoader.load("resummarize") already
            # raises PromptLoaderError when both YAML and built-in default
            # are empty (post-TD-03c). We still guard the user_template path
            # here because that field is not part of REQUIRED_PROMPT_STAGES'
            # system-prompt invariant — a stage YAML could ship system.prompt
            # without user.template and still be "loaded successfully".
            logger.error("f5c_resummarize_template_missing", topic_id=topic_id)
            record_resummarize_outcome(
                topic_id=topic_id,
                status="llm_error",
                channel_id=metric_channel,
                trigger=metric_trigger,
                duration_s=0.0,
            )
            raise PromptLoaderError(
                f"resummarize stage has no user.template (topic_id={topic_id!r}); "
                "check prompts/resummarize.yaml or built-in default"
            )

        user_prompt = user_template.format(
            topic_id=card.id,
            topic_title=card.title,
            current_summary=card.summary,
            current_scope_in=", ".join(card.scope_in),
            current_scope_out=", ".join(card.scope_out),
            items_json=items_json,
        )

        # O-9a: use the per-tick client when injected; otherwise create one
        # in-place (standalone force_resummarize / CLI path) and own its close.
        if llm is not None:
            client, provider, model = llm
            owns_client = False
        else:
            provider, api_key, model = resolve_llm_config("resummarize")
            client = create_llm_client(provider=provider, api_key=api_key, model=model)
            owns_client = True
        model_settings = self.prompt_loader.get_model_settings("resummarize") or {}
        # Model settings are temperature/max_tokens/etc; pass through.
        t0 = time.perf_counter()
        try:
            resp = await client.generate_with_usage(
                user_prompt,
                system_prompt=sys_prompt,
                **model_settings,
            )
        except AnthropicBillingError:
            # Decision #13 / Gotcha #16: never reclassify as llm_error and
            # never record an outcome here — it must propagate untouched so
            # the scheduler hook pauses the source for billing.
            raise
        except Exception:
            # Any other LLM-call failure (e.g. the prod 404 from a retired
            # model) must still hit tg_resummarize_total{outcome="llm_error"}
            # so ResummarizeLLMErrorRate can see a full-failure outage. The
            # in-function parse / template-missing branches already record
            # llm_error; this is the previously-missing call-exception path.
            record_resummarize_outcome(
                topic_id=topic_id,
                status="llm_error",
                channel_id=metric_channel,
                trigger=metric_trigger,
                duration_s=time.perf_counter() - t0,
                model=f"{provider}/{model}",
            )
            raise
        finally:
            duration_s = time.perf_counter() - t0
            if owns_client:
                with contextlib.suppress(Exception):
                    # close() on an instrumented client may itself raise —
                    # best effort, we already have the response (or the
                    # exception we'll re-raise on the way out of the try
                    # block). An injected per-tick client is closed by
                    # run_for_channel instead.
                    await client.close()

        # 3b. Refusal handling (BUG-083). Anthropic returns HTTP 200 with an
        # empty content[] and stop_reason='refusal' when its safety classifier
        # declines (observed on legitimate medical topics, e.g. "ботулотоксин").
        # This is deterministic per (model, content), so retrying every tick just
        # burns a call and pins the LLM-error tripwire. Detect it explicitly,
        # optionally recover via a configured fallback stage, else quarantine the
        # topic with an escalating cooldown (distinct outcome, NOT llm_error).
        if getattr(resp, "stop_reason", None) == "refusal":
            fb = await self._try_refusal_fallback(
                sys_prompt=sys_prompt,
                user_prompt=user_prompt,
                model_settings=model_settings,
                refused_provider=provider,
            )
            if fb is not None:
                resp, provider, model = fb
                duration_s = time.perf_counter() - t0
            else:
                return await self._handle_refusal(
                    topic_id=topic_id,
                    card=card,
                    provider=provider,
                    model=model,
                    metric_channel=metric_channel,
                    metric_trigger=metric_trigger,
                    duration_s=duration_s,
                )

        # 4. Parse + validate.  Anthropic may return HTTP 200 with empty
        # content[] (refusal / stop without text) — treat like topicization's
        # JSON parse failure: record llm_error and return without raising.
        if not (resp.text or "").strip():
            logger.warning(
                "f5c_resummarize_empty_llm_response",
                topic_id=topic_id,
                provider=provider,
                model=model,
            )
            record_resummarize_outcome(
                topic_id=topic_id,
                status="llm_error",
                channel_id=metric_channel,
                trigger=metric_trigger,
                duration_s=duration_s,
                model=f"{provider}/{model}",
            )
            return {"status": "llm_error"}

        # Newer Sonnet models wrap their JSON output in a ```json markdown
        # fence; strip it the same way topicization does
        # (extract_json_from_response) before json.loads, otherwise a fenced
        # response fails at char 0 with "Expecting value: line 1 column 1".
        try:
            parsed = json.loads(extract_json_from_response(resp.text))
            new_summary = str(parsed["summary"]).strip()
            new_scope_in = [str(s).strip() for s in parsed.get("scope_in", []) if str(s).strip()]
            new_scope_out = [str(s).strip() for s in parsed.get("scope_out", []) if str(s).strip()]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "f5c_resummarize_parse_error",
                topic_id=topic_id,
                error=str(exc),
            )
            record_resummarize_outcome(
                topic_id=topic_id,
                status="llm_error",
                channel_id=metric_channel,
                trigger=metric_trigger,
                duration_s=duration_s,
                model=f"{provider}/{model}",
            )
            return {"status": "llm_error"}

        if not new_scope_in or not new_summary:
            record_resummarize_outcome(
                topic_id=topic_id,
                status="empty_scope",
                channel_id=metric_channel,
                trigger=metric_trigger,
                duration_s=duration_s,
                model=f"{provider}/{model}",
            )
            return {"status": "empty_scope"}
        if not new_scope_out:
            new_scope_out = list(card.scope_out)

        # 5. Append version snapshot of the *previous* state.  Done BEFORE
        # commit_resummary so that even if the optimistic check loses the
        # race we still preserve provenance (Real-bug #2 mitigation).
        snapshot = TopicCardVersion(
            id=1,  # placeholder — repo.insert assigns a real BIGSERIAL id
            topic_id=topic_id,
            version_no=card.summary_version,
            summary=card.summary,
            scope_in=list(card.scope_in),
            scope_out=list(card.scope_out),
            supporting_items_count_at_time=len(bundle.items),
            llm_provider=provider,
            llm_model=model,
            prompt_version=prompt_version,
            created_at=datetime.now(UTC),
        )
        try:
            await self.topic_card_version_repo.insert(snapshot)
        except Exception as exc:
            # UNIQUE(topic_id, version_no) collision is the second line of
            # defence (Gotcha #5): if it fires, another tick already wrote
            # this version — treat it as a race-loss.
            logger.warning(
                "f5c_version_snapshot_failed",
                topic_id=topic_id,
                version_no=card.summary_version,
                error=str(exc),
            )
            record_resummarize_outcome(
                topic_id=topic_id,
                status="version_raced",
                channel_id=metric_channel,
                trigger=metric_trigger,
                duration_s=duration_s,
                model=f"{provider}/{model}",
            )
            return {"status": "version_raced"}

        # 6. Atomic commit_resummary — single UPDATE + optimistic check.
        now = datetime.now(UTC)
        new_metadata = dict(card.metadata or {})
        # BUG-083: a successful (re)summary clears any prior refusal quarantine
        # so the topic returns to the normal cadence (incl. a fallback recovery).
        for _refusal_key in (
            "resummarize_refusal_until",
            "resummarize_refusal_count",
            "resummarize_refusal_at",
            "resummarize_refusal_llm",
        ):
            new_metadata.pop(_refusal_key, None)
        new_metadata.update(
            {
                "resummarize_run_at": now.isoformat(),
                "resummarize_version_no": card.summary_version + 1,
                "resummarize_llm": f"{provider}/{model}",
                "resummarize_prompt_version": prompt_version,
            }
        )
        applied = await self.topic_card_repo.commit_resummary(
            topic_id,
            summary=new_summary,
            scope_in=new_scope_in,
            scope_out=new_scope_out,
            prev_summary_version=card.summary_version,
            summarized_at=now,
            metadata_extras=new_metadata,
        )
        if not applied:
            logger.warning(
                "f5c_commit_resummary_raced",
                topic_id=topic_id,
                prev_v=card.summary_version,
            )
            record_resummarize_outcome(
                topic_id=topic_id,
                status="version_raced",
                channel_id=metric_channel,
                trigger=metric_trigger,
                duration_s=duration_s,
                model=f"{provider}/{model}",
            )
            return {"status": "version_raced"}

        new_version_no = card.summary_version + 1

        # 7. Best-effort re-embed (force=True).  Failure must not roll back
        # the committed summary — observability via warn log.
        try:
            primary_channel = card.sources[0] if card.sources else None
            if primary_channel:
                await run_topic_embedding(
                    channel_id=primary_channel,
                    topic_ids=[topic_id],
                    force=True,
                )
        except Exception as exc:
            logger.warning(
                "f5c_reembed_failed",
                topic_id=topic_id,
                error=str(exc),
            )

        # 8. Metrics on the happy path.
        input_tokens = int(getattr(resp, "input_tokens", 0) or 0)
        output_tokens = int(getattr(resp, "output_tokens", 0) or 0)
        record_resummarize_outcome(
            topic_id=topic_id,
            status="ok",
            channel_id=metric_channel,
            trigger=metric_trigger,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_s=duration_s,
            model=f"{provider}/{model}",
        )

        return {
            "status": "ok",
            "version_no": new_version_no,
            "tokens": input_tokens + output_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "duration_s": duration_s,
            "provider": provider,
            "model": model,
        }

    # ------------------------------------------------------------------
    # BUG-083 — refusal poison-pill guard helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _in_refusal_cooldown(card: Any) -> bool:
        """True if ``card`` is inside an active refusal cooldown window.

        Reads the ISO ``resummarize_refusal_until`` marker from the card
        metadata. A malformed / missing marker is treated as "not in cooldown"
        (fail-open → the topic is retried, which just re-arms the cooldown).
        """
        until_raw = (card.metadata or {}).get("resummarize_refusal_until")
        if not until_raw:
            return False
        try:
            until_dt = datetime.fromisoformat(until_raw)
        except (TypeError, ValueError):
            return False
        if until_dt.tzinfo is None:
            until_dt = until_dt.replace(tzinfo=UTC)
        return datetime.now(UTC) < until_dt

    async def _handle_refusal(
        self,
        *,
        topic_id: str,
        card: Any,
        provider: str,
        model: str,
        metric_channel: str,
        metric_trigger: str,
        duration_s: float,
    ) -> dict[str, Any]:
        """Quarantine a refused topic and record the ``refusal`` outcome.

        Persists an escalating cooldown (geometric in the consecutive-refusal
        count, capped at ``resummarize_refusal_backoff_max_s``) into the card
        metadata via a metadata-only UPDATE, then records
        ``tg_resummarize_total{outcome="refusal"}`` — deliberately NOT
        ``llm_error`` so the LLM-health tripwire is not skewed by a deterministic
        content-safety refusal.
        """
        prev_count = int((card.metadata or {}).get("resummarize_refusal_count", 0) or 0)
        count = prev_count + 1
        base = settings.resummarize_refusal_backoff_s
        until_iso: str | None = None
        if base > 0:
            backoff = min(
                base * (2 ** min(count - 1, 20)),
                settings.resummarize_refusal_backoff_max_s,
            )
            now = datetime.now(UTC)
            until_iso = (now + timedelta(seconds=backoff)).isoformat()
            new_metadata = dict(card.metadata or {})
            new_metadata.update(
                {
                    "resummarize_refusal_count": count,
                    "resummarize_refusal_until": until_iso,
                    "resummarize_refusal_at": now.isoformat(),
                    "resummarize_refusal_llm": f"{provider}/{model}",
                }
            )
            try:
                await self.topic_card_repo.set_resummarize_backoff(
                    topic_id, metadata=new_metadata, updated_at=now
                )
            except Exception as exc:  # persistence is best-effort; still record metric
                logger.warning(
                    "f5c_resummarize_backoff_persist_failed",
                    topic_id=topic_id,
                    error=str(exc),
                )

        logger.warning(
            "f5c_resummarize_refusal",
            topic_id=topic_id,
            provider=provider,
            model=model,
            refusal_count=count,
            cooldown_until=until_iso,
        )
        record_resummarize_outcome(
            topic_id=topic_id,
            status="refusal",
            channel_id=metric_channel,
            trigger=metric_trigger,
            duration_s=duration_s,
            model=f"{provider}/{model}",
        )
        return {"status": "refusal", "refusal_count": count, "cooldown_until": until_iso}

    async def _try_refusal_fallback(
        self,
        *,
        sys_prompt: str | None,
        user_prompt: str,
        model_settings: dict[str, Any],
        refused_provider: str,
    ) -> tuple[Any, str, str] | None:
        """Retry a refused resummarize once via the configured fallback stage.

        Returns ``(resp, provider, model)`` on a usable (non-refusal, non-empty)
        fallback response, else ``None``. Disabled unless
        ``resummarize_refusal_fallback_stage`` is set, and skipped when the
        fallback resolves to the same provider as the refused call (a same-family
        model would just refuse again). All failures are contained (return None)
        so a broken fallback config never breaks the tick.
        """
        stage = (settings.resummarize_refusal_fallback_stage or "").strip()
        if not stage:
            return None
        try:
            fb_provider, fb_key, fb_model = resolve_llm_config(stage)
        except Exception as exc:
            logger.warning("f5c_resummarize_fallback_resolve_failed", stage=stage, error=str(exc))
            return None
        if not fb_provider or fb_provider == refused_provider:
            return None

        client = None
        try:
            client = create_llm_client(provider=fb_provider, api_key=fb_key, model=fb_model)
            resp = await client.generate_with_usage(
                user_prompt, system_prompt=sys_prompt, **model_settings
            )
        except Exception as exc:
            logger.warning("f5c_resummarize_fallback_failed", stage=stage, error=str(exc))
            return None
        finally:
            if client is not None:
                with contextlib.suppress(Exception):
                    await client.close()

        if getattr(resp, "stop_reason", None) == "refusal" or not (resp.text or "").strip():
            return None
        logger.info(
            "f5c_resummarize_fallback_ok",
            stage=stage,
            provider=fb_provider,
            model=fb_model or "",
        )
        return resp, fb_provider, fb_model or ""

    async def aclose(self) -> None:
        """No-op: LLM clients are closed where they are created.

        Post-O-9a the per-tick client is created and closed inside
        ``run_for_channel`` (one client per tick), while the standalone
        ``resummarize_topic`` path creates and closes its own client in a
        ``finally``. This service owns no long-lived engines. The method is
        kept so callers (scheduler hook, MCP tool, CLI) can use a uniform
        ``try/finally: await service.aclose()`` pattern.
        """
        return None
