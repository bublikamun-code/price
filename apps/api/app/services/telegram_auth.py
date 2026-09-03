"""Telegram auth service — заглушка (501 Not Implemented)."""
import uuid


def generate_link_code(user_id: uuid.UUID) -> dict:
    """Сгенерировать одноразовый код связки Telegram — заглушка."""
    return {"code": "STUB", "expires_in": 0}
