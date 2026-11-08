import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.celery_app import run_agent_workflow
from app.database import TaskLog, get_db, init_db
from app.schemas import BlogRequest, TaskCreateResponse, TaskStatusResponse

STATIC_DIR = Path(__file__).parent / "static"
(STATIC_DIR / "images").mkdir(parents=True, exist_ok=True)

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="MAS Blog Generator API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _to_status(db_task: TaskLog) -> TaskStatusResponse:
    return TaskStatusResponse(
        task_id=db_task.id,
        topic=db_task.topic,
        status=db_task.status,
        result=db_task.result,
        created_at=db_task.created_at,
    )


@app.post("/generate-blog", response_model=TaskCreateResponse)
def generate_blog(request: BlogRequest, db: Session = Depends(get_db)):
    # The row must exist before the worker can pick up the task.
    task_id = str(uuid.uuid4())
    db.add(TaskLog(id=task_id, topic=request.topic, status="PENDING"))
    db.commit()

    try:
        run_agent_workflow.apply_async(args=[request.topic], task_id=task_id)
    except Exception as e:
        db_task = db.get(TaskLog, task_id)
        db_task.status = "FAILED"
        db_task.result = str(e)
        db.commit()
        raise HTTPException(status_code=503, detail="Task queue unavailable")

    return TaskCreateResponse(
        task_id=task_id,
        status="PENDING",
        message="Agent workflow started in the background.",
    )


@app.get("/tasks", response_model=list[TaskStatusResponse])
def list_tasks(
    since: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = select(TaskLog).order_by(TaskLog.created_at.desc()).limit(limit)
    if since is not None:
        query = query.where(TaskLog.created_at >= since)
    return [_to_status(t) for t in db.scalars(query)]


@app.get("/task/{task_id}", response_model=TaskStatusResponse)
def get_task_status(task_id: str, db: Session = Depends(get_db)):
    db_task = db.get(TaskLog, task_id)
    if not db_task:
        raise HTTPException(status_code=404, detail="Task not found")

    return _to_status(db_task)
