"""LLM-specific exception types."""


class AnthropicBillingError(Exception):
    """Raised when Anthropic rejects request due to exhausted balance."""

    def __init__(self, message: str, request_id: str | None = None):
        super().__init__(message)
        self.request_id = request_id
