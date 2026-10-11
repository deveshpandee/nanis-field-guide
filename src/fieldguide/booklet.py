"""Render the field guide: one HTML page per plant, ready to print as an A5 booklet."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import av
from jinja2 import Environment, PackageLoader, select_autoescape

from .media import load_image


def cut_clip(src: Path, start: float, end: float, dst: Path) -> None:
    """Copy start..end seconds of a recording into a small mono AAC file."""
    with av.open(str(src)) as inp, av.open(str(dst), "w", format="mp4") as out:
        ins = inp.streams.audio[0]
        outs = out.add_stream("aac", rate=44100, layout="mono")
        outs.bit_rate = 96_000
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=44100)
        inp.seek(int(max(0.0, start - 2) * av.time_base))
        for frame in inp.decode(ins):
            if frame.pts is None:
                continue
            t = float(frame.pts * frame.time_base)
            if t + frame.samples / frame.sample_rate < start:
                continue
            if t > end:
                break
            for rf in resampler.resample(frame):
                rf.pts = None
                out.mux(outs.encode(rf))
        for rf in resampler.resample(None):
            rf.pts = None
            out.mux(outs.encode(rf))
        out.mux(outs.encode(None))


def export_photo(src: Path, dst: Path, max_side: int = 1400) -> tuple[int, int]:
    """Resized copy without EXIF, so no GPS or phone details leave in the booklet."""
    im = load_image(src, max_side)
    im.save(dst, "JPEG", quality=84, optimize=True, progressive=True)
    return im.size


def clock(dt: datetime) -> str:
    return dt.strftime("%-I:%M %p").lower()


def route_svg(points: list[tuple[int, float, float]], w: int = 480, h: int = 300, pad: int = 28) -> str | None:
    """A bare route line through the numbered stops. No map tiles, no coordinates printed."""
    pts = [(n, lat, lon) for n, lat, lon in points if lat is not None]
    if len(pts) < 2:
        return None
    lats = [p[1] for p in pts]
    lons = [p[2] for p in pts]
    import math

    k = math.cos(math.radians(sum(lats) / len(lats)))
    xs = [lon * k for lon in lons]
    dx, dy = (max(xs) - min(xs)) or 1e-6, (max(lats) - min(lats)) or 1e-6
    s = min((w - 2 * pad) / dx, (h - 2 * pad) / dy)
    ox, oy = (w - dx * s) / 2, (h - dy * s) / 2  # centre the route
    xy = [(ox + (x - min(xs)) * s, h - oy - (lat - min(lats)) * s) for x, lat in zip(xs, lats)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in xy)
    dots = "".join(
        f'<g class="stop"><circle cx="{x:.1f}" cy="{y:.1f}" r="11"/><text x="{x:.1f}" y="{y + 4:.1f}">{n}</text></g>'
        for (n, _, _), (x, y) in zip(pts, xy)
    )
    return f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Route of the walk"><polyline points="{line}"/>{dots}</svg>'


def render(walk_dir: Path, cfg: dict, stops: list[dict], recordings: list[dict], stats: dict) -> Path:
    out = walk_dir / "booklet"
    media = out / "media"
    if media.exists():
        shutil.rmtree(media)
    media.mkdir(parents=True)

    pages = []
    for st in stops:
        e = st.get("entry")
        if not e:
            continue
        photos = []
        for j, name in enumerate(st["photos"][:3]):
            fn = f"stop-{st['number']:02d}-{j + 1}.jpg"
            w, h = export_photo(walk_dir / name, media / fn)
            photos.append({"src": f"media/{fn}", "portrait": h > w})
        audio = None
        if st.get("clip") and cfg.get("include_audio", True):
            rec_i, a, b = st["clip"]
            fn = f"stop-{st['number']:02d}.m4a"
            cut_clip(walk_dir / recordings[rec_i]["file"], a, b, media / fn)
            audio = {"src": f"media/{fn}", "seconds": round(b - a)}
        pages.append({**st, "e": e, "photo_files": photos, "audio": audio, "time": clock(datetime.fromisoformat(st["time"]))})

    cover = None
    cover_name = cfg.get("cover") or (stops[0]["photos"][0] if stops else None)
    if cover_name and (walk_dir / cover_name).exists():
        w, h = export_photo(walk_dir / cover_name, media / "cover.jpg", 1600)
        cover = {"src": "media/cover.jpg", "portrait": h > w}

    route = route_svg([(st["number"], *(st.get("gps") or (None, None))) for st in stops if st.get("entry")]) if cfg.get("show_route", True) else None

    env = Environment(loader=PackageLoader("fieldguide", "templates"), autoescape=select_autoescape(["html", "j2"]))
    html = env.get_template("booklet.html.j2").render(
        cfg=cfg,
        elder=cfg.get("elder", "Nani"),
        pages=pages,
        cover=cover,
        route=route,
        stats=stats,
        questions=[(p, q) for p in pages for q in p["e"].get("ask_next_time", [])],
        generated=datetime.now().strftime("%-d %B %Y"),
    )
    (out / "index.html").write_text(html)
    return out / "index.html"
