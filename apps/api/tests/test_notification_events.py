"""Публикация SSE-событий (services/notification_events, §16 п.26).

Слои:
  * ``publish_notification`` — sync-клиент, канал по ``user_id`` (None →
    broadcast); Redis подменяется in-memory фейком (стиль ``_get_redis`` в
    test_telegram_link.py);
  * SSE-генератор ``_notification_events`` — pub/sub-клиент стабается, проверяем
    кадры (``retry``/``event: notification``/heartbeat) и набор каналов;
  * round-trip publish → подписчик на fakeredis с общим FakeServer: публикация
    и подписка в реале ходят через один брокер, как в проде (sync-паблишер,
    async-подписчик).

Формат события зафиксирован потребителем (apps/web useNotifications.ts):
``event: notification`` + JSON ``{id, type, title, body}`` в data.
"""
import asyncio
import json
import uuid

import pytest

import app.services.notification_events as ne
from app.api.v1.notifications import _notification_events
from app.models.enums import UserRole
from app.models.system import Notification
from tests.conftest import create_user


class _FakeRedis:
    """Sync-фейк: запись publish-вызовов, опциональный сбой."""

    def __init__(self, fail: bool = False) -> None:
        self.published: list[tuple[str, str]] = []
        self.fail = fail

    def publish(self, channel: str, data: str) -> int:
        if self.fail:
            raise ConnectionError("redis недоступен")
        self.published.append((channel, data))
        return 1


@pytest.fixture
def fake_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(ne, "_get_redis", lambda: fake)
    return fake


# =========================================================
# publish_notification: каналы и payload
# =========================================================
def test_publish_to_broadcast_channel(fake_redis):
    payload = {"id": "abc", "type": "LEAD_CREATED", "title": "t", "body": "b"}
    ne.publish_notification(payload, user_id=None)
    assert len(fake_redis.published) == 1
    channel, data = fake_redis.published[0]
    assert channel == ne.BROADCAST_CHANNEL
    # Потребитель (useNotifications.ts) делает JSON.parse(data) — формат тот же.
    assert json.loads(data) == payload


def test_publish_to_personal_channel(fake_redis):
    user_id = uuid.uuid4()
    ne.publish_notification({"id": "x"}, user_id=user_id)
    channel, _ = fake_redis.published[0]
    assert channel == ne.user_channel(user_id)
    assert channel.startswith("notifications:user:")


def test_publish_broker_failure_is_fail_open(fake_redis, monkeypatch):
    """Redis упал → исключение не идёт наверх (создание уведомления не ломается)."""
    fake_redis.fail = True
    spy = _LogSpy()
    monkeypatch.setattr(ne, "log", spy)

    ne.publish_notification({"id": "x"}, user_id=None)  # не бросает

    assert fake_redis.published == []
    assert any("notifications.publish_failed" in ev for ev, _ in spy.warnings)


class _LogSpy:
    """Ловит structlog-вызовы (style теста test_notification_dispatch_idempotency)."""

    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict]] = []

    def warning(self, event, **kw):
        self.warnings.append((event, kw))


def test_notification_payload_from_model():
    notif_id = uuid.uuid4()
    notif = Notification(
        id=notif_id,
        type="PRICE_CHANGED_DIGEST",
        title="Изменились цены",
        body="digest",
        user_id=None,
    )
    payload = ne.notification_payload(notif)
    assert payload["type"] == "PRICE_CHANGED_DIGEST"
    assert payload["title"] == "Изменились цены"
    assert payload["body"] == "digest"
    assert payload["id"] == str(notif_id)  # после flush id есть всегда


# =========================================================
# SSE-генератор: кадры и каналы
# =========================================================
class _StubPubsub:
    """Pub/sub-стаб: очередь сообщений вместо живого Redis."""

    def __init__(self, messages) -> None:
        self._messages = list(messages)
        self.subscribed: list[str] = []
        self.closed = False

    async def subscribe(self, *channels):
        self.subscribed.extend(channels)

    async def get_message(self, ignore_subscribe_messages=False, timeout=None):
        return self._messages.pop(0) if self._messages else None

    async def aclose(self):
        self.closed = True


async def test_stream_sends_frames_and_heartbeats(monkeypatch):
    user = uuid.uuid4()
    message = {"type": "message", "data": json.dumps({"id": "n1"}).encode()}
    stub = _StubPubsub([message])

    monkeypatch.setattr(ne, "create_pubsub_client", lambda: type("C", (), {"pubsub": lambda self: stub, "aclose": lambda self: asyncio.sleep(0)})())

    gen = _notification_events(type("U", (), {"id": user, "role": UserRole.CLIENT})())
    # Первый кадр — reconnect-интервал EventSource (до входа в цикл).
    assert await gen.__anext__() == "retry: 5000\n\n"
    # Опубликованное событие → именованный кадр notification (ждёт фронт).
    frame = await gen.__anext__()
    assert frame == "event: notification\ndata: {\"id\": \"n1\"}\n\n"
    # Пустой интервал → heartbeat-комментарий (браузер его пропускает сам).
    assert await gen.__anext__() == ": ping\n\n"
    await gen.aclose()
    assert stub.closed


async def test_stream_subscribes_user_and_broadcast_for_manager(session_factory, monkeypatch):
    manager = await create_user(
        session_factory, email="stream-mgr@example.by", role=UserRole.MANAGER
    )
    stub = _StubPubsub([])
    monkeypatch.setattr(
        ne, "create_pubsub_client", lambda: type("C", (), {"pubsub": lambda self: stub, "aclose": lambda self: asyncio.sleep(0)})()
    )
    gen = _notification_events(manager)
    assert await gen.__anext__() == "retry: 5000\n\n"
    assert stub.subscribed == [ne.user_channel(manager.id), ne.BROADCAST_CHANNEL]
    await gen.aclose()


async def test_stream_client_role_has_no_broadcast_channel(session_factory, monkeypatch):
    client = await create_user(
        session_factory, email="stream-client@example.by", role=UserRole.CLIENT
    )
    stub = _StubPubsub([])
    monkeypatch.setattr(
        ne, "create_pubsub_client", lambda: type("C", (), {"pubsub": lambda self: stub, "aclose": lambda self: asyncio.sleep(0)})()
    )
    gen = _notification_events(client)
    await gen.__anext__()
    assert stub.subscribed == [ne.user_channel(client.id)]
    await gen.aclose()


# =========================================================
# Round-trip: sync-паблишер → async-подписчик (fakeredis, общий сервер)
# =========================================================
async def test_publish_reaches_sse_subscriber(monkeypatch):
    """Создали уведомление → подписчик SSE получил кадр (как в проде).

    Sync-паблишер и async-подписчик делят один fakeredis FakeServer — тот же
    расклад, что в рантайме: publish из FastAPI/Celery, подписка в SSE.
    """
    import fakeredis

    server = fakeredis.FakeServer()
    async_client = fakeredis.aioredis.FakeRedis(server=server)
    sync_client = fakeredis.FakeRedis(server=server)
    monkeypatch.setattr(ne, "create_pubsub_client", lambda: async_client)
    monkeypatch.setattr(ne, "_get_redis", lambda: sync_client)

    user_id = uuid.uuid4()
    pubsub = async_client.pubsub()
    await pubsub.subscribe(ne.user_channel(user_id))
    try:
        ne.publish_notification(
            {"id": "n2", "type": "LEAD_CREATED", "title": "t", "body": "b"},
            user_id=user_id,
        )
        # Подписка асинхронная — даём сообщению доехать (fakeredis in-memory).
        message = None
        for _ in range(50):
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=0.05
            )
            if message is not None:
                break
            await asyncio.sleep(0.02)
        assert message is not None, "событие не дошло до подписчика"
        data = message["data"]
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        assert json.loads(data)["id"] == "n2"
    finally:
        await pubsub.aclose()
