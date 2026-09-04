"""Сервис новостейной ленты (публичная + админский CRUD)."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import news as news_repo
from app.schemas import MetaPage
from app.schemas.news import NewsCreate, NewsPage, NewsRead, NewsUpdate


class NotFoundError(ValueError):
    """Новость не найдена."""


class NewsService:
    """Публичная лента новостей и CRUD для менеджера."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list(self, page: int, per_page: int) -> NewsPage:
        limit, offset = per_page, (page - 1) * per_page
        rows = await news_repo.fetch_news(self.db, limit=limit, offset=offset)
        total = await news_repo.count_news(self.db)
        items = [NewsRead.model_validate(row) for row in rows]
        return NewsPage(
            data=items,
            meta=MetaPage(page=page, per_page=per_page, total=total),
        )

    async def get_public(self, news_id: uuid.UUID) -> NewsRead:
        """Одна активная опубликованная новость; иначе NotFoundError (→ 404)."""
        row = await news_repo.get_active_by_id(self.db, news_id)
        if row is None:
            raise NotFoundError("Новость не найдена")
        return NewsRead.model_validate(row)

    async def list_admin(self, page: int, per_page: int) -> NewsPage:
        limit, offset = per_page, (page - 1) * per_page
        rows = await news_repo.fetch_news_all(self.db, limit=limit, offset=offset)
        total = await news_repo.count_news_all(self.db)
        items = [NewsRead.model_validate(row) for row in rows]
        return NewsPage(
            data=items,
            meta=MetaPage(page=page, per_page=per_page, total=total),
        )

    async def create(self, payload: NewsCreate) -> NewsRead:
        fields = payload.model_dump()
        if fields["published_at"] is None:
            fields.pop("published_at")  # server_default now()
        row = await news_repo.create(self.db, **fields)
        return NewsRead.model_validate(row)

    async def update(self, news_id: uuid.UUID, payload: NewsUpdate) -> NewsRead:
        row = await news_repo.get_by_id(self.db, news_id)
        if row is None:
            raise NotFoundError("Новость не найдена")
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return NewsRead.model_validate(row)

    async def delete(self, news_id: uuid.UUID) -> None:
        row = await news_repo.get_by_id(self.db, news_id)
        if row is None:
            raise NotFoundError("Новость не найдена")
        await news_repo.delete(self.db, row)
