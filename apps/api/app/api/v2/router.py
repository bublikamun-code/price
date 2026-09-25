"""API v2 router namespace."""
from fastapi import APIRouter

from app.api.v2 import cart, catalog, orders, organizations, session

api_router = APIRouter(prefix="/api/v2")
api_router.include_router(session.router)
api_router.include_router(organizations.router)
api_router.include_router(catalog.router)
api_router.include_router(cart.router)
api_router.include_router(orders.router)
