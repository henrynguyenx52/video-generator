from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance

Color = Tuple[int, int, int]

SKIES = {
    "night": ((5, 8, 24), (22, 28, 58)),
    "sunrise": ((255, 126, 74), (92, 146, 214)),
    "sunset": ((255, 98, 72), (46, 22, 82)),
    "day": ((88, 166, 230), (214, 232, 248)),
    "storm": ((42, 48, 62), (18, 22, 32)),
}
GROUNDS = {
    "ocean": (14, 74, 132),
    "forest": (16, 68, 34),
    "city": (16, 18, 26),
    "desert": (214, 176, 98),
    "mountain": (48, 86, 54),
}
COLORS = {
    "red": (214, 54, 48),
    "blue": (48, 112, 214),
    "green": (42, 158, 78),
    "silver": (196, 204, 214),
    "gold": (232, 184, 64),
    "yellow": (242, 204, 64),
    "orange": (236, 122, 42),
    "pink": (236, 112, 164),
    "purple": (142, 82, 204),
    "white": (244, 244, 246),
    "black": (24, 26, 32),
    "luminous": (255, 236, 168),
    "paper": (246, 236, 214),
}
TIMES = (
    ("night", ("night", "midnight", "dark")),
    ("sunrise", ("sunrise", "dawn")),
    ("sunset", ("sunset", "dusk")),
    ("day", ("day", "sunny", "noon")),
)
SETTINGS = (
    ("space", ("space", "galaxy", "planet")),
    ("ocean", ("ocean", "sea", "water", "lake")),
    ("forest", ("forest", "woods", "trees")),
    ("city", ("city", "street", "skyline")),
    ("desert", ("desert", "dune", "sand")),
    ("mountain", ("mountain", "valley", "hill")),
    ("sky", ("sky", "air")),
)
SUBJECTS = (
    ("bird", ("bird", "birds")),
    ("kite", ("kite", "kites")),
    ("boat", ("boat", "ship", "sailboat")),
    ("moon", ("moon",)),
    ("sun", ("sun",)),
    ("car", ("car", "vehicle")),
    ("fish", ("fish",)),
    ("cat", ("cat", "kitten")),
    ("dog", ("dog", "puppy")),
    ("person", ("person", "man", "woman", "child")),
    ("flower", ("flower", "rose")),
)
WEATHERS = (
    ("storm", ("storm", "lightning")),
    ("rain", ("rain", "rainy")),
    ("snow", ("snow", "snowy")),
    ("mist", ("mist", "fog", "foggy")),
    ("clouds", ("cloud", "clouds")),
)
MOTIONS = (
    ("sail", ("sail", "sailing")),
    ("glide", ("glide", "gliding", "fly", "flying", "float", "floating")),
    ("rise", ("rise", "rising", "ascend")),
    ("zoom", ("zoom", "dolly")),
    ("drift", ("drift", "drifting", "pan")),
)


@dataclass(frozen=True)
class ScenePlan:
    time_of_day: str
    setting: str
    subject: str
    weather: str
    motion: str
    sky_top: Color
    sky_bottom: Color
    ground: Optional[Color]
    horizon: float
    subject_color: Color
    stars: bool


def _words(text: str) -> Sequence[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _first(tokens: Sequence[str], groups: Sequence[tuple]) -> Optional[str]:
    choices = {word: name for name, words in groups for word in words}
    for token in tokens:
        if token in choices:
            return choices[token]
    return None


def plan_scene(prompt: str, negative_prompt: str = "", seed: int = 1) -> ScenePlan:
    """Turn prompt words into the visible scene. The same seed keeps it stable."""
    tokens = _words(prompt)
    blocked = set(_words(negative_prompt))
    time_of_day = _first(tokens, TIMES) or "day"
    setting = _first(tokens, SETTINGS) or "sky"
    subject = _first(tokens, SUBJECTS) or "orb"
    weather = _first(tokens, WEATHERS) or "clear"
    motion = _first(tokens, MOTIONS)
    if subject in blocked or any(word in blocked for word in dict(SUBJECTS).get(subject, ())):
        subject = "orb" if "orb" not in blocked else "none"
    if weather in blocked:
        weather = "clear"
    if not motion:
        motion = "sail" if subject == "boat" else "glide"

    sky_name = "storm" if weather == "storm" else time_of_day
    sky_top, sky_bottom = SKIES[sky_name]
    ground = None if setting in {"sky", "space"} else GROUNDS[setting]
    color = next((COLORS[token] for token in tokens if token in COLORS), None)
    if color is None:
        color = {
            "bird": (246, 236, 214),
            "boat": (232, 214, 184),
            "kite": (236, 72, 86),
            "sun": (255, 196, 64),
            "moon": (236, 236, 226),
            "fish": (242, 132, 64),
            "flower": (226, 72, 112),
        }.get(subject, (244, 244, 248))
    return ScenePlan(
        time_of_day=time_of_day,
        setting=setting,
        subject=subject,
        weather=weather,
        motion=motion,
        sky_top=sky_top,
        sky_bottom=sky_bottom,
        ground=ground,
        horizon=0.64 if ground else 1.0,
        subject_color=color,
        stars=(time_of_day == "night" or setting == "space") and "stars" not in blocked,
    )


def dimensions(aspect_ratio: str) -> tuple:
    return {"16:9": (768, 432), "9:16": (432, 768), "1:1": (576, 576)}[aspect_ratio]


def render_frame(plan: ScenePlan, width: int, height: int, phase: float, seed: int) -> np.ndarray:
    vertical = np.linspace(0, 1, height)[:, None, None]
    gradient = np.array(plan.sky_top) * (1 - vertical) + np.array(plan.sky_bottom) * vertical
    pixels = np.broadcast_to(gradient, (height, width, 3)).copy()
    if plan.ground:
        xx = np.arange(width)
        yy = np.arange(height)[:, None]
        wave = np.sin(xx / 38 + phase * math.pi * 2) * (10 if plan.setting == "ocean" else 6)
        pixels[yy > int(height * plan.horizon) + wave] = plan.ground
    image = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8))
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    rng = random.Random(seed)
    if plan.stars:
        _draw_stars(draw, width, height, phase, rng)
    _draw_setting(draw, plan, width, height, rng)
    if plan.subject != "none":
        x, y, scale = _subject_transform(plan, width, height, phase)
        _draw_subject(draw, plan.subject, x, y, scale, plan.subject_color, phase)
    _draw_weather(draw, plan, width, height, phase, seed)
    return np.asarray(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))


def build_prompt_video(item, destination: Path) -> None:
    plan = plan_scene(item.prompt, item.negative_prompt, item.seed)
    width, height = dimensions(item.aspect_ratio)
    frame_count = item.duration * 12
    source = None
    if item.image_path:
        source = Image.open(item.image_path).convert("RGB")
    writer = imageio.get_writer(destination, fps=12, codec="libx264", quality=7)
    try:
        for index in range(frame_count):
            phase = index / max(frame_count - 1, 1)
            if source is None:
                frame = render_frame(plan, width, height, phase, item.seed)
            else:
                frame = _image_frame(source, plan, width, height, phase, item.seed)
            writer.append_data(frame)
    finally:
        writer.close()


def _subject_transform(plan: ScenePlan, width: int, height: int, phase: float) -> tuple:
    scale = 0.75 + (0.85 * phase if plan.motion == "zoom" else 0.2)
    if plan.motion == "rise":
        return width * 0.5, height * (0.72 - 0.46 * phase), scale
    travel = 0.1 + 0.8 * phase
    if plan.motion == "drift":
        travel = 0.35 + 0.3 * phase
    y_base = height * (0.4 if plan.ground is None else plan.horizon - 0.16)
    y = y_base + height * 0.045 * math.sin(phase * math.pi * (6 if plan.motion == "glide" else 2))
    return width * travel, y, scale


def _draw_stars(draw: ImageDraw.ImageDraw, width: int, height: int, phase: float, rng: random.Random) -> None:
    for _ in range(28):
        x, y = rng.randint(0, width - 1), rng.randint(0, int(height * 0.62))
        alpha = 120 + int(100 * abs(math.sin(phase * 8 + x)))
        radius = 1 if rng.random() > 0.15 else 2
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(255, 255, 245, alpha))


def _draw_setting(draw: ImageDraw.ImageDraw, plan: ScenePlan, width: int, height: int, rng: random.Random) -> None:
    horizon = int(height * plan.horizon)
    if plan.setting == "city":
        cursor = 0
        while cursor < width:
            building_width = rng.randint(width // 14, width // 7)
            building_height = rng.randint(height // 8, height // 3)
            draw.rectangle((cursor, horizon - building_height, cursor + building_width, horizon), fill=(8, 10, 16, 255))
            cursor += building_width + 4
    elif plan.setting == "forest":
        for index in range(7):
            x = int((index + 0.5) * width / 7)
            size = height // (5 + index % 2)
            draw.polygon([(x, horizon), (x - size, horizon), (x, horizon - size * 1.7), (x + size, horizon)], fill=(8, 42, 24, 255))
    elif plan.setting == "mountain":
        for index, peak in enumerate((0.2, 0.5, 0.78)):
            x = int(width * peak)
            size = int(height * (0.28 - index * 0.04))
            draw.polygon([(x - size, horizon), (x, horizon - size), (x + size, horizon)], fill=(28, 58, 42, 255))


def _draw_subject(draw: ImageDraw.ImageDraw, subject: str, x: float, y: float, scale: float, color: Color, phase: float) -> None:
    fill = color + (255,)
    size = 18 * scale
    flap = math.sin(phase * math.pi * 8)
    if subject == "bird":
        draw.polygon([(x - size, y), (x + size * 1.3, y + size * 0.15), (x - size * 0.2, y + size * 0.45)], fill=fill)
        draw.polygon([(x - size * 0.2, y), (x + size * 0.8, y - size * flap), (x + size, y + size * 0.1)], fill=fill)
    elif subject == "kite":
        draw.polygon([(x, y - size), (x + size * 0.7, y), (x, y + size), (x - size * 0.7, y)], fill=fill)
        draw.line((x, y + size, x, y + size * 2.4), fill=fill, width=2)
    elif subject == "boat":
        draw.polygon([(x - size * 1.4, y), (x + size * 1.4, y), (x + size, y + size * 0.55), (x - size, y + size * 0.55)], fill=fill)
        draw.polygon([(x, y), (x, y - size * 1.6), (x + size, y)], fill=(248, 248, 248, 235))
    elif subject in {"moon", "sun", "orb"}:
        radius = size * (1.5 if subject == "orb" else 2)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
    elif subject == "car":
        draw.rounded_rectangle((x - size * 1.6, y - size * 0.4, x + size * 1.6, y + size * 0.5), radius=6, fill=fill)
        draw.ellipse((x - size, y + size * 0.25, x - size * 0.4, y + size * 0.85), fill=(20, 20, 20, 255))
        draw.ellipse((x + size * 0.4, y + size * 0.25, x + size, y + size * 0.85), fill=(20, 20, 20, 255))
    elif subject == "fish":
        draw.ellipse((x - size, y - size * 0.45, x + size, y + size * 0.45), fill=fill)
        draw.polygon([(x - size, y), (x - size * 1.7, y - size * 0.5), (x - size * 1.7, y + size * 0.5)], fill=fill)
    elif subject == "flower":
        for angle in range(0, 360, 60):
            petal_x = x + math.cos(math.radians(angle)) * size * 0.55
            petal_y = y + math.sin(math.radians(angle)) * size * 0.55
            draw.ellipse((petal_x - size * 0.35, petal_y - size * 0.35, petal_x + size * 0.35, petal_y + size * 0.35), fill=fill)
        draw.line((x, y + size * 0.3, x, y + size * 2), fill=(42, 130, 58, 255), width=3)
    elif subject in {"cat", "dog"}:
        draw.ellipse((x - size, y - size * 0.3, x + size, y + size * 0.7), fill=fill)
        draw.ellipse((x - size * 0.45, y - size, x + size * 0.45, y + size * 0.1), fill=fill)
        if subject == "cat":
            draw.polygon([(x - size * 0.35, y - size * 0.7), (x - size * 0.15, y - size * 1.25), (x, y - size * 0.65)], fill=fill)
    elif subject == "person":
        draw.ellipse((x - size * 0.35, y - size * 1.3, x + size * 0.35, y - size * 0.6), fill=fill)
        draw.line((x, y - size * 0.6, x, y + size * 0.6), fill=fill, width=4)
        draw.line((x, y - size * 0.2, x - size * 0.7, y + size * 0.25), fill=fill, width=3)
        draw.line((x, y - size * 0.2, x + size * 0.7, y + size * 0.25), fill=fill, width=3)


def _draw_weather(draw: ImageDraw.ImageDraw, plan: ScenePlan, width: int, height: int, phase: float, seed: int) -> None:
    rng = random.Random(seed + 17)
    if plan.weather in {"rain", "storm"}:
        for _ in range(50):
            x = rng.randint(0, width)
            y = (rng.randint(0, height) + int(phase * height * 2)) % height
            draw.line((x, y, x - 4, y + 14), fill=(190, 210, 230, 150), width=1)
    elif plan.weather == "snow":
        for _ in range(40):
            x = (rng.randint(0, width) + int(phase * 30)) % width
            y = (rng.randint(0, height) + int(phase * height)) % height
            draw.ellipse((x, y, x + 3, y + 3), fill=(255, 255, 255, 200))
    elif plan.weather == "mist":
        band = int(height * (0.5 + 0.05 * math.sin(phase * math.pi * 2)))
        draw.rectangle((0, band, width, band + height // 5), fill=(230, 236, 240, 70))
    elif plan.weather == "clouds":
        for index in range(4):
            x = ((index * width // 3) + int(phase * width * 0.4)) % (width + 80) - 40
            y = height * (0.18 + index * 0.07)
            draw.ellipse((x, y, x + 110, y + 36), fill=(255, 255, 255, 150))


def _image_frame(source: Image.Image, plan: ScenePlan, width: int, height: int, phase: float, seed: int) -> np.ndarray:
    scale = 1.08 + (0.14 * phase if plan.motion == "zoom" else 0.05 * phase)
    enlarged = source.resize((math.ceil(width * scale), math.ceil(height * scale)), Image.Resampling.LANCZOS)
    max_left = enlarged.width - width
    max_top = enlarged.height - height
    left = int(max_left * (0.15 + 0.7 * phase if plan.motion != "zoom" else 0.5))
    top = int(max_top * 0.5)
    frame = enlarged.crop((left, top, left + width, top + height))
    if plan.time_of_day == "night":
        frame = ImageEnhance.Brightness(frame).enhance(0.62)
        frame = Image.blend(frame, Image.new("RGB", frame.size, (24, 38, 82)), 0.22)
    elif plan.time_of_day in {"sunset", "sunrise"}:
        frame = Image.blend(frame, Image.new("RGB", frame.size, (176, 78, 36)), 0.16)
    overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    _draw_weather(ImageDraw.Draw(overlay), plan, width, height, phase, seed)
    return np.asarray(Image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB"))
