from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ..auth import require_authenticated_request
from ..database import get_session
from ..models.auth import User
from ..schemas.operational import ApplicationBootstrapRead
from ..services.operational import OperationalCaseService


router = APIRouter(tags=["Operational workspace"])


@router.get("/app/bootstrap", response_model=ApplicationBootstrapRead)
def application_bootstrap(
    response: Response,
    user: Annotated[User, Depends(require_authenticated_request)],
    session: Annotated[Session, Depends(get_session)],
):
    started = time.perf_counter()
    summaries, database_ms = OperationalCaseService(session).case_summaries()
    total_ms = (time.perf_counter() - started) * 1000
    response.headers["Server-Timing"] = (
        f'db;dur={database_ms:.2f};desc="case summary query", '
        f'app;dur={total_ms:.2f};desc="bootstrap total"'
    )
    return {
        "user": user,
        "case_summary": summaries,
        "timings_ms": {"database": round(database_ms, 2), "total": round(total_ms, 2)},
    }
