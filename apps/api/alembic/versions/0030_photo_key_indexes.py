"""Индексы на photo_key + чистка неподдерживаемых display_currency.

Выдача фото (``GET /api/v1/files/photo``) — fail-closed: ключ должен быть
известен системе, иначе 404. Проверка идёт по трём источникам: реестр медиа
(``media_assets.s3_key``, индекс есть), фото серии (``series.photo_key``) и
галерея товара (``product_photos.photo_key``). Индексов на последних двух
колонках не было — проверка шла последовательным просмотром таблицы на КАЖДЫЙ
запрошенный кадр. На каталоге с сотней тысяч фотографий это заметная нагрузка
на ровно том эндпоинте, который отдаёт картинки.

Вторая часть — чистка ``users.display_currency``: v1-профиль принимал любые три
латинские буквы, а v2-контракт требует whitelist {BYN, EUR, RUB, USD}. Значение
из профиля попадало в v2-DTO, и невалидная валюта давала 500 (валидация
ответа) — менеджер не мог войти в v2 вообще. Невалидные значения заменяем на
BYN (правка §17: клиент видит цены только в BYN).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_photo_key_indexes"
down_revision: str | Sequence[str] | None = "0029_quotes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUPPORTED_CURRENCIES = ("BYN", "EUR", "RUB", "USD")


def upgrade() -> None:
    op.create_index(
        "ix_series_photo_key", "series", ["photo_key"], unique=False
    )
    op.create_index(
        "ix_product_photos_photo_key", "product_photos", ["photo_key"], unique=False
    )
    op.execute(
        sa.text(
            "UPDATE users SET display_currency = 'BYN' "
            "WHERE display_currency IS NOT NULL "
            "AND display_currency NOT IN :allowed"
        ).bindparams(sa.bindparam("allowed", value=list(SUPPORTED_CURRENCIES), expanding=True))
    )


def downgrade() -> None:
    op.drop_index("ix_product_photos_photo_key", table_name="product_photos")
    op.drop_index("ix_series_photo_key", table_name="series")
