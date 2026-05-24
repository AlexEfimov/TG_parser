"""Contract tests for docs/contracts/subscription_target.schema.json."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "docs/contracts/subscription_target.schema.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "instance",
    [
        {"kind": "chat", "chat_id": 42},
        {"kind": "channel", "channel_id": "@digest"},
        {"kind": "channel", "channel_id": "-1001234567890"},
    ],
)
def test_subscription_target_valid_examples(schema: dict, instance: dict) -> None:
    jsonschema.validate(instance=instance, schema=schema)


@pytest.mark.parametrize(
    "instance",
    [
        # kind=webhook is anti-scope (Wave 2A) — schema must reject.
        {"kind": "webhook", "webhook_url": "https://example.com/hook"},
        # missing required discriminated key
        {"kind": "chat"},
        {"kind": "channel"},
        # empty channel_id (minLength=1)
        {"kind": "channel", "channel_id": ""},
        # missing kind discriminator entirely
        {"chat_id": 1},
        # discriminator/type mismatch — channel_id on chat variant
        {"kind": "chat", "channel_id": "@x"},
        # extra field on chat variant (additionalProperties=false)
        {"kind": "chat", "chat_id": 1, "channel_id": "@x"},
        # extra field on channel variant
        {"kind": "channel", "channel_id": "@x", "chat_id": 1},
        # wrong type for chat_id (must be integer)
        {"kind": "chat", "chat_id": "not-an-int"},
    ],
)
def test_subscription_target_rejects_invalid(schema: dict, instance: dict) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=instance, schema=schema)


def test_subscription_target_examples_field_is_self_consistent(schema: dict) -> None:
    """Each ``examples`` entry shipped in the schema must validate against it
    (regression: trailing-comma / shape drift between docs and validators)."""
    for example in schema["examples"]:
        jsonschema.validate(instance=example, schema=schema)
