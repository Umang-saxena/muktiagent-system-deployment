from datetime import datetime

from pydantic import BaseModel, Field


class BlogRequest(BaseModel):
    topic: str = Field(..., min_length=1)


class TaskCreateResponse(BaseModel):
    task_id: str
    status: str
    message: str


class TaskStatusResponse(BaseModel):
    task_id: str
    topic: str
    status: str
    result: str | None = None
    created_at: datetime
