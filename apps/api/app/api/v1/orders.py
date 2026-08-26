"""Роутер заявок клиента. См. ARCHITECTURE_PLAN.md §6, §9, §16 п.25 (фича F).

Создание заявки замораживает цены/курс (§17.2). Клиент видит только свои заявки.
"""
import asyncio
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.limiter import EXPORT_RATE_LIMIT, export_rate_key, limiter
from app.db.session import get_db
from app.models.enums import OrderStatus, UserRole
from app.models.order import Order
from app.models.user import User
from app.repositories import orders as orders_repo
from app.schemas import MetaPage
from app.schemas.cart import CartRead
from app.schemas.catalog import ExportJobOut, ExportStartOut
from app.schemas.order import (
    OrderCreate,
    OrderItemRead,
    OrderListPage,
    OrderRead,
)
from app.services import export as export_service
from app.services import storage
from app.services import email as email_service
from app.services.order import OrderService, StockExceededError

router = APIRouter(prefix="/orders", tags=["orders"])


def _from_value_error(e: ValueError) -> HTTPException:
    msg = str(e)
    code = (
        status.HTTP_404_NOT_FOUND
        if "не найден" in msg
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=msg)


async def _to_read(
    db: AsyncSession,
    order: Order,
    *,
    with_items: bool,
    clients: dict[uuid.UUID, User] | None = None,
) -> OrderRead:
    items = None
    if with_items:
        rows = await orders_repo.get_order_items(db, order_id=order.id)
        items = [OrderItemRead.model_validate(i) for i in rows]
    read = OrderRead.model_validate(order).model_copy(update={"items": items})
    # Имя/компания клиента (map по client_id — один запрос на список).
    user = clients.get(order.client_id) if clients else None
    if user is not None:
        read.client_name = user.full_name
        read.client_company = user.company
    return read


@router.get("", response_model=OrderListPage)
async def list_orders(
    status_filter: OrderStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderListPage:
    rows, total = await OrderService(db).list_for_client(
        user, status_filter, page, per_page
    )
    clients = await orders_repo.fetch_users_by_ids(db, [o.client_id for o in rows])
    data = [await _to_read(db, o, with_items=False, clients=clients) for o in rows]
    return OrderListPage(data=data, meta=MetaPage(page=page, per_page=per_page, total=total))


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderRead:
    service = OrderService(db)
    try:
        order = await service.create(user, payload)
    except StockExceededError as e:
        # 422: фронт показывает деталь ошибки пользователю (остатки при заказе).
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ValueError as e:
        raise _from_value_error(e)
    await db.commit()
    await db.refresh(order)
    # Email-уведомление менеджеру о новой заявке (fire-and-forget: ошибки
    # постановки в очередь не роняют запрос).
    _notify_manager_order_created(order, user, items_count=len(payload.items))
    # user уже загружен — обогащаем ответ без доп. запроса.
    return await _to_read(db, order, with_items=True, clients={user.id: user})


def _notify_manager_order_created(order: Order, client: User, *, items_count: int) -> None:
    """Письмо менеджеру о новой заявке. MANAGER_NOTIFY_EMAIL пуст → не шлём."""
    if not settings.manager_notify_email:
        return
    subject, html_body = email_service.build_order_created_manager_email(
        order_no=email_service.format_order_no(order.seq),
        client_name=client.full_name,
        client_company=client.company,
        total_amount=float(order.total_amount),
        currency_code=order.currency_code,
        delivery_method=order.delivery_method,
        items_count=items_count,
    )
    email_service.queue_email(
        to=settings.manager_notify_email, subject=subject, html_body=html_body
    )


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderRead:
    try:
        order = await OrderService(db).get(user, order_id, as_manager=False)
    except ValueError as e:
        raise _from_value_error(e)
    clients = await orders_repo.fetch_users_by_ids(db, [order.client_id])
    return await _to_read(db, order, with_items=True, clients=clients)


@router.post(
    "/{order_id}/pdf",
    response_model=ExportStartOut,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(EXPORT_RATE_LIMIT, key_func=export_rate_key)
async def start_order_pdf(
    request: Request,
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExportStartOut:
    """Запустить PDF-выгрузку заявки (§16 п.25, фича F).

    Доступ: клиент-владелец или MANAGER. PDF собирает Celery-задача
    (``export_order_pdf``): статус — ``GET /orders/export/{job_id}``.
    Лимит: 10 запусков/час (общий с экспортом каталога).
    """
    try:
        order = await OrderService(db).get(
            user, order_id, as_manager=user.role == UserRole.MANAGER
        )
    except ValueError as e:
        raise _from_value_error(e)
    job_id = await export_service.start_order_pdf(user=user, order=order)
    return ExportStartOut(job_id=job_id)


@router.get("/export/{job_id}", response_model=ExportJobOut)
async def get_order_pdf_job(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
) -> ExportJobOut:
    """Статус job PDF-выгрузки заявки (только создатель, чужой → 404).

    ``url`` — presigned-ссылка на файл в S3 (5 мин), отдаётся только при DONE.
    """
    state = await export_service.get_job(user.id, job_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Экспорт не найден"
        )
    url = None
    if state.get("status") == "DONE" and state.get("s3_key"):
        try:
            url = storage.presigned_get(settings.s3_bucket_exports, state["s3_key"])
        except storage.StorageError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            ) from exc
    return ExportJobOut(
        job_id=state["job_id"],
        status=state["status"],
        format=state["format"],
        error=state.get("error"),
        url=url,
    )


@router.get("/{order_id}/export.xlsx")
@limiter.limit(EXPORT_RATE_LIMIT, key_func=export_rate_key)
async def export_order_xlsx(
    request: Request,
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Выгрузка заявки в XLSX для переноса в 1С (синхронно, без job/Celery).

    Доступ: клиент-владелец или MANAGER/ADMIN (как PDF-старт). Заявка маленькая,
    поэтому отдаём файл напрямую (StreamingResponse), а не через S3-job.
    """
    try:
        order = await OrderService(db).get(
            user, order_id, as_manager=user.role != UserRole.CLIENT
        )
    except ValueError as e:
        raise _from_value_error(e)
    clients = await orders_repo.fetch_users_by_ids(db, [order.client_id])
    client = clients[order.client_id]
    items = await orders_repo.get_order_items(db, order_id=order.id)
    body = await asyncio.to_thread(
        export_service.build_order_xlsx, order=order, client=client, items=items
    )
    return StreamingResponse(
        io.BytesIO(body),
        media_type=export_service._XLSX_MEDIA_TYPE,
        headers=export_service.order_xlsx_headers(seq=order.seq, order_id=order.id),
    )


@router.post("/{order_id}/repeat", response_model=CartRead)
async def repeat_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CartRead:
    try:
        cart = await OrderService(db).repeat(user, order_id)
    except ValueError as e:
        raise _from_value_error(e)
    await db.commit()
    return cart


@router.post("/{order_id}/cancel", response_model=OrderRead)
async def cancel_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderRead:
    service = OrderService(db)
    try:
        order = await service.cancel(user, order_id)
    except ValueError as e:
        msg = str(e)
        code = (
            status.HTTP_404_NOT_FOUND
            if "не найден" in msg
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=code, detail=msg)
    await db.commit()
    await db.refresh(order)
    # user уже загружен — обогащаем ответ без доп. запроса.
    return await _to_read(db, order, with_items=True, clients={user.id: user})
