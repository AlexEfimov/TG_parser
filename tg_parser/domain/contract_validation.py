"""
Валидация объектов против JSON Schema контрактов из `docs/contracts/`.

Реализует TR-IF-1: обмен между модулями через структуры из контрактов.
TR-IF-2: изменения в контрактах должны сопровождаться тестами.
"""

import json
from pathlib import Path
from typing import Any, Dict

import jsonschema
from jsonschema import Draft7Validator


# Путь к директории контрактов относительно корня проекта
CONTRACTS_DIR = Path(__file__).parent.parent.parent / "docs" / "contracts"


class ContractValidator:
    """
    Валидатор доменных объектов против JSON Schema контрактов.
    
    Использование:
    ```python
    validator = ContractValidator()
    validator.validate_raw_message(raw_msg_dict)
    validator.validate_processed_document(processed_doc_dict)
    ```
    """
    
    def __init__(self, contracts_dir: Path = CONTRACTS_DIR):
        """
        Args:
            contracts_dir: Путь к директории с JSON Schema файлами
        """
        self.contracts_dir = contracts_dir
        self._schemas: Dict[str, Any] = {}
        self._validators: Dict[str, Draft7Validator] = {}
    
    def _load_schema(self, schema_name: str) -> Any:
        """Загрузить JSON Schema из файла."""
        if schema_name not in self._schemas:
            schema_path = self.contracts_dir / f"{schema_name}.schema.json"
            if not schema_path.exists():
                raise FileNotFoundError(f"Schema not found: {schema_path}")
            
            with open(schema_path, "r", encoding="utf-8") as f:
                self._schemas[schema_name] = json.load(f)
        
        return self._schemas[schema_name]
    
    def _get_validator(self, schema_name: str) -> Draft7Validator:
        """Получить валидатор для схемы."""
        if schema_name not in self._validators:
            schema = self._load_schema(schema_name)
            self._validators[schema_name] = Draft7Validator(schema)
        
        return self._validators[schema_name]
    
    def validate(self, schema_name: str, obj: Dict[str, Any]) -> None:
        """
        Валидировать объект против схемы.
        
        Args:
            schema_name: Имя схемы (без .schema.json)
            obj: Объект для валидации (dict)
            
        Raises:
            jsonschema.ValidationError: если объект не соответствует схеме
        """
        validator = self._get_validator(schema_name)
        validator.validate(obj)
    
    # Convenience methods для каждого контракта
    
    def validate_raw_message(self, obj: Dict[str, Any]) -> None:
        """Валидировать RawTelegramMessage."""
        self.validate("raw_telegram_message", obj)
    
    def validate_processed_document(self, obj: Dict[str, Any]) -> None:
        """Валидировать ProcessedDocument."""
        self.validate("processed_document", obj)
    
    def validate_topic_card(self, obj: Dict[str, Any]) -> None:
        """Валидировать TopicCard."""
        self.validate("topic_card", obj)
    
    def validate_topic_bundle(self, obj: Dict[str, Any]) -> None:
        """Валидировать TopicBundle."""
        self.validate("topic_bundle", obj)
    
    def validate_knowledge_base_entry(self, obj: Dict[str, Any]) -> None:
        """Валидировать KnowledgeBaseEntry."""
        self.validate("knowledge_base_entry", obj)


# Глобальный экземпляр для удобства
_default_validator = ContractValidator()


def validate_contract(schema_name: str, obj: Dict[str, Any]) -> None:
    """
    Валидировать объект против контракта (глобальный helper).
    
    Args:
        schema_name: Имя схемы
        obj: Объект для валидации
        
    Raises:
        jsonschema.ValidationError: если объект не соответствует схеме
    """
    _default_validator.validate(schema_name, obj)
