"""FSM state groups for the Telegram bot's two-turn conversation flows.

Two flows live here:

* :class:`ConfirmFlow` — pending write-tool preview awaiting a yes/no reply.
  Closes BUG-002: handler executes the previewed tool deterministically with
  ``confirm=True``; the LLM is **not** consulted again, so it cannot
  hallucinate a different ``tool_name`` / ``args`` / ``channel_id`` on a
  bare "да".

* :class:`PaginationFlow` — list-tool result has more pages; user can ask
  "ещё / next" or "стоп / cancel". Closes BUG-004: ``offset`` is bumped by
  the handler from FSM-stored ``args`` (in particular ``channel_id``), so
  the second page can never collapse into "all topics across the KB".

:class:`ReadContextData` — NOT a state group; a plain TypedDict stored as
an FSM data field (BUG-011, Session H). Tracks the most-recent channel the
user was reading from across turns. Coexists with active ConfirmFlow /
PaginationFlow states; TTL-governed (15 min default).

Storage backend is configured in :func:`tg_parser.bot.main.run_bot`
(MemoryStorage by default per BUG_LOG § Session planning D-4 — single
replica deployment; switch to RedisStorage when scaling out).
"""

from __future__ import annotations

from typing import TypedDict

from aiogram.fsm.state import State, StatesGroup


class ConfirmFlow(StatesGroup):
    """User just received a write-tool preview, expects yes/no on next turn."""

    awaiting_confirmation = State()


class PaginationFlow(StatesGroup):
    """Last list-tool returned ``has_more=True``; user may say ``ещё`` / ``next``."""

    has_active_list = State()


class ClarifyFlow(StatesGroup):
    """User just received a channel-name clarification, expects a correction.

    Closes BUG-039 / BUG-040: when ``validate_channel_username`` rejects a
    space-bearing / typo'd channel name and surfaces a ``suggestion``, the
    subscribe flow stashes the in-flight tool call here instead of dropping
    the clarification on the floor. The next turn is handled
    **deterministically** by ``handlers._handle_clarification_response``:

    * an affirmative token («да», «ok», ...) re-runs the previewed
      ``subscribe_*`` with the suggested channel id;
    * a bare channel-name reply («profendocrinologist») is interpreted
      **within the in-flight subscribe flow** (NOT re-classified through the
      stateless LLM, which is what mis-routed it to ``update_channel`` /
      ``list_topics`` pre-fix — BUG-040);
    * a negative token cancels.

    The LLM is never consulted on this turn, so a single channel-name typo is
    recoverable in-flow rather than dead-ending on the opaque
    «Я не совсем понимаю ваш ответ» fallback (BUG-039).

    2026-05-31 residual: the same FSM is reused for the READ surface
    (``kind == "read"`` in ``clarify_action``) — the channel-not-found fuzzy
    suggestion emitted by ``tools._build_no_results_suggestion`` for
    ``list_topics`` / ``search`` / ``get_cross_channel_stats``. There the
    affirmative re-runs the ORIGINAL read intent with the suggested channel
    (rendered deterministically), closing the same dead-end on the read side.
    """

    awaiting_channel_clarification = State()


class ReadContextData(TypedDict):
    """Shadow read-context preserved across read-tool turns (BUG-011, Session H).

    Stored as ``FSMContext.update_data(read_context=...)`` — NOT a state.
    Coexists with active ``ConfirmFlow.awaiting_confirmation`` /
    ``PaginationFlow.has_active_list`` states; persists across ``state.clear()``
    via explicit re-write in the handler.

    See ``handlers._refresh_read_context`` for update sites and
    ``handlers._read_context_for_agent`` for the resolution path.
    """

    last_channel_id: str
    last_tool: str
    created_at: str  # ISO UTC timestamp, used for TTL check


class LastSubscriptionData(TypedDict):
    """Shadow context tracking the most-recently-referenced subscription
    (BUG-047). Sibling of :class:`ReadContextData` — stored as an FSM data
    field (``FSMContext.update_data(last_subscription=...)``), NOT a state.

    Written whenever a subscription is CREATED (the affirmative confirm of a
    ``subscribe_*``) or SHOWN in an ``unsubscribe_*`` preview, so the
    deterministic delete pre-router (``handlers._handle_delete_prerouter``) can
    resolve an anaphoric «удали эту подписку» / «удали последнюю» without
    consulting the LLM. TTL-governed by ``READ_CONTEXT_TTL_SECONDS`` (15 min)
    and preserved across ``state.clear()`` via the same snapshot-and-restore
    pattern used for ``read_context``.

    ``kind`` discriminates the two subscription surfaces so the pre-router can
    pick the right unsubscribe tool / id parameter:

    * ``"digest"`` → ``unsubscribe_digest`` / ``subscription_id``;
    * ``"watchlist"`` → ``unsubscribe_watchlist`` / ``interest_id``.
    """

    id: str
    kind: str  # "digest" | "watchlist"
    name: str
    created_at: str  # ISO UTC timestamp, used for TTL check


class DeleteIntentData(TypedDict, total=False):
    """Shadow context recording an EXPLICIT delete intent (BUG-048, D2).

    Sibling of :class:`ReadContextData` / :class:`LastSubscriptionData` —
    stored as an FSM data field (``FSMContext.update_data(delete_intent=...)``),
    NOT a state. Written by ``handlers._handle_delete_prerouter`` the moment the
    user explicitly asks to delete / unsubscribe something (a leading delete
    verb or a delete anaphora), and refreshed whenever a deterministic delete
    flow is (re-)armed.

    It exists so that a delete intent SURVIVES an intervening FSM clear: after a
    ``delete_suggest`` FSM is correctly cleared on a zero-match junk reply
    (BUG-047 D1), a subsequent BARE subscription name (no delete verb, no
    anaphora) must still route to a DELETE — not fall to the stateless agent and
    get misrouted to ``subscribe_digest`` (create). The deterministic
    ``handlers._handle_delete_intent_router`` consults this snapshot before the
    agent and re-resolves the bare name owner-scoped.

    TTL-governed by ``READ_CONTEXT_TTL_SECONDS`` (15 min) and preserved across
    ``state.clear()`` via the same snapshot-and-restore pattern as
    ``read_context`` / ``last_subscription`` — EXCEPT the terminal-clear cases
    (successful unsubscribe, «нет» cancel on a delete clarify / unsubscribe
    confirm reject, explicit new-intent escape, TTL expiry) which drop it.

    ``requested`` (optional) is the original free-text the delete verb was
    stripped from — retained only for logging / diagnostics.
    """

    created_at: str  # ISO UTC timestamp, used for TTL check
    requested: str


class SubscribeIntentData(TypedDict, total=False):
    """Shadow context recording an EXPLICIT subscribe-create intent (BUG-050).

    Sibling of :class:`DeleteIntentData` — stored as an FSM data field
    (``FSMContext.update_data(subscribe_intent=...)``), NOT a state. Written by
    the POST-agent detector in ``handlers.handle_text`` the moment a turn that
    matched a subscribe-create request (``_detect_subscribe_create_intent``)
    returns TEXT-ONLY (no ``clarify_pending`` / ``preview_pending`` /
    ``pagination_pending`` — i.e. the LLM answered «канал X не найден…»
    conversationally instead of calling ``subscribe_digest`` and arming the
    deterministic G2 clarify).

    It exists so that the user's follow-up BARE channel name («genotek») RESUMES
    the subscribe rather than being processed statelessly and misrouted to
    ``list_topics``. The deterministic ``handlers._handle_subscribe_intent_router``
    consults this snapshot before the agent: it merges the bare token as the
    channel into the (partial) subscribe args, re-runs ``subscribe_digest``
    (confirm=false) and arms the existing ClarifyFlow / ConfirmFlow gate — the
    SUBSCRIBE-surface analogue of BUG-048's ``delete_intent`` router.

    TTL-governed by ``READ_CONTEXT_TTL_SECONDS`` (15 min) and preserved across
    ``state.clear()`` via the same snapshot-and-restore pattern as
    ``read_context`` / ``last_subscription`` / ``delete_intent`` — EXCEPT the
    terminal-clear cases (ClarifyFlow / ConfirmFlow armed, a successful subscribe
    confirm, «нет» on a subscribe clarify, an explicit new-intent escape, TTL
    expiry) which drop it.

    ``requested_channel`` (optional) is the bad/typo token from turn 1 (retained
    for logging / diagnostics). ``tool_name`` (optional, default digest at
    resume time) discriminates ``subscribe_digest`` vs ``subscribe_watchlist``.
    ``partial_args`` (optional) carries the cheaply parsed ``name`` / ``title`` /
    ``cron_expression`` / ``timezone`` / ``format`` so the resume re-run can
    pre-fill them; the executor + G2 / preview backfill the rest.
    """

    created_at: str  # ISO UTC timestamp, used for TTL check
    tool_name: str
    requested_channel: str
    partial_args: dict


class PendingWriteIntentData(TypedDict, total=False):
    """A confirm-gated write call that produced NO preview (#359, ADR-0020).

    Sibling of :class:`SubscribeIntentData` — stored as an FSM data field
    (``FSMContext.update_data(pending_write_intent=...)``), NOT a state. Written
    at the end of ``handlers.handle_text`` when the agent reports that a tool in
    ``_WRITE_TOOLS_REQUIRING_CONFIRM`` ran while nothing armed ``ConfirmFlow``
    (a ``dry_run`` report, a BUG-009 rejection, an executor error) — a state in
    which the user's «да» would otherwise dead-end (BUG-086).

    ``handlers._handle_write_intent_router`` consults it on the NEXT message: a
    bare affirmative token re-issues ``tool_name`` with ``args`` to obtain the
    real preview and arms ``ConfirmFlow``; a bare negative cancels. The actual
    mutation still requires a SECOND «да» on top of that preview, so the
    BUG-009 / BUG-046 two-step gate is preserved.

    Two lifetime rules, both load-bearing and DIFFERENT from
    ``delete_intent`` / ``subscribe_intent``:

    * TTL is ``PENDING_TTL_SECONDS`` (5 min, the ConfirmFlow window) rather than
      15 min — this is a *pre*-confirmation, so it expires with confirmations;
    * it is strictly ADJACENT: ``handle_text`` POPS it on entry, so it cannot
      survive a single message down any path. The delete / subscribe intents
      deliberately survive intervening turns because their trigger is a specific
      NAME; this one's trigger is a general «да», and a «да» three turns later
      about something else must never arm a mutation preview.

    ``args`` are already sanitized at creation (``confirm`` and every
    ``agent._PREVIEW_SUPPRESSING_ARGS`` flag stripped), so the mutating shape
    cannot be reconstructed from storage. No identity / role is stored —
    authorization is re-checked by the executor on the resume turn.
    """

    created_at: str  # ISO UTC timestamp, used for TTL check
    tool_name: str
    args: dict
