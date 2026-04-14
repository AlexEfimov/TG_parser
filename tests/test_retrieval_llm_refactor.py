"""
Tests for _call_llm() refactoring: verify LLMClient is used instead of httpx.
Updated for RAG & Prompt Config: system/user split, PromptLoader, scope 'rag'.
"""

from unittest.mock import AsyncMock, patch

import pytest


class TestCallLlm:
    """_call_llm() uses LLMClient via DI or factory."""

    async def test_call_llm_with_injected_client(self):
        from tg_parser.services.retrieval_service import _call_llm

        mock_client = AsyncMock()
        mock_client.generate.return_value = "  Generated answer  "
        mock_client.model = "test-model-1"

        text, model = await _call_llm(
            "test prompt", system_prompt="sys", llm_client=mock_client,
        )

        assert text == "Generated answer"
        assert model == "test-model-1"
        mock_client.generate.assert_awaited_once_with(
            prompt="test prompt",
            system_prompt="sys",
            temperature=0.2,
            max_tokens=2048,
        )

    async def test_call_llm_creates_client_from_factory(self):
        from tg_parser.services.retrieval_service import _call_llm

        mock_client = AsyncMock()
        mock_client.generate.return_value = "Factory answer"
        mock_client.model = "gpt-4o-mini"

        mock_resolve_full = {
            "provider": "openai",
            "api_key": "sk-test",
            "model": "gpt-4o-mini",
            "temperature": None,
            "max_tokens": None,
        }

        with (
            patch(
                "tg_parser.services.retrieval_service.settings",
            ) as mock_settings,
            patch(
                "tg_parser.config.llm_config",
            ) as mock_llm_config,
            patch(
                "tg_parser.processing.llm.factory.create_llm_client",
                return_value=mock_client,
            ),
        ):
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.llm_model = "gpt-4o-mini"
            mock_llm_config.resolve_full.return_value = mock_resolve_full

            text, model = await _call_llm("prompt via factory", system_prompt="sys")

        assert text == "Factory answer"
        mock_client.generate.assert_awaited_once()


class TestAnswerWithLlmClient:
    """answer() passes llm_client through to _call_llm()."""

    async def test_answer_passes_llm_client(self):
        from tg_parser.services.retrieval_service import SearchResult, answer

        mock_llm = AsyncMock()
        mock_llm.generate.return_value = "LLM answer"
        mock_llm.model = "test-model"

        mock_doc = AsyncMock()
        mock_doc.summary = "Summary"
        mock_doc.text_clean = "Full text content"
        mock_doc.channel_id = "ch"
        mock_doc.topics = ["health"]

        search_results = [
            SearchResult(
                source_ref="tg:ch:post:1",
                score=0.95,
                document=mock_doc,
            )
        ]

        with patch(
            "tg_parser.services.retrieval_service.search",
            new_callable=AsyncMock,
            return_value=search_results,
        ):
            result = await answer(
                question="Test question?",
                llm_client=mock_llm,
            )

        assert result.answer == "LLM answer"
        assert result.model == "test-model"
        mock_llm.generate.assert_awaited_once()
