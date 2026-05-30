"""
BUG-036 regression test: Grafana Wave-1-step-4 alert rules provisioned as code.

Background
----------
The alert rules ``tg_parser_bot_down`` / ``tg_parser_api_down`` /
``tg_api_5xx_spike`` were originally hand-created in the Grafana UI. UI state
did not persist ``noDataState`` across Grafana eval cycles / container
restarts, so the rules kept drifting back to ``Alerting/NoData`` and
re-emitted spurious ``DatasourceNoData`` webhook issues (fingerprint
``47991b0914dd7148``; GitHub #96/#98/#100/#101/#102/#103/#104).

The fix provisions all three rules + the ``cursor-watch-webhook`` contact
point as code at
``docker/grafana/provisioning/alerting/wave1_step4.yaml`` with explicit
``noDataState: OK`` and ``for: 5m``.

What this test does (and does NOT do)
-------------------------------------
This is a *static* validation/idempotency guard: it parses the provisioning
YAML and asserts the schema essentials that make the fix correct, so a future
edit cannot silently re-introduce the drift (e.g. drop ``noDataState: OK`` or
unbind the contact point).

It does NOT spin up a live Grafana — true restart-idempotency requires a
running container and is documented as a manual verification step in the
BUG-036 PR description / runbook. ``yaml`` (PyYAML) is already a project
dependency (see pyproject.toml), so no new deps are introduced.

Placement note: the repo keeps infra/config tests at the top level of
``tests/`` (e.g. ``test_compose_env_propagation.py``,
``test_alembic_ini_consistency.py``), so this test lives there too rather
than in a new ``tests/infra/`` package.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

PROVISIONING_PATH = (
    Path(__file__).resolve().parent.parent
    / "docker"
    / "grafana"
    / "provisioning"
    / "alerting"
    / "wave1_step4.yaml"
)

EXPECTED_RULES = {"tg_parser_bot_down", "tg_parser_api_down", "tg_api_5xx_spike"}
CONTACT_POINT_NAME = "cursor-watch-webhook"
PROMETHEUS_DS_UID = "prometheus"


@pytest.fixture(scope="module")
def provisioning() -> dict:
    assert PROVISIONING_PATH.exists(), f"BUG-036 provisioning file missing: {PROVISIONING_PATH}"
    with PROVISIONING_PATH.open(encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    assert isinstance(loaded, dict), "provisioning YAML must parse to a mapping"
    return loaded


def _all_rules(provisioning: dict) -> list[dict]:
    groups = provisioning.get("groups") or []
    assert groups, "provisioning must declare at least one alert-rule group"
    rules: list[dict] = []
    for group in groups:
        rules.extend(group.get("rules") or [])
    return rules


def _rules_by_title(provisioning: dict) -> dict[str, dict]:
    by_title: dict[str, dict] = {}
    for rule in _all_rules(provisioning):
        title = rule.get("title")
        assert title, f"every rule needs a title: {rule!r}"
        by_title[title] = rule
    return by_title


# ---------------------------------------------------------------------------
# Schema essentials
# ---------------------------------------------------------------------------


def test_api_version_is_1(provisioning: dict) -> None:
    assert provisioning.get("apiVersion") == 1, (
        "Grafana file-based provisioning requires apiVersion: 1"
    )


def test_all_three_rules_present(provisioning: dict) -> None:
    titles = set(_rules_by_title(provisioning))
    missing = EXPECTED_RULES - titles
    assert not missing, f"missing provisioned alert rules: {sorted(missing)}"


@pytest.mark.parametrize("rule_title", sorted(EXPECTED_RULES))
def test_rule_has_nodatastate_ok(provisioning: dict, rule_title: str) -> None:
    """The core BUG-036 invariant: noDataState must be explicitly OK."""
    rule = _rules_by_title(provisioning)[rule_title]
    assert rule.get("noDataState") == "OK", (
        f"{rule_title}: noDataState must be 'OK' to stop DatasourceNoData "
        f"webhook drift (BUG-036), got {rule.get('noDataState')!r}"
    )


@pytest.mark.parametrize("rule_title", sorted(EXPECTED_RULES))
def test_rule_has_for_5m(provisioning: dict, rule_title: str) -> None:
    rule = _rules_by_title(provisioning)[rule_title]
    assert str(rule.get("for")) == "5m", f"{rule_title}: expected for: 5m, got {rule.get('for')!r}"


@pytest.mark.parametrize("rule_title", sorted(EXPECTED_RULES))
def test_rule_uses_prometheus_datasource(provisioning: dict, rule_title: str) -> None:
    rule = _rules_by_title(provisioning)[rule_title]
    data = rule.get("data") or []
    ds_uids = {q.get("datasourceUid") for q in data}
    assert PROMETHEUS_DS_UID in ds_uids, (
        f"{rule_title}: must query the '{PROMETHEUS_DS_UID}' datasource uid, "
        f"got {sorted(u for u in ds_uids if u)}"
    )


@pytest.mark.parametrize("rule_title", sorted(EXPECTED_RULES))
def test_rule_has_condition_and_expr(provisioning: dict, rule_title: str) -> None:
    rule = _rules_by_title(provisioning)[rule_title]
    assert rule.get("condition"), f"{rule_title}: missing condition refId"
    exprs = [
        q.get("model", {}).get("expr")
        for q in (rule.get("data") or [])
        if q.get("datasourceUid") == PROMETHEUS_DS_UID
    ]
    assert any(exprs), f"{rule_title}: no PromQL expr on the prometheus query"


# ---------------------------------------------------------------------------
# Contact point + binding
# ---------------------------------------------------------------------------


def test_contact_point_defined(provisioning: dict) -> None:
    contact_points = provisioning.get("contactPoints") or []
    names = {cp.get("name") for cp in contact_points}
    assert CONTACT_POINT_NAME in names, (
        f"contact point '{CONTACT_POINT_NAME}' must be provisioned, got {sorted(names)}"
    )


def test_contact_point_webhook_not_hardcoded(provisioning: dict) -> None:
    """The webhook URL/token must be env-var references, never plaintext secrets."""
    contact_points = provisioning.get("contactPoints") or []
    cp = next(c for c in contact_points if c.get("name") == CONTACT_POINT_NAME)
    receivers = cp.get("receivers") or []
    assert receivers, f"{CONTACT_POINT_NAME}: must declare at least one receiver"
    url = receivers[0].get("settings", {}).get("url", "")
    assert "${" in url or "$__env" in url, (
        f"{CONTACT_POINT_NAME}: webhook url must reference an env var "
        f"(no hardcoded secret), got {url!r}"
    )


def test_contact_point_bound_in_policies(provisioning: dict) -> None:
    policies = provisioning.get("policies") or []
    receivers = {p.get("receiver") for p in policies}
    # also allow nested route bindings
    for p in policies:
        for route in p.get("routes") or []:
            receivers.add(route.get("receiver"))
    assert CONTACT_POINT_NAME in receivers, (
        f"contact point '{CONTACT_POINT_NAME}' must be bound as a policy "
        f"receiver so it survives restarts, got {sorted(r for r in receivers if r)}"
    )
