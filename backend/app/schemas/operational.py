from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from ..models import WorkflowState
from .auth import UserRead


WorkQueue = Literal["ACTION_REQUIRED", "WAITING", "REVIEW", "READY"]


class CaseSummaryRead(BaseModel):
    id: uuid.UUID
    case_number: str
    display_name: str
    visa_type: str
    purpose: str
    workflow_state: WorkflowState
    issue_count: int
    next_action: str
    queue: WorkQueue
    updated_at: datetime


class ApplicationBootstrapRead(BaseModel):
    user: UserRead
    case_summary: list[CaseSummaryRead]
    timings_ms: dict[str, float]
