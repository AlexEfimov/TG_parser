"""
BUG-108 (a) — LLM spend is attributable by pipeline stage, Phase 2 discover
leaves its size and cost in the log, the daily spend alert reaches a human, and
application logs outlive a day.

Background: on prod 2026-09-02…22 Phase 2 discover was ~75 % of all LLM tokens
(~280k Sonnet prompt tokens per call, the whole cross-channel catalog in the
prompt), yet ``tg_parser_llm_tokens_total`` had no ``stage`` label, the Phase 2
log lines carried no token counts, Prometheus had no Alertmanager, and the
daemon-default 10m x 3 log rotation kept under a day of ``tg_parser`` logs.

The call-site test is the load-bearing one: a new ``create_llm_client(...)``
without ``stage=`` would silently land in ``stage="unknown"``, which is exactly
how Phase 2 stayed invisible.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from tg_parser.api.metrics import LLM_STAGE_UNKNOWN, LLM_STAGES, record_llm_request
from tg_parser.config.settings import LLM_SCOPES
from tg_parser.processing.llm.factory import create_llm_client
from tg_parser.processing.llm.instrumented import InstrumentedLLMClient
from tg_parser.processing.llm.response_cache import LLMResponseCache
from tg_parser.processing.ports import LLMResponse

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "tg_parser"
ALERTS_PATH = REPO_ROOT / "docker" / "prometheus" / "alerts.yml"
GRAFANA_ALERTING_DIR = REPO_ROOT / "docker" / "grafana" / "provisioning" / "alerting"
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"

# 9 on 2026-09-23. A drop means a call site moved out of reach of the AST scan
# (e.g. aliased import) and the parametrized guard below went partially blind.
MIN_CALL_SITES = 9


# ---------------------------------------------------------------------------
# Every create_llm_client call site names a stage from the closed vocabulary
# ---------------------------------------------------------------------------


def _create_llm_client_calls() -> list[tuple[str, int, ast.Call]]:
    calls: list[tuple[str, int, ast.Call]] = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name == "create_llm_client":
                calls.append((str(path.relative_to(REPO_ROOT)), node.lineno, node))
    return calls


_CALLS = _create_llm_client_calls()


def test_call_site_scan_is_not_vacuous() -> None:
    assert len(_CALLS) >= MIN_CALL_SITES, (
        f"found {len(_CALLS)} create_llm_client(...) calls in tg_parser/, "
        f"expected at least {MIN_CALL_SITES}"
    )


@pytest.mark.parametrize(
    "path,lineno,call",
    _CALLS,
    ids=[f"{path}:{lineno}" for path, lineno, _ in _CALLS],
)
def test_every_create_llm_client_call_passes_a_known_stage(
    path: str, lineno: int, call: ast.Call
) -> None:
    stage_kw = next((kw for kw in call.keywords if kw.arg == "stage"), None)
    assert stage_kw is not None, (
        f"{path}:{lineno}: create_llm_client(...) without stage= records its tokens "
        f"as stage='unknown' — pass one of {sorted(LLM_STAGES)} (BUG-108 a)"
    )
    assert isinstance(stage_kw.value, ast.Constant), (
        f"{path}:{lineno}: stage= must be a string literal so this test can check it"
    )
    assert stage_kw.value.value in LLM_STAGES, (
        f"{path}:{lineno}: stage={stage_kw.value.value!r} is not in {sorted(LLM_STAGES)}"
    )


def test_both_topicization_paths_are_distinguishable() -> None:
    """The point of the label: Phase 2 discover vs the full run."""
    stages = {kw.value.value for _, _, call in _CALLS for kw in call.keywords if kw.arg == "stage"}
    assert {"topicization_full", "topicization_discover"} <= stages


def test_vocabulary_covers_every_llm_config_scope() -> None:
    """Each set_llm_config scope that builds a client through the factory has a
    stage; ``topicization`` splits into full / discover. ``global`` is the
    fallback root and ``bot`` has its own Gemini client outside the factory."""
    for scope in LLM_SCOPES:
        if scope in ("global", "bot"):
            continue
        if scope == "topicization":
            assert {"topicization_full", "topicization_discover"} <= LLM_STAGES
        else:
            assert scope in LLM_STAGES, f"scope {scope!r} has no metrics stage"
    assert LLM_STAGE_UNKNOWN not in LLM_STAGES


# ---------------------------------------------------------------------------
# record_llm_request / InstrumentedLLMClient write the stage
# ---------------------------------------------------------------------------


def _tokens(stage: str, token_type: str, model: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "tg_parser_llm_tokens_total",
            {"provider": "anthropic", "model": model, "token_type": token_type, "stage": stage},
        )
        or 0.0
    )


def _requests(stage: str, model: str, status: str = "success") -> float:
    return (
        REGISTRY.get_sample_value(
            "tg_parser_llm_requests_total",
            {"provider": "anthropic", "model": model, "status": status, "stage": stage},
        )
        or 0.0
    )


def test_record_llm_request_labels_both_counters_with_stage() -> None:
    model = "bug108-record"
    before = (
        _requests("topicization_discover", model),
        _tokens("topicization_discover", "prompt", model),
        _tokens("topicization_discover", "completion", model),
    )
    record_llm_request(
        provider="anthropic",
        model=model,
        success=True,
        duration_seconds=1.0,
        prompt_tokens=281_000,
        completion_tokens=420,
        stage="topicization_discover",
    )
    assert _requests("topicization_discover", model) - before[0] == 1
    assert _tokens("topicization_discover", "prompt", model) - before[1] == 281_000
    assert _tokens("topicization_discover", "completion", model) - before[2] == 420


def test_record_llm_request_folds_unlisted_stage_into_unknown() -> None:
    model = "bug108-unknown"
    before = _tokens(LLM_STAGE_UNKNOWN, "prompt", model)
    record_llm_request(
        provider="anthropic",
        model=model,
        success=True,
        duration_seconds=0.1,
        prompt_tokens=7,
        stage="topicization_typo",
    )
    assert _tokens(LLM_STAGE_UNKNOWN, "prompt", model) - before == 7
    assert (
        REGISTRY.get_sample_value(
            "tg_parser_llm_tokens_total",
            {
                "provider": "anthropic",
                "model": model,
                "token_type": "prompt",
                "stage": "topicization_typo",
            },
        )
        is None
    )


def test_factory_threads_stage_into_the_wrapper() -> None:
    client = create_llm_client(provider="anthropic", api_key="sk-test", stage="rag")
    assert isinstance(client, InstrumentedLLMClient)
    assert client._stage == "rag"
    assert create_llm_client(provider="anthropic", api_key="sk-test")._stage == LLM_STAGE_UNKNOWN


# ---------------------------------------------------------------------------
# Series exist at 0 before the first call — otherwise increase() misses it
# ---------------------------------------------------------------------------


def test_stage_scope_map_covers_the_vocabulary() -> None:
    from tg_parser.processing.llm.factory import LLM_STAGE_SCOPES

    assert set(LLM_STAGE_SCOPES) == LLM_STAGES
    assert set(LLM_STAGE_SCOPES.values()) <= set(LLM_SCOPES)


def test_client_construction_creates_its_series_at_zero() -> None:
    """A series born at its first value hides that whole call from increase()."""
    model = "bug108-born-at-zero"
    InstrumentedLLMClient(AsyncMock(), provider="anthropic", model=model, stage="digest")
    assert (
        REGISTRY.get_sample_value(
            "tg_parser_llm_tokens_total",
            {"provider": "anthropic", "model": model, "token_type": "prompt", "stage": "digest"},
        )
        == 0.0
    )


def test_prime_creates_every_stage_series_for_the_configured_model(monkeypatch) -> None:
    from tg_parser.processing.llm import factory

    monkeypatch.setattr(
        factory,
        "resolve_llm_config",
        lambda scope: ("Anthropic", "sk-test", f"bug108-prime-{scope}"),
    )
    factory.prime_llm_stage_metrics()

    for stage, scope in factory.LLM_STAGE_SCOPES.items():
        value = REGISTRY.get_sample_value(
            "tg_parser_llm_tokens_total",
            {
                "provider": "anthropic",
                "model": f"bug108-prime-{scope}",
                "token_type": "prompt",
                "stage": stage,
            },
        )
        assert value is not None, f"stage {stage!r} not primed"


def test_prime_survives_a_broken_scope(monkeypatch) -> None:
    from tg_parser.processing.llm import factory

    def _resolve(scope):
        if scope == "rag":
            raise ValueError("bad config")
        return ("anthropic", "sk-test", "bug108-prime-partial")

    monkeypatch.setattr(factory, "resolve_llm_config", _resolve)
    factory.prime_llm_stage_metrics()
    assert (
        REGISTRY.get_sample_value(
            "tg_parser_llm_tokens_total",
            {
                "provider": "anthropic",
                "model": "bug108-prime-partial",
                "token_type": "prompt",
                "stage": "digest",
            },
        )
        == 0.0
    )


@pytest.mark.parametrize(
    "path", ["tg_parser/api/main.py", "tg_parser/mcp_server.py", "tg_parser/bot/main.py"]
)
def test_every_process_primes_at_startup(path: str) -> None:
    tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "prime_llm_stage_metrics" in called, f"{path} does not prime LLM stage series"


async def test_generate_with_usage_records_tokens_under_the_client_stage() -> None:
    model = "bug108-usage"
    inner = AsyncMock()
    inner.generate_with_usage.return_value = LLMResponse(
        text="{}", input_tokens=280_000, output_tokens=500
    )
    client = InstrumentedLLMClient(
        inner, provider="anthropic", model=model, stage="topicization_discover"
    )
    before = _tokens("topicization_discover", "prompt", model)

    await client.generate_with_usage("prompt")

    assert _tokens("topicization_discover", "prompt", model) - before == 280_000


async def test_generate_cache_hit_records_nothing() -> None:
    """No tokens were spent on a cache hit, so no request may be counted."""
    model = "bug108-cache"
    inner = AsyncMock()
    client = InstrumentedLLMClient(inner, provider="anthropic", model=model, stage="rag")
    client._cache = LLMResponseCache(ttl_seconds=60)
    client._cache.put("hello", None, 0.0, 4096, "cached", "anthropic", model)
    before = _requests("rag", model)

    assert await client.generate("hello") == "cached"

    inner.generate.assert_not_awaited()
    assert _requests("rag", model) == before


# ---------------------------------------------------------------------------
# Phase 2 discover logs its catalog size, prompt length and tokens
# ---------------------------------------------------------------------------


async def test_phase2_discover_logs_catalog_prompt_size_and_tokens() -> None:
    from tg_parser.processing.topicization import TopicizationPipelineImpl

    llm = MagicMock()
    llm.generate_with_usage = AsyncMock(
        return_value=LLMResponse(
            text=json.dumps(
                {"assignments": [], "new_topics": [], "unassignable": ["tg:ch:post:1"]}
            ),
            input_tokens=281_234,
            output_tokens=321,
            stop_reason="end_turn",
        )
    )
    pipeline = TopicizationPipelineImpl(
        llm_client=llm,
        processed_doc_repo=MagicMock(),
        topic_card_repo=MagicMock(),
        topic_bundle_repo=MagicMock(),
    )
    doc = SimpleNamespace(source_ref="tg:ch:post:1", summary="s", topics=[], text_clean="text")
    own = [{"id": "topic:own", "title": "Own", "scope_in": ["a"]}]
    cross = [
        {"id": f"topic:other:{i}", "title": f"Other {i}", "scope_in": ["b"], "channel_id": "x"}
        for i in range(3)
    ]

    with capture_logs() as logs:
        await pipeline._discover_single_batch(
            "ch", [doc], own, {"topic:own"}, cross_channel_topics=cross
        )

    messages = [entry["event"] % tuple(entry.get("positional_args", ())) for entry in logs]
    start = next(m for m in messages if m.startswith("Phase 2 discover call:"))
    assert "channel=ch" in start
    assert "docs=1" in start
    assert "own_topics=1" in start
    assert "cross_channel_topics=3" in start
    prompt = llm.generate_with_usage.await_args.kwargs["prompt"]
    assert f"prompt_chars={len(prompt)}" in start

    done = next(m for m in messages if m.startswith("Phase 2 batch:"))
    assert "input_tokens=281234" in done
    assert "output_tokens=321" in done


# ---------------------------------------------------------------------------
# The daily spend alert: Prometheus reference == Grafana copy, and it is routed
# ---------------------------------------------------------------------------


def _prometheus_rule() -> dict:
    groups = yaml.safe_load(ALERTS_PATH.read_text(encoding="utf-8"))["groups"]
    group = next(g for g in groups if g["name"] == "tg_parser_bug108_llm_spend")
    return next(r for r in group["rules"] if r["alert"] == "LLMDailySonnetSpendHigh")


def _grafana_file() -> dict:
    return yaml.safe_load((GRAFANA_ALERTING_DIR / "bug108_llm_spend.yaml").read_text("utf-8"))


def _grafana_rule() -> dict:
    rules = [r for g in _grafana_file()["groups"] for r in g["rules"]]
    return next(r for r in rules if r["uid"] == "bug108_llm_daily_sonnet_spend")


def test_grafana_copy_matches_the_prometheus_rule() -> None:
    prom_expr = " ".join(_prometheus_rule()["expr"].split())
    query, threshold = prom_expr.rsplit(" > ", 1)

    data = {q["refId"]: q for q in _grafana_rule()["data"]}
    assert " ".join(data["A"]["model"]["expr"].split()) == query
    evaluator = data["C"]["model"]["conditions"][0]["evaluator"]
    assert evaluator["type"] == "gt"
    assert float(evaluator["params"][0]) == float(threshold)


def test_grafana_rule_is_routed_to_the_owner_telegram_contact_point() -> None:
    rule = _grafana_rule()
    assert rule["labels"].get("notify") == "owner_telegram"
    assert rule["noDataState"] == "OK"

    receivers = [
        r
        for cp in _grafana_file()["contactPoints"]
        if cp["name"] == "owner-telegram"
        for r in cp["receivers"]
    ]
    assert [r["type"] for r in receivers] == ["telegram"]
    settings = receivers[0]["settings"]
    assert settings["bottoken"] == "$GRAFANA_TELEGRAM_BOT_TOKEN", "never commit the token"
    assert settings["chatid"] == "$GRAFANA_TELEGRAM_CHAT_ID"

    policies = yaml.safe_load((GRAFANA_ALERTING_DIR / "wave1_step4.yaml").read_text("utf-8"))[
        "policies"
    ]
    root = policies[0]
    assert root["receiver"] == "noop-null", "the root must stay a no-op sink (#149)"
    routes = [r for r in root.get("routes") or [] if r["receiver"] == "owner-telegram"]
    assert routes, "owner-telegram must be reachable from the single policy tree"
    assert ["notify", "=", "owner_telegram"] in routes[0]["object_matchers"]


def test_only_one_file_provisions_the_policy_tree() -> None:
    """Grafana keeps the whole tree in one place; a second file would replace it."""
    owners = [
        p.name
        for p in GRAFANA_ALERTING_DIR.glob("*.yaml")
        if "policies" in (yaml.safe_load(p.read_text("utf-8")) or {})
    ]
    assert owners == ["wave1_step4.yaml"]


# ---------------------------------------------------------------------------
# compose: Grafana gets the Telegram vars, app containers get log rotation
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_grafana_env_carries_non_empty_telegram_placeholders(compose: dict) -> None:
    env = compose["services"]["grafana"]["environment"]
    for var in ("GRAFANA_TELEGRAM_BOT_TOKEN", "GRAFANA_TELEGRAM_CHAT_ID"):
        entry = next((e for e in env if e.startswith(f"{var}=")), None)
        assert entry is not None, f"grafana service must pass {var}"
        assert f"${{{var}:-" in entry and not entry.endswith(":-}"), (
            f"{var} needs a non-empty default: an empty required contact-point "
            "setting stops Grafana provisioning"
        )


@pytest.mark.parametrize("service", ["tg_parser", "mcp", "tg_bot"])
def test_app_containers_rotate_logs_with_bounded_retention(compose: dict, service: str) -> None:
    logging_cfg = compose["services"][service].get("logging")
    assert logging_cfg, f"{service} falls back to the daemon default (10m x 3, < 1 day)"
    assert logging_cfg["driver"] == "json-file"
    assert set(logging_cfg["options"]) >= {"max-size", "max-file"}


def test_postgres_keeps_the_daemon_default(compose: dict) -> None:
    """A logging change on postgres recreates the database container."""
    assert "logging" not in compose["services"]["postgres"]
