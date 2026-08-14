"""Кастомные SQL-типы для PostgreSQL.

CITEXT — case-insensitive текст (для email). Требует расширения `citext`
(создаётся в миграции 0001).
"""
from sqlalchemy.types import UserDefinedType


class CITEXT(UserDefinedType):
    """PostgreSQL CITEXT — case-insensitive text."""

    cache_ok = True

    def get_col_spec(self) -> str:
        return "CITEXT"

    def bind_processor(self, dialect):
        return None  # CITEXT сам приводит к lowercase при сравнении

    def result_processor(self, dialect, coltype):
        return None
