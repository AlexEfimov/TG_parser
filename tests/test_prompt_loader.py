"""
Тесты для PromptLoader (v1.1 Configurable Prompts).
"""

from pathlib import Path

import pytest

from tg_parser.processing.prompt_loader import (
    PromptLoader,
    get_prompt_loader,
    set_prompt_loader,
)


class TestPromptLoaderDefaults:
    """Тесты fallback на defaults."""

    def test_load_processing_defaults(self):
        """Test loading default processing prompts."""
        loader = PromptLoader(prompts_dir=Path("/nonexistent"))
        
        config = loader.load("processing")
        
        assert config is not None
        assert "system" in config
        assert "user" in config
        assert "model" in config
        assert config["system"]["prompt"]
        assert "text_clean" in config["system"]["prompt"]

    def test_load_topicization_defaults(self):
        """Test loading default topicization prompts."""
        loader = PromptLoader(prompts_dir=Path("/nonexistent"))
        
        config = loader.load("topicization")
        
        assert config is not None
        assert "system" in config
        assert "user" in config
        assert "topics" in config["system"]["prompt"]

    def test_load_supporting_items_defaults(self):
        """Test loading default supporting items prompts."""
        loader = PromptLoader(prompts_dir=Path("/nonexistent"))
        
        config = loader.load("supporting_items")
        
        assert config is not None
        assert "system" in config
        assert "supporting_items" in config["system"]["prompt"]

    def test_unknown_prompt_returns_empty(self):
        """Test loading unknown prompt returns empty dict."""
        loader = PromptLoader(prompts_dir=Path("/nonexistent"))
        
        config = loader.load("unknown_prompt_type")
        
        assert config == {}


class TestPromptLoaderHelpers:
    """Тесты helper методов."""

    def test_get_system_prompt(self):
        """Test getting system prompt."""
        loader = PromptLoader(prompts_dir=Path("/nonexistent"))
        
        system_prompt = loader.get_system_prompt("processing")
        
        assert system_prompt
        assert "text_clean" in system_prompt
        assert "JSON" in system_prompt

    def test_get_user_template(self):
        """Test getting user template."""
        loader = PromptLoader(prompts_dir=Path("/nonexistent"))
        
        template = loader.get_user_template("processing")
        
        assert template
        assert "{text}" in template

    def test_get_model_settings(self):
        """Test getting model settings."""
        loader = PromptLoader(prompts_dir=Path("/nonexistent"))
        
        settings = loader.get_model_settings("processing")
        
        assert settings
        assert settings.get("temperature") == 0
        assert settings.get("max_tokens") == 4096

    def test_get_metadata(self):
        """Test getting metadata."""
        loader = PromptLoader(prompts_dir=Path("/nonexistent"))
        
        metadata = loader.get_metadata("processing")
        
        assert metadata
        assert "version" in metadata


class TestPromptLoaderYAML:
    """Тесты загрузки из YAML файлов."""

    def test_load_from_yaml_file(self, tmp_path: Path):
        """Test loading prompts from YAML file."""
        # Create custom prompts directory
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        
        # Create custom processing.yaml
        yaml_content = """
metadata:
  version: "2.0.0"
  description: "Custom processing prompts"

system:
  prompt: "Custom system prompt for testing"

user:
  template: "Custom user template: {text}"
  variables:
    - text

model:
  temperature: 0.1
  max_tokens: 2048
"""
        (prompts_dir / "processing.yaml").write_text(yaml_content)
        
        # Load and verify
        loader = PromptLoader(prompts_dir=prompts_dir)
        config = loader.load("processing")
        
        assert config["metadata"]["version"] == "2.0.0"
        assert config["system"]["prompt"] == "Custom system prompt for testing"
        assert config["user"]["template"] == "Custom user template: {text}"
        assert config["model"]["temperature"] == 0.1
        assert config["model"]["max_tokens"] == 2048

    def test_yaml_fallback_on_missing_file(self, tmp_path: Path):
        """Test fallback to defaults when YAML file is missing."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        
        # Create only processing.yaml, not topicization.yaml
        (prompts_dir / "processing.yaml").write_text("system:\n  prompt: 'Custom'")
        
        loader = PromptLoader(prompts_dir=prompts_dir)
        
        # processing should use custom
        processing_config = loader.load("processing")
        assert processing_config["system"]["prompt"] == "Custom"
        
        # topicization should use default
        topicization_config = loader.load("topicization")
        assert "topics" in topicization_config["system"]["prompt"]

    def test_invalid_yaml_fallback(self, tmp_path: Path):
        """Test fallback to defaults on invalid YAML."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        
        # Create invalid YAML
        (prompts_dir / "processing.yaml").write_text("invalid: yaml: content: [[[")
        
        loader = PromptLoader(prompts_dir=prompts_dir)
        config = loader.load("processing")
        
        # Should fallback to default
        assert "text_clean" in config["system"]["prompt"]


class TestPromptLoaderCaching:
    """Тесты кэширования."""

    def test_caching_works(self, tmp_path: Path):
        """Test that prompts are cached."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        
        yaml_file = prompts_dir / "processing.yaml"
        yaml_file.write_text("system:\n  prompt: 'Original'")
        
        loader = PromptLoader(prompts_dir=prompts_dir)
        
        # First load
        config1 = loader.load("processing")
        assert config1["system"]["prompt"] == "Original"
        
        # Modify file
        yaml_file.write_text("system:\n  prompt: 'Modified'")
        
        # Second load should return cached
        config2 = loader.load("processing")
        assert config2["system"]["prompt"] == "Original"  # Still cached

    def test_clear_cache(self, tmp_path: Path):
        """Test clearing cache."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        
        yaml_file = prompts_dir / "processing.yaml"
        yaml_file.write_text("system:\n  prompt: 'Original'")
        
        loader = PromptLoader(prompts_dir=prompts_dir)
        
        # First load
        loader.load("processing")
        
        # Modify file
        yaml_file.write_text("system:\n  prompt: 'Modified'")
        
        # Clear cache and reload
        loader.clear_cache()
        config = loader.load("processing")
        
        assert config["system"]["prompt"] == "Modified"

    def test_reload_specific(self, tmp_path: Path):
        """Test reloading specific prompt."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        
        processing_file = prompts_dir / "processing.yaml"
        processing_file.write_text("system:\n  prompt: 'Processing v1'")
        
        topicization_file = prompts_dir / "topicization.yaml"
        topicization_file.write_text("system:\n  prompt: 'Topicization v1'")
        
        loader = PromptLoader(prompts_dir=prompts_dir)
        
        # Load both
        loader.load("processing")
        loader.load("topicization")
        
        # Modify only processing
        processing_file.write_text("system:\n  prompt: 'Processing v2'")
        topicization_file.write_text("system:\n  prompt: 'Topicization v2'")
        
        # Reload only processing
        loader.reload("processing")
        
        # Processing should be updated, topicization still cached
        assert loader.load("processing")["system"]["prompt"] == "Processing v2"
        assert loader.load("topicization")["system"]["prompt"] == "Topicization v1"


class TestGlobalPromptLoader:
    """Тесты глобального PromptLoader."""

    def test_get_default_loader(self):
        """Test getting default global loader."""
        # Reset global state
        set_prompt_loader(PromptLoader())
        
        loader = get_prompt_loader()
        
        assert loader is not None
        assert isinstance(loader, PromptLoader)

    def test_set_custom_loader(self, tmp_path: Path):
        """Test setting custom global loader."""
        custom_loader = PromptLoader(prompts_dir=tmp_path)
        
        set_prompt_loader(custom_loader)
        
        assert get_prompt_loader() is custom_loader


class TestPromptLoaderIntegration:
    """Интеграционные тесты."""

    def test_format_user_prompt(self):
        """Test formatting user prompt with variables."""
        loader = PromptLoader(prompts_dir=Path("/nonexistent"))
        
        template = loader.get_user_template("processing")
        formatted = template.format(text="Test message content")
        
        assert "Test message content" in formatted

    def test_real_prompts_directory(self):
        """Test loading from real prompts directory."""
        # Check if prompts directory exists in project root
        project_root = Path(__file__).parent.parent
        prompts_dir = project_root / "prompts"
        
        if prompts_dir.exists():
            loader = PromptLoader(prompts_dir=prompts_dir)
            
            # Should load from YAML files
            config = loader.load("processing")
            
            assert config is not None
            assert "system" in config
            assert config["system"]["prompt"]

