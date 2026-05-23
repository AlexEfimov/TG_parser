"""BUG-028 hotfix tests: digest cron PromptLoader None regression.

Pins the contract that :func:`tg_parser.services.scheduler_service.run_scheduled_digests_task`
(the APScheduler entry point that runs every active daily digest tick)
constructs its :class:`tg_parser.processing.prompt_loader.PromptLoader`
with a path that resolves to real YAML files even when
``settings.prompts_dir`` is ``None`` or carries the post-Layer-C default
``Path("prompts")``.

Pre-fix call-site (``scheduler_service.py:560``)::

    prompt_loader = PromptLoader(prompts_dir=str(settings.prompts_dir))

evaluated to ``PromptLoader(prompts_dir="None")`` whenever the env var
``PROMPTS_DIR`` was unset (because ``str(None) == "None"``). ``Path("None")``
then silently became a valid relative path, and ``.load("digest")`` raised
:class:`PromptLoaderError` with ``YAML at None/digest.yaml did not provide
a non-empty system.prompt`` — surfaced in production on 2026-05-23T06:00:00Z
during Wave 1 step 3 24h watch.

Coverage map (mirrors hotfix layers documented in BUG_LOG.md § BUG-028):

* :func:`test_settings_default_prompts_dir_is_path_prompts` — Layer C: a
  hermetic ``Settings()`` (env scrubbed, ``.env`` bypassed) must expose
  ``Path("prompts")`` as the default for :attr:`Settings.prompts_dir`.

* :func:`test_digest_task_with_default_settings_loads_yaml_prompt` —
  Layers A + C end-to-end: runs ``run_scheduled_digests_task`` with the
  post-fix default settings, captures the live ``PromptLoader`` instance,
  and asserts it resolves real non-empty YAML for the ``digest`` and
  ``processing`` stages. The DB context is stubbed so ``sub_repo.get`` returns
  ``None`` and the function short-circuits at ``not_found`` before any LLM
  / bot work — but the ``PromptLoader`` construction at line 560 fires
  unconditionally, which is exactly the call-site we need to exercise.

* :func:`test_digest_task_with_explicit_none_prompts_dir_does_not_raise` —
  Layer A guard isolation: forces ``settings.prompts_dir = None`` to
  simulate the pre-Layer-C state and asserts that the guard converts
  ``None`` to ``None`` (not the literal string ``"None"``) so the
  downstream ``PromptLoader`` falls back to its own ``Path("prompts")``
  default and still loads real YAML.

Why this gap existed before BUG-028: ``tests/test_f6_scheduled_digests.py``
exercises :class:`DigestService` directly with a manually-constructed
``PromptLoader`` backed by the real ``prompts/`` directory; the production
call-site at ``scheduler_service.py:560`` was never reached by any unit
test, so the ``str(settings.prompts_dir)`` footgun stayed latent for
~5 weeks after F6 landed (2026-04-19).
"""

from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_ingestion_and_processing_repos():
    """Return an async-context factory yielding throwaway repo mocks.

    Mirrors :func:`tests.test_scheduler_service._mock_ingestion_and_processing_repos`
    but with no behaviour wired up — the test exits via ``not_found`` before
    touching either repo, so AsyncMock defaults are sufficient.
    """

    @asynccontextmanager
    async def _cm():
        mock_state_repo = AsyncMock()
        mock_processed_repo = AsyncMock()
        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        yield mock_state_repo, mock_processed_repo, mock_db

    return _cm


def _stub_digest_subscription_repo(*, sub_to_return):
    """Return an async-context factory yielding a ``sub_repo`` mock.

    ``sub_repo.get`` resolves to ``sub_to_return``; in BUG-028 tests we always
    pass ``None`` so :func:`run_scheduled_digests_task` short-circuits at
    ``not_found`` immediately after the ``PromptLoader`` construction.
    """

    @asynccontextmanager
    async def _cm():
        mock_sub_repo = AsyncMock()
        mock_sub_repo.get.return_value = sub_to_return
        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        yield mock_sub_repo, mock_db

    return _cm


def _build_hermetic_settings():
    """Construct a ``Settings`` instance fully isolated from local env / .env.

    - ``_env_file=None`` bypasses the ``.env`` autoload so a developer's
      personal ``PROMPTS_DIR`` override in ``.env`` cannot poison the test.
    - ``PROMPTS_DIR`` env var must be scrubbed by the caller (via the
      ``hermetic_prompts_env`` fixture).
    """
    from tg_parser.config.settings import Settings

    return Settings(_env_file=None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def hermetic_prompts_env(monkeypatch):
    """Scrub ``PROMPTS_DIR`` so default-mode ``Settings()`` is deterministic.

    The fixture only touches env — ``_env_file`` is handled per-test via
    :func:`_build_hermetic_settings`. Yields the monkeypatch handle so
    callers can layer additional patches on top.
    """
    monkeypatch.delenv("PROMPTS_DIR", raising=False)
    return monkeypatch


# ---------------------------------------------------------------------------
# Layer C — Settings default
# ---------------------------------------------------------------------------


def test_settings_default_prompts_dir_is_path_prompts(hermetic_prompts_env):
    """Layer C: bare ``Settings()`` must expose ``Path("prompts")`` default.

    Pre-fix default was ``None``, which combined with the ``str(...)`` cast
    at the scheduler call-site to produce the literal ``"None"`` string.
    Layer C removes the ambiguity by making the default explicit; the
    ``Path | None`` typing is preserved so Layers A + B remain valid
    defense-in-depth.
    """
    test_settings = _build_hermetic_settings()

    assert test_settings.prompts_dir == Path("prompts"), (
        "Layer C regressed: Settings.prompts_dir default is "
        f"{test_settings.prompts_dir!r} (expected Path('prompts'))"
    )


# ---------------------------------------------------------------------------
# Layer A + C end-to-end through digest_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_digest_task_with_default_settings_loads_yaml_prompt(
    hermetic_prompts_env,
):
    """``run_scheduled_digests_task`` must NOT raise PromptLoaderError on default settings.

    Exercises the *exact* production call-site that BUG-028 fires from
    (scheduler_service.py:560) with the post-fix settings default. After
    short-circuiting at ``not_found`` (PromptLoader is constructed BEFORE
    the DB lookup), we inspect the captured loader and assert it resolves
    real YAML for the two stages :class:`DigestService` actually consumes
    (``digest`` and ``processing``).
    """
    monkeypatch = hermetic_prompts_env

    test_settings = _build_hermetic_settings()
    # Sanity: this test only makes sense once Layer C is in place. If this
    # assertion fails the second integration assertion below would be
    # vacuously testing the wrong code path.
    assert test_settings.prompts_dir == Path("prompts")

    monkeypatch.setattr("tg_parser.services.scheduler_service.settings", test_settings)

    # Capture every PromptLoader instance constructed during the call so we
    # can assert against the *production* object rather than rebuilding our
    # own. spy_init must call the real __init__ to preserve all attributes.
    from tg_parser.processing import prompt_loader as pl_module

    real_init = pl_module.PromptLoader.__init__
    captured_loaders: list[pl_module.PromptLoader] = []
    captured_init_args: list[object] = []

    def spy_init(self, prompts_dir=None):
        captured_init_args.append(prompts_dir)
        real_init(self, prompts_dir=prompts_dir)
        captured_loaders.append(self)

    monkeypatch.setattr(pl_module.PromptLoader, "__init__", spy_init)

    # Function-local imports inside run_scheduled_digests_task pull names
    # from their source modules each call — patch the source, not the
    # scheduler module symbol table.
    monkeypatch.setattr(
        "tg_parser.services.db_context.ingestion_and_processing_repos",
        _stub_ingestion_and_processing_repos(),
    )
    monkeypatch.setattr(
        "tg_parser.services.db_context.digest_subscription_repo",
        _stub_digest_subscription_repo(sub_to_return=None),
    )

    from tg_parser.services.scheduler_service import run_scheduled_digests_task

    # not_found short-circuits BEFORE DigestService / LLM / bot are touched,
    # which keeps the test hermetic. The PromptLoader line is BEFORE the DB
    # lookup, so this still exercises the BUG-028 call-site.
    result = await run_scheduled_digests_task("00000000-0000-0000-0000-000000000000")

    assert result == {
        "subscription_id": "00000000-0000-0000-0000-000000000000",
        "status": "not_found",
    }

    # The not_found short-circuit path constructs exactly ONE PromptLoader
    # (the one at scheduler_service.py:560 — the BUG-028 call-site).
    # Asserting exact count catches spurious extra construction during
    # cold-import of scheduler_service or db_context that would muddy
    # which captured arg we are inspecting.
    assert len(captured_loaders) == 1, (
        f"Expected exactly 1 PromptLoader construction in not_found path, "
        f"got {len(captured_loaders)} (init_args={captured_init_args!r})"
    )

    # Layer A + C: the call-site passes ``str(Path("prompts")) == "prompts"``
    # — never the literal "None". This is the assertion that would have
    # caught BUG-028 if it had existed. Pre-Layer-C alone: arg would be
    # "None" (because str(None) == "None"). Pre-Layer-A with post-Layer-C:
    # arg would still be "prompts" — but the dedicated Layer-A isolation
    # test below covers the None-default scenario.
    assert captured_init_args[0] == "prompts", (
        f"Layer A/C regressed: PromptLoader received {captured_init_args[0]!r} (expected 'prompts')"
    )

    loader = captured_loaders[0]
    assert loader.prompts_dir == Path("prompts")

    # Real YAML resolution (not just "didn't raise"). digest_service loads
    # both "digest" (for system / user templates) and "processing" (re-used
    # in some delivery code paths). Both must yield non-empty system prompts.
    digest_cfg = loader.load("digest")
    assert isinstance(digest_cfg, dict) and digest_cfg, "digest.yaml resolved to empty"
    digest_prompt = digest_cfg.get("system", {}).get("prompt", "")
    assert isinstance(digest_prompt, str) and digest_prompt.strip(), (
        f"digest.yaml system.prompt is empty: {digest_prompt!r}"
    )

    processing_cfg = loader.load("processing")
    assert isinstance(processing_cfg, dict) and processing_cfg
    processing_prompt = processing_cfg.get("system", {}).get("prompt", "")
    assert isinstance(processing_prompt, str) and processing_prompt.strip(), (
        f"processing.yaml system.prompt is empty: {processing_prompt!r}"
    )


# ---------------------------------------------------------------------------
# Layer A guard isolation (forces the pre-Layer-C bug state)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_digest_task_with_explicit_none_prompts_dir_does_not_raise(
    hermetic_prompts_env,
):
    """Layer A: even if ``settings.prompts_dir`` is the bare ``None`` value
    the original F6 sprint shipped, the call-site must NOT regress to
    ``str(None) == "None"`` semantics.

    This is the regression test specifically pinned at the Layer A guard.
    Without the guard, ``captured_init_args[0]`` would equal the string
    ``"None"`` and the assertion below would fail; with the guard, it
    must be the Python ``None`` value (and the PromptLoader's own
    ``None``-handling kicks in to produce ``Path("prompts")``).
    """
    monkeypatch = hermetic_prompts_env

    test_settings = _build_hermetic_settings()
    # Force the original pre-Layer-C bug state — this is what production
    # looked like before 2026-05-23.
    test_settings.prompts_dir = None

    monkeypatch.setattr("tg_parser.services.scheduler_service.settings", test_settings)

    from tg_parser.processing import prompt_loader as pl_module

    real_init = pl_module.PromptLoader.__init__
    captured_loaders: list[pl_module.PromptLoader] = []
    captured_init_args: list[object] = []

    def spy_init(self, prompts_dir=None):
        captured_init_args.append(prompts_dir)
        real_init(self, prompts_dir=prompts_dir)
        captured_loaders.append(self)

    monkeypatch.setattr(pl_module.PromptLoader, "__init__", spy_init)

    monkeypatch.setattr(
        "tg_parser.services.db_context.ingestion_and_processing_repos",
        _stub_ingestion_and_processing_repos(),
    )
    monkeypatch.setattr(
        "tg_parser.services.db_context.digest_subscription_repo",
        _stub_digest_subscription_repo(sub_to_return=None),
    )

    from tg_parser.services.scheduler_service import run_scheduled_digests_task

    result = await run_scheduled_digests_task("00000000-0000-0000-0000-000000000000")

    assert result["status"] == "not_found"
    assert len(captured_loaders) == 1, (
        f"Expected exactly 1 PromptLoader construction, got {len(captured_loaders)} "
        f"(init_args={captured_init_args!r})"
    )

    # Crux of Layer A: guard converts ``None`` → ``None`` (NOT "None").
    # Pre-fix code would have produced the string ``"None"`` here, which
    # would in turn make ``loader.prompts_dir == Path("None")`` — and that
    # is exactly the BUG-028 production failure mode.
    assert captured_init_args[0] is None, (
        f"Layer A guard broken: PromptLoader received {captured_init_args[0]!r} instead of None"
    )

    loader = captured_loaders[0]
    # PromptLoader's own None-branch chooses Path("prompts").
    assert loader.prompts_dir == Path("prompts")

    # Belt-and-suspenders: real YAML still resolves. Pre-fix this raised
    # PromptLoaderError with the "None/digest.yaml" message.
    digest_cfg = loader.load("digest")
    digest_prompt = digest_cfg.get("system", {}).get("prompt", "")
    assert digest_prompt.strip(), (
        f"digest.yaml resolved to empty under None-default fallback: {digest_prompt!r}"
    )
