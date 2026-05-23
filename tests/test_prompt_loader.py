"""
Тесты для PromptLoader (v1.1 Configurable Prompts).
"""

from pathlib import Path

import pytest

from tg_parser.processing.prompt_loader import (
    REQUIRED_PROMPT_STAGES,
    PromptLoader,
    PromptLoaderError,
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


class TestRequiredStagesFailLoud:
    """TD-03c: required-stage prompts must fail-loud, never silently empty.

    The pre-TD-03c behaviour was to return ``{}`` from ``_get_default`` for
    any stage missing from the built-in registry, and to silently cache
    that empty config. A subsequent ``get_system_prompt`` would then return
    ``""``, handing the LLM a no-op instruction. These tests pin the
    fail-loud contract introduced in TD-03c (post-Living-KB Phase 2).
    """

    def test_required_stages_match_llm_scopes(self):
        """REQUIRED_PROMPT_STAGES stays in sync with config.LLM_SCOPES."""
        from tg_parser.config.settings import LLM_SCOPES

        assert REQUIRED_PROMPT_STAGES == set(LLM_SCOPES) - {"global"}

    @pytest.mark.parametrize("stage", sorted(REQUIRED_PROMPT_STAGES))
    def test_required_stage_raises_when_yaml_and_default_both_empty(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        stage: str,
    ):
        """Both YAML missing AND built-in default empty → PromptLoaderError."""
        loader = PromptLoader(prompts_dir=tmp_path / "nonexistent")

        monkeypatch.setattr(loader, "_get_default", lambda name: {})

        with pytest.raises(PromptLoaderError) as exc_info:
            loader.load(stage)

        message = str(exc_info.value)
        assert stage in message
        assert "required stage" in message

    def test_required_stage_raises_when_yaml_lacks_system_prompt(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """YAML present but missing ``system.prompt`` falls through to default;
        if default is also empty, raise."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "digest.yaml").write_text("metadata:\n  version: '1.0.0'\n")

        loader = PromptLoader(prompts_dir=prompts_dir)
        monkeypatch.setattr(loader, "_get_default", lambda name: {})

        with pytest.raises(PromptLoaderError):
            loader.load("digest")

    def test_required_stage_raises_when_yaml_system_prompt_blank(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Whitespace-only ``system.prompt`` is treated as empty."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "rag.yaml").write_text('system:\n  prompt: "     "\n')

        loader = PromptLoader(prompts_dir=prompts_dir)
        monkeypatch.setattr(loader, "_get_default", lambda name: {})

        with pytest.raises(PromptLoaderError):
            loader.load("rag")

    def test_nonrequired_stage_still_returns_empty_on_unknown(self):
        """Stages outside REQUIRED_PROMPT_STAGES preserve the soft fallback.

        ``bot``, ``merge``, ``supporting_items``, ``incremental_discover``,
        ``unknown_*`` etc. retain pre-TD-03c behaviour so that callers
        inspecting auxiliary prompts never trigger an exception.
        """
        loader = PromptLoader(prompts_dir=Path("/nonexistent"))

        config = loader.load("unknown_prompt_type")

        assert config == {}

    def test_validate_required_stages_passes_with_real_yamls(self):
        """Real ``prompts/`` directory satisfies the invariant for all stages."""
        project_root = Path(__file__).parent.parent
        prompts_dir = project_root / "prompts"
        if not prompts_dir.exists():
            pytest.skip("prompts/ directory not available in this checkout")

        loader = PromptLoader(prompts_dir=prompts_dir)
        loader.validate_required_stages()

    def test_validate_required_stages_raises_when_one_stage_missing(
        self,
        tmp_path: Path,
    ):
        """validate_required_stages walks the full set; any miss aborts boot.

        Provide healthy YAML for every required stage *except* one to
        prove that the missing stage — not the alphabetically first one —
        is what surfaces in the error.
        """
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        for stage in REQUIRED_PROMPT_STAGES:
            if stage == "resummarize":
                continue
            (prompts_dir / f"{stage}.yaml").write_text(
                f'system:\n  prompt: "minimal {stage} prompt"\n'
            )

        loader = PromptLoader(prompts_dir=prompts_dir)

        with pytest.raises(PromptLoaderError) as exc_info:
            loader.validate_required_stages()

        assert "resummarize" in str(exc_info.value)

    def test_yaml_present_with_content_skips_default_check(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Healthy YAML wins regardless of default-registry state."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "resummarize.yaml").write_text(
            "system:\n  prompt: 'Real resummarize prompt.'\n"
            "user:\n  template: 'Items: {items_json}'\n"
        )

        loader = PromptLoader(prompts_dir=prompts_dir)
        monkeypatch.setattr(loader, "_get_default", lambda name: {})

        config = loader.load("resummarize")
        assert config["system"]["prompt"] == "Real resummarize prompt."


class TestBug028LiteralNoneStringGuard:
    """BUG-028 Layer B: defense-in-depth against literal ``"None"`` string.

    Pre-hotfix, ``scheduler_service.py:560`` did
    ``PromptLoader(prompts_dir=str(settings.prompts_dir))`` — when
    ``settings.prompts_dir`` was ``None`` (the pre-Layer-C default), this
    evaluated to ``PromptLoader(prompts_dir="None")`` because
    ``str(None) == "None"``. ``Path("None")`` is a valid relative path
    (PosixPath('None')), so the loader silently resolved
    ``Path("None/<stage>.yaml")`` — surfaced in production as
    ``YAML at None/digest.yaml did not provide a non-empty system.prompt``.

    Layer A (call-site guard) plus Layer C (sensible default) already
    prevent this for the production code path; Layer B is an explicit
    in-class guard so any *future* call-site that accidentally passes
    ``str(None)`` is rescued rather than silently degraded. This test
    pins the Layer B contract.
    """

    def test_prompt_loader_falls_back_when_literal_None_string_passed(self):
        """``PromptLoader(prompts_dir="None")`` MUST fall back to ``Path("prompts")``.

        The fallback path is what makes the loader recover real YAML; the
        critical anti-regression assertion is that ``prompts_dir`` is *not*
        ``Path("None")`` after construction. Loading ``processing`` then
        resolves real (non-empty) YAML content rather than the empty
        config a non-existent ``None/processing.yaml`` would have yielded.
        """
        loader = PromptLoader(prompts_dir="None")

        assert loader.prompts_dir == Path("prompts"), (
            f"Layer B fallback regressed: prompts_dir={loader.prompts_dir!r} "
            "(expected Path('prompts'))"
        )
        # Anti-regression: must NEVER silently resolve to literal 'None/...'.
        assert loader.prompts_dir != Path("None")
        assert str(loader.prompts_dir) != "None"

        config = loader.load("processing")
        assert isinstance(config, dict) and config, (
            f"processing prompt resolved to empty: {config!r}"
        )
        assert config.get("system", {}).get("prompt", "").strip(), (
            f"processing system.prompt is empty: {config!r}"
        )

    def test_prompt_loader_falls_back_when_pathified_None_string_passed(self):
        """Same fallback must fire when caller pre-wraps the bad string in a Path.

        ``PromptLoader(prompts_dir=Path("None"))`` is the second-order
        artifact of an upstream ``Path(str(settings.prompts_dir))`` mistake.
        The Layer B guard normalises both forms identically because it
        compares ``str(self.prompts_dir) == "None"``.
        """
        loader = PromptLoader(prompts_dir=Path("None"))

        assert loader.prompts_dir == Path("prompts"), (
            f"Layer B fallback (Path form) regressed: {loader.prompts_dir!r}"
        )

        config = loader.load("processing")
        assert config.get("system", {}).get("prompt", "").strip()

    def test_prompt_loader_does_not_falsely_match_paths_containing_None(
        self,
        tmp_path: Path,
    ):
        """Layer B must only trigger on the *literal* string ``"None"``.

        A directory whose name merely *contains* ``None`` (e.g.
        ``/tmp/None-shaped-cache``) is a legitimate path and must be
        accepted verbatim — otherwise the guard would erroneously rescue
        a real, intentional configuration.
        """
        funny_dir = tmp_path / "NoneShapedCache"
        funny_dir.mkdir()

        loader = PromptLoader(prompts_dir=funny_dir)

        assert loader.prompts_dir == funny_dir, (
            "Layer B guard over-triggered: rewrote a legitimate directory "
            f"name to {loader.prompts_dir!r}"
        )
