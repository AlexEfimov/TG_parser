"""
Tests for RAG & Prompt Config (Wave 1.5):
- LLMConfigManager: scope 'rag', temperature/max_tokens in overrides, resolve_full()
- PromptLoader: new defaults (rag, bot, incremental_discover, merge)
- retrieval_service: system/user split, source_ref, topic context, YAML-driven
- reload_prompts bot tool
- MCP server tools: set_llm_config, reload_prompts, reset_llm_config
- topicization wiring with PromptLoader
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# LLMConfigManager: scope 'rag', temperature/max_tokens, resolve_full()
# ---------------------------------------------------------------------------


class TestLLMConfigManagerRagScope:
    def _make_manager(self):
        from tg_parser.config.settings import LLMConfigManager

        LLMConfigManager.reset()
        mock_settings = MagicMock(spec=[])
        mock_settings.llm_provider = "openai"
        mock_settings.llm_model = "gpt-4o-mini"
        mock_settings.openai_api_key = "sk-test"
        mock_settings.anthropic_api_key = "sk-ant-test"
        mock_settings.gemini_api_key = "gemini-key"
        mock_settings.google_api_key = None
        return LLMConfigManager(mock_settings)

    def test_rag_in_scopes(self):
        from tg_parser.config.settings import LLM_SCOPES

        assert "rag" in LLM_SCOPES

    def test_set_rag_scope(self):
        mgr = self._make_manager()
        result = mgr.set(scope="rag", provider="anthropic", model="claude-sonnet")
        assert result["stages"]["rag"]["provider"] == "anthropic"
        assert result["stages"]["rag"]["model"] == "claude-sonnet"
        assert result["stages"]["rag"]["overridden"] is True

    def test_set_with_temperature_and_max_tokens(self):
        mgr = self._make_manager()
        result = mgr.set(
            scope="rag",
            provider="openai",
            temperature=0.3,
            max_tokens=4096,
        )
        assert result["stages"]["rag"]["temperature"] == 0.3
        assert result["stages"]["rag"]["max_tokens"] == 4096

    def test_resolve_full_with_overrides(self):
        mgr = self._make_manager()
        mgr.set(
            scope="rag",
            provider="anthropic",
            model="claude-sonnet",
            temperature=0.5,
            max_tokens=1024,
        )
        full = mgr.resolve_full("rag")
        assert full["provider"] == "anthropic"
        assert full["model"] == "claude-sonnet"
        assert full["temperature"] == 0.5
        assert full["max_tokens"] == 1024
        assert full["api_key"] == "sk-ant-test"

    def test_resolve_full_no_overrides(self):
        mgr = self._make_manager()
        full = mgr.resolve_full("rag")
        assert full["provider"] == "openai"
        assert full["model"] == "gpt-4o-mini"
        assert full["temperature"] is None
        assert full["max_tokens"] is None

    def test_resolve_full_global_override_affects_rag(self):
        mgr = self._make_manager()
        mgr.set(scope="global", provider="gemini", temperature=0.7)
        full = mgr.resolve_full("rag")
        assert full["provider"] == "gemini"
        assert full["temperature"] == 0.7

    def test_stage_override_beats_global(self):
        mgr = self._make_manager()
        mgr.set(scope="global", provider="gemini", temperature=0.7)
        mgr.set(scope="rag", provider="anthropic", temperature=0.1)
        full = mgr.resolve_full("rag")
        assert full["provider"] == "anthropic"
        assert full["temperature"] == 0.1

    def test_resolve_full_temperature_zero_not_falsy(self):
        """temperature=0.0 is a valid override — must not fall through to global."""
        mgr = self._make_manager()
        mgr.set(scope="global", provider="openai", temperature=0.9)
        mgr.set(scope="rag", provider="openai", temperature=0.0)
        full = mgr.resolve_full("rag")
        assert full["temperature"] == 0.0

    def test_resolve_full_max_tokens_zero_not_falsy(self):
        """max_tokens=0 (edge case) must not fall through to global."""
        mgr = self._make_manager()
        mgr.set(scope="global", provider="openai", max_tokens=8192)
        mgr.set(scope="rag", provider="openai", max_tokens=0)
        full = mgr.resolve_full("rag")
        assert full["max_tokens"] == 0

    def test_get_all_includes_rag(self):
        mgr = self._make_manager()
        result = mgr.get_all()
        assert "rag" in result["stages"]
        assert "processing" in result["stages"]
        assert "topicization" in result["stages"]

    def test_get_all_temperature_zero_preserved(self):
        """get_all() must report temperature=0.0, not skip it."""
        mgr = self._make_manager()
        mgr.set(scope="rag", provider="openai", temperature=0.0)
        result = mgr.get_all()
        assert result["stages"]["rag"]["temperature"] == 0.0

    def test_get_all_stage_temp_zero_not_replaced_by_global(self):
        """Stage-level 0.0 must not be replaced by global 0.7."""
        mgr = self._make_manager()
        mgr.set(scope="global", provider="openai", temperature=0.7)
        mgr.set(scope="rag", provider="openai", temperature=0.0)
        result = mgr.get_all()
        assert result["stages"]["rag"]["temperature"] == 0.0

    def test_clear_rag_scope(self):
        mgr = self._make_manager()
        mgr.set(scope="rag", provider="anthropic")
        mgr.clear(scope="rag")
        full = mgr.resolve_full("rag")
        assert full["provider"] == "openai"

    def test_resolve_full_for_processing_scope(self):
        """resolve_full works for non-rag stages too."""
        mgr = self._make_manager()
        mgr.set(scope="processing", provider="gemini", temperature=0.4, max_tokens=2000)
        full = mgr.resolve_full("processing")
        assert full["provider"] == "gemini"
        assert full["temperature"] == 0.4
        assert full["max_tokens"] == 2000

    def test_set_invalid_scope_raises(self):
        mgr = self._make_manager()
        with pytest.raises(ValueError, match="Invalid scope"):
            mgr.set(scope="nonexistent", provider="openai")


# ---------------------------------------------------------------------------
# PromptLoader: new defaults for rag, bot, incremental_discover, merge
# ---------------------------------------------------------------------------


class TestPromptLoaderNewDefaults:
    def _make_loader(self):
        from tg_parser.processing.prompt_loader import PromptLoader

        return PromptLoader(prompts_dir=Path("/nonexistent"))

    def test_rag_default_has_system_prompt(self):
        loader = self._make_loader()
        config = loader.load("rag")
        assert "system" in config
        prompt = config["system"]["prompt"]
        assert "knowledge base" in prompt.lower()
        assert "SAME LANGUAGE" in prompt

    def test_rag_default_has_user_template(self):
        loader = self._make_loader()
        config = loader.load("rag")
        tpl = config["user"]["template"]
        assert "{context}" in tpl
        assert "{question}" in tpl

    def test_rag_default_has_model_settings(self):
        loader = self._make_loader()
        config = loader.load("rag")
        model = config["model"]
        assert model["temperature"] == 0.2
        assert model["max_tokens"] == 2048
        assert model["context_char_limit"] == 2000

    def test_rag_default_has_no_results(self):
        loader = self._make_loader()
        config = loader.load("rag")
        assert config["no_results"]["message"]

    def test_bot_default_has_system_prompt(self):
        loader = self._make_loader()
        config = loader.load("bot")
        prompt = config["system"]["prompt"]
        assert "knowledge base assistant" in prompt
        assert "Telegram channels" in prompt

    def test_incremental_discover_default(self):
        loader = self._make_loader()
        config = loader.load("incremental_discover")
        prompt = config["system"]["prompt"]
        assert "topic analysis" in prompt.lower()
        assert "assignments" in prompt

    def test_merge_default(self):
        loader = self._make_loader()
        config = loader.load("merge")
        assert "deduplication" in config["system"]["prompt"]
        tpl = config["user"]["template"]
        assert "{topic_count}" in tpl
        assert "{topics_json}" in tpl

    def test_unknown_prompt_returns_empty(self):
        loader = self._make_loader()
        config = loader.load("totally_unknown_prompt_xyz")
        assert config == {}

    def test_reload_clears_cache_and_reloads(self):
        loader = self._make_loader()
        first = loader.load("rag")
        loader.reload("rag")
        second = loader.load("rag")
        assert first == second  # same content from defaults
        assert first is not second  # different dict instances (cache was cleared)

    def test_reload_all_clears_entire_cache(self):
        loader = self._make_loader()
        loader.load("rag")
        loader.load("bot")
        loader.reload()  # clear all
        # re-loading works fine after full clear
        assert "system" in loader.load("rag")
        assert "system" in loader.load("bot")


class TestPromptLoaderYamlOverride:
    def test_rag_yaml_loads(self):
        from tg_parser.processing.prompt_loader import PromptLoader

        loader = PromptLoader(prompts_dir=Path("prompts"))
        config = loader.load("rag")
        assert "system" in config
        assert "knowledge base" in config["system"]["prompt"].lower()

    def test_bot_yaml_loads(self):
        from tg_parser.processing.prompt_loader import PromptLoader

        loader = PromptLoader(prompts_dir=Path("prompts"))
        config = loader.load("bot")
        assert "system" in config
        assert "knowledge base assistant" in config["system"]["prompt"]

    def test_merge_yaml_loads(self):
        from tg_parser.processing.prompt_loader import PromptLoader

        loader = PromptLoader(prompts_dir=Path("prompts"))
        config = loader.load("merge")
        assert config["model"]["temperature"] == 0.0
        assert config["model"]["max_tokens"] == 16384

    def test_incremental_discover_yaml_loads(self):
        from tg_parser.processing.prompt_loader import PromptLoader

        loader = PromptLoader(prompts_dir=Path("prompts"))
        config = loader.load("incremental_discover")
        assert "system" in config
        assert "model" in config

    def test_yaml_user_template_is_formattable(self):
        """rag.yaml user template must contain {context} and {question} placeholders."""
        from tg_parser.processing.prompt_loader import PromptLoader

        loader = PromptLoader(prompts_dir=Path("prompts"))
        config = loader.load("rag")
        tpl = config["user"]["template"]
        formatted = tpl.format(context="CTX", question="Q?")
        assert "CTX" in formatted
        assert "Q?" in formatted

    def test_merge_yaml_user_template_is_formattable(self):
        """merge.yaml user template must contain {topic_count} and {topics_json}."""
        from tg_parser.processing.prompt_loader import PromptLoader

        loader = PromptLoader(prompts_dir=Path("prompts"))
        config = loader.load("merge")
        tpl = config["user"]["template"]
        formatted = tpl.format(topic_count=5, topics_json="[]")
        assert "5" in formatted
        assert "[]" in formatted


# ---------------------------------------------------------------------------
# retrieval_service: context builder
# ---------------------------------------------------------------------------


class TestBuildContext:
    def test_build_context_with_topics(self):
        from tg_parser.services.retrieval_service import SearchResult, _build_context

        doc = MagicMock()
        doc.channel_id = "genotek"
        doc.summary = "Анализ генома"
        doc.text_clean = "Полный текст о генетическом анализе." * 10
        doc.topics = ["генетика", "здоровье"]

        results = [
            SearchResult(source_ref="tg:genotek:post:456", score=0.83, document=doc),
        ]
        ctx = _build_context(results, char_limit=100)

        assert "channel: genotek" in ctx
        assert "ref: tg:genotek:post:456" in ctx
        assert "score: 0.83" in ctx
        assert "Topics: генетика, здоровье" in ctx

    def test_build_context_respects_char_limit(self):
        from tg_parser.services.retrieval_service import SearchResult, _build_context

        doc = MagicMock()
        doc.channel_id = "ch"
        doc.summary = "Sum"
        doc.text_clean = "A" * 5000
        doc.topics = []

        results = [SearchResult(source_ref="tg:ch:post:1", score=0.9, document=doc)]
        ctx = _build_context(results, char_limit=200)

        text_part = ctx.split("Text: ")[1]
        assert len(text_part) <= 210  # 200 chars + small header overhead

    def test_build_context_skips_missing_document(self):
        """Results with document=None should be silently skipped."""
        from tg_parser.services.retrieval_service import SearchResult, _build_context

        doc = MagicMock()
        doc.channel_id = "ch"
        doc.summary = "Sum"
        doc.text_clean = "Real text"
        doc.topics = []

        results = [
            SearchResult(source_ref="tg:ch:post:1", score=0.9, document=None),
            SearchResult(source_ref="tg:ch:post:2", score=0.8, document=doc),
        ]
        ctx = _build_context(results, char_limit=500)
        assert "tg:ch:post:2" in ctx
        assert "tg:ch:post:1" not in ctx

    def test_build_context_empty_results(self):
        from tg_parser.services.retrieval_service import _build_context

        assert _build_context([], char_limit=500) == ""

    def test_build_context_no_topics(self):
        """When doc.topics is empty, 'Topics:' line should be absent."""
        from tg_parser.services.retrieval_service import SearchResult, _build_context

        doc = MagicMock()
        doc.channel_id = "ch"
        doc.summary = "Sum"
        doc.text_clean = "content"
        doc.topics = []

        results = [SearchResult(source_ref="tg:ch:post:1", score=0.9, document=doc)]
        ctx = _build_context(results, char_limit=500)
        assert "Topics:" not in ctx

    def test_build_context_multiple_results_separated(self):
        """Multiple results are separated by '---'."""
        from tg_parser.services.retrieval_service import SearchResult, _build_context

        def _doc(ch):
            d = MagicMock()
            d.channel_id = ch
            d.summary = f"Doc from {ch}"
            d.text_clean = f"Text {ch}"
            d.topics = []
            return d

        results = [
            SearchResult(source_ref="tg:ch1:post:1", score=0.9, document=_doc("ch1")),
            SearchResult(source_ref="tg:ch2:post:2", score=0.8, document=_doc("ch2")),
        ]
        ctx = _build_context(results, char_limit=500)
        assert ctx.count("---") == 1
        assert "channel: ch1" in ctx
        assert "channel: ch2" in ctx

    def test_build_context_uses_text_clean_as_title_fallback(self):
        """When summary is None, title falls back to text_clean[:80]."""
        from tg_parser.services.retrieval_service import SearchResult, _build_context

        doc = MagicMock()
        doc.channel_id = "ch"
        doc.summary = None
        doc.text_clean = "X" * 200
        doc.topics = []

        results = [SearchResult(source_ref="tg:ch:post:1", score=0.9, document=doc)]
        ctx = _build_context(results, char_limit=500)
        assert "Title: " + "X" * 80 in ctx
        assert "Title: " + "X" * 81 not in ctx


# ---------------------------------------------------------------------------
# retrieval_service: answer()
# ---------------------------------------------------------------------------


class TestAnswerWithPromptLoader:
    async def test_answer_uses_system_prompt(self):
        from tg_parser.services.retrieval_service import SearchResult, answer

        mock_llm = AsyncMock()
        mock_llm.generate.return_value = "Test answer"
        mock_llm.model = "test-model"

        mock_doc = MagicMock()
        mock_doc.summary = "Summary"
        mock_doc.text_clean = "Content"
        mock_doc.channel_id = "ch"
        mock_doc.topics = []

        search_results = [SearchResult(source_ref="tg:ch:post:1", score=0.95, document=mock_doc)]

        with patch(
            "tg_parser.services.retrieval_service.search",
            new_callable=AsyncMock,
            return_value=search_results,
        ):
            result = await answer(question="Test?", llm_client=mock_llm)

        assert result.answer == "Test answer"
        call_kwargs = mock_llm.generate.call_args
        assert "system_prompt" in call_kwargs.kwargs
        assert call_kwargs.kwargs["system_prompt"]  # non-empty

    async def test_answer_no_results_uses_yaml_message(self):
        from tg_parser.services.retrieval_service import answer

        with patch(
            "tg_parser.services.retrieval_service.search",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await answer(question="Missing?")

        assert "релевантных" in result.answer.lower() or "документов" in result.answer.lower()

    async def test_answer_passes_channel_id_to_search(self):
        from tg_parser.services.retrieval_service import SearchResult, answer

        mock_llm = AsyncMock()
        mock_llm.generate.return_value = "Answer"
        mock_llm.model = "m"

        mock_doc = MagicMock()
        mock_doc.summary = "S"
        mock_doc.text_clean = "T"
        mock_doc.channel_id = "genotek"
        mock_doc.topics = []

        with patch(
            "tg_parser.services.retrieval_service.search",
            new_callable=AsyncMock,
            return_value=[SearchResult(source_ref="r", score=0.9, document=mock_doc)],
        ) as mock_search:
            await answer(question="Q?", channel_id="genotek", llm_client=mock_llm)

        mock_search.assert_awaited_once()
        call_kwargs = mock_search.call_args
        assert (
            call_kwargs.kwargs.get("channel_id") == "genotek"
            or call_kwargs[1].get("channel_id") == "genotek"
        )

    async def test_answer_sources_populated(self):
        from tg_parser.services.retrieval_service import SearchResult, answer

        mock_llm = AsyncMock()
        mock_llm.generate.return_value = "Answer text"
        mock_llm.model = "m"

        mock_doc = MagicMock()
        mock_doc.summary = "S"
        mock_doc.text_clean = "T"
        mock_doc.channel_id = "ch"
        mock_doc.topics = []

        sr = SearchResult(source_ref="tg:ch:post:42", score=0.88, document=mock_doc)

        with patch(
            "tg_parser.services.retrieval_service.search",
            new_callable=AsyncMock,
            return_value=[sr],
        ):
            result = await answer(question="Q?", llm_client=mock_llm)

        assert len(result.sources) == 1
        assert result.sources[0].source_ref == "tg:ch:post:42"
        assert result.model == "m"

    async def test_answer_no_results_returns_empty_sources(self):
        from tg_parser.services.retrieval_service import answer

        with patch(
            "tg_parser.services.retrieval_service.search",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await answer(question="Q?")

        assert result.sources == []
        assert result.model is None


# ---------------------------------------------------------------------------
# _call_llm: branches
# ---------------------------------------------------------------------------


class TestCallLlmBranches:
    async def test_injected_client_uses_yaml_defaults(self):
        """When no runtime override, _call_llm uses function defaults."""
        from tg_parser.services.retrieval_service import _call_llm

        mock_client = AsyncMock()
        mock_client.generate.return_value = "  Result  "
        mock_client.model = "test-model"

        text, model = await _call_llm(
            "prompt",
            system_prompt="sys",
            llm_client=mock_client,
        )

        assert text == "Result"
        assert model == "test-model"
        call_kwargs = mock_client.generate.call_args.kwargs
        assert call_kwargs["temperature"] == 0.2
        assert call_kwargs["max_tokens"] == 2048

    async def test_runtime_temp_override_zero(self):
        """temperature=0.0 from runtime config must be used, not the default 0.2."""
        from tg_parser.services.retrieval_service import _call_llm

        mock_client = AsyncMock()
        mock_client.generate.return_value = "R"
        mock_client.model = "m"

        mock_resolve_full = {
            "provider": "openai",
            "api_key": "k",
            "model": "m",
            "temperature": 0.0,
            "max_tokens": 512,
        }
        with patch("tg_parser.config.llm_config") as mock_cfg:
            mock_cfg.resolve_full.return_value = mock_resolve_full
            await _call_llm("p", system_prompt="s", llm_client=mock_client)

        call_kwargs = mock_client.generate.call_args.kwargs
        assert call_kwargs["temperature"] == 0.0
        assert call_kwargs["max_tokens"] == 512

    async def test_runtime_override_none_uses_function_defaults(self):
        """When resolve_full returns None for temp/max, use the function arg defaults."""
        from tg_parser.services.retrieval_service import _call_llm

        mock_client = AsyncMock()
        mock_client.generate.return_value = "R"
        mock_client.model = "m"

        mock_resolve_full = {
            "provider": "openai",
            "api_key": "k",
            "model": "m",
            "temperature": None,
            "max_tokens": None,
        }
        with patch("tg_parser.config.llm_config") as mock_cfg:
            mock_cfg.resolve_full.return_value = mock_resolve_full
            await _call_llm(
                "p",
                system_prompt="s",
                temperature=0.5,
                max_tokens=999,
                llm_client=mock_client,
            )

        call_kwargs = mock_client.generate.call_args.kwargs
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_tokens"] == 999

    async def test_factory_path_non_openai_no_base_url(self):
        """Non-openai provider should not pass base_url to create_llm_client."""
        from tg_parser.services.retrieval_service import _call_llm

        mock_client = AsyncMock()
        mock_client.generate.return_value = "R"
        mock_client.model = "claude"

        mock_resolve_full = {
            "provider": "anthropic",
            "api_key": "sk-ant-x",
            "model": "claude-sonnet",
            "temperature": None,
            "max_tokens": None,
        }
        with (
            patch("tg_parser.config.llm_config") as mock_cfg,
            patch(
                "tg_parser.processing.llm.factory.create_llm_client",
                return_value=mock_client,
            ) as mock_factory,
            patch("tg_parser.services.retrieval_service.settings") as mock_settings,
        ):
            mock_cfg.resolve_full.return_value = mock_resolve_full
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.llm_model = "gpt-4o-mini"

            await _call_llm("prompt", system_prompt="sys")

        mock_factory.assert_called_once_with(
            provider="anthropic",
            api_key="sk-ant-x",
            model="claude-sonnet",
            base_url=None,
        )

    async def test_factory_path_openai_gets_base_url(self):
        """OpenAI provider should pass base_url from settings."""
        from tg_parser.services.retrieval_service import _call_llm

        mock_client = AsyncMock()
        mock_client.generate.return_value = "R"
        mock_client.model = "gpt-4o"

        mock_resolve_full = {
            "provider": "openai",
            "api_key": "sk-test",
            "model": "gpt-4o",
            "temperature": None,
            "max_tokens": None,
        }
        with (
            patch("tg_parser.config.llm_config") as mock_cfg,
            patch(
                "tg_parser.processing.llm.factory.create_llm_client",
                return_value=mock_client,
            ) as mock_factory,
            patch("tg_parser.services.retrieval_service.settings") as mock_settings,
        ):
            mock_cfg.resolve_full.return_value = mock_resolve_full
            mock_settings.openai_base_url = "https://custom.api.com/v1"
            mock_settings.llm_model = "gpt-4o"

            await _call_llm("prompt", system_prompt="sys")

        mock_factory.assert_called_once_with(
            provider="openai",
            api_key="sk-test",
            model="gpt-4o",
            base_url="https://custom.api.com/v1",
        )

    async def test_model_fallback_when_client_has_no_model_attr(self):
        """When llm_client lacks .model, fall back to settings.llm_model."""
        from tg_parser.services.retrieval_service import _call_llm

        mock_client = AsyncMock(spec=[])
        mock_client.generate = AsyncMock(return_value="R")

        with patch("tg_parser.services.retrieval_service.settings") as mock_settings:
            mock_settings.llm_model = "fallback-model"
            _, model = await _call_llm("p", llm_client=mock_client)

        assert model == "fallback-model"


# ---------------------------------------------------------------------------
# reload_prompts bot tool
# ---------------------------------------------------------------------------


class TestReloadPromptsBotTool:
    async def test_reload_all(self):
        from tg_parser.bot.tools import execute_tool

        result = await execute_tool("reload_prompts", {})
        assert result["success"] is True
        assert result["reloaded"] == "all"

    async def test_reload_specific(self):
        from tg_parser.bot.tools import execute_tool

        result = await execute_tool("reload_prompts", {"name": "rag"})
        assert result["success"] is True
        assert result["reloaded"] == "rag"

    def test_reload_prompts_in_declarations(self):
        from tg_parser.bot.tools import TOOL_DECLARATIONS

        names = [t["name"] for t in TOOL_DECLARATIONS]
        assert "reload_prompts" in names

    def test_reload_prompts_declaration_schema(self):
        """reload_prompts declaration has correct parameters schema."""
        from tg_parser.bot.tools import TOOL_DECLARATIONS

        decl = next(t for t in TOOL_DECLARATIONS if t["name"] == "reload_prompts")
        params = decl["parameters"]["properties"]
        assert "name" in params
        assert params["name"]["type"] == "STRING"


# ---------------------------------------------------------------------------
# Bot execute_tool set_llm_config with rag scope + temperature/max_tokens
# ---------------------------------------------------------------------------

LLM_CONFIG_PATCH = "tg_parser.config.llm_config"


def _sample_llm_config():
    return {
        "global": {"provider": "openai", "model": "gpt-4o", "overridden": False},
        "stages": {
            "processing": {"provider": "openai", "model": "gpt-4o", "overridden": False},
            "topicization": {"provider": "openai", "model": "gpt-4o", "overridden": False},
            "rag": {"provider": "openai", "model": "gpt-4o", "overridden": False},
        },
        "available_providers": {
            "openai": True,
            "anthropic": False,
            "gemini": True,
            "ollama": True,
        },
        "runtime_overrides": {},
    }


class TestBotSetLlmConfigRagScope:
    async def test_preview_rag_with_temperature(self):
        from tg_parser.bot.tools import execute_tool

        mock_cfg = MagicMock()
        mock_cfg.get_all.return_value = _sample_llm_config()

        with patch(LLM_CONFIG_PATCH, mock_cfg):
            result = await execute_tool(
                "set_llm_config",
                {"scope": "rag", "provider": "anthropic", "temperature": 0.3},
            )

        assert result["preview"] is True
        assert result["will_set"]["scope"] == "rag"
        assert result["will_set"]["temperature"] == 0.3

    async def test_confirm_rag_with_temperature_and_max_tokens(self):
        from tg_parser.bot.tools import execute_tool

        updated = _sample_llm_config()
        updated["stages"]["rag"]["provider"] = "anthropic"
        updated["stages"]["rag"]["temperature"] = 0.1
        updated["stages"]["rag"]["max_tokens"] = 1024
        updated["stages"]["rag"]["overridden"] = True

        mock_cfg = MagicMock()
        mock_cfg.set.return_value = updated

        with patch(LLM_CONFIG_PATCH, mock_cfg):
            result = await execute_tool(
                "set_llm_config",
                {
                    "scope": "rag",
                    "provider": "anthropic",
                    "temperature": 0.1,
                    "max_tokens": 1024,
                    "confirm": True,
                },
                confirm_flow_state={
                    "tool_name": "set_llm_config",
                    "args": {
                        "scope": "rag",
                        "provider": "anthropic",
                        "temperature": 0.1,
                        "max_tokens": 1024,
                    },
                },
            )

        assert result["success"] is True
        mock_cfg.set.assert_called_once_with(
            scope="rag",
            provider="anthropic",
            model=None,
            temperature=0.1,
            max_tokens=1024,
        )

    async def test_confirm_rag_temperature_zero(self):
        """temperature=0.0 must be passed through, not treated as missing."""
        from tg_parser.bot.tools import execute_tool

        mock_cfg = MagicMock()
        mock_cfg.set.return_value = _sample_llm_config()

        with patch(LLM_CONFIG_PATCH, mock_cfg):
            result = await execute_tool(
                "set_llm_config",
                {"scope": "rag", "provider": "openai", "temperature": 0.0, "confirm": True},
                confirm_flow_state={
                    "tool_name": "set_llm_config",
                    "args": {"scope": "rag", "provider": "openai", "temperature": 0.0},
                },
            )

        assert result["success"] is True
        mock_cfg.set.assert_called_once_with(
            scope="rag",
            provider="openai",
            model=None,
            temperature=0.0,
            max_tokens=None,
        )


# ---------------------------------------------------------------------------
# MCP server tools: set_llm_config, reload_prompts, reset_llm_config
# ---------------------------------------------------------------------------


class TestMCPSetLlmConfig:
    async def test_set_llm_config_success(self):
        from tg_parser.mcp_server import set_llm_config

        mock_cfg = MagicMock()
        mock_cfg.set.return_value = _sample_llm_config()

        with patch("tg_parser.config.llm_config", mock_cfg):
            result = await set_llm_config(
                scope="rag",
                provider="anthropic",
                model="claude-sonnet",
                temperature=0.5,
                max_tokens=2048,
            )

        assert result.success is True
        mock_cfg.set.assert_called_once_with(
            scope="rag",
            provider="anthropic",
            model="claude-sonnet",
            temperature=0.5,
            max_tokens=2048,
        )

    async def test_set_llm_config_invalid_provider(self):
        from tg_parser.mcp_server import set_llm_config

        mock_cfg = MagicMock()
        mock_cfg.set.side_effect = ValueError("Unsupported provider 'bad'")
        mock_cfg.get_all.return_value = _sample_llm_config()

        with patch("tg_parser.config.llm_config", mock_cfg):
            result = await set_llm_config(scope="global", provider="bad")

        assert result.success is False
        assert "Unsupported" in result.message

    async def test_set_llm_config_temperature_zero(self):
        """MCP set_llm_config must pass temperature=0.0 correctly."""
        from tg_parser.mcp_server import set_llm_config

        mock_cfg = MagicMock()
        mock_cfg.set.return_value = _sample_llm_config()

        with patch("tg_parser.config.llm_config", mock_cfg):
            result = await set_llm_config(
                scope="rag",
                provider="openai",
                temperature=0.0,
            )

        assert result.success is True
        mock_cfg.set.assert_called_once_with(
            scope="rag",
            provider="openai",
            model=None,
            temperature=0.0,
            max_tokens=None,
        )


class TestMCPReloadPrompts:
    async def test_reload_all(self):
        from tg_parser.mcp_server import reload_prompts

        result = await reload_prompts()
        assert result["success"] is True
        assert result["reloaded"] == "all"

    async def test_reload_specific_name(self):
        from tg_parser.mcp_server import reload_prompts

        result = await reload_prompts(name="rag")
        assert result["success"] is True
        assert result["reloaded"] == "rag"


class TestMCPResetLlmConfig:
    async def test_reset_single_scope(self):
        from tg_parser.mcp_server import reset_llm_config

        mock_cfg = MagicMock()
        mock_cfg.clear.return_value = _sample_llm_config()

        with patch("tg_parser.config.llm_config", mock_cfg):
            result = await reset_llm_config(scope="rag")

        assert result.success is True
        assert "rag" in result.message
        mock_cfg.clear.assert_called_once_with(scope="rag")

    async def test_reset_all_scopes(self):
        from tg_parser.mcp_server import reset_llm_config

        mock_cfg = MagicMock()
        mock_cfg.clear.return_value = _sample_llm_config()

        with patch("tg_parser.config.llm_config", mock_cfg):
            result = await reset_llm_config()

        assert result.success is True
        assert "all scopes" in result.message
        mock_cfg.clear.assert_called_once_with(scope=None)


class TestMCPGetLlmConfig:
    async def test_returns_config_with_rag(self):
        from tg_parser.mcp_server import get_llm_config

        mock_cfg = MagicMock()
        mock_cfg.get_all.return_value = _sample_llm_config()

        with patch("tg_parser.config.llm_config", mock_cfg):
            result = await get_llm_config()

        assert "rag" in result.config["stages"]


# ---------------------------------------------------------------------------
# GeminiAgent loads prompt from PromptLoader
# ---------------------------------------------------------------------------


class TestGeminiAgentPromptLoading:
    def test_agent_loads_system_prompt(self):
        from tg_parser.bot.agent import GeminiAgent

        agent = GeminiAgent(api_key="test-key")
        assert agent._system_prompt
        assert "knowledge base" in agent._system_prompt.lower()

    def test_agent_reload_prompt(self):
        from tg_parser.bot.agent import GeminiAgent

        agent = GeminiAgent(api_key="test-key")
        original = agent._system_prompt
        agent.reload_prompt()
        assert agent._system_prompt == original  # same YAML, same result

    def test_agent_reload_updates_prompt_from_loader(self):
        """After reloading the loader with a different value, agent picks it up."""
        from tg_parser.bot.agent import GeminiAgent

        agent = GeminiAgent(api_key="test-key")
        original = agent._system_prompt

        with patch(
            "tg_parser.bot.agent._load_bot_system_prompt",
            return_value="NEW PROMPT CONTENT",
        ):
            agent.reload_prompt()

        assert agent._system_prompt == "NEW PROMPT CONTENT"
        assert agent._system_prompt != original


# ---------------------------------------------------------------------------
# Topicization wiring with PromptLoader
# ---------------------------------------------------------------------------


class TestTopicizationPromptLoaderWiring:
    """Verify that _discover_single_batch and _merge_topics
    load prompts from PromptLoader and pass them to LLM calls."""

    def _make_pipeline(self, mock_llm=None):
        from tg_parser.processing.topicization import TopicizationPipelineImpl

        if mock_llm is None:
            mock_llm = AsyncMock()

        mock_proc_repo = AsyncMock()
        mock_topic_card_repo = AsyncMock()
        mock_topic_bundle_repo = AsyncMock()

        return TopicizationPipelineImpl(
            llm_client=mock_llm,
            processed_doc_repo=mock_proc_repo,
            topic_card_repo=mock_topic_card_repo,
            topic_bundle_repo=mock_topic_bundle_repo,
        )

    async def test_discover_single_batch_uses_prompt_loader(self):
        """_discover_single_batch loads 'incremental_discover' config from PromptLoader."""
        mock_llm = AsyncMock()
        llm_response = MagicMock()
        llm_response.text = json.dumps(
            {
                "assignments": [
                    {
                        "source_ref": "tg:ch:post:1",
                        "topic_id": "topic-1",
                        "confidence": 0.9,
                        "topic_name": "Test Topic",
                        "topic_description": "Desc",
                    }
                ],
                "new_topics": [
                    {
                        "topic_id": "topic-1",
                        "name": "Test Topic",
                        "description": "Desc",
                        "keywords": ["test"],
                    }
                ],
            }
        )
        llm_response.total_tokens = 100
        mock_llm.generate_with_usage = AsyncMock(return_value=llm_response)

        pipeline = self._make_pipeline(mock_llm)

        mock_doc = MagicMock()
        mock_doc.source_ref = "tg:ch:post:1"
        mock_doc.summary = "Summary"
        mock_doc.topics = []
        mock_doc.text_clean = "Test document text"

        custom_config = {
            "system": {"prompt": "CUSTOM DISCOVER PROMPT"},
            "model": {"temperature": 0.11, "max_tokens": 4096},
        }

        with patch("tg_parser.processing.topicization.get_prompt_loader") as mock_get_loader:
            mock_loader = MagicMock()
            mock_loader.load.return_value = custom_config
            mock_get_loader.return_value = mock_loader

            await pipeline._discover_single_batch(
                channel_id="ch",
                batch_docs=[mock_doc],
                existing_topics=[],
                existing_topic_ids=set(),
            )

        mock_loader.load.assert_called_with("incremental_discover")
        call_kwargs = mock_llm.generate_with_usage.call_args.kwargs
        assert call_kwargs["system_prompt"] == "CUSTOM DISCOVER PROMPT"
        assert call_kwargs["temperature"] == 0.11
        assert call_kwargs["max_tokens"] == 4096

    async def test_merge_topics_uses_prompt_loader(self):
        """_merge_topics loads 'merge' config from PromptLoader."""
        mock_llm = AsyncMock()
        llm_response = MagicMock()
        llm_response.text = json.dumps({"groups": [[0], [1]]})
        llm_response.total_tokens = 50
        mock_llm.generate_with_usage = AsyncMock(return_value=llm_response)

        pipeline = self._make_pipeline(mock_llm)

        topics = [
            {"title": f"Topic {i}", "summary": f"Desc {i}", "keywords": [f"kw{i}"]}
            for i in range(2)
        ]

        custom_config = {
            "system": {"prompt": "CUSTOM MERGE SYSTEM"},
            "user": {"template": "Merge {topic_count} topics:\n{topics_json}"},
            "model": {"temperature": 0.05, "max_tokens": 8000},
        }

        with patch("tg_parser.processing.topicization.get_prompt_loader") as mock_get_loader:
            mock_loader = MagicMock()
            mock_loader.load.return_value = custom_config
            mock_get_loader.return_value = mock_loader

            await pipeline._merge_topics(topics, topics)

        mock_loader.load.assert_called_with("merge")
        call_kwargs = mock_llm.generate_with_usage.call_args.kwargs
        assert call_kwargs["system_prompt"] == "CUSTOM MERGE SYSTEM"
        assert call_kwargs["temperature"] == 0.05
        assert call_kwargs["max_tokens"] == 8000
        assert "Merge 2 topics" in call_kwargs["prompt"]

    async def test_merge_topics_fallback_without_user_template(self):
        """When merge config has no user template, uses the inline fallback."""
        mock_llm = AsyncMock()
        llm_response = MagicMock()
        llm_response.text = json.dumps({"groups": [[0, 1]]})
        llm_response.total_tokens = 50
        mock_llm.generate_with_usage = AsyncMock(return_value=llm_response)

        pipeline = self._make_pipeline(mock_llm)

        topics = [
            {"title": f"Topic {i}", "summary": f"Desc {i}", "keywords": [f"kw{i}"]}
            for i in range(2)
        ]

        config_no_template = {
            "system": {"prompt": "SYS"},
            "user": {},
            "model": {"temperature": 0.0, "max_tokens": 16384},
        }

        with patch("tg_parser.processing.topicization.get_prompt_loader") as mock_get_loader:
            mock_loader = MagicMock()
            mock_loader.load.return_value = config_no_template
            mock_get_loader.return_value = mock_loader

            await pipeline._merge_topics(topics, topics)

        call_kwargs = mock_llm.generate_with_usage.call_args.kwargs
        assert "You have 2 topics" in call_kwargs["prompt"]
        assert "group them aggressively" in call_kwargs["prompt"]

    async def test_discover_fallback_to_constant_prompt(self):
        """When PromptLoader returns empty config, falls back to INCREMENTAL_DISCOVER_SYSTEM_PROMPT."""
        from tg_parser.processing.topicization_prompts import INCREMENTAL_DISCOVER_SYSTEM_PROMPT

        mock_llm = AsyncMock()
        llm_response = MagicMock()
        llm_response.text = json.dumps({"assignments": [], "new_topics": []})
        llm_response.total_tokens = 50
        mock_llm.generate_with_usage = AsyncMock(return_value=llm_response)

        pipeline = self._make_pipeline(mock_llm)

        mock_doc = MagicMock()
        mock_doc.source_ref = "tg:ch:post:1"
        mock_doc.summary = "S"
        mock_doc.topics = []
        mock_doc.text_clean = "Text"

        with patch("tg_parser.processing.topicization.get_prompt_loader") as mock_get_loader:
            mock_loader = MagicMock()
            mock_loader.load.return_value = {}
            mock_get_loader.return_value = mock_loader

            await pipeline._discover_single_batch(
                channel_id="ch",
                batch_docs=[mock_doc],
                existing_topics=[],
                existing_topic_ids=set(),
            )

        call_kwargs = mock_llm.generate_with_usage.call_args.kwargs
        assert call_kwargs["system_prompt"] == INCREMENTAL_DISCOVER_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Wave 1.5: Phase 1 — _generate_topics_batch uses PromptLoader
# ---------------------------------------------------------------------------


class TestGenerateTopicsBatchPromptLoader:
    """Verify that _generate_topics_batch loads topicization config from PromptLoader."""

    def _make_pipeline(self, mock_llm=None):
        from tg_parser.processing.topicization import TopicizationPipelineImpl

        if mock_llm is None:
            mock_llm = AsyncMock()

        mock_proc_repo = AsyncMock()
        mock_topic_card_repo = AsyncMock()
        mock_topic_bundle_repo = AsyncMock()

        return TopicizationPipelineImpl(
            llm_client=mock_llm,
            processed_doc_repo=mock_proc_repo,
            topic_card_repo=mock_topic_card_repo,
            topic_bundle_repo=mock_topic_bundle_repo,
        )

    async def test_generate_batch_uses_yaml_system_prompt(self):
        """_generate_topics_batch loads 'topicization' system prompt from PromptLoader."""
        mock_llm = AsyncMock()
        llm_response = MagicMock()
        llm_response.text = json.dumps({"topics": []})
        llm_response.input_tokens = 10
        llm_response.output_tokens = 5
        mock_llm.generate_with_usage = AsyncMock(return_value=llm_response)

        pipeline = self._make_pipeline(mock_llm)

        candidates = [
            {
                "source_ref": "tg:ch:post:1",
                "text_clean": "Test text",
                "summary": "Test summary",
                "topics": [],
            }
        ]

        custom_config = {
            "system": {"prompt": "CUSTOM TOPICIZATION SYSTEM"},
            "model": {"temperature": 0.15, "max_tokens": 4096},
        }

        with patch("tg_parser.processing.topicization.get_prompt_loader") as mock_get_loader:
            mock_loader = MagicMock()
            mock_loader.load.return_value = custom_config
            mock_get_loader.return_value = mock_loader

            await pipeline._generate_topics_batch(candidates)

        mock_loader.load.assert_called_with("topicization")
        call_kwargs = mock_llm.generate_with_usage.call_args.kwargs
        assert call_kwargs["system_prompt"] == "CUSTOM TOPICIZATION SYSTEM"
        assert call_kwargs["temperature"] == 0.15
        assert call_kwargs["max_tokens"] == 4096

    async def test_generate_batch_fallback_to_constant(self):
        """When PromptLoader returns empty config, falls back to TOPICIZATION_SYSTEM_PROMPT."""
        from tg_parser.processing.topicization_prompts import TOPICIZATION_SYSTEM_PROMPT

        mock_llm = AsyncMock()
        llm_response = MagicMock()
        llm_response.text = json.dumps({"topics": []})
        llm_response.input_tokens = 10
        llm_response.output_tokens = 5
        mock_llm.generate_with_usage = AsyncMock(return_value=llm_response)

        pipeline = self._make_pipeline(mock_llm)

        candidates = [
            {
                "source_ref": "tg:ch:post:1",
                "text_clean": "Test text",
                "summary": "Test",
                "topics": [],
            }
        ]

        with patch("tg_parser.processing.topicization.get_prompt_loader") as mock_get_loader:
            mock_loader = MagicMock()
            mock_loader.load.return_value = {}
            mock_get_loader.return_value = mock_loader

            await pipeline._generate_topics_batch(candidates)

        call_kwargs = mock_llm.generate_with_usage.call_args.kwargs
        assert call_kwargs["system_prompt"] == TOPICIZATION_SYSTEM_PROMPT
        assert call_kwargs["temperature"] == 0.0
        assert call_kwargs["max_tokens"] == 8192

    async def test_generate_batch_uses_yaml_model_defaults(self):
        """_generate_topics_batch uses temperature/max_tokens from YAML model section."""
        mock_llm = AsyncMock()
        llm_response = MagicMock()
        llm_response.text = json.dumps(
            {
                "topics": [
                    {
                        "type": "singleton",
                        "anchors": [{"source_ref": "tg:ch:post:1", "score": 0.9}],
                        "title": "T",
                        "summary": "S",
                        "scope_in": ["a"],
                        "scope_out": ["b"],
                    }
                ]
            }
        )
        llm_response.input_tokens = 10
        llm_response.output_tokens = 5
        mock_llm.generate_with_usage = AsyncMock(return_value=llm_response)

        pipeline = self._make_pipeline(mock_llm)

        candidates = [
            {
                "source_ref": "tg:ch:post:1",
                "text_clean": "Test text " * 50,
                "summary": "Summary",
                "topics": ["topic1"],
            }
        ]

        config_with_model = {
            "system": {"prompt": "SYS"},
            "model": {"temperature": 0.3, "max_tokens": 16000},
        }

        with patch("tg_parser.processing.topicization.get_prompt_loader") as mock_get_loader:
            mock_loader = MagicMock()
            mock_loader.load.return_value = config_with_model
            mock_get_loader.return_value = mock_loader

            await pipeline._generate_topics_batch(candidates)

        call_kwargs = mock_llm.generate_with_usage.call_args.kwargs
        assert call_kwargs["temperature"] == 0.3
        assert call_kwargs["max_tokens"] == 16000


# ---------------------------------------------------------------------------
# Wave 1.5: Phase 2 — settings.prompts_dir wired to get_prompt_loader()
# ---------------------------------------------------------------------------


class TestPromptsDir:
    def test_settings_prompts_dir_wired_to_loader(self, tmp_path: Path):
        """When settings.prompts_dir is set, get_prompt_loader() uses it."""
        from tg_parser.processing.prompt_loader import (
            PromptLoader,
            get_prompt_loader,
            set_prompt_loader,
        )

        custom_dir = tmp_path / "custom_prompts"
        custom_dir.mkdir()
        (custom_dir / "rag.yaml").write_text(
            "system:\n  prompt: 'Custom RAG from prompts_dir'\n"
            "model:\n  temperature: 0.99\n  max_tokens: 9999\n  context_char_limit: 5000\n"
        )

        import tg_parser.processing.prompt_loader as pl_module

        pl_module._default_loader = None

        with patch("tg_parser.config.settings") as mock_settings:
            mock_settings.prompts_dir = custom_dir
            loader = get_prompt_loader()

        config = loader.load("rag")
        assert config["system"]["prompt"] == "Custom RAG from prompts_dir"
        assert config["model"]["temperature"] == 0.99

        set_prompt_loader(PromptLoader())

    def test_settings_prompts_dir_none_uses_default(self):
        """When settings.prompts_dir is None, loader uses default ./prompts."""
        import tg_parser.processing.prompt_loader as pl_module
        from tg_parser.processing.prompt_loader import (
            PromptLoader,
            get_prompt_loader,
            set_prompt_loader,
        )

        pl_module._default_loader = None

        with patch("tg_parser.config.settings") as mock_settings:
            mock_settings.prompts_dir = None
            loader = get_prompt_loader()

        assert loader.prompts_dir == Path("prompts")

        set_prompt_loader(PromptLoader())


# ---------------------------------------------------------------------------
# Wave 1.5: Phase 3 — rag_llm_provider / rag_llm_model resolve via LLMConfigManager
# ---------------------------------------------------------------------------


class TestRagLlmStaticEnvVars:
    def test_rag_llm_settings_exist(self):
        """Settings class has rag_llm_provider and rag_llm_model fields."""
        from tg_parser.config.settings import Settings

        fields = Settings.model_fields
        assert "rag_llm_provider" in fields
        assert "rag_llm_model" in fields

    def test_rag_llm_default_none(self):
        """rag_llm_provider/model default to None (falls back to global)."""
        from tg_parser.config.settings import Settings

        s = Settings(
            db_password="x",
            openai_api_key="sk-test",
        )
        assert s.rag_llm_provider is None
        assert s.rag_llm_model is None

    def test_rag_llm_resolve_via_config_manager(self):
        """LLMConfigManager resolves rag stage from static rag_llm_* settings."""
        from tg_parser.config.settings import LLMConfigManager

        LLMConfigManager.reset()

        mock_settings = MagicMock(spec=[])
        mock_settings.llm_provider = "openai"
        mock_settings.llm_model = "gpt-4o-mini"
        mock_settings.openai_api_key = "sk-test"
        mock_settings.anthropic_api_key = None
        mock_settings.gemini_api_key = None
        mock_settings.google_api_key = None
        mock_settings.rag_llm_provider = "openai"
        mock_settings.rag_llm_model = "gpt-4o"

        mgr = LLMConfigManager(mock_settings)
        provider, _key, model = mgr.resolve("rag")

        assert provider == "openai"
        assert model == "gpt-4o"

    def test_rag_llm_fallback_to_global(self):
        """When rag_llm_* are None, resolve falls back to global."""
        from tg_parser.config.settings import LLMConfigManager

        LLMConfigManager.reset()

        mock_settings = MagicMock(spec=[])
        mock_settings.llm_provider = "anthropic"
        mock_settings.llm_model = "claude-sonnet"
        mock_settings.openai_api_key = None
        mock_settings.anthropic_api_key = "sk-ant"
        mock_settings.gemini_api_key = None
        mock_settings.google_api_key = None
        mock_settings.rag_llm_provider = None
        mock_settings.rag_llm_model = None

        mgr = LLMConfigManager(mock_settings)
        provider, _key, model = mgr.resolve("rag")

        assert provider == "anthropic"
        assert model == "claude-sonnet"


# ---------------------------------------------------------------------------
# Wave 1.5: Phase 4 — RAG prompt quality improvements
# ---------------------------------------------------------------------------


class TestRagPromptQualityImprovements:
    def test_rag_yaml_context_char_limit_2000(self):
        """rag.yaml now has context_char_limit=2000."""
        from tg_parser.processing.prompt_loader import PromptLoader

        loader = PromptLoader(prompts_dir=Path("prompts"))
        config = loader.load("rag")
        assert config["model"]["context_char_limit"] == 2000

    def test_rag_system_prompt_mentions_source_ref(self):
        """RAG system prompt instructs citing source_ref identifiers."""
        from tg_parser.processing.prompt_loader import PromptLoader

        loader = PromptLoader(prompts_dir=Path("prompts"))
        config = loader.load("rag")
        prompt = config["system"]["prompt"]
        assert "source_ref" in prompt or "ref:" in prompt or "tg:channel:post:" in prompt

    def test_rag_system_prompt_mentions_topic_context(self):
        """RAG system prompt v1.2.0 mentions the two-section context
        with Related Topics and Source Messages."""
        from tg_parser.processing.prompt_loader import PromptLoader

        loader = PromptLoader(prompts_dir=Path("prompts"))
        config = loader.load("rag")
        prompt = config["system"]["prompt"]
        assert "## Related Topics" in prompt
        assert "## Source Messages" in prompt

    def test_build_context_includes_source_ref(self):
        """_build_context includes the source_ref value in message headers
        via the 'ref:' field (v1.2.0 format)."""
        from tg_parser.services.retrieval_service import SearchResult, _build_context

        doc = MagicMock()
        doc.channel_id = "ch"
        doc.summary = "Sum"
        doc.text_clean = "Content text"
        doc.topics = []

        results = [SearchResult(source_ref="tg:ch:post:42", score=0.9, document=doc)]
        ctx = _build_context(results, char_limit=500)
        assert "ref: tg:ch:post:42" in ctx

    def test_rag_default_context_char_limit_updated(self):
        """Default PromptLoader RAG config has context_char_limit=2000."""
        from tg_parser.processing.prompt_loader import PromptLoader

        loader = PromptLoader(prompts_dir=Path("/nonexistent"))
        config = loader.load("rag")
        assert config["model"]["context_char_limit"] == 2000

    def test_rag_default_system_prompt_cites_source_ref(self):
        """Default RAG system prompt instructs citing by source_ref."""
        from tg_parser.processing.prompt_loader import PromptLoader

        loader = PromptLoader(prompts_dir=Path("/nonexistent"))
        config = loader.load("rag")
        prompt = config["system"]["prompt"]
        assert "tg:channel:post:123" in prompt


class TestBotPromptBug012FormatDirective:
    """BUG-012 — Bot LLM emits «темы 1 из ['AgeManagment']» pagination phrasing
    on suggestion/available_channel_ids fields.

    v1.5.0 of bot.yaml adds an explicit HARD RULE in the «Fallback on empty
    results» section forbidding any pagination template ("N из M", "1 из 10",
    "первая страница", etc.) on the advisory hint fields. These tests pin
    that directive's wording so that any future prompt sweep that accidentally
    drops it fails CI explicitly (mirrors Session F BUG-007 contract tests).
    """

    def test_bot_yaml_version_at_least_1_5_0(self):
        """bot.yaml metadata.version must be >= 1.5.0 since BUG-012 mitigation landed."""
        from tg_parser.processing.prompt_loader import PromptLoader

        loader = PromptLoader(prompts_dir=Path("prompts"))
        config = loader.load("bot")
        version = config["metadata"]["version"]
        major, minor, patch = (int(p) for p in version.split("."))
        assert (major, minor, patch) >= (1, 5, 0), (
            f"bot.yaml version regressed below 1.5.0: {version!r} "
            "(BUG-012 format directive must remain)"
        )

    def test_bot_yaml_mentions_bug_012_mitigation(self):
        """Fallback section must explicitly tag the BUG-012 mitigation rule
        so future readers can trace WHY the directive exists."""
        from tg_parser.processing.prompt_loader import PromptLoader

        loader = PromptLoader(prompts_dir=Path("prompts"))
        config = loader.load("bot")
        prompt = config["system"]["prompt"]
        assert "BUG-012" in prompt, (
            "bot.yaml lost BUG-012 mitigation tag — format directive likely dropped"
        )

    def test_bot_yaml_forbids_pagination_phrasing_on_hint_fields(self):
        """Direct contract: prompt must contain explicit anti-pattern phrasing
        for "N из M" / "first page" templates on suggestion+available_channel_ids."""
        from tg_parser.processing.prompt_loader import PromptLoader

        loader = PromptLoader(prompts_dir=Path("prompts"))
        config = loader.load("bot")
        prompt = config["system"]["prompt"]
        assert "N из M" in prompt or "1 из 10" in prompt, (
            "bot.yaml must explicitly cite pagination-phrasing anti-pattern "
            "(e.g. 'N из M' / '1 из 10') so the LLM recognizes which template to avoid"
        )
        assert "available_channel_ids" in prompt and "suggestion" in prompt, (
            "BUG-012 directive must name BOTH affected hint fields by their "
            "payload-key names so the LLM binds the rule to the correct shape"
        )

    def test_bot_yaml_separates_pagination_scope_from_hint_fields(self):
        """The BUG-012 directive must explicitly state that pagination semantics
        apply ONLY to ``items`` / list_topics / list_channels / search_knowledge_base —
        NOT to suggestion/available_channel_ids. This separation prevents
        format-bleed between the two sections of the prompt."""
        from tg_parser.processing.prompt_loader import PromptLoader

        loader = PromptLoader(prompts_dir=Path("prompts"))
        config = loader.load("bot")
        prompt = config["system"]["prompt"]
        assert "items" in prompt, "items must be referenced as the paginated field"
        assert "advisory" in prompt or "hint" in prompt.lower(), (
            "advisory/hint role of available_channel_ids must be explicit "
            "so the LLM does not treat it as a result page"
        )
