from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TaskStatus = Literal[
    "PENDING", "PROCESSING", "COMPLETED", "FAILED", "CANCELLING", "CANCELLED"
]


class BlogRequest(BaseModel):
    topic: str = Field(..., min_length=1)


class TaskCreateResponse(BaseModel):
    task_id: str
    status: TaskStatus
    message: str


class TaskStatusResponse(BaseModel):
    task_id: str
    topic: str
    status: TaskStatus
    result: str | None = None
    created_at: datetime
