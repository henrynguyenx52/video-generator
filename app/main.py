from __future__ import annotations

import asyncio
import json
import os
import random
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

from app.prompt_video import build_prompt_video

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
OUTPUT_DIR = ROOT / "outputs"
UPLOAD_DIR = ROOT / "uploads"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "generations.json"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

for directory in (OUTPUT_DIR, UPLOAD_DIR, DATA_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Generation(BaseModel):
    id: str
    prompt: str = Field(min_length=3, max_length=1500)
    negative_prompt: str = Field(default="", max_length=500)
    mode: Literal["text-to-video", "image-to-video"]
    aspect_ratio: Literal["16:9", "9:16", "1:1"]
    duration: Literal[5, 10]
    seed: int
    status: Literal["queued", "generating", "succeeded", "failed"] = "queued"
    progress: int = 0
    eta_seconds: Optional[int] = None
    image_path: Optional[str] = None
    video_url: Optional[str] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str


class GenerationStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()
        self.items: dict[str, Generation] = {}
        if path.exists():
            try:
                records = json.loads(path.read_text())
                self.items = {item["id"]: Generation.model_validate(item) for item in records}
                for item in self.items.values():
                    if item.status in {"queued", "generating"}:
                        item.status = "failed"
                        item.error = "The server restarted before this generation finished."
            except (json.JSONDecodeError, OSError, ValueError):
                self.items = {}

    async def save(self) -> None:
        async with self._lock:
            payload = [item.model_dump() for item in self.items.values()]
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(payload, indent=2))
            temp.replace(self.path)

    async def put(self, item: Generation) -> None:
        item.updated_at = now_iso()
        self.items[item.id] = item
        await self.save()

    def get(self, generation_id: str) -> Generation:
        item = self.items.get(generation_id)
        if not item:
            raise HTTPException(status_code=404, detail="Generation not found")
        return item

    def list(self) -> list[Generation]:
        return sorted(self.items.values(), key=lambda item: item.created_at, reverse=True)


def build_demo_video(item: Generation, destination: Path) -> None:
    """Render a scene whose subject, setting, color, weather, and motion follow the prompt."""
    build_prompt_video(item, destination)


def build_replicate_video(item: Generation, destination: Path) -> None:
    try:
        import replicate
    except ImportError as exc:
        raise RuntimeError("Install the 'replicate' package to use this provider.") from exc

    model = os.getenv("REPLICATE_MODEL")
    if not model:
        raise RuntimeError("REPLICATE_MODEL is required when VIDEO_PROVIDER=replicate.")

    inputs: dict[str, object] = {
        "prompt": item.prompt,
        "duration": item.duration,
        "aspect_ratio": item.aspect_ratio,
        "seed": item.seed,
    }
    if item.negative_prompt:
        inputs["negative_prompt"] = item.negative_prompt
    image_file = open(item.image_path, "rb") if item.image_path else None
    if image_file:
        inputs["image"] = image_file
    try:
        result = replicate.run(model, input=inputs)
    finally:
        if image_file:
            image_file.close()

    value = result[0] if isinstance(result, list) else result
    source_url = str(getattr(value, "url", value))
    if not source_url.startswith(("http://", "https://")):
        raise RuntimeError("The provider did not return a downloadable video URL.")
    urllib.request.urlretrieve(source_url, destination)


store = GenerationStore(DB_PATH)
app = FastAPI(title="Motion Lab", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")


async def run_generation(generation_id: str) -> None:
    item = store.get(generation_id)
    try:
        item.status = "generating"
        item.progress = 8
        item.eta_seconds = max(8, item.duration * 2)
        await store.put(item)

        destination = OUTPUT_DIR / f"{item.id}.mp4"
        provider = os.getenv("VIDEO_PROVIDER", "demo").lower()
        task = build_replicate_video if provider == "replicate" else build_demo_video

        worker = asyncio.create_task(asyncio.to_thread(task, item, destination))
        while not worker.done():
            await asyncio.sleep(1)
            item.progress = min(92, item.progress + random.randint(4, 11))
            item.eta_seconds = max(1, int((100 - item.progress) / 8))
            await store.put(item)
        await worker

        item.status = "succeeded"
        item.progress = 100
        item.eta_seconds = 0
        item.video_url = f"/outputs/{destination.name}"
        await store.put(item)
    except Exception as exc:
        item.status = "failed"
        item.error = str(exc)
        item.eta_seconds = None
        await store.put(item)


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/generations", response_model=list[Generation])
async def list_generations() -> list[Generation]:
    return store.list()


@app.get("/api/generations/{generation_id}", response_model=Generation)
async def get_generation(generation_id: str) -> Generation:
    return store.get(generation_id)


@app.post("/api/generations", response_model=Generation, status_code=202)
async def create_generation(
    prompt: str = Form(..., min_length=3, max_length=1500),
    negative_prompt: str = Form("", max_length=500),
    mode: Literal["text-to-video", "image-to-video"] = Form("text-to-video"),
    aspect_ratio: Literal["16:9", "9:16", "1:1"] = Form("16:9"),
    duration: int = Form(5),
    seed: Optional[int] = Form(None),
    image: Optional[UploadFile] = File(None),
) -> Generation:
    image_path: Optional[str] = None
    if duration not in {5, 10}:
        raise HTTPException(status_code=422, detail="Duration must be 5 or 10 seconds.")
    if mode == "image-to-video" and not image:
        raise HTTPException(status_code=422, detail="An image is required for image-to-video.")
    if image:
        if not (image.content_type or "").startswith("image/"):
            raise HTTPException(status_code=415, detail="Only image uploads are accepted.")
        content = await image.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Images must be 10 MB or smaller.")
        suffix = Path(image.filename or "upload.jpg").suffix.lower()
        suffix = suffix if suffix in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"
        upload_path = UPLOAD_DIR / f"{uuid4().hex}{suffix}"
        upload_path.write_bytes(content)
        try:
            Image.open(upload_path).verify()
        except Exception:
            upload_path.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail="The uploaded image is invalid.")
        image_path = str(upload_path)

    timestamp = now_iso()
    item = Generation(
        id=uuid4().hex,
        prompt=prompt.strip(),
        negative_prompt=negative_prompt.strip(),
        mode=mode,
        aspect_ratio=aspect_ratio,
        duration=duration,
        seed=seed if seed is not None else random.randint(1, 2_147_483_647),
        image_path=image_path,
        created_at=timestamp,
        updated_at=timestamp,
        eta_seconds=max(8, duration * 2),
    )
    await store.put(item)
    asyncio.create_task(run_generation(item.id))
    return item


@app.delete("/api/generations/{generation_id}", status_code=204)
async def delete_generation(generation_id: str) -> None:
    item = store.get(generation_id)
    if item.status in {"queued", "generating"}:
        raise HTTPException(status_code=409, detail="A running generation cannot be deleted.")
    if item.video_url:
        (ROOT / item.video_url.lstrip("/")).unlink(missing_ok=True)
    if item.image_path:
        Path(item.image_path).unlink(missing_ok=True)
    store.items.pop(generation_id)
    await store.save()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "provider": os.getenv("VIDEO_PROVIDER", "prompt")}
