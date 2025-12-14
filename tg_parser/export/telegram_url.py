"""
Резолюция Telegram URL (best-effort).

Реализует TR-58/TR-65 и эвристики из docs/pipeline.md.
"""

import re
from typing import Optional


def resolve_telegram_url(
    channel_id: str,
    message_id: str,
    channel_username: Optional[str] = None,
) -> Optional[str]:
    """
    Создать человекочитаемую ссылку на Telegram (best-effort).
    
    Правила (TR-58/TR-65 + эвристики pipeline.md):
    1) Если известен channel_username → https://t.me/<username>/<message_id>
    2) Иначе, если channel_id вида -100... → https://t.me/c/<internal_id>/<message_id>
    3) Иначе, если channel_id похож на username (эвристика) → https://t.me/<channel_id>/<message_id>
    4) Иначе → None
    
    Args:
        channel_id: Идентификатор канала
        message_id: Идентификатор сообщения
        channel_username: Опциональное имя канала
        
    Returns:
        URL строка или None если не удалось построить
        
    Examples:
        >>> resolve_telegram_url("mychannel", "123", "mychannel")
        'https://t.me/mychannel/123'
        
        >>> resolve_telegram_url("-1001234567890", "123")
        'https://t.me/c/1234567890/123'
        
        >>> resolve_telegram_url("publicchannel", "123")
        'https://t.me/publicchannel/123'
        
        >>> resolve_telegram_url("-123456", "123")
        None
    """
    # 1) Username известен → используем его
    if channel_username:
        return f"https://t.me/{channel_username}/{message_id}"
    
    # 2) channel_id вида -100... → формат /c/<internal_id>/<message_id>
    if channel_id.startswith("-100"):
        internal_id = channel_id[4:]  # убираем префикс -100
        return f"https://t.me/c/{internal_id}/{message_id}"
    
    # 3) Эвристика: channel_id похож на публичный username
    # Правило MVP: не начинается с '-' и матчится на ^[A-Za-z0-9_]{5,}$
    if not channel_id.startswith("-") and re.match(r"^[A-Za-z0-9_]{5,}$", channel_id):
        return f"https://t.me/{channel_id}/{message_id}"
    
    # 4) Не удалось построить URL
    return None
