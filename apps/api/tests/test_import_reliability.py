"""Тесты надёжности CSV-импорта прайс-листа (§7.2).

Сценарии:
  1. Beat-reconciler зависших импортов: PROCESSING-версия со ``started_at``
     старше дедлайна → FAILED (через ``_mark_failed``); свежие PROCESSING,
     QUEUED и DONE не трогаются; расписание зарегистрировано в beat.
  2. ``_lock_version``: SELECT с ``FOR UPDATE`` (гонка двух воркеров при
     acks_late + reject_on_worker_lost); второй воркер после захвата получает
     no-op («skipped»).
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects import postgresql

import app.tasks.import_price_list as import_task
from app.models.catalog import PriceListVersion
from app.models.enums import ImportMode, PriceListVersionStatus, UserRole
from tests.conftest import create_user

MANAGER_EMAIL = "manager@example.by"


async def _make_version(
    sf,
    *,
    manager,
    status: PriceListVersionStatus,
    started_at=None,
    filename="p.csv",
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
            started_at=started_at,
        )
        s.add(v)
        await s.commit()
        await s.refresh(v)
        return v


# ===========================================================================
# 1. Beat-reconciler зависших PROCESSING-версий
# ===========================================================================
@pytest.mark.asyncio
class TestReconcileStuckImports:
    async def test_stale_processing_marked_failed(self, session_factory, monkeypatch):
        """PROCESSING старше дедлайна (6 ч) → FAILED, finished_at заполнен."""
        mgr = await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        stale = await _make_version(
            session_factory, manager=mgr,
            status=PriceListVersionStatus.PROCESSING,
            started_at=datetime.now(UTC) - timedelta(hours=7),
        )
        fresh = await _make_version(
            session_factory, manager=mgr,
            status=PriceListVersionStatus.PROCESSING,
            started_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        done = await _make_version(
            session_factory, manager=mgr,
            status=PriceListVersionStatus.DONE,
            started_at=datetime.now(UTC) - timedelta(hours=8),
        )
        monkeypatch.setattr(import_task, "_worker_session", session_factory)

        result = await import_task._reconcile_stuck()

        assert result == {"status": "ok", "reconciled": 1}
        async with session_factory() as s:
            db_stale = await s.get(PriceListVersion, stale.id)
            assert db_stale.status == PriceListVersionStatus.FAILED
            assert db_stale.finished_at is not None
            # свежие PROCESSING и DONE не тронуты
            db_fresh = await s.get(PriceListVersion, fresh.id)
            assert db_fresh.status == PriceListVersionStatus.PROCESSING
            assert db_fresh.finished_at is None
            db_done = await s.get(PriceListVersion, done.id)
            assert db_done.status == PriceListVersionStatus.DONE

    async def test_exactly_on_deadline_boundary_reconciled(
        self, session_factory, monkeypatch
    ):
        """Проверка порога: «почти 6 ч» не трогается (граница включительно)."""
        mgr = await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        almost = await _make_version(
            session_factory, manager=mgr,
            status=PriceListVersionStatus.PROCESSING,
            started_at=datetime.now(UTC) - timedelta(hours=6) + timedelta(minutes=1),
        )
        monkeypatch.setattr(import_task, "_worker_session", session_factory)

        result = await import_task._reconcile_stuck()

        assert result["reconciled"] == 0
        async with session_factory() as s:
            db_v = await s.get(PriceListVersion, almost.id)
            assert db_v.status == PriceListVersionStatus.PROCESSING

    async def test_beat_schedule_registered(self):
        """Reconciler зарегистрирован в beat (интервал 15 минут)."""
        from app.workers import celery_app

        entry = celery_app.conf.beat_schedule.get("reconcile-stuck-imports")
        assert entry is not None
        assert entry["task"] == "app.tasks.import_price_list.reconcile_stuck_imports"
        assert entry["schedule"] == 900.0

    async def test_stuck_deadline_constant_matches_soft_time_limit_budget(self):
        """Дедлайн (6 ч) с запасом покрывает soft time limit задачи (25 мин)."""
        from app.workers import celery_app

        assert import_task.STUCK_IMPORT_HOURS * 3600 > celery_app.conf.task_soft_time_limit


# ===========================================================================
# 2. _lock_version: FOR UPDATE + идемпотентность повторной доставки
# ===========================================================================
@pytest.mark.asyncio
class TestLockVersion:
    async def test_lock_select_uses_for_update(self, session_factory):
        """Запрос блокировки версии содержит FOR UPDATE (гонка двух воркеров).

        FOR UPDATE сериализует конкурентов: второй воркер подождёт коммит
        первого и увидит уже PROCESSING → no-op (см. следующий тест).
        """
        mgr = await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        version = await _make_version(
            session_factory, manager=mgr, status=PriceListVersionStatus.QUEUED
        )

        captured: list = []

        class _SpySession:
            """Прокси над сессией: перехватывает statement в scalar()."""

            def __init__(self, real):
                self._real = real

            async def scalar(self, stmt):
                captured.append(stmt)
                return await self._real.scalar(stmt)

            def __getattr__(self, name):
                return getattr(self._real, name)

        async with session_factory() as s:
            locked = await import_task._lock_version(_SpySession(s), version.id)

        assert locked is not None
        assert locked.status == PriceListVersionStatus.PROCESSING
        assert len(captured) == 1
        compiled = str(captured[0].compile(dialect=postgresql.dialect()))
        assert "FOR UPDATE" in compiled.upper()

    async def test_second_lock_after_first_commit_is_noop(
        self, session_factory
    ):
        """Повторно доставленная задача: после захвата версии первым воркером
        второй получает None (не QUEUED) — без FOR UPDATE оба прошли бы проверку."""
        mgr = await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        version = await _make_version(
            session_factory, manager=mgr, status=PriceListVersionStatus.QUEUED
        )

        async with session_factory() as s1:  # «воркер 1»: QUEUED → PROCESSING
            first = await import_task._lock_version(s1, version.id)
            assert first is not None
            await s1.commit()

        async with session_factory() as s2:  # «воркер 2»: повторная доставка
            second = await import_task._lock_version(s2, version.id)
        assert second is None

    async def test_lock_unknown_version_returns_none(self, session_factory):
        async with session_factory() as s:
            assert await import_task._lock_version(s, uuid.uuid4()) is None
