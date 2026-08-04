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

Isolation note
--------------
A dedicated :class:`~prometheus_client.CollectorRegistry` is used for the
instrumentator metrics so this test neither pollutes the global default
registry nor risks "Duplicated timeseries" errors against the module-level
metrics in :mod:`tg_parser.api.metrics`. The ``route.path`` access exercised by
the middleware — the actual bug surface — is independent of which registry the
metrics live in, so the regression guard is faithful regardless.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry
from prometheus_fastapi_instrumentator import Instrumentator, metrics

# NB: must NOT contain the substring "/metrics" — excluded_handlers patterns
# are unanchored ``re.search`` regexes, so a path like ".../metrics-ping" would
# be silently excluded from instrumentation and break the recording assertion.
_PING_PATH = "/api/v1/regression/ping"

# Keep in sync with ``create_instrumentator`` in tg_parser/api/metrics.py — the
# local app must mirror prod for the bucket and metric-name assertions to mean
# anything.
_LATENCY_LOWR_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)

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


def _build_instrumented_app() -> FastAPI:
    """Wire an app the way prod does: instrument().expose() + include_router.

    Uses an isolated ``CollectorRegistry`` so repeated construction within the
    test session can never collide with the global Prometheus registry.
    """
    registry = CollectorRegistry()

    router = APIRouter()

    @router.get(_PING_PATH)
    async def _ping() -> dict[str, bool]:  # pragma: no cover - body is trivial
        return {"ok": True}

    app = FastAPI()

    instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_respect_env_var=False,
        excluded_handlers=["/metrics"],
        registry=registry,
    )
    instrumentator.add(
        metrics.default(
            metric_namespace="tg_parser",
            latency_lowr_buckets=_LATENCY_LOWR_BUCKETS,
            registry=registry,
        )
    )
    # Order mirrors prod (tg_parser/api/main.py): instrument + expose first,
    # routers attached via include_router afterwards — the exact shape that
    # fastapi 0.137's lazy _IncludedRouter broke.
    instrumentator.instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    app.include_router(router)

    return app


def test_metrics_records_request_through_include_router(monkeypatch) -> None:
    """A request to an include_router route must be 200 AND recorded by metrics.

    Explicitly neutralises the conftest session-wide metrics-disable so the
    instrumentator middleware is actually exercised (otherwise the bug surface
    is never reached). Regression guard for the fastapi 0.137 /
    prometheus-fastapi-instrumentator ``_IncludedRouter`` 500 class of bug.
    """
    # Override conftest's METRICS_ENABLED=false (PROD default is true). Both the
    # env var and the patched settings singleton are flipped so the override is
    # robust regardless of which one a future app-construction path consults.
    monkeypatch.setenv("METRICS_ENABLED", "true")
    from tg_parser.config import settings

    monkeypatch.setattr(settings, "metrics_enabled", True, raising=False)

    app = _build_instrumented_app()
    client = TestClient(app)

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
    # alerts and dashboards query (matches prod's create_instrumentator, which
    # passes NO metric_subsystem; a subsystem would double the prefix).
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
    # The configured low-res latency buckets must actually reach the histogram.
    # metrics.default()'s library default is (0.1, 0.5, 1), so a 0.01 boundary
    # exists only if latency_lowr_buckets was honoured — this is what the
    # silently-dropped duplicate ``metrics.latency()`` registration never achieved.
    assert re.search(
        r'^tg_parser_http_request_duration_seconds_bucket\{[^}]*le="0\.01"', body, re.M
    ), (
        "the custom latency_lowr_buckets did not reach "
        "tg_parser_http_request_duration_seconds — the histogram fell back to the "
        "library default buckets (0.1, 0.5, 1)"
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


def test_alerts_and_dashboards_query_metric_names_the_app_actually_exposes(monkeypatch) -> None:
    """Every ``tg_parser_http_*`` name in alerts/dashboards must exist at /metrics.

    The guard for BUG-089: the app emitted ``tg_parser_http_http_*`` (namespace +
    a subsystem on top of the library's already ``http_``-prefixed base names)
    while the alert rule and the dashboard panels queried the single-prefixed
    names, so one alert could never fire and three panels were permanently empty.
    Nothing compared the two sides. This test does, in both directions: a rename
    in the app or in a consumer breaks it.
    """
    monkeypatch.setenv("METRICS_ENABLED", "true")
    from tg_parser.config import settings

    monkeypatch.setattr(settings, "metrics_enabled", True, raising=False)

    client = TestClient(_build_instrumented_app())
    assert client.get(_PING_PATH).status_code == 200
    exposed = _exposed_metric_names(client.get("/metrics").text)

    checked: set[str] = set()
    missing: list[str] = []
    for path in (_ALERTS_YML, _SYSTEM_DASHBOARD):
        assert path.is_file(), f"consumer config not found: {path} — has it moved?"
        for name in sorted(_referenced_http_metric_names(path)):
            if name in _NOT_EXPOSABLE_IN_ISOLATED_REGISTRY:
                continue
            checked.add(name)
            if not _is_exposed(name, exposed):
                missing.append(f"{name} (referenced by {path.relative_to(_REPO_ROOT)})")

    # Guard against a vacuous pass if a consumer file is emptied or the regex rots.
    assert len(checked) >= 2, (
        f"only {len(checked)} tg_parser_http_* references found in "
        f"{_ALERTS_YML.name} + {_SYSTEM_DASHBOARD.name} — the extraction is "
        "probably broken, so this test is no longer guarding anything"
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
    from tg_parser.api.metrics import create_instrumentator

    referenced = _referenced_http_metric_names(_SYSTEM_DASHBOARD)
    assert _NOT_EXPOSABLE_IN_ISOLATED_REGISTRY <= referenced, (
        "the dashboard no longer references "
        f"{sorted(_NOT_EXPOSABLE_IN_ISOLATED_REGISTRY)} — drop the exclusion so the "
        "cross-check test covers everything again"
    )
    assert create_instrumentator().inprogress_name in referenced
