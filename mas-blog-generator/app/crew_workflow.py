import base64
import mimetypes
import os
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from crewai import LLM, Agent, Crew, Process, Task
from crewai.llms.hooks.base import BaseInterceptor
from crewai.tools import tool

DIAL_URL = os.getenv("DIAL_URL", "").rstrip("/")
DIAL_API_KEY = os.getenv("DIAL_API_KEY", "")
DIAL_API_VERSION = os.getenv("DIAL_API_VERSION", "2023-12-01-preview")
CHAT_DEPLOYMENT = os.getenv("DIAL_CHAT_DEPLOYMENT", "")
IMAGE_DEPLOYMENT = os.getenv("DIAL_IMAGE_DEPLOYMENT", "")
IMAGE_TIMEOUT_SECONDS = 300
IMAGE_DIR = Path(__file__).parent / "static" / "images"
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")


def _require_dial_config(**values: str) -> None:
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"Missing DIAL configuration: {', '.join(missing)}")


def _deployment_url(deployment: str) -> str:
    return f"{DIAL_URL}/openai/deployments/{deployment}"


class _DialApiKeyAuth(BaseInterceptor[httpx.Request, httpx.Response]):
    # The OpenAI SDK always sends `Authorization: Bearer <api_key>`, but DIAL
    # reads that header as a JWT. Only the `Api-Key` header may carry the key.
    def on_outbound(self, message: httpx.Request) -> httpx.Request:
        message.headers.pop("Authorization", None)
        message.headers["Api-Key"] = DIAL_API_KEY
        return message

    def on_inbound(self, message: httpx.Response) -> httpx.Response:
        return message

    async def aon_outbound(self, message: httpx.Request) -> httpx.Request:
        return self.on_outbound(message)

    async def aon_inbound(self, message: httpx.Response) -> httpx.Response:
        return message


def _dial_llm() -> LLM:
    _require_dial_config(
        DIAL_URL=DIAL_URL,
        DIAL_API_KEY=DIAL_API_KEY,
        DIAL_CHAT_DEPLOYMENT=CHAT_DEPLOYMENT,
    )
    return LLM(
        model=CHAT_DEPLOYMENT,
        custom_openai=True,
        base_url=_deployment_url(CHAT_DEPLOYMENT),
        api_key=DIAL_API_KEY,
        default_query={"api-version": DIAL_API_VERSION},
        interceptor=_DialApiKeyAuth(),
    )


def _last_image_attachment(completion: dict) -> dict | None:
    choices = completion.get("choices") or [{}]
    message = choices[0].get("message") or {}
    attachments = (message.get("custom_content") or {}).get("attachments") or []
    images = [
        a
        for a in attachments
        if (a.get("type") or "").startswith("image/") and (a.get("data") or a.get("url"))
    ]
    return images[-1] if images else None


def _attachment_bytes(client: httpx.Client, attachment: dict) -> bytes:
    if attachment.get("data"):
        return base64.b64decode(attachment["data"])

    url = attachment["url"]
    parsed = urlparse(url)
    if not parsed.scheme:
        url = urljoin(f"{DIAL_URL}/v1/", url)
    parsed = urlparse(url)
    dial_origin = urlparse(DIAL_URL)
    same_origin = (parsed.scheme, parsed.netloc) == (
        dial_origin.scheme,
        dial_origin.netloc,
    )
    headers = {"Api-Key": DIAL_API_KEY} if same_origin else {}
    response = client.get(url, headers=headers)
    response.raise_for_status()
    return response.content


def _save_image(data: bytes, mime_type: str | None) -> str:
    ext = mimetypes.guess_extension(mime_type or "") or ".png"
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"blog_{uuid.uuid4().hex}{ext}"
    (IMAGE_DIR / filename).write_bytes(data)
    return f"Image URL: {PUBLIC_BASE_URL}/static/images/{filename}"


@tool("Generate Blog Image")
def generate_blog_image(prompt: str) -> str:
    """Generates a featured image for the blog post with the DIAL text-to-image deployment from a visual prompt. Returns the image URL."""
    _require_dial_config(
        DIAL_URL=DIAL_URL,
        DIAL_API_KEY=DIAL_API_KEY,
        DIAL_IMAGE_DEPLOYMENT=IMAGE_DEPLOYMENT,
    )
    with httpx.Client(timeout=IMAGE_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{_deployment_url(IMAGE_DEPLOYMENT)}/chat/completions",
            params={"api-version": DIAL_API_VERSION},
            headers={"Api-Key": DIAL_API_KEY},
            json={"messages": [{"role": "user", "content": prompt}]},
        )
        response.raise_for_status()
        image = _last_image_attachment(response.json())
        if image is None:
            return "Image generation returned no image."
        data = _attachment_bytes(client, image)
    return _save_image(data, image.get("type"))


def run_blog_crew(topic: str) -> str:
    llm = _dial_llm()

    writer = Agent(
        role="Content Writer",
        goal=f"Write engaging blog posts about {topic}.",
        backstory="An expert tech journalist.",
        llm=llm,
        allow_delegation=False,
        verbose=True,
    )

    editor = Agent(
        role="Senior Editor & Visual Director",
        goal="Review posts and create an image prompt for a featured image.",
        backstory="A strict editor with an eye for visual storytelling.",
        tools=[generate_blog_image],
        llm=llm,
        allow_delegation=False,
        verbose=True,
    )

    write_task = Task(
        description=(
            f"Write a short 3-paragraph article on the latest trends in {topic}."
        ),
        expected_output="A 3-paragraph draft article.",
        agent=writer,
    )

    edit_task = Task(
        description=(
            "1. Review and polish the article. 2. Write a vivid visual prompt"
            " and call the Generate Blog Image tool exactly once. 3. Output the"
            " final article followed by the image URL line returned by the tool."
        ),
        expected_output=(
            "The polished 3-paragraph article, followed by a final line"
            " 'Image URL: <url>'."
        ),
        agent=editor,
    )

    crew = Crew(
        agents=[writer, editor],
        tasks=[write_task, edit_task],
        process=Process.sequential,
        verbose=True,
    )

    return str(crew.kickoff())
