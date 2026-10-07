from fastapi import APIRouter, Depends

from ..auth import require_authenticated_request
from ..authorization import authorize_business_request

from .core import router as core_router
from .canada import router as canada_router
from .canada_imports import router as canada_imports_router
from .canada_preparation import router as canada_preparation_router
from .operational import router as operational_router

router = APIRouter(dependencies=[
    Depends(require_authenticated_request),
    Depends(authorize_business_request),
])
router.include_router(core_router)
router.include_router(canada_router)
router.include_router(canada_imports_router)
router.include_router(canada_preparation_router)
router.include_router(operational_router)

__all__ = ["router"]
