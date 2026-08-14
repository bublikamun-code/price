"""Сервис избранного. См. ARCHITECTURE_PLAN.md §16.1 (фича A).

Избранное — список отслеживания клиента; источник данных для будущих
уведомлений ``PRICE_CHANGED_DIGEST`` (Этап 6.5). Архивные/удалённые товары
из списка НЕ скрываются — фронт показывает бейдж статуса.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import catalog as catalog_repo, favorites as fav_repo
from app.schemas import MetaPage
from app.schemas.favorite import FavoriteListPage, FavoriteRead
from app.services.pricing import PricingService


class FavoriteService:
    """Операции со списком избранного текущего пользователя."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.pricing = PricingService(db)

    async def list(self, user, page: int, per_page: int) -> FavoriteListPage:
        limit, offset = per_page, (page - 1) * per_page
        rows = await fav_repo.fetch_favorites(
            self.db, user_id=user.id, limit=limit, offset=offset
        )
        total = await fav_repo.count_favorites(self.db, user_id=user.id)

        items: list[FavoriteRead] = []
        for row in rows:
            product = row[1]
            if product is None:
                continue  # товар удалён — пропускаем в выдаче
            pr = await self.pricing.price_product(product, user, "fixed")
            items.append(
                FavoriteRead(
                    product_id=product.id,
                    sku=product.sku,
                    name=product.name,
                    brand_name=row.brand_name,
                    photo_key=row.photo_key,
                    stock_status=product.stock_status.value
                    if hasattr(product.stock_status, "value")
                    else str(product.stock_status),
                    base_price_byn=float(pr["base_price_byn"]),
                    retail_price=float(pr["retail_price"]),
                    client_price=float(pr["client_price"]),
                    currency=pr["currency"],
                    has_discount=pr["has_discount"],
                )
            )
        return FavoriteListPage(
            data=items, meta=MetaPage(page=page, per_page=per_page, total=total)
        )

    async def add(self, user, sku: str) -> None:
        product = await catalog_repo.get_by_sku(self.db, sku)
        if product is None:
            raise ValueError("Товар не найден")
        await fav_repo.add_favorite(
            self.db, user_id=user.id, product_id=product.id
        )

    async def delete(self, user, sku: str) -> None:
        product = await catalog_repo.get_by_sku(self.db, sku)
        if product is None:
            raise ValueError("Товар не найден")
        ok = await fav_repo.delete_favorite(
            self.db, user_id=user.id, product_id=product.id
        )
        if not ok:
            raise ValueError("Товара нет в избранном")
