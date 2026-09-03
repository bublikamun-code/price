"""Admin API — заглушка (501 Not Implemented)."""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/")
async def admin_index():
    """Admin endpoints not implemented."""
    raise HTTPException(status_code=501, detail="Admin API not implemented")
