"""Public API — заглушка (501 Not Implemented)."""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/")
async def public_index():
    """Public endpoints not implemented."""
    raise HTTPException(status_code=501, detail="Public API not implemented")
