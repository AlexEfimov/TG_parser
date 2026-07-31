#!/usr/bin/env python3
"""Mutation verification for #359 / ADR-0020 (deterministic confirm trigger).

Applies each mutation from the plan's §3.9 table one at a time, runs the
bot-adapter blast radius, and reports which tests died. A mutation that kills
nothing means the corresponding pin does not exist; a mutation that kills more
than its row claims means the pin is coarser than documented.

Usage: TEST_POSTGRES=1 .venv/bin/python scripts/mutation_verify_359.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HANDLERS = ROOT / "tg_parser" / "bot" / "handlers.py"
AGENT = ROOT / "tg_parser" / "bot" / "agent.py"

# Every test module that imports the bot adapter (rg -l 'bot\.handlers|bot\.agent|bot import|bot\.tools').
BLAST_RADIUS = [
    "tests/test_bot_admin_confirm_flow.py",
    "tests/test_bot_agent.py",
    "tests/test_bot_agent_resolved_model.py",
    "tests/test_bot_channel_name_parser.py",
    "tests/test_bot_chat_target_resolution.py",
    "tests/test_bot_clarify_concurrency_bug051.py",
    "tests/test_bot_confirm_flow.py",
    "tests/test_bot_conversation_layer_bug039_042.py",
    "tests/test_bot_delete_candidate_slicing_bug049.py",
    "tests/test_bot_delete_routing_bug047.py",
    "tests/test_bot_execute_tool_guard.py",
    "tests/test_bot_fsm.py",
    "tests/test_bot_intent_break_bug048.py",
    "tests/test_bot_pagination_channel_token_bug052.py",
    "tests/test_bot_read_clarify_short_prefix_bug053.py",
    "tests/test_bot_read_context.py",
    "tests/test_bot_subscribe_channel_resume_bug050.py",
    "tests/test_bot_subscribe_watchlist_intent_parity.py",
    "tests/test_bot_tools_bug010_username_alias.py",
    "tests/test_bot_tools_session_f.py",
    "tests/test_bot_tools_v11.py",
    "tests/test_bot_tools_v12.py",
    "tests/test_bot_unsubscribe_confirm_gate_g1.py",
    "tests/test_bot_write_intent_trigger_359.py",
    "tests/test_cron_humanize.py",
    "tests/test_digest_scheduler_initial_load_retry.py",
    "tests/test_f11_bot_tools.py",
    "tests/test_f2_parse_only_export.py",
    "tests/test_f4_coverage_supplement.py",
    "tests/test_f4_ownership.py",
    "tests/test_f4_scoped_access.py",
    "tests/test_f4_user_management.py",
    "tests/test_f4b_deferred_surface_guard.py",
    "tests/test_f5c_bot_force_resummarize.py",
    "tests/test_f5c_bot_topic_history.py",
    "tests/test_f6_scheduled_digests.py",
    "tests/test_f9_phase3_audit_log.py",
    "tests/test_ingestion_state_repo_username_alias.py",
    "tests/test_mcp_pagination_contract.py",
    "tests/test_pagination_contract_tdd.py",
    "tests/test_rag_prompt_config.py",
    "tests/test_scheduler_invalidation_on_unsubscribe.py",
]


@dataclass
class Mutation:
    """One row of the §3.9 table."""

    name: str
    expected: str
    edits: list[tuple[Path, str, str]] = field(default_factory=list)


MUTATIONS: list[Mutation] = [
    Mutation(
        name="drop the router call from handle_text",
        expected="resume tests only",
        edits=[
            (
                HANDLERS,
                "    if await _handle_write_intent_router(message, state, write_intent, current_user):\n        return\n",
                "",
            )
        ],
    ),
    Mutation(
        name="pop inside the router instead of at the top (peek, TTL kept)",
        expected="TestWriteIntentSurvivesNoTurn only",
        edits=[
            (
                HANDLERS,
                "    write_intent = await _take_write_intent(state, chat_id=message.chat.id)\n",
                "    _wi_peek = (await state.get_data()).get('pending_write_intent')\n"
                "    write_intent = (\n"
                "        _wi_peek\n"
                "        if isinstance(_wi_peek, dict)\n"
                "        and not _is_stale(_wi_peek.get('created_at'), PENDING_TTL_SECONDS)\n"
                "        else None\n"
                "    )\n",
            )
        ],
    ),
    Mutation(
        name="set-site as an independent `if` instead of a branch of the chain",
        expected="pagination+snapshot case in ...SurvivesNoTurn only",
        edits=[
            (
                HANDLERS,
                "    elif result.write_intent_pending or _detect_subscribe_tool(user_text):",
                "    if result.write_intent_pending or _detect_subscribe_tool(user_text):",
            )
        ],
    ),
    Mutation(
        name="tier-1 gate replaced by the full ConfirmFlow classifier",
        expected="TestCompoundAffirmativeIsNotATrigger only",
        edits=[
            (
                HANDLERS,
                "    verdict = _classify_bare_confirmation_token(text)",
                "    verdict = classify_confirmation_token(text)",
            )
        ],
    ),
    Mutation(
        name="fail-open TTL helper (_is_pending_expired instead of _is_stale)",
        expected="the missing/broken created_at TTL test only",
        edits=[
            (
                HANDLERS,
                '    if _is_stale(wi.get("created_at"), PENDING_TTL_SECONDS):',
                '    if _is_pending_expired(wi.get("created_at")):',
            )
        ],
    ),
    Mutation(
        name="do not pass current_user to execute_tool on resume",
        expected="TestWriteIntentResumeRechecksAuthorization only",
        edits=[
            (
                HANDLERS,
                "        result = await execute_tool(\n"
                "            tool_name,\n"
                "            dict(args),\n"
                "            current_user=current_user,",
                "        result = await execute_tool(\n"
                "            tool_name,\n"
                "            dict(args),\n"
                "            current_user=None,",
            )
        ],
    ),
    Mutation(
        name="drop the adjacency-drop (re-persist on an unrelated turn)",
        expected="the «unrelated then да» test only",
        edits=[
            (
                HANDLERS,
                '            reason="unrelated",\n'
                "            chat_id=message.chat.id,\n"
                "        )\n"
                "        return False",
                '            reason="unrelated",\n'
                "            chat_id=message.chat.id,\n"
                "        )\n"
                "        await state.update_data(pending_write_intent=snapshot)\n"
                "        return False",
            )
        ],
    ),
    Mutation(
        name="put confirm=True back into the re-issued args",
        expected="the BUG-009 invariant in ...IsToolAgnostic only",
        edits=[
            (
                HANDLERS,
                "        result = await execute_tool(\n            tool_name,\n            dict(args),",
                '        result = await execute_tool(\n            tool_name,\n            dict(args) | {"confirm": True},',
            )
        ],
    ),
    Mutation(
        name="stop stripping the report-only (dry_run) flag from the snapshot",
        expected="the dry-run resume test only",
        edits=[
            (
                AGENT,
                '            if k != "confirm" and k not in _PREVIEW_SUPPRESSING_ARGS',
                '            if k != "confirm"',
            )
        ],
    ),
    Mutation(
        name="drop the snapshot when the agent runs out of turns",
        expected="TestPreviewLessWriteCallIsSnapshotted"
        "::test_turn_limit_exhaustion_still_hands_over_the_snapshot only",
        edits=[
            (
                AGENT,
                """            read_tools_called=read_tools_called,
            write_intent_pending=_write_intent_or_none(preview_pending, unpreviewed_write_calls),
        )

    async def _call_gemini(""",
                """            read_tools_called=read_tools_called,
        )

    async def _call_gemini(""",
            )
        ],
    ),
    Mutation(
        name="log the args wholesale instead of their keys",
        expected="TestWriteIntentLogPrivacy only",
        edits=[
            (
                HANDLERS,
                '                arg_keys=sorted(result.write_intent_pending.get("args") or {}),',
                '                arg_keys=sorted(result.write_intent_pending.get("args") or {}),\n'
                '                args=result.write_intent_pending.get("args") or {},',
            )
        ],
    ),
    Mutation(
        name="remove the fsm_confirm_declined log",
        expected="TestCancelPathIsObservable only",
        edits=[
            (
                HANDLERS,
                "        logger.info(\n"
                '            "fsm_confirm_declined",\n'
                '            tool=pending_action.get("tool_name"),\n'
                "            chat_id=message.chat.id,\n"
                "        )\n",
                "",
            )
        ],
    ),
    Mutation(
        name="stop stripping trailing punctuation (a bare «да.» becomes unrelated)",
        expected="TestCompoundAffirmativeIsNotATrigger"
        "::test_trailing_punctuation_does_not_make_a_token_unrelated only",
        edits=[
            (
                HANDLERS,
                '    normalized = " ".join(text.split()).casefold().rstrip(",.;:!?").strip()',
                '    normalized = " ".join(text.split()).casefold()',
            )
        ],
    ),
    Mutation(
        name="resume arms ConfirmFlow without clearing a coexisting subscribe_intent",
        expected="TestWriteIntentAndConfirmFlowAreMutuallyExclusive"
        "::test_resume_clears_a_coexisting_subscribe_intent only",
        edits=[
            (
                HANDLERS,
                "    await _clear_subscribe_intent(state)\n"
                "    await state.set_state(ConfirmFlow.awaiting_confirmation)\n"
                "    await state.update_data(\n"
                '        pending_action={"tool_name": tool_name, "args": args},',
                "    await state.set_state(ConfirmFlow.awaiting_confirmation)\n"
                "    await state.update_data(\n"
                '        pending_action={"tool_name": tool_name, "args": args},',
            )
        ],
    ),
    Mutation(
        name="resume of an unsubscribe_* does not record last_subscription",
        expected="TestWriteIntentAndConfirmFlowAreMutuallyExclusive"
        "::test_resume_of_an_unsubscribe_records_last_subscription only",
        edits=[
            (
                HANDLERS,
                '    _ls = _last_subscription_from_preview({"tool_name": tool_name, "args": args})\n'
                "    if _ls is not None:\n"
                "        await state.update_data(last_subscription=_ls)\n",
                "",
            )
        ],
    ),
    Mutation(
        name="pop the snapshot BELOW the blank-text guard",
        expected="TestWriteIntentSurvivesNoTurn::test_whitespace_only_message_drops_it only",
        edits=[
            (
                HANDLERS,
                "    write_intent = await _take_write_intent(state, chat_id=message.chat.id)\n"
                "    if not user_text or not user_text.strip():\n"
                "        return\n",
                "    if not user_text or not user_text.strip():\n"
                "        return\n"
                "    write_intent = await _take_write_intent(state, chat_id=message.chat.id)\n",
            )
        ],
    ),
    Mutation(
        name="bring the prose detector back ALONGSIDE the router (phased rollout)",
        expected="TestFinalTextNeverArmsConfirmFlow (guards against a hybrid)",
        edits=[
            (
                HANDLERS,
                "        if result.write_intent_pending:\n"
                "            # #359: a confirm-gated write tool ran and armed no preview, so the",
                '        if result.write_intent_pending and "[да/нет]" in (result.response_text or ""):\n'
                "            await state.set_state(ConfirmFlow.awaiting_confirmation)\n"
                "            await state.update_data(\n"
                "                pending_action={\n"
                '                    "tool_name": result.write_intent_pending["tool_name"],\n'
                '                    "args": result.write_intent_pending.get("args") or {},\n'
                "                },\n"
                "                created_at=_utcnow_iso(),\n"
                "            )\n"
                "        if result.write_intent_pending:\n"
                "            # #359: a confirm-gated write tool ran and armed no preview, so the",
            )
        ],
    ),
]

_FAILED_RE = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.MULTILINE)


def run_suite() -> set[str]:
    proc = subprocess.run(
        [".venv/bin/python", "-m", "pytest", "-q", "-p", "no:randomly", *BLAST_RADIUS],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return {m.group(1) for m in _FAILED_RE.finditer(proc.stdout)}


def main() -> int:
    backups = {p: p.read_text() for p in (HANDLERS, AGENT)}
    selected = MUTATIONS
    if len(sys.argv) > 1:
        wanted = {int(a) for a in sys.argv[1:]}
        selected = [m for i, m in enumerate(MUTATIONS, start=1) if i in wanted]

    print("=== baseline ===", flush=True)
    baseline = run_suite()
    if baseline:
        print(f"BASELINE IS NOT GREEN ({len(baseline)} failures) — aborting")
        for node in sorted(baseline):
            print(f"  {node}")
        return 1
    print("baseline green", flush=True)

    verdicts: list[tuple[str, str, set[str]]] = []
    try:
        for mut in selected:
            for path, old, new in mut.edits:
                text = path.read_text()
                if text.count(old) != 1:
                    print(f"!! anchor not unique ({text.count(old)}x) for: {mut.name}")
                    return 1
                path.write_text(text.replace(old, new))
            killed = run_suite()
            verdicts.append((mut.name, mut.expected, killed))
            print(
                f"\n--- {mut.name}\n    expected: {mut.expected}\n    killed {len(killed)}:",
                flush=True,
            )
            for node in sorted(killed):
                print(f"      {node}", flush=True)
            for path, original in backups.items():
                path.write_text(original)
    finally:
        for path, original in backups.items():
            path.write_text(original)

    print("\n\n=== summary ===")
    survived = [name for name, _, killed in verdicts if not killed]
    for name, expected, killed in verdicts:
        mark = "SURVIVED" if not killed else f"killed {len(killed)}"
        print(f"[{mark:>10}] {name}  (expected: {expected})")
    if survived:
        print(f"\n{len(survived)} mutation(s) SURVIVED — those pins are missing.")
        return 1
    print(f"\nall {len(verdicts)} mutations killed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
