"""
Адаптивный rate limiting для LLM HTTP API (Session 27).

Token-bucket по RPM / input TPM / output TPM с подстройкой по заголовкам ответов Anthropic.
"""

from __future__ import annotations

import asyncio
import time

import structlog
from httpx import Headers

logger = structlog.get_logger(__name__)

# Tier 1 Anthropic (Claude) — консервативный fallback до первого ответа с заголовками
_DEFAULT_RPM = 50
_DEFAULT_ITPM = 30_000
_DEFAULT_OTPM = 8_000


def _parse_positive_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        v = float(value.strip())
        return v if v >= 0 else None
    except (TypeError, ValueError):
        return None


def _parse_positive_int(value: str | None) -> int | None:
    f = _parse_positive_float(value)
    if f is None:
        return None
    return int(f)


class LLMRateLimiter:
    """
    Async token-bucket limiter: requests/min, input tokens/min, output tokens/min.

    Перед запросом резервируются оценки; после ответа — синхронизация с заголовками Anthropic.
    """

    def __init__(
        self,
        rpm: int,
        input_tokens_per_minute: int,
        output_tokens_per_minute: int,
    ) -> None:
        self._lock = asyncio.Lock()
        self._rpm = max(1, rpm)
        self._itpm = max(1, input_tokens_per_minute)
        self._otpm = max(1, output_tokens_per_minute)

        self._req_tokens = float(self._rpm)
        self._in_tokens = float(self._itpm)
        self._out_tokens = float(self._otpm)
        self._last_refill = time.monotonic()

        self._last_requests_remaining: float | None = None
        self._last_input_remaining: float | None = None
        self._last_output_remaining: float | None = None

    @classmethod
    def from_settings(cls, settings: object) -> LLMRateLimiter:
        """Собрать лимиты из tg_parser.config.settings (ENV)."""
        rpm = getattr(settings, "processing_rate_limit_rpm", None) or _DEFAULT_RPM
        itpm = getattr(settings, "processing_rate_limit_itpm", None) or _DEFAULT_ITPM
        otpm = getattr(settings, "processing_rate_limit_otpm", None) or _DEFAULT_OTPM
        return cls(int(rpm), int(itpm), int(otpm))

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        if elapsed <= 0:
            return
        self._req_tokens = min(self._rpm, self._req_tokens + (self._rpm / 60.0) * elapsed)
        self._in_tokens = min(self._itpm, self._in_tokens + (self._itpm / 60.0) * elapsed)
        self._out_tokens = min(self._otpm, self._out_tokens + (self._otpm / 60.0) * elapsed)

    def _wait_seconds_for(
        self,
        need_req: float,
        need_in: float,
        need_out: float,
    ) -> float:
        """Минимальное время ожидания до возможного acquire (после refill)."""
        deficits: list[float] = []
        if need_req > self._req_tokens:
            deficits.append(60.0 * (need_req - self._req_tokens) / self._rpm)
        if need_in > self._in_tokens:
            deficits.append(60.0 * (need_in - self._in_tokens) / self._itpm)
        if need_out > self._out_tokens:
            deficits.append(60.0 * (need_out - self._out_tokens) / self._otpm)
        return max(deficits) if deficits else 0.0

    def _update_limits_from_headers_locked(self, headers: Headers) -> None:
        """Вызывать только под self._lock."""
        req_lim = _parse_positive_int(headers.get("anthropic-ratelimit-requests-limit"))
        in_lim = _parse_positive_int(headers.get("anthropic-ratelimit-input-tokens-limit"))
        out_lim = _parse_positive_int(headers.get("anthropic-ratelimit-output-tokens-limit"))

        if req_lim is not None and req_lim != self._rpm:
            logger.info("rate_limit_rpm_adjusted", extra={"from": self._rpm, "to": req_lim})
            self._rpm = max(1, req_lim)
            self._req_tokens = min(self._req_tokens, float(self._rpm))
        if in_lim is not None and in_lim != self._itpm:
            logger.info("rate_limit_itpm_adjusted", extra={"from": self._itpm, "to": in_lim})
            self._itpm = max(1, in_lim)
            self._in_tokens = min(self._in_tokens, float(self._itpm))
        if out_lim is not None and out_lim != self._otpm:
            logger.info("rate_limit_otpm_adjusted", extra={"from": self._otpm, "to": out_lim})
            self._otpm = max(1, out_lim)
            self._out_tokens = min(self._out_tokens, float(self._otpm))

    async def sync_remaining_from_headers(self, headers: Headers) -> None:
        """Синхронизировать уровни бакетов с *-remaining из последнего ответа."""
        r_rem: float | None = None
        in_rem: float | None = None
        out_rem: float | None = None
        async with self._lock:
            self._refill()
            self._update_limits_from_headers_locked(headers)

            r_rem = _parse_positive_float(headers.get("anthropic-ratelimit-requests-remaining"))
            in_rem = _parse_positive_float(headers.get("anthropic-ratelimit-input-tokens-remaining"))
            out_rem = _parse_positive_float(headers.get("anthropic-ratelimit-output-tokens-remaining"))

            if r_rem is not None:
                self._last_requests_remaining = r_rem
                self._req_tokens = min(self._req_tokens, r_rem)
            if in_rem is not None:
                self._last_input_remaining = in_rem
                self._in_tokens = min(self._in_tokens, in_rem)
            if out_rem is not None:
                self._last_output_remaining = out_rem
                self._out_tokens = min(self._out_tokens, out_rem)

        if r_rem is not None or in_rem is not None or out_rem is not None:
            logger.debug(
                "anthropic_rate_limit_snapshot",
                extra={
                    "requests_remaining": r_rem,
                    "input_tokens_remaining": in_rem,
                    "output_tokens_remaining": out_rem,
                },
            )

    async def reconcile_usage(
        self,
        input_estimate: int,
        output_estimate: int,
        input_actual: int | None,
        output_actual: int | None,
    ) -> None:
        """
        Уточнить списание: оценки уже вычтены в acquire; скорректировать по фактическому usage.
        """
        if input_actual is None and output_actual is None:
            return
        in_est = max(0, input_estimate)
        out_est = max(0, output_estimate)
        in_act = input_actual if input_actual is not None else in_est
        out_act = output_actual if output_actual is not None else out_est
        in_delta = in_est - max(0, in_act)
        out_delta = out_est - max(0, out_act)
        async with self._lock:
            if in_delta:
                self._in_tokens = min(float(self._itpm), self._in_tokens + in_delta)
            if out_delta:
                self._out_tokens = min(float(self._otpm), self._out_tokens + out_delta)

    async def refund_acquire(self, input_estimate: int, output_estimate: int) -> None:
        """Вернуть резерв после неуспешного запроса (например 429 до списания usage)."""
        async with self._lock:
            self._req_tokens = min(float(self._rpm), self._req_tokens + 1.0)
            self._in_tokens = min(float(self._itpm), self._in_tokens + max(0, float(input_estimate)))
            self._out_tokens = min(float(self._otpm), self._out_tokens + max(0, float(output_estimate)))

    async def acquire(
        self,
        input_estimate: int,
        output_estimate: int,
    ) -> None:
        """Заблокировать до возможности отправить 1 запрос с заданными оценками токенов."""
        need_in = max(0, float(input_estimate))
        need_out = max(0, float(output_estimate))

        while True:
            sleep_for: float
            async with self._lock:
                self._refill()
                if self._req_tokens >= 1.0 and self._in_tokens >= need_in and self._out_tokens >= need_out:
                    self._req_tokens -= 1.0
                    self._in_tokens -= need_in
                    self._out_tokens -= need_out
                    return
                sleep_for = self._wait_seconds_for(1.0, need_in, need_out)
                sleep_for = max(sleep_for, 0.05)

            await asyncio.sleep(min(sleep_for, 5.0))

    def suggested_parallel_cap(self, requested: int) -> int:
        """
        Снизить параллелизм, если по заголовкам осталось мало слотов в минутном окне.

        Вызывается один раз на старт батча (например из pipeline).
        """
        if requested <= 1:
            return requested
        r = self._last_requests_remaining
        if r is None:
            return requested
        # не запускать больше ~60% от оставшихся запросов в окне
        cap = max(1, int(r * 0.6))
        return min(requested, cap)
