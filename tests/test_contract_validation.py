"""
Tests for tg_parser/domain/contract_validation.py.

Validates that ContractValidator correctly checks objects against
the JSON Schema contracts in docs/contracts/.
"""

import pytest
from jsonschema import ValidationError

from tg_parser.domain.contract_validation import ContractValidator, validate_contract


@pytest.fixture
def validator():
    return ContractValidator()


def _valid_raw_message():
    return {
        "id": "987",
        "message_type": "post",
        "source_ref": "tg:channel_123:post:987",
        "channel_id": "channel_123",
        "date": "2025-12-13T10:00:00Z",
        "text": "Пост с полезной информацией.",
    }


def _valid_processed_document():
    return {
        "id": "doc:tg:channel_123:post:987",
        "source_ref": "tg:channel_123:post:987",
        "source_message_id": "987",
        "channel_id": "channel_123",
        "processed_at": "2025-12-13T10:30:00Z",
        "text_clean": "Очищенный текст.",
    }


class TestValidateRawMessage:
    def test_valid_raw_message(self, validator):
        validator.validate_raw_message(_valid_raw_message())

    def test_invalid_raw_message_missing_required(self, validator):
        invalid = {"id": "1", "text": "no other fields"}
        with pytest.raises(ValidationError):
            validator.validate_raw_message(invalid)

    def test_invalid_raw_message_bad_type(self, validator):
        msg = _valid_raw_message()
        msg["message_type"] = "story"
        with pytest.raises(ValidationError):
            validator.validate_raw_message(msg)


class TestValidateProcessedDocument:
    def test_valid_processed_document(self, validator):
        validator.validate_processed_document(_valid_processed_document())

    def test_invalid_processed_document(self, validator):
        with pytest.raises(ValidationError):
            validator.validate_processed_document({"id": "x"})


class TestValidateUnknownSchema:
    def test_unknown_schema_raises_file_not_found(self, validator):
        with pytest.raises(FileNotFoundError):
            validator.validate("nonexistent_schema", {})


class TestGlobalHelper:
    def test_validate_contract_helper(self):
        validate_contract("raw_telegram_message", _valid_raw_message())

    def test_validate_contract_helper_invalid(self):
        with pytest.raises(ValidationError):
            validate_contract("raw_telegram_message", {})
