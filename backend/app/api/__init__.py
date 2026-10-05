from fastapi import APIRouter

from .core import router as core_router
from .canada import router as canada_router
from .canada_imports import router as canada_imports_router
from .canada_preparation import router as canada_preparation_router

router = APIRouter()
router.include_router(core_router)
router.include_router(canada_router)
router.include_router(canada_imports_router)
router.include_router(canada_preparation_router)

__all__ = ["router"]
