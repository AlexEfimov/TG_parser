"""LLM-specific exception types."""


class AnthropicBillingError(Exception):
    """Raised when Anthropic rejects request due to exhausted balance."""

    def __init__(self, message: str, request_id: str | None = None):
        super().__init__(message)
        self.request_id = request_id


class LLMCallTimeoutError(TimeoutError):
    """Raised when a single LLM call exceeds its aggregate wall-clock budget.

    BUG-068 (A1): the per-HTTP-attempt httpx timeout does NOT bound the whole
    ``generate_with_usage`` call — the rate-limiter gate (``acquire``) is
    unbounded and the 429/5xx retry loop multiplies wall-clock. This error is
    raised when the aggregate ``asyncio.wait_for`` budget around the entire call
    elapses, so a hung/rate-limited call fails fast and propagates as a per-doc
    failure instead of wedging the serial scheduler indefinitely. Subclasses
    :class:`TimeoutError` (== ``asyncio.TimeoutError`` on 3.11+) so existing
    timeout-aware handlers still catch it.
    """


class LLMJsonParseError(ValueError):
    """LLM response could not be parsed as JSON after the hinted-retry loop.

    BUG-019: the inner stage (e.g. ``_process_single_message``) owns the JSON
    retry-with-corrective-hint loop. Once that budget is exhausted this is
    raised so the OUTER pipeline retry loop can treat malformed JSON as
    non-retryable (avoiding a multiplicative retry blow-up) while still
    retrying genuine transient HTTP/network errors. Subclasses ``ValueError``
    for backward compatibility with existing ``except ValueError`` handlers.
    """
