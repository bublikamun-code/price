"""Сервис новостейной ленты."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import news as news_repo
from app.schemas import MetaPage
from app.schemas.news import NewsPage, NewsRead


class NewsService:
    """Публичная лента новостей."""

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
