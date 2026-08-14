"""Тесты расчёта изменений цен и диспетчера PRICE_CHANGED/DIGEST (§20.4).

Слои:
  1. ``compute_version_diff`` — сравнение версий (new/up/down/override_reset/unchanged);
  2. ``find_digest_recipients`` — подбор клиентов opt-in по корзине/избранному/заказам;
  3. ``_dispatch`` (async-ядро Celery-таски) — создание in-app + TG менеджеру.

Таска зовётся через async-ядро напрямую (``_dispatch``), т.к. ``asyncio.run`` из
async-теста падает (канон проекта, см. test_import_csv / test_fetch_nbrb_rates).
``_worker_session`` подменяется на тестовый sessionmaker.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

import app.repositories.price_changes as pc
import app.tasks.notifications as notif_task
from app.core.security import hash_password
from app.models.catalog import PriceHistory, PriceListVersion
from app.models.enums import ImportMode, PriceListVersionStatus, UserRole
from app.models.order import Cart, CartItem
from app.models.system import Notification
from app.models.user import Favorite, User
from tests.conftest import create_brand, create_product, create_user


# ----------------------------- helpers -----------------------------

PASSWORD = "Passw0rd!"


async def _make_version(
    sf, *, manager, status=PriceListVersionStatus.DONE,
    filename="p.csv", created_at=None,
) -> PriceListVersion:
    async with sf() as s:
        v = PriceListVersion(
            uploaded_by=manager.id,
            filename=filename,
            import_mode=ImportMode.UPSERT,
            status=status,
            base_currency="BYN",
            rate_to_byn=1,
            rate_source="MANUAL",
        )
        if created_at is not None:
            v.created_at = created_at
        s.add(v)
        await s.commit()
        await s.refresh(v)
        return v


async def _add_history(sf, *, product, version, base, override=None) -> None:
    async with sf() as s:
        s.add(
            PriceHistory(
                product_id=product.id,
                base_price=base,
                override_price=override,
                price_list_version_id=version.id,
            )
        )
        await s.commit()


async def _make_client(sf, *, email, enabled=True,
                       sources=None) -> User:
    async with sf() as s:
        u = User(
            email=email,
            password_hash=hash_password(PASSWORD),
            full_name=email.split("@")[0].title(),
            role=UserRole.CLIENT,
            is_active=True,
            price_digest_enabled=enabled,
            price_digest_sources=sources or ["cart", "favorite", "orders"],
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


class _FakeTg:
    """Фейк Celery-таски send_telegram: записывает вызовы .delay()."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def delay(self, chat_id: str, text: str) -> None:
        self.calls.append((chat_id, text))


# ===========================================================================
# 1. compute_version_diff
# ===========================================================================
@pytest.mark.asyncio
class TestComputeVersionDiff:
    async def test_no_previous_version_all_new(self, session_factory):
        mgr = await create_user(session_factory, email="m1@x.by", role=UserRole.MANAGER)
        brand = await create_brand(session_factory, name="B1")
        prod = await create_product(
            session_factory, sku="A", name="Widget", brand=brand, base_price=100
        )
        v1 = await _make_version(session_factory, manager=mgr)
        await _add_history(
            session_factory, product=prod, version=v1, base=Decimal("100.00")
        )

        async with session_factory() as db:
            diff = await pc.compute_version_diff(db, v1.id)

        assert diff.previous_version_id is None
        assert diff.count_new == 1
        assert diff.count_up == 0
        assert diff.count_down == 0
        assert diff.count_override_reset == 0
        assert diff.count_unchanged == 0
        assert len(diff.changed) == 1
        change = diff.changed[0]
        assert change.category == "new"
        assert change.sku == "A"
        assert change.old_base is None
        assert change.new_base == Decimal("100.00")
        assert change.delta_percent is None

    async def test_up_down_unchanged(self, session_factory):
        mgr = await create_user(session_factory, email="m2@x.by", role=UserRole.MANAGER)
        brand = await create_brand(session_factory, name="B2")
        pa = await create_product(session_factory, sku="A", name="A", brand=brand, base_price=100)
        pb = await create_product(session_factory, sku="B", name="B", brand=brand, base_price=100)
        pс = await create_product(session_factory, sku="C", name="C", brand=brand, base_price=100)
        pd = await create_product(session_factory, sku="D", name="D", brand=brand, base_price=100)
        t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        v_prev = await _make_version(
            session_factory, manager=mgr, filename="prev.csv", created_at=t0
        )
        v_new = await _make_version(
            session_factory, manager=mgr, filename="new.csv",
            created_at=t0 + timedelta(hours=1),
        )
        # prev: все по 100, у D фикс-цена 90
        await _add_history(session_factory, product=pa, version=v_prev, base=Decimal("100.00"))
        await _add_history(session_factory, product=pb, version=v_prev, base=Decimal("100.00"))
        await _add_history(session_factory, product=pс, version=v_prev, base=Decimal("100.00"))
        await _add_history(
            session_factory, product=pd, version=v_prev,
            base=Decimal("100.00"), override=Decimal("90.00"),
        )
        # new: A↑, B↓, C=, D фикс-цена сброшена
        await _add_history(session_factory, product=pa, version=v_new, base=Decimal("110.00"))
        await _add_history(session_factory, product=pb, version=v_new, base=Decimal("90.00"))
        await _add_history(session_factory, product=pс, version=v_new, base=Decimal("100.00"))
        await _add_history(
            session_factory, product=pd, version=v_new,
            base=Decimal("100.00"), override=None,
        )

        async with session_factory() as db:
            diff = await pc.compute_version_diff(db, v_new.id)

        assert diff.previous_version_id == v_prev.id
        assert diff.count_up == 1
        assert diff.count_down == 1
        assert diff.count_override_reset == 1
        assert diff.count_unchanged == 1
        assert diff.count_new == 0
        by_sku = {c.sku: c for c in diff.changed}
        assert set(by_sku) == {"A", "B", "D"}
        assert by_sku["A"].category == "up"
        assert by_sku["B"].category == "down"
        assert by_sku["D"].category == "override_reset"
        assert by_sku["A"].delta_percent == 10.0
        assert by_sku["B"].delta_percent == -10.0

    async def test_override_reset_only_when_was_set(self, session_factory):
        """override_reset фиксируется только когда фикс-цена БЫЛА и ушла."""
        mgr = await create_user(session_factory, email="m3@x.by", role=UserRole.MANAGER)
        brand = await create_brand(session_factory, name="B3")
        p1 = await create_product(session_factory, sku="X", name="X", brand=brand, base_price=100)
        p2 = await create_product(session_factory, sku="Y", name="Y", brand=brand, base_price=100)
        t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        v_prev = await _make_version(
            session_factory, manager=mgr, filename="prev.csv", created_at=t0
        )
        v_new = await _make_version(
            session_factory, manager=mgr, filename="new.csv",
            created_at=t0 + timedelta(hours=1),
        )
        # X: фикс-цены не было и нет → unchanged
        await _add_history(session_factory, product=p1, version=v_prev, base=Decimal("100.00"))
        await _add_history(session_factory, product=p1, version=v_new, base=Decimal("100.00"))
        # Y: фикс-цена 80 была и осталась → unchanged
        await _add_history(
            session_factory, product=p2, version=v_prev,
            base=Decimal("100.00"), override=Decimal("80.00"),
        )
        await _add_history(
            session_factory, product=p2, version=v_new,
            base=Decimal("100.00"), override=Decimal("80.00"),
        )

        async with session_factory() as db:
            diff = await pc.compute_version_diff(db, v_new.id)

        assert diff.count_override_reset == 0
        assert diff.count_unchanged == 2
        assert diff.changed == []


# ===========================================================================
# 2. find_digest_recipients
# ===========================================================================
@pytest.mark.asyncio
class TestFindDigestRecipients:
    async def test_subscriber_with_cart_match_receives(self, session_factory):
        u1 = await _make_client(
            session_factory, email="c1@x.by",
            sources=["cart", "favorite", "orders"],
        )
        # U2 — не подписан
        await _make_client(session_factory, email="c2@x.by", enabled=False)
        brand = await create_brand(session_factory, name="BC")
        prod_a = await create_product(
            session_factory, sku="A", name="A", brand=brand, base_price=100
        )
        # U1 имеет A в корзине
        async with session_factory() as s:
            cart = Cart(user_id=u1.id, name="Корзина")
            s.add(cart)
            await s.flush()
            s.add(CartItem(cart_id=cart.id, product_id=prod_a.id, quantity=1))
            await s.commit()

        changed = [
            pc.ProductPriceChange(
                product_id=prod_a.id, sku="A", name="A", category="up",
                old_base=Decimal("100"), new_base=Decimal("110"), delta_percent=10.0,
            )
        ]

        async with session_factory() as db:
            recipients = await pc.find_digest_recipients(db, changed)

        assert len(recipients) == 1
        assert recipients[0].user_id == u1.id
        affected_by_id = {a.product_id: a for a in recipients[0].affected}
        assert prod_a.id in affected_by_id
        assert "cart" in affected_by_id[prod_a.id].sources

    async def test_non_subscriber_excluded(self, session_factory):
        # Подписчиков нет (клиент с enabled=False) → пусто.
        await _make_client(session_factory, email="n1@x.by", enabled=False)
        brand = await create_brand(session_factory, name="BN")
        prod = await create_product(
            session_factory, sku="N", name="N", brand=brand, base_price=100
        )
        changed = [
            pc.ProductPriceChange(
                product_id=prod.id, sku="N", name="N", category="up",
                old_base=Decimal("100"), new_base=Decimal("110"), delta_percent=10.0,
            )
        ]
        async with session_factory() as db:
            recipients = await pc.find_digest_recipients(db, changed)
        assert recipients == []

    async def test_subscriber_no_match_excluded(self, session_factory):
        u1 = await _make_client(session_factory, email="s1@x.by")
        brand = await create_brand(session_factory, name="BS")
        tracked = await create_product(
            session_factory, sku="TRACKED", name="T", brand=brand, base_price=100
        )
        changed_prod = await create_product(
            session_factory, sku="CHANGED", name="C", brand=brand, base_price=100
        )
        # U1 отслеживает TRACKED, а изменился CHANGED — пересечения нет
        async with session_factory() as s:
            s.add(Favorite(user_id=u1.id, product_id=tracked.id))
            await s.commit()
        changed = [
            pc.ProductPriceChange(
                product_id=changed_prod.id, sku="CHANGED", name="C", category="up",
                old_base=Decimal("100"), new_base=Decimal("110"), delta_percent=10.0,
            )
        ]
        async with session_factory() as db:
            recipients = await pc.find_digest_recipients(db, changed)
        assert recipients == []

    async def test_sources_filter(self, session_factory):
        """Подписан только на favorite → совпадение по cart не учитывается."""
        u1 = await _make_client(session_factory, email="f1@x.by", sources=["favorite"])
        brand = await create_brand(session_factory, name="BF")
        prod = await create_product(
            session_factory, sku="F", name="F", brand=brand, base_price=100
        )
        # prod есть в корзине, но НЕ в избранном
        async with session_factory() as s:
            cart = Cart(user_id=u1.id, name="Корзина")
            s.add(cart)
            await s.flush()
            s.add(CartItem(cart_id=cart.id, product_id=prod.id, quantity=1))
            await s.commit()
        changed = [
            pc.ProductPriceChange(
                product_id=prod.id, sku="F", name="F", category="up",
                old_base=Decimal("100"), new_base=Decimal("110"), delta_percent=10.0,
            )
        ]
        async with session_factory() as db:
            recipients = await pc.find_digest_recipients(db, changed)
        assert recipients == []


# ===========================================================================
# 3. _dispatch (Celery-таска, async-ядро)
# ===========================================================================
@pytest.mark.asyncio
class TestDispatch:
    async def test_dispatch_manager_and_client_notifications(
        self, session_factory, monkeypatch
    ):
        monkeypatch.setattr(notif_task, "_worker_session", session_factory)
        monkeypatch.setattr(notif_task.settings, "telegram_manager_chat_id", "999")
        fake_tg = _FakeTg()
        monkeypatch.setattr(notif_task, "send_telegram", fake_tg)

        mgr = await create_user(session_factory, email="m8@x.by", role=UserRole.MANAGER)
        u1 = await _make_client(
            session_factory, email="c8@x.by", sources=["favorite"]
        )
        brand = await create_brand(session_factory, name="B8")
        prod = await create_product(
            session_factory, sku="A", name="Widget", brand=brand, base_price=100
        )
        t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        v_prev = await _make_version(
            session_factory, manager=mgr, filename="prev.csv", created_at=t0
        )
        v_new = await _make_version(
            session_factory, manager=mgr, filename="new.csv",
            created_at=t0 + timedelta(hours=1),
        )
        await _add_history(session_factory, product=prod, version=v_prev, base=Decimal("100.00"))
        await _add_history(session_factory, product=prod, version=v_new, base=Decimal("110.00"))
        # U1 отслеживает prod в избранном
        async with session_factory() as s:
            s.add(Favorite(user_id=u1.id, product_id=prod.id))
            await s.commit()

        result = await notif_task._dispatch(v_new.id)

        assert result["status"] == "ok"
        assert result["counts"]["up"] == 1
        assert result["recipients"] == 1

        async with session_factory() as s:
            notifs = (await s.scalars(select(Notification))).all()
            assert len(notifs) == 2
            assert sorted(n.type for n in notifs) == [
                "PRICE_CHANGED", "PRICE_CHANGED_DIGEST",
            ]
            manager_notif = next(n for n in notifs if n.type == "PRICE_CHANGED")
            assert manager_notif.user_id is None
            assert "telegram" in manager_notif.channel
            digest = next(n for n in notifs if n.type == "PRICE_CHANGED_DIGEST")
            assert digest.user_id == u1.id
            assert digest.channel == ["inapp"]

        # TG-сообщение только менеджеру (один раз); клиентам в TG не шлём.
        assert len(fake_tg.calls) == 1
        assert fake_tg.calls[0][0] == "999"

    async def test_dispatch_skips_when_no_changes(self, session_factory, monkeypatch):
        monkeypatch.setattr(notif_task, "_worker_session", session_factory)
        monkeypatch.setattr(notif_task.settings, "telegram_manager_chat_id", "999")
        fake_tg = _FakeTg()
        monkeypatch.setattr(notif_task, "send_telegram", fake_tg)

        mgr = await create_user(session_factory, email="m9@x.by", role=UserRole.MANAGER)
        brand = await create_brand(session_factory, name="B9")
        prod = await create_product(
            session_factory, sku="A", name="Widget", brand=brand, base_price=100
        )
        t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        v_prev = await _make_version(
            session_factory, manager=mgr, filename="prev.csv", created_at=t0
        )
        v_new = await _make_version(
            session_factory, manager=mgr, filename="new.csv",
            created_at=t0 + timedelta(hours=1),
        )
        # Цена та же → unchanged, изменений нет.
        await _add_history(session_factory, product=prod, version=v_prev, base=Decimal("100.00"))
        await _add_history(session_factory, product=prod, version=v_new, base=Decimal("100.00"))

        result = await notif_task._dispatch(v_new.id)

        assert result["status"] == "ok"
        assert result["counts"]["unchanged"] == 1
        assert result["recipients"] == 0

        async with session_factory() as s:
            notifs = (await s.scalars(select(Notification))).all()
            assert len(notifs) == 0
        assert fake_tg.calls == []
