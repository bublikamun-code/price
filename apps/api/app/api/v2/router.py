"""API v2 router namespace."""
from fastapi import APIRouter

from app.api.v2 import (
    addresses,
    auth,
    cart,
    catalog,
    client_sku_mappings,
    documents,
    invoices,
    media,
    orders,
    organizations,
    session,
    volume_tiers,
)

api_router = APIRouter(prefix="/api/v2")
api_router.include_router(auth.router)
api_router.include_router(session.router)
api_router.include_router(organizations.router)
api_router.include_router(organizations.manager_router)
api_router.include_router(addresses.router)
# Кросс-справочник (§16 п.43): раньше каталога не критично, но держим рядом
# с organization-scope роутерами; apply-csv мутирует корзину v2.
api_router.include_router(client_sku_mappings.router)
api_router.include_router(client_sku_mappings.manager_router)
api_router.include_router(catalog.router)
api_router.include_router(documents.router)
api_router.include_router(cart.router)
# invoices раньше orders: путь /orders/invoices/{invoiceId}/download не должен
# перехватываться шаблоном /orders/{orderId} (маршруты идут по порядку).
api_router.include_router(invoices.router)
api_router.include_router(invoices.manager_router)
api_router.include_router(orders.router)
api_router.include_router(media.router)
api_router.include_router(volume_tiers.router)
