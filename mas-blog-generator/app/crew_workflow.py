import base64
import mimetypes
import os
import uuid
from pathlib import Path

from crewai import LLM, Agent, Crew, Process, Task
from crewai.tools import tool
from google import genai

TEXT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-nano-banana-2.1")
IMAGE_DIR = Path(__file__).parent / "static" / "images"
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")


@tool("Generate Blog Image")
def generate_blog_image(prompt: str) -> str:
    """Generates a featured image for the blog post with Gemini native image generation from a visual prompt. Returns the image URL."""
    client = genai.Client()
    interaction = client.interactions.create(
        model=IMAGE_MODEL, input=prompt, response_modalities=["IMAGE"]
    )

    # google-genai 1.65 (pinned by crewai) has no `output_image` shortcut.
    images = [
        o for o in (interaction.outputs or []) if o.type == "image" and o.data
    ]
    if not images:
        return "Image generation returned no image."
    image = images[-1]

    ext = mimetypes.guess_extension(image.mime_type or "") or ".png"
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"blog_{uuid.uuid4().hex}{ext}"
    (IMAGE_DIR / filename).write_bytes(base64.b64decode(image.data))
    return f"Image URL: {PUBLIC_BASE_URL}/static/images/{filename}"


def run_blog_crew(topic: str) -> str:
    # Gemini 3+ models reject temperature/top_p/top_k, so none are set here.
    llm = LLM(model=f"gemini/{TEXT_MODEL}")

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
