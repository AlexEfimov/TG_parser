"""
CurrentUser model for F4 Multi-Tenancy.

Lives at the interface layer; services and repos receive
allowed_channel_ids: list[str] | None instead.
"""

from dataclasses import dataclass


@dataclass
class CurrentUser:
    id: str
    name: str
    role: str  # 'admin' | 'user'
    allowed_channel_ids: list[str] | None  # None = admin (all channels)
    max_channels: int

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"
