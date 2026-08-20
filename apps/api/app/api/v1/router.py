"""Агрегирующий роутер /api/v1. См. ARCHITECTURE_PLAN.md §6.

Health-эндпоинты (/healthz, /readyz) монтируются на root в main.py (вне /api/v1).
"""
from fastapi import APIRouter

from app.api.v1 import auth, cart, catalog, favorites, files, notifications, orders
from app.api.v1.manager import router as manager_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(catalog.router)
api_router.include_router(cart.router)
api_router.include_router(favorites.router)
api_router.include_router(orders.router)
api_router.include_router(files.router)
api_router.include_router(notifications.router)
api_router.include_router(manager_router)

# --- Mini App (Telegram, post-MVP) ---
# from app.api.miniapp import router as miniapp_router
# api_router.include_router(miniapp_router, prefix="/m", tags=["miniapp"])
