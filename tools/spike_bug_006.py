"""Research spike for BUG-006 — bot Gemini-flash empty `parts=[]` issue.

This script runs reproducible Q1-Q5 queries against the live Gemini API
under different fix-option configurations and records:

* HTTP status / payload validity
* `finishReason` (key signal for HG-2 / HG-3)
* `usageMetadata.thoughtsTokenCount` (HG-2 confirmation signal)
* whether `candidates[].content.parts` is non-empty (BUG-006 inversion)
* response latency

Options tested:

* ``current`` — baseline reproduction (`maxOutputTokens=4096`, no
  `thinkingConfig`). Should reproduce the bug for Q1/Q2.
* ``a`` — Option A from START_PROMPT: bump `maxOutputTokens` 4096→8192.
* ``a-thinking-0`` — Option A + `thinkingBudget=0` (BUG_LOG hotfix).
* ``thinking-0`` — `thinkingBudget=0` alone (isolate thinking signal).
* ``b`` — Option B (split TOOL_DECLARATIONS via simple intent heuristic).
* ``c-pro`` — Option C-Gemini: switch to ``gemini-2.5-pro``.
* ``c-flash-2-0`` — Option C-Gemini: switch to ``gemini-2.0-flash``.
* ``all`` — run the full matrix sequentially (default).

Outputs a summary table per option with per-query success rates +
per-finishReason histogram, plus a JSON-Lines log of every individual
request to ``--out-dir`` (default ``/tmp/bug-006-spike/``).

Usage::

    .venv/bin/python tools/spike_bug_006.py --option all --runs 2

Set ``GEMINI_API_KEY`` in environment or rely on ``.env`` autoload.

Cost note (gemini-2.5-flash @ 2026-04 prices, ~12k prompt + ~1k output
tokens per call): ``--runs 2`` × 5 queries × 7 options ≈ 70 calls ≈
~$0.05-0.15.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tg_parser.bot.tools import TOOL_DECLARATIONS  # noqa: E402

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

QUERIES: dict[str, str] = {
    "Q1": "Покажи LLM конфиг",
    "Q2": "выведи текущий llm config",
    "Q3": "Что говорится по теме сна в каналах Lab4health, LongevityClub, biohacker_age?",
    "Q4_control": "перечисли темы канала Lab4health",
    "Q5_control": "покажи список каналов",
}


def _load_env() -> None:
    """Load ``.env`` from project root if available (no python-dotenv dep)."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _load_system_prompt() -> str:
    """Lightweight YAML-free read of ``prompts/bot.yaml`` ``system.prompt``."""
    bot_yaml = PROJECT_ROOT / "prompts" / "bot.yaml"
    text = bot_yaml.read_text(encoding="utf-8")
    marker = "  prompt: |"
    idx = text.find(marker)
    if idx == -1:
        return "You are a Telegram knowledge-base assistant."
    body = text[idx + len(marker) :]
    lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("    "):
            lines.append(line[4:])
        elif line.strip() == "":
            lines.append("")
        else:
            break
    return "\n".join(lines).strip()


def _classify_intent_for_option_b(message: str) -> list[dict[str, Any]]:
    """Return the subset of ``TOOL_DECLARATIONS`` for a coarse first-turn route.

    Heuristic — keyword-based, intentionally simple. Spike-quality only.
    """
    msg = message.lower()
    decls_by_name = {d["name"]: d for d in TOOL_DECLARATIONS}

    def pick(*names: str) -> list[dict[str, Any]]:
        return [decls_by_name[n] for n in names if n in decls_by_name]

    if "config" in msg or "llm" in msg or "конфиг" in msg or "модель" in msg:
        return pick(
            "get_llm_config",
            "set_llm_config",
            "reset_llm_config",
            "reload_prompts",
            "list_channels",
            "whoami",
        )
    if any(k in msg for k in ("удали", "удалить", "remove", "delete")):
        return pick("remove_channel", "list_channels")
    if any(k in msg for k in ("добав", "add ", "подключ")):
        return pick("add_channel", "list_channels")
    if any(k in msg for k in ("пауз", "приостанов", "pause")):
        return pick("pause_channel", "list_channels")
    if any(k in msg for k in ("возобнов", "resume")):
        return pick("resume_channel", "list_channels")
    return pick(
        "ask_question",
        "search_knowledge_base",
        "list_topics",
        "get_topic_details",
        "list_channels",
        "get_document",
        "get_related_topics",
        "get_cross_channel_stats",
    )


@dataclass
class OptionConfig:
    """One spike configuration row."""

    name: str
    model: str = "gemini-2.5-flash"
    max_output_tokens: int = 4096
    thinking_budget: int | None = None
    use_intent_subset: bool = False

    def label(self) -> str:
        return self.name


@dataclass
class CallResult:
    """Outcome of a single Gemini call."""

    option: str
    query_id: str
    run: int
    http_status: int
    elapsed_s: float
    success: bool
    finish_reason: str = ""
    has_function_call: bool = False
    parts_count: int = 0
    candidates_count: int = 0
    block_reason: str = ""
    prompt_tokens: int = 0
    candidates_tokens: int = 0
    thoughts_tokens: int = 0
    error: str = ""

    def to_jsonl(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)


OPTIONS: dict[str, OptionConfig] = {
    "current": OptionConfig("current"),
    "a": OptionConfig("a", max_output_tokens=8192),
    "a-thinking-0": OptionConfig("a-thinking-0", max_output_tokens=8192, thinking_budget=0),
    "thinking-0": OptionConfig("thinking-0", thinking_budget=0),
    "b": OptionConfig("b", use_intent_subset=True),
    "c-pro": OptionConfig("c-pro", model="gemini-2.5-pro"),
    "c-flash-2-0": OptionConfig("c-flash-2-0", model="gemini-2.0-flash"),
}


async def _call_once(
    client: httpx.AsyncClient,
    api_key: str,
    system_prompt: str,
    option: OptionConfig,
    query_id: str,
    query_text: str,
    run: int,
) -> CallResult:
    """One Gemini call under one option, no agent loop (single turn)."""
    if option.use_intent_subset:
        tools_subset = _classify_intent_for_option_b(query_text)
    else:
        tools_subset = TOOL_DECLARATIONS

    generation_config: dict[str, Any] = {
        "temperature": 0.2,
        "maxOutputTokens": option.max_output_tokens,
    }
    if option.thinking_budget is not None:
        generation_config["thinkingConfig"] = {
            "thinkingBudget": option.thinking_budget,
        }

    payload: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": query_text}]}],
        "tools": [{"functionDeclarations": tools_subset}],
        "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
        "generationConfig": generation_config,
    }

    url = f"{GEMINI_API_BASE}/{option.model}:generateContent"
    started = time.monotonic()
    try:
        resp = await client.post(url, json=payload, params={"key": api_key})
    except Exception as exc:  # noqa: BLE001
        return CallResult(
            option=option.label(),
            query_id=query_id,
            run=run,
            http_status=0,
            elapsed_s=time.monotonic() - started,
            success=False,
            error=f"transport: {exc!r}",
        )
    elapsed = time.monotonic() - started

    if resp.status_code != 200:
        return CallResult(
            option=option.label(),
            query_id=query_id,
            run=run,
            http_status=resp.status_code,
            elapsed_s=elapsed,
            success=False,
            error=resp.text[:300],
        )

    data = resp.json()
    candidates = data.get("candidates", []) or []
    block_reason = data.get("promptFeedback", {}).get("blockReason", "") or ""
    usage = data.get("usageMetadata", {}) or {}

    parts: list[dict[str, Any]] = []
    finish_reason = ""
    has_function_call = False
    if candidates:
        candidate = candidates[0]
        finish_reason = candidate.get("finishReason", "") or ""
        parts = candidate.get("content", {}).get("parts", []) or []
        has_function_call = any("functionCall" in p for p in parts)

    success = bool(parts) and not block_reason

    return CallResult(
        option=option.label(),
        query_id=query_id,
        run=run,
        http_status=200,
        elapsed_s=elapsed,
        success=success,
        finish_reason=finish_reason,
        has_function_call=has_function_call,
        parts_count=len(parts),
        candidates_count=len(candidates),
        block_reason=block_reason,
        prompt_tokens=int(usage.get("promptTokenCount", 0) or 0),
        candidates_tokens=int(usage.get("candidatesTokenCount", 0) or 0),
        thoughts_tokens=int(usage.get("thoughtsTokenCount", 0) or 0),
    )


async def _run_option(
    client: httpx.AsyncClient,
    api_key: str,
    system_prompt: str,
    option: OptionConfig,
    runs: int,
    out_dir: Path,
) -> list[CallResult]:
    results: list[CallResult] = []
    out_path = out_dir / f"option-{option.label()}.jsonl"
    with out_path.open("w", encoding="utf-8") as out_fh:
        for query_id, query_text in QUERIES.items():
            for run in range(runs):
                # Sequential — keeps order deterministic + avoids RPM bursts.
                res = await _call_once(
                    client,
                    api_key,
                    system_prompt,
                    option,
                    query_id,
                    query_text,
                    run,
                )
                results.append(res)
                out_fh.write(res.to_jsonl() + "\n")
                out_fh.flush()
                # Small spacing — Gemini RPM is ample, but keep it polite.
                await asyncio.sleep(0.4)
    return results


@dataclass
class OptionSummary:
    option: str
    total: int = 0
    successes: int = 0
    failures: int = 0
    finish_reasons: Counter[str] = field(default_factory=Counter)
    avg_latency: float = 0.0
    by_query: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: {"success": 0, "fail": 0})
    )
    avg_thoughts_tokens: float = 0.0
    avg_prompt_tokens: float = 0.0


def _summarize(results: list[CallResult]) -> dict[str, OptionSummary]:
    summaries: dict[str, OptionSummary] = {}
    grouped: dict[str, list[CallResult]] = defaultdict(list)
    for r in results:
        grouped[r.option].append(r)
    for option_name, calls in grouped.items():
        summary = OptionSummary(option=option_name)
        latencies: list[float] = []
        thoughts: list[int] = []
        prompts: list[int] = []
        for c in calls:
            summary.total += 1
            latencies.append(c.elapsed_s)
            thoughts.append(c.thoughts_tokens)
            prompts.append(c.prompt_tokens)
            if c.success:
                summary.successes += 1
                summary.by_query[c.query_id]["success"] += 1
            else:
                summary.failures += 1
                summary.by_query[c.query_id]["fail"] += 1
            reason = c.finish_reason or ("HTTP" if c.http_status != 200 else "EMPTY")
            summary.finish_reasons[reason] += 1
        summary.avg_latency = sum(latencies) / max(len(latencies), 1)
        summary.avg_thoughts_tokens = sum(thoughts) / max(len(thoughts), 1)
        summary.avg_prompt_tokens = sum(prompts) / max(len(prompts), 1)
        summaries[option_name] = summary
    return summaries


def _print_summary(summaries: dict[str, OptionSummary]) -> None:
    rows: list[tuple[str, str, str, str, str, str, str]] = [
        ("OPTION", "PASS", "TOTAL", "RATE%", "FINISH-REASONS", "AVG-LAT-S", "AVG-THOUGHT-TOK"),
    ]
    for name, s in summaries.items():
        rate = (100.0 * s.successes / s.total) if s.total else 0.0
        fr_summary = ",".join(f"{k}:{v}" for k, v in s.finish_reasons.most_common())
        rows.append(
            (
                name,
                str(s.successes),
                str(s.total),
                f"{rate:5.1f}",
                fr_summary[:40],
                f"{s.avg_latency:5.2f}",
                f"{int(s.avg_thoughts_tokens)}",
            )
        )
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        line = " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
        print(line)
    print()
    for name, s in summaries.items():
        print(f"\n=== {name} per-query ===")
        for q in QUERIES:
            outcomes = s.by_query.get(q, {"success": 0, "fail": 0})
            total = outcomes["success"] + outcomes["fail"]
            rate = (100.0 * outcomes["success"] / total) if total else 0.0
            print(f"  {q:14s}  {outcomes['success']}/{total}  rate={rate:5.1f}%")


async def _amain(args: argparse.Namespace) -> int:
    _load_env()
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print(
            "ERROR: GEMINI_API_KEY (or GOOGLE_API_KEY) must be set in environment or .env",
            file=sys.stderr,
        )
        return 2

    system_prompt = _load_system_prompt()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.option == "all":
        option_keys = list(OPTIONS.keys())
    else:
        if args.option not in OPTIONS:
            print(
                f"ERROR: unknown option '{args.option}'. Known: {', '.join(OPTIONS)}",
                file=sys.stderr,
            )
            return 2
        option_keys = [args.option]

    print(f"BUG-006 spike — runs={args.runs} options={option_keys}")
    print(f"Loaded TOOL_DECLARATIONS: {len(TOOL_DECLARATIONS)} tools")
    print(f"System prompt size: {len(system_prompt)} chars")
    print(f"Output dir: {out_dir}")
    print()

    timeout = httpx.Timeout(60.0, connect=10.0)
    all_results: list[CallResult] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for key in option_keys:
            option = OPTIONS[key]
            print(
                f"--- Running option={option.label()} (model={option.model}, "
                f"maxOut={option.max_output_tokens}, thinking={option.thinking_budget}, "
                f"intent_subset={option.use_intent_subset}) ---"
            )
            results = await _run_option(client, api_key, system_prompt, option, args.runs, out_dir)
            for r in results:
                marker = "OK " if r.success else "FAIL"
                extra = (
                    f"reason={r.finish_reason or '(none)'} "
                    f"parts={r.parts_count} thoughts={r.thoughts_tokens}"
                )
                if r.error:
                    extra += f" err={r.error[:120]}"
                print(f"  [{marker}] {r.query_id:14s} run={r.run} {extra}")
            all_results.extend(results)
            print()

    summaries = _summarize(all_results)
    _print_summary(summaries)

    summary_path = out_dir / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                name: {
                    "total": s.total,
                    "successes": s.successes,
                    "failures": s.failures,
                    "rate_pct": (100.0 * s.successes / s.total) if s.total else 0.0,
                    "finish_reasons": dict(s.finish_reasons),
                    "avg_latency_s": s.avg_latency,
                    "avg_thoughts_tokens": s.avg_thoughts_tokens,
                    "avg_prompt_tokens": s.avg_prompt_tokens,
                    "by_query": dict(s.by_query),
                }
                for name, s in summaries.items()
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote summary -> {summary_path}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="BUG-006 research spike runner")
    p.add_argument(
        "--option",
        default="all",
        choices=[*OPTIONS.keys(), "all"],
        help="Which option to run (default: all)",
    )
    p.add_argument("--runs", type=int, default=2, help="Repetitions per query (default: 2)")
    p.add_argument(
        "--out-dir",
        default="/tmp/bug-006-spike",
        help="Where to write per-option JSONL logs + summary.json",
    )
    return p


def main() -> int:
    args = _build_parser().parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
