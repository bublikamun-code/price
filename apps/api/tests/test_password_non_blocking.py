"""Пароли не должны блокировать event loop.

Регрессия: `verify_password` — синхронный bcrypt (cost=12, ~0.3 с CPU), и он
вызывался прямо из корутины `AuthService.login`. Пока цикл занят, FastAPI не
обслуживает НИ ОДНОГО другого запроса. Под нагрузкой запросы копятся, каждый
держит свою сессию `get_db`, пул (pool_size=10 + max_overflow=20 = 30)
забивается — и приложение перестаёт отвечать на всё, что ходит в БД, при том
что `/healthz` (пул не трогает) продолжает отвечать 200. Наблюдалось как 30
соединений `idle in transaction` в Postgres при живом healthcheck.

Проверяем поведением, а не чтением кода: пока идёт хэширование, event loop
обязан продолжать исполнять другие корутины.
"""

import asyncio
import time

import pytest

from app.core.security import hash_password_async, verify_password_async

# Сколько раз «маяк» должен успеть моргнуть, пока крутится bcrypt.
# При блокировке цикла маяк замирает и не набирает и двух отметок.
MIN_TICKS = 3
TICK_SECONDS = 0.02


async def test_bcrypt_не_блокирует_event_loop() -> None:
    """Хэширование в threadpool: цикл живёт, пока считается пароль."""
    # Один раз прогреваем хэш заранее, иначе замер включает и его создание.
    hashed = await hash_password_async("контрольный-пароль")

    ticks = 0
    stop = asyncio.Event()

    async def beacon() -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(TICK_SECONDS)

    marker = asyncio.create_task(beacon())
    await asyncio.sleep(TICK_SECONDS * 2)  # маяк гарантированно пошёл

    await verify_password_async("контрольный-пароль", hashed)

    stop.set()
    await marker
    assert ticks >= MIN_TICKS, (
        f"event loop заблокирован на всё время хэширования: маяк успел "
        f"моргнуть всего {ticks} раз(и). Вернулся синхронный verify_password "
        f"в корутину — это причина утечки соединений с БД."
    )


async def test_генерация_пароля_тоже_не_блокирует() -> None:
    """Та же гарантия для hash_password — он вызывается при смене пароля."""
    ticks = 0
    stop = asyncio.Event()

    async def beacon() -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(TICK_SECONDS)

    marker = asyncio.create_task(beacon())
    await asyncio.sleep(TICK_SECONDS * 2)

    await hash_password_async("совсем-другой-пароль")

    stop.set()
    await marker
    assert ticks >= MIN_TICKS, f"генерация хэша заблокировала цикл: {ticks} отметок"


async def test_async_хэширование_даёт_тот_же_результат() -> None:
    """Обёртка не должна менять поведение: пароль верный — True, неверный — False."""
    hashed = await hash_password_async("правильный-пароль")
    assert await verify_password_async("правильный-пароль", hashed) is True
    assert await verify_password_async("неправильный-пароль", hashed) is False
    # Битый хэш не должен ронять запрос — как и у синхронной версии.
    assert await verify_password_async("любой", "не-хэш") is False


@pytest.mark.parametrize("пароли", [("пароль-1", "пароль-2")])
async def test_параллельные_проверки_не_копятся(пароли: tuple[str, str]) -> None:
    """N проверок подряд не должны накапливать блокировку цикла.

    Именно этот сценарий ронял пул: пачка запросов на логин подряд.
    """
    plain, hashed = пароли
    await hash_password_async(plain)

    started = time.monotonic()
    results = await asyncio.gather(
        *(verify_password_async("подбор-пароля", hashed) for _ in range(20))
    )
    elapsed = time.monotonic() - started

    assert all(r is False for r in results)
    # 20 bcrypt-проверок последовательно заняли бы ~6 с. В threadpool укладываются
    # заметно быстрее; порог задан с запасом, чтобы тест не мигал на медленных CI.
    assert elapsed < 5.0, f"20 проверок заняли {elapsed:.2f} с — цикл, похоже, снова блокируется"