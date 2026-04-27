"""Regression tests for ``docker/f5c_watch.sh`` Tripwire #4 delta logic.

TD-NEW-B (2026-04-27): pre-fix the helper compared the cumulative
``tg_parser_anthropic_billing_block_total`` against zero, so once any
billing event ever occurred the alarm fired forever (until the API
container was restarted, which reset the in-memory counter). After the
fix the helper persists the previous tick's value to a state file under
``${F5C_WATCH_STATE_DIR}/billing_block_state`` and alarms only on a
positive delta between consecutive runs.

These tests don't drive ``f5c_watch.sh`` end-to-end (it requires
``docker compose`` and a live ``/metrics`` endpoint). Instead we exercise
a verbatim bash transcript of the delta block, which is the only piece
that changed in TD-NEW-B. If the inline block in ``f5c_watch.sh`` drifts
from the version below, the diff will be visible in PR review and these
tests will continue to lock in the *intent* of the fix.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

# Verbatim mirror of the Tripwire #4 delta block from
# ``docker/f5c_watch.sh`` (rev 2026-04-27 / TD-NEW-B). Keep this in sync
# manually if the inline block changes — see test
# ``test_state_file_path_matches_runbook`` for the contract on
# F5C_WATCH_STATE_DIR.
DELTA_BLOCK = textwrap.dedent(
    r"""
    PAUSED="$1"

    STATE_DIR="${F5C_WATCH_STATE_DIR:-${HOME}/.f5c-watch}"
    STATE_FILE="${STATE_DIR}/billing_block_state"
    PREV_PAUSED_RAW=""
    if [[ -r "$STATE_FILE" ]]; then
        PREV_PAUSED_RAW="$(cat "$STATE_FILE" 2>/dev/null || true)"
        PREV_PAUSED_RAW="${PREV_PAUSED_RAW//[^0-9]/}"
    fi

    mkdir -p "$STATE_DIR" 2>/dev/null || true
    echo "$PAUSED" > "$STATE_FILE" 2>/dev/null || true

    TRIP=""
    if [[ -z "$PREV_PAUSED_RAW" ]]; then
        echo "log:first-run cumulative=${PAUSED}"
    else
        PAUSED_DELTA=$((PAUSED - PREV_PAUSED_RAW))
        if [[ "$PAUSED_DELTA" -lt 0 ]]; then
            echo "log:reset cumulative=${PAUSED} prev=${PREV_PAUSED_RAW}"
            PAUSED_DELTA=0
        elif [[ "$PAUSED_DELTA" -gt 0 ]]; then
            TRIP="alarm:delta=${PAUSED_DELTA} cumulative=${PAUSED}"
            echo "log:alarm delta=${PAUSED_DELTA} cumulative=${PAUSED} prev=${PREV_PAUSED_RAW}"
        else
            echo "log:ok delta=0 cumulative=${PAUSED} prev=${PREV_PAUSED_RAW}"
        fi
    fi
    if [[ -n "$TRIP" ]]; then
        echo "$TRIP"
    fi
    """
).strip()


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / "f5c-watch-state"


def _run_tick(state_dir: Path, paused: int) -> str:
    """Invoke the delta block once with the given cumulative counter."""
    script = f"""
    set -euo pipefail
    export F5C_WATCH_STATE_DIR={state_dir}
    {DELTA_BLOCK}
    """
    result = subprocess.run(
        ["bash", "-c", script, "_", str(paused)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_first_run_no_baseline_no_alarm(state_dir: Path) -> None:
    """First run after deploy: no state file → warm-up tick, no alarm."""
    out = _run_tick(state_dir, 60)
    assert "log:first-run cumulative=60" in out
    assert "alarm:" not in out
    assert (state_dir / "billing_block_state").read_text().strip() == "60"


def test_steady_state_no_new_events_no_alarm(state_dir: Path) -> None:
    """Counter unchanged between ticks → no alarm. THE TD-NEW-B regression."""
    _run_tick(state_dir, 60)
    out = _run_tick(state_dir, 60)
    assert "log:ok delta=0" in out
    assert "alarm:" not in out


def test_counter_increased_alarms_with_delta(state_dir: Path) -> None:
    """Counter delta > 0 → ALARM with delta in message."""
    _run_tick(state_dir, 60)
    out = _run_tick(state_dir, 65)
    assert "log:alarm delta=5 cumulative=65 prev=60" in out
    assert "alarm:delta=5 cumulative=65" in out


def test_post_recovery_no_alarm_after_alarm(state_dir: Path) -> None:
    """After an alarm tick, if no new events occur the next tick is GREEN."""
    _run_tick(state_dir, 60)
    _run_tick(state_dir, 65)
    out = _run_tick(state_dir, 65)
    assert "log:ok delta=0" in out
    assert "alarm:" not in out


def test_counter_reset_no_alarm(state_dir: Path) -> None:
    """Container restart resets counter (prev > current) → no alarm, logged."""
    _run_tick(state_dir, 65)
    out = _run_tick(state_dir, 2)
    assert "log:reset cumulative=2 prev=65" in out
    assert "alarm:" not in out


def test_post_restart_steady_state_no_alarm(state_dir: Path) -> None:
    """After a counter reset, the next steady-state tick reports ok delta=0."""
    _run_tick(state_dir, 65)
    _run_tick(state_dir, 2)
    out = _run_tick(state_dir, 2)
    assert "log:ok delta=0 cumulative=2 prev=2" in out
    assert "alarm:" not in out


def test_corrupt_state_file_treated_as_first_run(state_dir: Path) -> None:
    """If the state file is corrupted (non-numeric), we treat it as no baseline."""
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "billing_block_state").write_text("not-a-number\n")
    out = _run_tick(state_dir, 7)
    assert "log:first-run cumulative=7" in out
    assert "alarm:" not in out
    assert (state_dir / "billing_block_state").read_text().strip() == "7"


def test_inline_block_in_script_matches_test_block() -> None:
    """Spot-check that ``docker/f5c_watch.sh`` still contains the canonical
    state-file path used by this test, so silent drift between the test and
    the live script is visible in PR review.
    """
    script = (Path(__file__).parent.parent / "docker" / "f5c_watch.sh").read_text()
    assert 'STATE_DIR="${F5C_WATCH_STATE_DIR:-${HOME}/.f5c-watch}"' in script
    assert 'STATE_FILE="${STATE_DIR}/billing_block_state"' in script
    assert "PAUSED_DELTA=$((PAUSED - PREV_PAUSED_RAW))" in script


def test_bash_available() -> None:
    """Sanity: this test suite needs bash to be installed (CI runners have it)."""
    assert shutil.which("bash") is not None
