"""Price-changes digest: заглушка (модуль был утерян из незакоммиченных файлов)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VersionDiff:
    product_id: str = ""
    old_price: float = 0.0
    new_price: float = 0.0
    category: str = ""


@dataclass
class DigestRecipient:
    user_id: str = ""
    email: str = ""
    telegram_id: str | None = None
    enabled: bool = True


async def compute_version_diff(*args: Any, **kwargs: Any) -> list[VersionDiff]:
    return []


async def find_digest_recipients(*args: Any, **kwargs: Any) -> list[DigestRecipient]:
    return []
