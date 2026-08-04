"""Regression guard for the Prometheus-instrumentator × ``include_router`` surface.

Incident background (#295)
--------------------------
FastAPI **0.137.0** introduced lazy ``_IncludedRouter`` route objects that do
*not* expose a ``.path`` attribute. ``prometheus-fastapi-instrumentator`` reads
``route.path`` from ``app.routes`` inside its per-request middleware, so once
``METRICS_ENABLED=true`` (the PROD default) **every** request to a route that
was registered via ``app.include_router(...)`` raised ``AttributeError`` and
returned HTTP 500 — i.e. "green tests, broken prod".

The existing suite missed this because ``tests/conftest.py`` force-disables
metrics for the whole session (``METRICS_ENABLED=false`` + patching
``settings.metrics_enabled``) to avoid global Prometheus registry conflicts.
With metrics off, the instrumentator middleware is never installed, so the
``route.path`` access never happens.

What this test does
-------------------
It explicitly **overrides** the conftest metrics-disable for this test only
(``METRICS_ENABLED=true`` via env + ``settings.metrics_enabled=True`` via
monkeypatch) and wires a representative app *exactly* like prod
(``Instrumentator().instrument(app).expose(app)`` **plus**
``app.include_router(...)``). It then fires a REAL ``TestClient`` request at an
``include_router``-registered route and asserts:

* the response is **200** (it would be 500 / ``AttributeError`` under the
  fastapi 0.137 + instrumentator combination), and
* the instrumentator actually **recorded** the request (the http request
  counter is exposed at ``/metrics`` with the handler label for that route).

This guards the **fastapi / starlette / prometheus-fastapi-instrumentator
compatibility surface**: it must FAIL if someone bumps fastapi past the safe
range with an incompatible instrumentator (e.g. fastapi 0.137).

Metric-name cross-check (BUG-089)
---------------------------------
The same instrumented app is reused by
``test_alerts_and_dashboards_query_metric_names_the_app_actually_exposes``,
which asserts that every ``tg_parser_http_*`` name referenced by
``docker/prometheus/alerts.yml`` and ``docker/grafana/dashboards/system.json``
is really exposed at ``/metrics``. BUG-089 was a double namespace
(``tg_parser_http_http_*``) that no test compared against the consumers.

The app is built by prod's own
:func:`tg_parser.api.metrics.create_instrumentator`, not by a local replica of
its configuration: a replica passes the tests while prod stays broken, which is
precisely how BUG-089 survived.

Isolation note
--------------
``create_instrumentator`` is handed a dedicated
:class:`~prometheus_client.CollectorRegistry` so this test neither pollutes the
global default registry nor risks "Duplicated timeseries" errors against the
module-level metrics in :mod:`tg_parser.api.metrics`. The ``route.path`` access
exercised by the middleware — the actual bug surface — is independent of which
registry the metrics live in, so the regression guard is faithful regardless.

The one exception is the requests-inprogress gauge, which the library's
middleware always registers on the global default registry (see
``_NOT_EXPOSABLE_IN_ISOLATED_REGISTRY``). Registering it twice in one session
would raise, so the instrumented app is built exactly once per module and shared
by the tests below.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry, Histogram

from tg_parser.api.metrics import (
    HTTP_LATENCY_LOWR_BUCKETS,
    LLM_REQUEST_DURATION_SECONDS,
    create_instrumentator,
)

# NB: must NOT contain any of prod's excluded_handlers as a substring ("/metrics",
# "/health", "/docs", "/redoc", "/openapi.json") — those patterns are unanchored
# ``re.search`` regexes, so a path like ".../metrics-ping" would be silently
# excluded from instrumentation and break the recording assertion.
_PING_PATH = "/api/v1/regression/ping"

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ALERTS_YML = _REPO_ROOT / "docker" / "prometheus" / "alerts.yml"
_SYSTEM_DASHBOARD = _REPO_ROOT / "docker" / "grafana" / "dashboards" / "system.json"

# ``tg_parser_http_requests_inprogress`` is created by the instrumentator's own
# middleware (prometheus_fastapi_instrumentator/middleware.py) with NO
# ``registry=`` kwarg, so it always lands on the global default registry and can
# never appear on a ``/metrics`` endpoint backed by an isolated
# CollectorRegistry. Its name is pinned directly against ``create_instrumentator``
# in the cross-check test instead of via the exposition body.
_NOT_EXPOSABLE_IN_ISOLATED_REGISTRY = {"tg_parser_http_requests_inprogress"}


def _finite_bucket_bounds(histogram: Histogram) -> set[float]:
    """The finite bucket upper bounds a registered histogram was built with.

    ``_upper_bounds`` is private, but it is where prometheus_client has stored a
    Histogram's buckets for its whole 0.x line and there is no public accessor.
    Read through this helper so a future client release that moves it fails
    loudly here instead of quietly turning the cross-check below into a no-op.
    """
    bounds = getattr(histogram, "_upper_bounds", None)
    assert bounds, (
        "prometheus_client no longer exposes a Histogram's buckets via "
        "``_upper_bounds`` — update this helper, otherwise the latency-coverage "
        "assertion that depends on it is not guarding anything"
    )
    return {float(bound) for bound in bounds if bound != float("inf")}


def _build_instrumented_app() -> FastAPI:
    """Wire an app the way prod does: instrument().expose() + include_router.

    The instrumentator comes from prod's ``create_instrumentator`` — the
    configuration under test — on an isolated ``CollectorRegistry``.
    """
    router = APIRouter()

    @router.get(_PING_PATH)
    async def _ping() -> dict[str, bool]:  # pragma: no cover - body is trivial
        return {"ok": True}

    app = FastAPI()

    instrumentator = create_instrumentator(registry=CollectorRegistry())
    # Order mirrors prod (tg_parser/api/main.py): instrument + expose first,
    # routers attached via include_router afterwards — the exact shape that
    # fastapi 0.137's lazy _IncludedRouter broke.
    instrumentator.instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    app.include_router(router)

    return app


@pytest.fixture(scope="module")
def instrumented_client() -> Iterator[TestClient]:
    """A client for the prod-configured app, built once per module.

    Overrides conftest's session-wide ``METRICS_ENABLED=false`` (the PROD default
    is true). Both the env var and the patched settings singleton are flipped so
    the override is robust regardless of which one a future app-construction path
    consults.
    """
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setenv("METRICS_ENABLED", "true")
        from tg_parser.config import settings

        monkeypatch.setattr(settings, "metrics_enabled", True, raising=False)
        yield TestClient(_build_instrumented_app())
    finally:
        monkeypatch.undo()


def test_metrics_records_request_through_include_router(instrumented_client: TestClient) -> None:
    """A request to an include_router route must be 200 AND recorded by metrics.

    The ``instrumented_client`` fixture neutralises the conftest session-wide
    metrics-disable so the instrumentator middleware is actually exercised
    (otherwise the bug surface is never reached). Regression guard for the
    fastapi 0.137 / prometheus-fastapi-instrumentator ``_IncludedRouter`` 500
    class of bug.
    """
    client = instrumented_client

    # Under fastapi 0.137 + prometheus-fastapi-instrumentator the instrumentation
    # middleware reads ``route.path`` on a lazy ``_IncludedRouter`` object that
    # has no ``.path`` -> AttributeError -> HTTP 500. On the safe range this is 200.
    resp = client.get(_PING_PATH)
    assert resp.status_code == 200, (
        f"include_router route returned {resp.status_code} with metrics enabled — "
        f"likely the fastapi/instrumentator _IncludedRouter incompatibility. Body: {resp.text!r}"
    )
    assert resp.json() == {"ok": True}

    # The instrumentator must have actually recorded the request: the http
    # request counter is exposed with the handler label for our route.
    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 200
    body = metrics_resp.text
    # metrics.default base names already start with ``http_``, so namespace
    # ``tg_parser`` alone yields ``tg_parser_http_requests_total`` — the name the
    # alerts and dashboards query. create_instrumentator therefore passes NO
    # metric_subsystem; a subsystem would double the prefix.
    assert "tg_parser_http_requests_total" in body, (
        "instrumentator did not expose the http request counter — metrics were "
        "not wired through the instrument()/expose() path"
    )
    # Covers the four series that have no positive assertion above (duration,
    # highr duration, request size, response size): none may carry a doubled prefix.
    assert "tg_parser_http_http" not in body, (
        "a doubled ``tg_parser_http_http_*`` metric name is exposed — "
        "metric_subsystem='http' was reintroduced on top of the library's "
        "``http_``-prefixed base names (BUG-089)"
    )
    assert f'handler="{_PING_PATH}"' in body, (
        "the include_router route was not recorded by the instrumentator — the "
        "per-request middleware did not resolve the route path"
    )
    # Every configured low-res latency bucket must actually reach the histogram,
    # not just the lowest boundary. Expected values are read from the factory's own
    # ``HTTP_LATENCY_LOWR_BUCKETS`` and never re-typed here: a duplicated tuple is
    # the replica anti-pattern that let BUG-089 through in the first place.
    # Compared as FLOATS because the exposition text goes through
    # prometheus_client's ``floatToGoString`` (``0.01``, ``1.0``, ``+Inf``), whose
    # formatting is not a stable contract worth pinning by string.
    exposed_le = {
        float(value)
        for value in re.findall(
            r'^tg_parser_http_request_duration_seconds_bucket\{[^}]*le="([^"]+)"', body, re.M
        )
    }
    exposed_le.discard(float("inf"))  # prometheus_client always appends the +Inf bucket
    configured_le = set(HTTP_LATENCY_LOWR_BUCKETS)
    assert exposed_le == configured_le, (
        "tg_parser_http_request_duration_seconds does not carry the latency buckets "
        "create_instrumentator configures. Missing "
        f"{sorted(configured_le - exposed_le)}; unexpected "
        f"{sorted(exposed_le - configured_le)}. The histogram has most likely fallen "
        "back to the library default (0.1, 0.5, 1) because latency_lowr_buckets no "
        "longer reaches metrics.default() — exactly what the silently-dropped "
        "duplicate metrics.latency() registration produced before BUG-089 was fixed."
    )

    # The equality above reads BOTH sides from the factory, so it says nothing
    # about whether the configured range is still the right one — trimming the
    # tuple moves expectation and reality together. The deliberate high-latency
    # tail is therefore pinned separately, against the sibling histogram the
    # decision was taken from (see the HTTP_LATENCY_LOWR_BUCKETS comment) rather
    # than against numbers re-typed here.
    llm_ceiling = max(_finite_bucket_bounds(LLM_REQUEST_DURATION_SECONDS))
    assert max(exposed_le) >= llm_ceiling, (
        f"the HTTP latency histogram now tops out at {max(exposed_le)}s while "
        f"tg_parser_llm_request_duration_seconds reaches {llm_ceiling}s — the "
        "high-latency tail of HTTP_LATENCY_LOWR_BUCKETS was trimmed. RAG endpoints "
        "inherit the LLM call's latency (haiku ~6.8s, sonnet ~8.7s), so with a lower "
        "ceiling every slow request collapses into the +Inf bucket and "
        "histogram_quantile(0.99) on tg_parser_http_request_duration_seconds returns "
        "+Inf — the p99 panel goes blank exactly when latency is worth looking at."
    )


def _referenced_http_metric_names(path: Path) -> set[str]:
    """Every ``tg_parser_http_*`` metric name a consumer config refers to.

    Deliberately a regex over the raw file text rather than a YAML/JSON load plus
    a PromQL parse: the goal is to catch every mention (alert ``expr``, dashboard
    targets, legend formats) without taking on a query grammar.
    """
    names = set(re.findall(r"tg_parser_http_[a-z0-9_]+", path.read_text(encoding="utf-8")))
    # ``_bucket`` / ``_sum`` / ``_count`` are exposition artefacts of a histogram
    # or summary, not part of the registered metric name.
    return {re.sub(r"_(?:bucket|sum|count)$", "", name) for name in names}


def _exposed_metric_names(body: str) -> set[str]:
    """Metric names present in a Prometheus exposition body."""
    names: set[str] = set()
    for line in body.splitlines():
        if line.startswith(("# TYPE ", "# HELP ")):
            names.add(line.split()[2])
        elif line and not line.startswith("#"):
            names.add(re.split(r"[{ ]", line, maxsplit=1)[0])
    return names


def _is_exposed(name: str, exposed: set[str]) -> bool:
    """Whether ``name`` is exposed, tolerating the counter ``_total`` convention.

    prometheus_client registers a counter under its bare name and exposes it with
    a ``_total`` suffix; which of the two the ``# TYPE`` line carries has varied
    across client versions, so both directions are accepted.
    """
    if name in exposed or f"{name}_total" in exposed:
        return True
    return name.endswith("_total") and name.removesuffix("_total") in exposed


def test_alerts_and_dashboards_query_metric_names_the_app_actually_exposes(
    instrumented_client: TestClient,
) -> None:
    """Every ``tg_parser_http_*`` name in alerts/dashboards must exist at /metrics.

    The guard for BUG-089: the app emitted ``tg_parser_http_http_*`` (namespace +
    a subsystem on top of the library's already ``http_``-prefixed base names)
    while the alert rule and the dashboard panels queried the single-prefixed
    names, so one alert could never fire and three panels were permanently empty.
    Nothing compared the two sides. This test does, in both directions: a rename
    in the app or in a consumer breaks it.
    """
    assert instrumented_client.get(_PING_PATH).status_code == 200
    exposed = _exposed_metric_names(instrumented_client.get("/metrics").text)

    checked: dict[Path, set[str]] = {}
    missing: list[str] = []
    for path in (_ALERTS_YML, _SYSTEM_DASHBOARD):
        assert path.is_file(), f"consumer config not found: {path} — has it moved?"
        per_file = checked.setdefault(path, set())
        for name in sorted(_referenced_http_metric_names(path)):
            if name in _NOT_EXPOSABLE_IN_ISOLATED_REGISTRY:
                continue
            per_file.add(name)
            if not _is_exposed(name, exposed):
                missing.append(f"{name} (referenced by {path.relative_to(_REPO_ROOT)})")

    # Guard against a vacuous pass if a consumer file is emptied or the regex rots.
    # The floor is PER FILE, not per suite: system.json alone references enough
    # names to satisfy a suite-wide count, so alerts.yml could be emptied — or the
    # extraction could rot on YAML specifically — while the total stayed healthy.
    barren = sorted(str(p.relative_to(_REPO_ROOT)) for p, names in checked.items() if not names)
    per_file_counts = ", ".join(f"{p.name}={len(names)}" for p, names in checked.items())
    assert not barren, (
        f"no tg_parser_http_* references extracted from {', '.join(barren)} — the "
        "file was emptied or the extraction broke on it, so this test no longer "
        f"guards that consumer at all (references checked per file: {per_file_counts})"
    )
    assert not missing, (
        "alerts/dashboards query HTTP metric names the app does not expose:\n  "
        + "\n  ".join(missing)
        + "\nExposed tg_parser_http_* names:\n  "
        + "\n  ".join(sorted(n for n in exposed if n.startswith("tg_parser_http")))
        + "\nFix whichever side is wrong — the instrumentator in "
        "tg_parser/api/metrics.py::create_instrumentator or the consumer config."
    )


def test_inprogress_gauge_name_matches_the_dashboard_reference() -> None:
    """Pin the one dashboard reference the exposition cross-check cannot cover.

    See ``_NOT_EXPOSABLE_IN_ISOLATED_REGISTRY``: the gauge is registered on the
    global default registry by the library's middleware, so it is checked against
    the name prod configures rather than against a ``/metrics`` body.
    """
    referenced = _referenced_http_metric_names(_SYSTEM_DASHBOARD)
    assert _NOT_EXPOSABLE_IN_ISOLATED_REGISTRY <= referenced, (
        "the dashboard no longer references "
        f"{sorted(_NOT_EXPOSABLE_IN_ISOLATED_REGISTRY)} — drop the exclusion so the "
        "cross-check test covers everything again"
    )
    # Isolated registry: reading the configured name must not register prod's
    # default metrics on the global one as a side effect.
    assert create_instrumentator(registry=CollectorRegistry()).inprogress_name in referenced
