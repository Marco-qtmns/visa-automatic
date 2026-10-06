import os

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import router
from .api.auth import router as auth_router
from .services import (
    DocumentUploadTooLarge,
    DomainNotFound,
    DomainValidationError,
    UnsupportedDocumentFile,
)
from .storage import StorageObjectNotFound
from .health import deployment_readiness


def configured_cors_origins() -> list[str]:
    return [
        origin.strip()
        for origin in os.environ.get(
            "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        ).split(",")
        if origin.strip()
    ]


app = FastAPI(
    title="Visa Automatic",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)
app.include_router(router)
app.include_router(auth_router)


@app.exception_handler(DomainNotFound)
async def not_found_handler(_request: Request, error: DomainNotFound):
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(error)})


@app.exception_handler(DomainValidationError)
async def validation_handler(_request: Request, error: DomainValidationError):
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(error)})


@app.exception_handler(DocumentUploadTooLarge)
async def upload_too_large_handler(_request: Request, error: DocumentUploadTooLarge):
    return JSONResponse(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE, content={"detail": str(error)}
    )


@app.exception_handler(UnsupportedDocumentFile)
async def unsupported_upload_handler(_request: Request, error: UnsupportedDocumentFile):
    return JSONResponse(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        content={"detail": str(error)},
    )


@app.exception_handler(StorageObjectNotFound)
async def storage_not_found_handler(_request: Request, error: StorageObjectNotFound):
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(error)})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/live")
def health_live():
    return {"status": "alive"}


@app.get("/health/ready")
def health_ready():
    ready, payload = deployment_readiness()
    if not ready:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return payload
