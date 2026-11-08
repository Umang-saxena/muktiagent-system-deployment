import multiprocessing
import os
import sys
from multiprocessing.connection import Connection
from pathlib import Path

import redis
from celery import Celery
from sqlalchemy import update

from app.crew_workflow import run_blog_crew
from app.database import SessionLocal, TaskLog

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CANCEL_POLL_SECONDS = 2
HEARTBEAT_TTL_SECONDS = 15
CANCEL_STATES = ("CANCELLING", "CANCELLED")

celery_app = Celery("tasks", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)

redis_client = redis.Redis.from_url(REDIS_URL)
# "spawn" gives the crew a fresh interpreter: no inherited DB pool, Redis
# sockets, or locks held by worker threads at fork time.
_mp = multiprocessing.get_context("spawn")
# Spawned children inherit sys.path, but celery adds the project dir only while
# loading the app and removes one copy afterwards; insert unconditionally so a
# second copy survives for the child to unpickle `app.*` targets.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, _PROJECT_ROOT)


class Cancelled(Exception):
    pass


def heartbeat_key(task_id: str) -> str:
    return f"mas:task-alive:{task_id}"


def is_alive(task_id: str) -> bool:
    return bool(redis_client.exists(heartbeat_key(task_id)))


def _beat(task_id: str) -> None:
    redis_client.set(heartbeat_key(task_id), 1, ex=HEARTBEAT_TTL_SECONDS)


def _read_status(task_id: str) -> str | None:
    db = SessionLocal()
    try:
        db_task = db.get(TaskLog, task_id)
        return db_task.status if db_task else None
    finally:
        db.close()


def _write_status(
    task_id: str,
    status: str,
    result: str | None = None,
    only_from: tuple[str, ...] | None = None,
    not_from: tuple[str, ...] | None = None,
) -> bool:
    # Conditional UPDATE so a finishing run cannot overwrite a concurrent cancel.
    values: dict = {"status": status}
    if result is not None:
        values["result"] = result
    stmt = update(TaskLog).where(TaskLog.id == task_id).values(**values)
    if only_from:
        stmt = stmt.where(TaskLog.status.in_(only_from))
    if not_from:
        stmt = stmt.where(TaskLog.status.not_in(not_from))
    db = SessionLocal()
    try:
        updated = db.execute(stmt).rowcount
        db.commit()
        return updated > 0
    finally:
        db.close()


def _crew_child(crew_fn, topic: str, conn: Connection) -> None:
    try:
        conn.send(("ok", crew_fn(topic)))
    except BaseException as e:
        conn.send(("error", str(e) or e.__class__.__name__))
    finally:
        conn.close()


def _run_cancellable(task_id: str, topic: str) -> str:
    """Run the crew in a child process, killing it if the run gets cancelled."""
    parent_conn, child_conn = _mp.Pipe(duplex=False)
    proc = _mp.Process(
        target=_crew_child, args=(run_blog_crew, topic, child_conn), daemon=True
    )
    proc.start()
    child_conn.close()
    try:
        while True:
            _beat(task_id)
            # Receive before join: a large result would block the child on a full pipe.
            if parent_conn.poll(CANCEL_POLL_SECONDS):
                try:
                    kind, payload = parent_conn.recv()
                except EOFError:
                    raise RuntimeError(f"Crew process exited with code {proc.exitcode}")
                if kind == "error":
                    raise RuntimeError(payload)
                return payload
            if _read_status(task_id) in CANCEL_STATES:
                raise Cancelled()
            if not proc.is_alive() and not parent_conn.poll():
                raise RuntimeError(f"Crew process exited with code {proc.exitcode}")
    finally:
        if proc.is_alive():
            proc.terminate()
            proc.join(5)
            if proc.is_alive():
                proc.kill()
        proc.join()
        parent_conn.close()


@celery_app.task(bind=True)
def run_agent_workflow(self, topic: str) -> str:
    task_id = self.request.id
    _beat(task_id)
    try:
        # A queued run may be cancelled before a worker picks it up, and
        # revoke() is in-memory only, so the DB is the source of truth.
        if not _write_status(task_id, "PROCESSING", not_from=CANCEL_STATES):
            if _read_status(task_id) in CANCEL_STATES:
                _write_status(task_id, "CANCELLED", only_from=("CANCELLING",))
                return "Cancelled"
        try:
            final_output = _run_cancellable(task_id, topic)
        except Cancelled:
            _write_status(task_id, "CANCELLED", only_from=("CANCELLING",))
            return "Cancelled"
        except Exception as e:
            if not _write_status(task_id, "FAILED", str(e), not_from=CANCEL_STATES):
                _write_status(task_id, "CANCELLED", only_from=("CANCELLING",))
            return str(e)

        if not _write_status(task_id, "COMPLETED", final_output, not_from=CANCEL_STATES):
            _write_status(task_id, "CANCELLED", only_from=("CANCELLING",))
            return "Cancelled"
        return final_output
    finally:
        redis_client.delete(heartbeat_key(task_id))
