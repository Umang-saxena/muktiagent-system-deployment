# MAS Blog Generator

FastAPI app that writes a short blog post with CrewAI and generates a featured image, both through [EPAM AI DIAL](https://dialx.ai/dial_api), then stores the result in PostgreSQL. The crew runs in a Celery worker so the HTTP request returns immediately.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) running
- A DIAL Core URL and API key, with access to one chat deployment that supports tool calling and one text-to-image deployment (for example DALL-E 3, Imagen, or Gemini Image)

Ports `8000`, `5432`, and `6379` must be free.

## Start

From this folder:

```powershell
Copy-Item .env.example .env
```

Open `.env` and set the DIAL values. Docker Compose reads that file. A PowerShell `export` will not reach the containers.

| Variable | Meaning |
|---|---|
| `DIAL_URL` | DIAL Core base URL, without a trailing slash |
| `DIAL_API_KEY` | DIAL API key, sent as the `Api-Key` header |
| `DIAL_API_VERSION` | API version query parameter, default `2023-12-01-preview` |
| `DIAL_CHAT_DEPLOYMENT` | Chat deployment used by both agents |
| `DIAL_IMAGE_DEPLOYMENT` | Text-to-image deployment used by the image tool |

The deployment names in `.env.example` are only examples. List the deployments your key can use and copy their `id` values:

```powershell
$h = @{ "Api-Key" = "<your-dial-api-key>" }
(Invoke-RestMethod -Headers $h "https://<your-dial-host>/openai/models").data | Select-Object id
```

or with curl:

```sh
curl https://<your-dial-host>/openai/models -H "Api-Key: <your-dial-api-key>"
```

Both agents call `{DIAL_URL}/openai/deployments/{DIAL_CHAT_DEPLOYMENT}/chat/completions` through CrewAI's native OpenAI provider. The image tool calls the image deployment's `chat/completions` endpoint and saves the image attachment from the response under `app/static/images/`.

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

A missing or invalid key, an unreachable `DIAL_URL`, or a wrong deployment name finishes as `FAILED`, with the DIAL error in `result`. Watch the agents with:

```powershell
docker compose logs -f celery_worker
```

## Track runs in a browser

A local page lists every run with its status and opens the article and image. It lives in `../mas-ui`, outside the Docker build.

```powershell
cd ..\mas-ui
npm install
npm run dev
```

Open http://localhost:5173. It shows runs started since the tab opened and refreshes every 3 seconds. "Show all runs" includes older runs and runs started from Postman. "New session" resets the start time.

The page reads `GET /tasks`. Point it at another API with `VITE_API_URL` in `mas-ui/.env.local`, and add that page's origin to the API's `CORS_ORIGINS` environment variable.

## After changes

| Change | Command |
|---|---|
| `.env` (DIAL key, URL, or deployments) | `docker compose up -d --force-recreate api celery_worker` |
| Python code | `docker compose restart api celery_worker` |
| `requirements.txt` or `Dockerfile` | `docker compose up --build -d` |

The key is copied into a container when it is created. Editing `.env` does not update a container that is already running, which is why the recreate command is needed.

The worker does not auto-reload. Restart it after code changes.

## Stop

```powershell
docker compose down
```

`docker compose down -v` also deletes the Postgres volume and every saved task.
