import os

from celery import Celery

from app.crew_workflow import run_blog_crew
from app.database import SessionLocal, TaskLog

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("tasks", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)


def _write_status(task_id: str, status: str, result: str | None = None) -> None:
    db = SessionLocal()
    try:
        db_task = db.get(TaskLog, task_id)
        if db_task:
            db_task.status = status
            if result is not None:
                db_task.result = result
            db.commit()
    finally:
        db.close()


@celery_app.task(bind=True)
def run_agent_workflow(self, topic: str) -> str:
    task_id = self.request.id
    # A crew run takes minutes; holding one DB connection across it gets dropped.
    _write_status(task_id, "PROCESSING")
    try:
        final_output = run_blog_crew(topic)
    except Exception as e:
        _write_status(task_id, "FAILED", str(e))
        return str(e)

    _write_status(task_id, "COMPLETED", final_output)
    return final_output
