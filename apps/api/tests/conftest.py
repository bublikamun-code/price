"""Тестовая инфраструктура.

Поднимает PostgreSQL (testcontainers) на сессию, создаёт схему по моделям
(Base.metadata.create_all), для каждого теста чистит таблицы (TRUNCATE CASCADE).
Provides:
  - db_url, engine, db_session (низкоуровневый доступ к БД)
  - api_client (httpx AsyncClient поверх FastAPI через ASGITransport)
  - create_user(email, role, password) -> User  (хелпер для сидинга)
"""
import os
from datetime import date

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401  (регистрация моделей в Base.metadata)
from app.core.limiter import limiter
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.catalog import Brand, Product, Series
from app.models.enums import OrganizationRole, StockStatus, UserRole
from app.models.pricing import ExchangeRate, UserBrand
from app.models.organization import (
    Organization,
    OrganizationBrandTerm,
    OrganizationMembership,
    OrganizationPricingAgreement,
)
from app.models.user import User

# testcontainers — импортируем лениво (нужен только без TEST_DB_URL)
def _import_pg_container():
    from testcontainers.postgres import PostgresContainer
    return PostgresContainer


# ---------- DB URL: env override или testcontainers ----------
@pytest.fixture(scope="session")
def db_url():
    env_url = os.environ.get("TEST_DB_URL")
    if env_url:
        yield env_url
        return
    PostgresContainer = _import_pg_container()
    container = PostgresContainer("postgres:16-alpine", driver="asyncpg")
    container.start()
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


# ---------- Engine + schema (session-scoped) ----------
@pytest_asyncio.fixture(scope="session")
async def engine(db_url):
    # NullPool: новое соединение на каждый checkout → нет переиспользования
    # между разными event-loop'ами (pytest-asyncio + asyncpg).
    eng = create_async_engine(db_url, pool_pre_ping=True, poolclass=NullPool)
    # Расширения, нужные моделям (create_all не запускает логику миграций)
    async with eng.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)
    # PG-enum нельзя ALTER'ить внутри транзакции — отдельный autocommit-коннект.
    # Нужно только для ранее созданной тестовой БД (свежая create_all уже
    # содержит все значения enum). Idempotent.
    raw = create_async_engine(db_url, poolclass=NullPool)
    try:
        async with raw.connect() as raw_conn:
            await raw_conn.execution_options(isolation_level="AUTOCOMMIT")
            await raw_conn.execute(
                text(
                    "DO $$ BEGIN "
                    "ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'ADMIN'; "
                    "EXCEPTION WHEN undefined_object THEN NULL; END $$"
                )
            )
    finally:
        await raw.dispose()
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _truncate_tables(engine):
    """Чистим все таблицы перед каждым тестом."""
    async with engine.begin() as conn:
        names = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
        await conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def _isolated_cache():
    """Module-level Redis-клиент кэша привязан к первому event-loop, а у каждого
    теста свой loop → подменяем клиент на свежий и чистим ключи между тестами
    (RESTART IDENTITY переиспользует user_id, stale-кэш протёк бы в следующий тест)."""
    from redis.asyncio import Redis

    from app.core.config import settings
    from app.services import cache as cache_module

    original_redis = cache_module.cache.redis
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    cache_module.cache.redis = client
    try:
        keys = await client.keys(f"{settings.cache_key_prefix}:*")
        if keys:
            await client.delete(*keys)
    except Exception:
        pass  # Redis недоступен (локальный запуск без compose) — тесты кэша со своими стабами
    yield
    cache_module.cache.redis = original_redis
    await client.aclose()


# ---------- helpers ----------
@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(bind=engine, expire_on_commit=False)


async def create_user(
    session_factory, *, email: str, role: UserRole, password: str = "Passw0rd!"
) -> User:
    async with session_factory() as s:
        user = User(
            email=email,
            password_hash=hash_password(password),
            full_name=email.split("@")[0].title(),
            role=role,
            is_active=True,
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


# ---------- catalog seed helpers ----------


async def create_brand(session_factory, *, name: str, slug: str | None = None) -> Brand:
    async with session_factory() as s:
        brand = Brand(name=name, slug=slug or name.lower().replace(" ", "-"))
        s.add(brand)
        await s.commit()
        await s.refresh(brand)
        return brand


async def create_series(session_factory, *, brand: Brand, name: str, photo_key: str | None = None) -> Series:
    async with session_factory() as s:
        ser = Series(name=name, brand_id=brand.id, photo_key=photo_key)
        s.add(ser)
        await s.commit()
        await s.refresh(ser)
        return ser


async def create_product(
    session_factory,
    *,
    sku: str,
    name: str,
    brand: Brand | None = None,
    series: Series | None = None,
    base_price=100,
    override_price=None,
    stock: StockStatus = StockStatus.IN_STOCK,
    stock_qty: int | None = None,
    attributes: dict | None = None,
) -> Product:
    async with session_factory() as s:
        p = Product(
            sku=sku,
            name=name,
            brand_id=brand.id if brand else None,
            series_id=series.id if series else None,
            base_price=base_price,
            override_price=override_price,
            stock_status=stock,
            stock_qty=stock_qty,
            attributes=attributes or {},
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p


async def set_discount(session_factory, *, user: User, brand: Brand, percent) -> None:
    async with session_factory() as s:
        s.add(UserBrand(user_id=user.id, brand_id=brand.id, discount_percent=percent))
        await s.commit()


async def set_rate(
    session_factory,
    *,
    currency: str,
    rate,
    scale: int = 1,
    fetched_at: date | None = None,
    source: str = "NBRB",
) -> ExchangeRate:
    async with session_factory() as s:
        er = ExchangeRate(
            currency_code=currency.upper(),
            rate=rate,
            scale=scale,
            fetched_at=fetched_at or date.today(),
            source=source,
            is_manual=False,
        )
        s.add(er)
        await s.commit()
        await s.refresh(er)
        return er


async def set_fixed_rate_for_user(session_factory, *, user: User, rate: ExchangeRate) -> User:
    async with session_factory() as s:
        db_user = await s.get(User, user.id)
        db_user.fixed_rate_id = rate.id
        db_user.display_currency = rate.currency_code
        await s.commit()
        return db_user


async def set_display_currency(session_factory, *, user: User, currency: str) -> None:
    async with session_factory() as s:
        db_user = await s.get(User, user.id)
        db_user.display_currency = currency.upper()
        await s.commit()


async def create_organization(
    session_factory,
    *,
    legal_name: str,
    default_currency: str = "BYN",
    display_name: str | None = None,
) -> Organization:
    async with session_factory() as s:
        organization = Organization(
            legal_name=legal_name,
            display_name=display_name,
            default_currency=default_currency.upper(),
        )
        s.add(organization)
        await s.commit()
        await s.refresh(organization)
        return organization


async def add_organization_membership(
    session_factory,
    *,
    user: User,
    organization: Organization,
    role: OrganizationRole = OrganizationRole.BUYER,
    is_active: bool = True,
    is_primary: bool = False,
) -> OrganizationMembership:
    async with session_factory() as s:
        membership = OrganizationMembership(
            user_id=user.id,
            organization_id=organization.id,
            role=role,
            is_active=is_active,
            is_primary=is_primary,
        )
        s.add(membership)
        await s.commit()
        await s.refresh(membership)
        return membership


async def set_active_organization(
    session_factory, *, user: User, organization: Organization
) -> User:
    async with session_factory() as s:
        db_user = await s.get(User, user.id)
        db_user.active_organization_id = organization.id
        await s.commit()
        return db_user


async def set_organization_pricing_agreement(
    session_factory,
    *,
    organization: Organization,
    display_currency: str,
    fixed_rate_id=None,
    agreement_reference: str | None = None,
) -> OrganizationPricingAgreement:
    async with session_factory() as s:
        agreement = OrganizationPricingAgreement(
            organization_id=organization.id,
            display_currency=display_currency.upper(),
            fixed_rate_id=fixed_rate_id,
            agreement_reference=agreement_reference,
        )
        s.add(agreement)
        await s.commit()
        await s.refresh(agreement)
        return agreement


async def set_organization_brand_term(
    session_factory,
    *,
    organization: Organization,
    brand: Brand,
    percent,
) -> OrganizationBrandTerm:
    async with session_factory() as s:
        term = OrganizationBrandTerm(
            organization_id=organization.id,
            brand_id=brand.id,
            discount_percent=percent,
        )
        s.add(term)
        await s.commit()
        await s.refresh(term)
        return term


# ---------- HTTP client ----------
@pytest_asyncio.fixture
async def api_client(engine, session_factory):
    """httpx AsyncClient с переопределённой get_db → тестовый движок.

    Rate-limiter отключён (включается точечно в тесте rate-limit).
    """
    async def _override_get_db():
        async with session_factory() as s:
            try:
                yield s
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    limiter.enabled = False
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        original_request = client.request

        async def _request_with_csrf(method, url, **kwargs):
            if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
                headers = dict(kwargs.pop("headers", {}) or {})
                if "Authorization" not in headers and "authorization" not in headers:
                    csrf_token = client.cookies.get("csrf_token")
                    if csrf_token:
                        headers.setdefault("X-CSRF-Token", csrf_token)
                kwargs["headers"] = headers
            return await original_request(method, url, **kwargs)

        client.request = _request_with_csrf
        yield client
    app.dependency_overrides.clear()
    limiter.enabled = False
