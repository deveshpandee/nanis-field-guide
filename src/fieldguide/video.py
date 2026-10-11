"""A short 'talking booklet' video: each plant's spread on screen while the elder's clip plays.

Needs Google Chrome or Chromium (to print the booklet) and pdftoppm (poppler-utils).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from PIL import Image

W, H = 1920, 1080
FPS = 12
RATE = 44100
DESK = (217, 210, 195)
FADE = 0.5


def _chrome() -> str:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if path := shutil.which(name):
            return path
    raise SystemExit("fieldguide video needs Google Chrome or Chromium to print the booklet.")


def page_images(index_html: Path, tmp: Path, height: int = 1000) -> list[Image.Image]:
    if not shutil.which("pdftoppm"):
        raise SystemExit("fieldguide video needs pdftoppm (poppler-utils).")
    pdf = tmp / "booklet.pdf"
    subprocess.run([_chrome(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=10000",
                    f"--print-to-pdf={pdf}", index_html.resolve().as_uri()], check=True, capture_output=True)
    subprocess.run(["pdftoppm", "-png", "-scale-to-y", str(height), "-scale-to-x", "-1", str(pdf), str(tmp / "pg")], check=True)
    files = sorted(tmp.glob("pg-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
    return [Image.open(p).convert("RGB") for p in files]


def slide(pages: list[Image.Image]) -> Image.Image:
    frame = Image.new("RGB", (W, H), DESK)
    gap = 28
    total = sum(p.width for p in pages) + gap * (len(pages) - 1)
    x = (W - total) // 2
    for p in pages:
        frame.paste(p, (x, (H - p.height) // 2))
        x += p.width + gap
    return frame


def load_clip(path: Path) -> np.ndarray:
    out = []
    resampler = av.AudioResampler(format="flt", layout="mono", rate=RATE)
    with av.open(str(path)) as c:
        for frame in c.decode(audio=0):
            for rf in resampler.resample(frame):
                out.append(rf.to_ndarray().reshape(-1))
    return np.concatenate(out) if out else np.zeros(0, np.float32)


def make_video(walk: Path, state: dict, cfg: dict, out: Path) -> Path:
    booklet = walk / "booklet"
    plants = [s for s in state["stops"] if s.get("entry")]
    with tempfile.TemporaryDirectory() as td:
        imgs = page_images(booklet / "index.html", Path(td))

    # Page order mirrors booklet.html.j2.
    i = 0
    cover = imgs[i]; i += 1
    if (cfg.get("foreword") or "").strip():
        i += 1
    i += 1  # contents
    slides: list[tuple[Image.Image, float, np.ndarray | None]] = [(slide([cover]), 4.0, None)]
    for n, st in enumerate(plants, start=1):
        left, right = imgs[i], imgs[i + 1]
        i += 2
        clip_path = booklet / "media" / f"stop-{st['number']:02d}.m4a"
        audio = load_clip(clip_path) if clip_path.exists() else None
        seconds = (len(audio) / RATE + 1.5) if audio is not None and len(audio) else 5.0
        slides.append((slide([left, right]), max(seconds, 4.0), audio))
    walk_page = imgs[i]; i += 1
    rest = imgs[i:]
    slides.append((slide([walk_page] + rest[:1]), 6.0, None))
    if len(rest) > 1:
        slides.append((slide(rest[1:2]), 5.0, None))

    total = sum(d for _, d, _ in slides)
    track = np.zeros(int(total * RATE) + RATE, np.float32)
    t = 0.0
    for _, d, audio in slides:
        if audio is not None and len(audio):
            start = int((t + 0.6) * RATE)
            track[start : start + len(audio)] += audio[: len(track) - start]
        t += d

    with av.open(str(out), "w", format="mp4") as c:
        vs = c.add_stream("libx264", rate=FPS, options={"crf": "22", "preset": "veryfast", "tune": "stillimage"})
        vs.width, vs.height, vs.pix_fmt = W, H, "yuv420p"
        a_s = c.add_stream("aac", rate=RATE, layout="mono")
        a_s.bit_rate = 128_000

        prev = None
        for img, d, _ in slides:
            frames = int(round(d * FPS))
            fade = int(FADE * FPS) if prev is not None else 0
            for f in range(frames):
                shown = Image.blend(prev, img, (f + 1) / (fade + 1)) if f < fade else img
                for pkt in vs.encode(av.VideoFrame.from_image(shown)):
                    c.mux(pkt)
            prev = img
        for pkt in vs.encode(None):
            c.mux(pkt)

        chunk = 1024
        for k in range(0, int(total * RATE), chunk):
            block = track[k : k + chunk]
            if len(block) < chunk:
                block = np.pad(block, (0, chunk - len(block)))
            af = av.AudioFrame.from_ndarray(np.clip(block, -1, 1).reshape(1, -1).astype(np.float32), format="flt", layout="mono")
            af.sample_rate = RATE
            af.pts = k
            af.time_base = Fraction(1, RATE)
            for pkt in a_s.encode(af):
                c.mux(pkt)
        for pkt in a_s.encode(None):
            c.mux(pkt)
    return out
