import time

import numpy as np
from fastapi.testclient import TestClient

from app.main import app, store
from app.prompt_video import plan_scene, render_frame


client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_image_mode_requires_image():
    response = client.post(
        "/api/generations",
        data={
            "prompt": "A paper boat sailing through clouds",
            "mode": "image-to-video",
            "aspect_ratio": "16:9",
            "duration": "5",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "An image is required for image-to-video."


def test_text_generation_lifecycle(monkeypatch):
    def fake_video(item, destination):
        destination.write_bytes(b"fake-mp4")

    monkeypatch.setattr("app.main.build_demo_video", fake_video)
    with TestClient(app) as lifecycle_client:
        response = lifecycle_client.post(
            "/api/generations",
            data={
                "prompt": "A silver kite over a green valley",
                "mode": "text-to-video",
                "aspect_ratio": "1:1",
                "duration": "5",
                "seed": "42",
            },
        )
        assert response.status_code == 202
        generation_id = response.json()["id"]

        result = None
        for _ in range(40):
            result = lifecycle_client.get(f"/api/generations/{generation_id}").json()
            if result["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.05)

        assert result["status"] == "succeeded"
        assert result["progress"] == 100
        assert result["seed"] == 42
        assert result["video_url"].endswith(".mp4")

        delete = lifecycle_client.delete(f"/api/generations/{generation_id}")
        assert delete.status_code == 204
        assert generation_id not in store.items


def test_prompt_controls_the_scene():
    night = plan_scene("a luminous paper bird gliding through a midnight sky", "", 7)
    day = plan_scene("a red boat sailing on a sunny ocean", "rain", 7)

    assert night.subject == "bird"
    assert night.time_of_day == "night"
    assert night.setting == "sky"
    assert night.motion == "glide"
    assert day.subject == "boat"
    assert day.setting == "ocean"
    assert day.subject_color == (214, 54, 48)
    assert day.weather == "clear"

    night_frame = render_frame(night, 320, 180, 0.35, 7)
    day_frame = render_frame(day, 320, 180, 0.35, 7)
    assert np.mean(night_frame) < np.mean(day_frame) - 15
