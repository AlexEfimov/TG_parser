"""LLM-specific exception types."""


class AnthropicBillingError(Exception):
    """Raised when Anthropic rejects request due to exhausted balance."""

    def __init__(self, message: str, request_id: str | None = None):
        super().__init__(message)
        self.request_id = request_id


class LLMJsonParseError(ValueError):
    """LLM response could not be parsed as JSON after the hinted-retry loop.

    BUG-019: the inner stage (e.g. ``_process_single_message``) owns the JSON
    retry-with-corrective-hint loop. Once that budget is exhausted this is
    raised so the OUTER pipeline retry loop can treat malformed JSON as
    non-retryable (avoiding a multiplicative retry blow-up) while still
    retrying genuine transient HTTP/network errors. Subclasses ``ValueError``
    for backward compatibility with existing ``except ValueError`` handlers.
    """
