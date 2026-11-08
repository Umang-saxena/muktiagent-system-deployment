import json
import os
import threading
import time
import urllib.request
import uuid

import _fake_crew
import app.celery_app as ca
from app.database import SessionLocal, TaskLog


def new_row(topic):
    task_id = str(uuid.uuid4())
    db = SessionLocal()
    db.add(TaskLog(id=task_id, topic=topic, status="PENDING"))
    db.commit()
    db.close()
    return task_id


def status(task_id):
    return ca._read_status(task_id)


def api_cancel(task_id):
    req = urllib.request.Request(f"http://api:8000/task/{task_id}/cancel", method="POST")
    with urllib.request.urlopen(req) as r:
        return json.load(r)["status"]


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name, flush=True)


def test_cancel_running():
    ca.run_blog_crew = _fake_crew.slow_crew
    task_id = new_row("[test] cancel while running (fake slow crew)")
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", ca.run_agent_workflow.apply(args=["x"], task_id=task_id).get()))
    t.start()
    deadline = time.time() + 30
    while time.time() < deadline and not os.path.exists("/tmp/fake_crew_last_pid"):
        time.sleep(0.2)
    time.sleep(1.5)
    pid = int(open("/tmp/fake_crew_last_pid").read())
    check("status PROCESSING while child runs", status(task_id) == "PROCESSING")
    check("heartbeat present", ca.is_alive(task_id))
    t0 = time.time()
    first = api_cancel(task_id)
    check(f"API cancel returns CANCELLING (got {first})", first == "CANCELLING")
    t.join(30)
    elapsed = time.time() - t0
    check(f"task returned 'Cancelled' in {elapsed:.1f}s (got {out.get('r')!r})", out.get("r") == "Cancelled")
    check("status CANCELLED", status(task_id) == "CANCELLED")
    check("child process gone", not os.path.exists(f"/proc/{pid}") or open(f"/proc/{pid}/status").read().find("zombie") >= 0)
    step = open(f"/tmp/fake_crew_{pid}").read()
    time.sleep(2)
    check("child stopped making progress", open(f"/tmp/fake_crew_{pid}").read() == step)
    check("heartbeat cleared", not ca.is_alive(task_id))
    time.sleep(3)
    check("still CANCELLED later", status(task_id) == "CANCELLED")


def test_complete():
    ca.run_blog_crew = _fake_crew.fast_crew
    task_id = new_row("[test] fake crew completes (200 KB result via pipe)")
    r = ca.run_agent_workflow.apply(args=["pipes"], task_id=task_id).get()
    db = SessionLocal()
    row = db.get(TaskLog, task_id)
    check("COMPLETED with full result", row.status == "COMPLETED" and len(row.result) > 200_000 and r == row.result)
    db.close()


def test_fail():
    ca.run_blog_crew = _fake_crew.failing_crew
    task_id = new_row("[test] fake crew raises")
    ca.run_agent_workflow.apply(args=["x"], task_id=task_id).get()
    db = SessionLocal()
    row = db.get(TaskLog, task_id)
    check(f"FAILED with message ({row.result!r})", row.status == "FAILED" and "boom" in row.result)
    db.close()


def test_conditional_write():
    task_id = new_row("[test] completion cannot overwrite cancel")
    ca._write_status(task_id, "CANCELLING")
    wrote = ca._write_status(task_id, "COMPLETED", "late", not_from=ca.CANCEL_STATES)
    check("COMPLETED blocked while CANCELLING", not wrote and status(task_id) == "CANCELLING")
    ca._write_status(task_id, "CANCELLED", only_from=("CANCELLING",))
    check("then CANCELLED", status(task_id) == "CANCELLED")


if __name__ == "__main__":
    test_cancel_running()
    test_complete()
    test_fail()
    test_conditional_write()
