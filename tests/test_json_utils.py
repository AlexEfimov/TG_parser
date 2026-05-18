"""
Tests for tg_parser/domain/json_utils.py.

Covers stable_json_dumps, stable_json_loads, parse_iso_datetime,
and the custom _json_default serializer.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from tg_parser.domain.json_utils import (
    coerce_aware_utc,
    parse_iso_datetime,
    stable_json_dumps,
    stable_json_loads,
)


class TestStableJsonDumps:
    def test_sort_keys_deterministic(self):
        obj = {"z": 1, "a": 2, "m": 3}
        result = stable_json_dumps(obj)
        assert result == '{"a":2,"m":3,"z":1}'

    def test_compact_separators(self):
        obj = {"key": "value"}
        result = stable_json_dumps(obj)
        assert " " not in result
        assert result == '{"key":"value"}'

    def test_pretty_mode(self):
        obj = {"b": 2, "a": 1}
        result = stable_json_dumps(obj, pretty=True)
        assert "\n" in result
        assert "  " in result
        lines = result.strip().splitlines()
        assert '"a": 1' in lines[1]

    def test_unicode_preserved(self):
        obj = {"текст": "Привет"}
        result = stable_json_dumps(obj)
        assert "текст" in result
        assert "Привет" in result
        assert "\\u" not in result

    def test_datetime_serialization(self):
        dt = datetime(2025, 12, 13, 10, 0, 0)
        result = stable_json_dumps({"ts": dt})
        assert '"ts":"2025-12-13T10:00:00Z"' in result

    def test_datetime_with_timezone(self):
        dt = datetime(2025, 12, 13, 10, 0, 0, tzinfo=UTC)
        result = stable_json_dumps({"ts": dt})
        assert "2025-12-13" in result

    def test_unsupported_type_raises(self):
        with pytest.raises(TypeError):
            stable_json_dumps({"val": object()})


class TestStableJsonLoads:
    def test_roundtrip(self):
        original = {"a": 1, "b": [2, 3], "c": {"nested": True}}
        serialized = stable_json_dumps(original)
        result = stable_json_loads(serialized)
        assert result == original

    def test_loads_string(self):
        result = stable_json_loads('{"key": "value"}')
        assert result == {"key": "value"}


class TestParseIsoDatetime:
    def test_with_z_suffix(self):
        dt = parse_iso_datetime("2025-12-13T10:00:00Z")
        assert dt == datetime(2025, 12, 13, 10, 0, 0)
        assert dt.tzinfo is None

    def test_without_z_suffix(self):
        dt = parse_iso_datetime("2025-12-13T10:00:00")
        assert dt == datetime(2025, 12, 13, 10, 0, 0)

    def test_with_timezone_offset(self):
        dt = parse_iso_datetime("2025-12-13T10:00:00+03:00")
        assert dt.tzinfo is not None
        assert dt.hour == 10

    def test_with_microseconds(self):
        dt = parse_iso_datetime("2025-12-13T10:00:00.123456Z")
        assert dt.microsecond == 123456


class TestCoerceAwareUtc:
    """BUG-014 / BUG-014B helper contract — locks idempotent aware-coerce behavior."""

    def test_none_passes_through(self):
        assert coerce_aware_utc(None) is None

    def test_naive_gets_utc_attached(self):
        naive = datetime(2026, 5, 15, 16, 2, 4)
        assert naive.tzinfo is None
        result = coerce_aware_utc(naive)
        assert result is not None
        assert result.tzinfo == UTC
        assert result.replace(tzinfo=None) == naive

    def test_aware_utc_is_identity(self):
        aware = datetime(2026, 5, 15, 16, 2, 4, tzinfo=UTC)
        result = coerce_aware_utc(aware)
        assert result is aware

    def test_aware_non_utc_is_preserved(self):
        tz_plus3 = timezone(timedelta(hours=3))
        aware_other_tz = datetime(2026, 5, 15, 19, 2, 4, tzinfo=tz_plus3)
        result = coerce_aware_utc(aware_other_tz)
        assert result is aware_other_tz
        assert result.tzinfo == tz_plus3
