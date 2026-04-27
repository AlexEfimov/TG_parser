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
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import text as sa_text

from tg_parser.api.metrics import record_resummarize_outcome
from tg_parser.config import settings
from tg_parser.domain.models import TopicCardVersion
from tg_parser.processing.llm.errors import AnthropicBillingError
from tg_parser.processing.llm.factory import create_llm_client, resolve_llm_config
from tg_parser.processing.prompt_loader import (
    PromptLoader,
    PromptLoaderError,
    get_prompt_loader,
)
from tg_parser.services.embedding_service import run_topic_embedding

if TYPE_CHECKING:
    from tg_parser.storage.ports import (
        TopicBundleRepo,
        TopicCardRepo,
        TopicCardVersionRepo,
    )

logger = structlog.get_logger(__name__)


F5C_LOCK_NS = 0xF5C
"""Magic constant for the F5-C namespace of ``pg_try_advisory_xact_lock``.

Two-key form (``pg_try_advisory_xact_lock(:ns, hashtext(:tid))``) reduces
the chance of a false collision against other code paths that also use
``hashtext(topic_id)`` for advisory locking (Gotcha #5).
"""


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
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        self.topic_card_repo = topic_card_repo
        self.topic_bundle_repo = topic_bundle_repo
        self.topic_card_version_repo = topic_card_version_repo
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
            channel_id=channel_id, threshold=n
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
                outcome = await self.resummarize_topic(card.id)
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

        return {
            "candidates": len(candidates),
            "resummarized": done,
            "skipped": sum(skipped.values()),
            "skipped_breakdown": skipped,
            "tokens": tokens_used,
        }

    async def resummarize_topic(self, topic_id: str) -> dict[str, Any]:
        """Re-summarize a single topic with full F5-C contract.

        Outcome status values:
          ``ok`` | ``locked`` | ``no_card`` | ``no_bundle`` |
          ``empty_scope`` | ``llm_error`` | ``version_raced``

        ``AnthropicBillingError`` is NOT caught here — it propagates so
        the scheduler hook can pause the source.
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

        bundle = await self.topic_bundle_repo.get_by_topic_id(topic_id)
        if bundle is None or not bundle.items:
            record_resummarize_outcome(topic_id=topic_id, status="no_bundle", duration_s=0.0)
            return {"status": "no_bundle"}

        # 2. Input window — Gotcha #6: top-N (anchors + highest-score
        # supports) NOT [-N:] which would give alphabetical tail items.
        window_n = settings.resummarize_input_window_n
        input_items = bundle.items[:window_n] if window_n > 0 else list(bundle.items)
        items_payload = [
            {
                "source_ref": it.source_ref,
                "role": it.role.value,
                "score": it.score if it.score is not None else 0.0,
                "justification": it.justification or "",
            }
            for it in input_items
        ]
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
            record_resummarize_outcome(topic_id=topic_id, status="llm_error", duration_s=0.0)
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

        provider, api_key, model = resolve_llm_config("resummarize")
        client = create_llm_client(provider=provider, api_key=api_key, model=model)
        model_settings = self.prompt_loader.get_model_settings("resummarize") or {}
        # Model settings are temperature/max_tokens/etc; pass through.
        t0 = time.perf_counter()
        try:
            resp = await client.generate_with_usage(
                user_prompt,
                system_prompt=sys_prompt,
                **model_settings,
            )
        finally:
            duration_s = time.perf_counter() - t0
            with contextlib.suppress(Exception):
                # close() on an instrumented client may itself raise — best
                # effort, we already have the response (or the exception
                # we'll re-raise on the way out of the try block).
                await client.close()

        # 4. Parse + validate.
        try:
            parsed = json.loads(resp.text.strip())
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
                duration_s=duration_s,
                model=f"{provider}/{model}",
            )
            return {"status": "llm_error"}

        if not new_scope_in or not new_summary:
            record_resummarize_outcome(
                topic_id=topic_id,
                status="empty_scope",
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
                duration_s=duration_s,
                model=f"{provider}/{model}",
            )
            return {"status": "version_raced"}

        # 6. Atomic commit_resummary — single UPDATE + optimistic check.
        now = datetime.now(UTC)
        new_metadata = dict(card.metadata or {})
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

    async def aclose(self) -> None:
        """No-op: clients are short-lived and closed inside resummarize_topic.

        Provided so callers (scheduler hook, MCP tool) can use a uniform
        ``try/finally: await service.aclose()`` pattern.
        """
        return None
