import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.celery_app import run_agent_workflow
from app.database import TaskLog, get_db, init_db
from app.schemas import BlogRequest, TaskCreateResponse, TaskStatusResponse

STATIC_DIR = Path(__file__).parent / "static"
(STATIC_DIR / "images").mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="MAS Blog Generator API", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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


@app.get("/task/{task_id}", response_model=TaskStatusResponse)
def get_task_status(task_id: str, db: Session = Depends(get_db)):
    db_task = db.get(TaskLog, task_id)
    if not db_task:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskStatusResponse(
        task_id=db_task.id,
        topic=db_task.topic,
        status=db_task.status,
        result=db_task.result,
    )
