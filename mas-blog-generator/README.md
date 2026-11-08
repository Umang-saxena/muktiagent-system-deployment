# MAS Blog Generator

FastAPI app that writes a short blog post with CrewAI and a Gemini image, then stores the result in PostgreSQL. The crew runs in a Celery worker so the HTTP request returns immediately.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) running
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey)

Ports `8000`, `5432`, and `6379` must be free.

## Start

From this folder:

```powershell
Copy-Item .env.example .env
```

Open `.env` and set `GEMINI_API_KEY`. Docker Compose reads that file. A PowerShell `export` will not reach the containers.

```powershell
docker compose up --build -d
```

The first build installs CrewAI and can take several minutes. Later starts reuse the image.

Check that Postgres and Redis are healthy and the API and worker are up:

```powershell
docker compose ps
```

API docs: http://localhost:8000/docs

## Generate a post

```powershell
$r = Invoke-RestMethod -Method Post -Uri http://localhost:8000/generate-blog -ContentType "application/json" -Body '{"topic": "Quantum AI Agents"}'
do {
  Start-Sleep 5
  $s = Invoke-RestMethod "http://localhost:8000/task/$($r.task_id)"
  $s.status
} while ($s.status -in "PENDING", "PROCESSING")
$s.result
```

`COMPLETED` means the result holds the article and a line like `Image URL: http://localhost:8000/static/images/blog_....png`. Open that URL in a browser.

A missing or invalid key finishes as `FAILED`, with Google's error in `result`. Watch the agents with:

```powershell
docker compose logs -f celery_worker
```

## After changes

| Change | Command |
|---|---|
| `.env` (API key or model) | `docker compose up -d --force-recreate api celery_worker` |
| Python code | `docker compose restart api celery_worker` |
| `requirements.txt` or `Dockerfile` | `docker compose up --build -d` |

The key is copied into a container when it is created. Editing `.env` does not update a container that is already running, which is why the recreate command is needed.

The worker does not auto-reload. Restart it after code changes.

## Stop

```powershell
docker compose down
```

`docker compose down -v` also deletes the Postgres volume and every saved task.
