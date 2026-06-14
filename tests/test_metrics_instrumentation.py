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

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry
from prometheus_fastapi_instrumentator import Instrumentator, metrics

# NB: must NOT contain the substring "/metrics" — excluded_handlers patterns
# are unanchored ``re.search`` regexes, so a path like ".../metrics-ping" would
# be silently excluded from instrumentation and break the recording assertion.
_PING_PATH = "/api/v1/regression/ping"


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
            metric_subsystem="http",
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
    # metrics.default base name is ``http_requests_total``; with
    # namespace=tg_parser + subsystem=http the exposed series is
    # ``tg_parser_http_http_requests_total`` (matches prod's create_instrumentator).
    assert "tg_parser_http_http_requests_total" in body, (
        "instrumentator did not expose the http request counter — metrics were "
        "not wired through the instrument()/expose() path"
    )
    assert f'handler="{_PING_PATH}"' in body, (
        "the include_router route was not recorded by the instrumentator — the "
        "per-request middleware did not resolve the route path"
    )
