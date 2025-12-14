"""
Тесты для резолюции Telegram URL.

Покрывает требования:
- TR-58/TR-65: best-effort резолюция URL
- Эвристики из docs/pipeline.md
"""

import pytest

from tg_parser.export.telegram_url import resolve_telegram_url


class TestResolveTelegramUrl:
    """Тесты резолюции Telegram URL (TR-58/TR-65)."""
    
    def test_with_username(self):
        """Если известен username → https://t.me/<username>/<message_id>"""
        url = resolve_telegram_url("any_channel_id", "123", channel_username="mychannel")
        assert url == "https://t.me/mychannel/123"
    
    def test_channel_id_with_100_prefix(self):
        """channel_id вида -100... → https://t.me/c/<internal_id>/<message_id>"""
        url = resolve_telegram_url("-1001234567890", "123")
        assert url == "https://t.me/c/1234567890/123"
    
    def test_public_channel_heuristic(self):
        """Эвристика: channel_id похож на username → прямая ссылка."""
        url = resolve_telegram_url("publicchannel", "123")
        assert url == "https://t.me/publicchannel/123"
        
        url = resolve_telegram_url("My_Channel_2024", "456")
        assert url == "https://t.me/My_Channel_2024/456"
    
    def test_short_username_rejected(self):
        """Username < 5 символов не проходит эвристику."""
        url = resolve_telegram_url("ab", "123")
        assert url is None
    
    def test_numeric_only_channel_rejected(self):
        """Числовой channel_id (но не -100...) не проходит эвристику."""
        url = resolve_telegram_url("-123456", "123")
        assert url is None
    
    def test_special_chars_rejected(self):
        """channel_id со спецсимволами не проходит эвристику."""
        url = resolve_telegram_url("chan#nel", "123")
        assert url is None
    
    def test_username_priority(self):
        """username имеет приоритет даже если channel_id валиден."""
        url = resolve_telegram_url("-1001234567890", "123", channel_username="myusername")
        assert url == "https://t.me/myusername/123"


class TestTelegramUrlDeterminism:
    """Тесты детерминизма резолюции URL."""
    
    def test_deterministic_with_username(self):
        """Повторные вызовы с username дают тот же результат."""
        url1 = resolve_telegram_url("ch", "123", "user")
        url2 = resolve_telegram_url("ch", "123", "user")
        assert url1 == url2
        assert url1 is not None
    
    def test_deterministic_without_username(self):
        """Повторные вызовы без username дают тот же результат."""
        url1 = resolve_telegram_url("-1001234567890", "123")
        url2 = resolve_telegram_url("-1001234567890", "123")
        assert url1 == url2
        assert url1 is not None
    
    def test_deterministic_none(self):
        """Повторные вызовы для неразрешимого ID дают None."""
        url1 = resolve_telegram_url("-999", "123")
        url2 = resolve_telegram_url("-999", "123")
        assert url1 is None
        assert url2 is None
