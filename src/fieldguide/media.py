"""Find the photos and the recording in a walk folder and put them on one clock.

Everything is converted to timezone-aware datetimes in the laptop's local zone.
Phones write EXIF times without a zone, so those are read as local time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import av
from PIL import Image, ImageOps

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
AUDIO_EXT = {".m4a", ".mp3", ".aac", ".wav", ".ogg", ".opus", ".amr", ".3gp", ".flac", ".webm", ".mp4"}

LOCAL_TZ = datetime.now().astimezone().tzinfo

# 20261011_171503, 2026-10-11 17.15.03, 20261011-171503123 ...
STAMP_RE = re.compile(
    r"(?P<y>20\d\d)[-_.]?(?P<mo>[01]\d)[-_.]?(?P<d>[0-3]\d)[ _T-]?"
    r"(?P<h>[0-2]\d)[-_.:]?(?P<mi>[0-5]\d)[-_.:]?(?P<s>[0-5]\d)"
)

EXIF_IFD = 0x8769
GPS_IFD = 0x8825
DATETIME_ORIGINAL = 36867
OFFSET_TIME_ORIGINAL = 36881
DATETIME = 306


@dataclass
class Photo:
    path: Path
    taken_at: datetime
    time_source: str
    gps: tuple[float, float] | None = None


@dataclass
class Recording:
    path: Path
    started_at: datetime
    duration: float
    time_source: str

    @property
    def ended_at(self) -> datetime:
        return self.started_at + timedelta(seconds=self.duration)

    def offset(self, moment: datetime) -> float:
        """Seconds from the start of the recording to `moment`."""
        return (moment - self.started_at).total_seconds()


def _register_heif() -> None:
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:
        pass


_register_heif()


def stamp_from_name(name: str) -> datetime | None:
    m = STAMP_RE.search(name)
    if not m:
        return None
    try:
        naive = datetime(*(int(m[k]) for k in ("y", "mo", "d", "h", "mi", "s")))
    except ValueError:
        return None
    # Pixel names photos after UTC time; everyone else uses local time.
    if name.upper().startswith("PXL_"):
        return naive.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
    return naive.replace(tzinfo=LOCAL_TZ)


def _parse_exif_time(value: str, offset: str | None) -> datetime | None:
    try:
        naive = datetime.strptime(value.strip()[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    if offset:
        try:
            return datetime.strptime(f"{naive:%Y-%m-%d %H:%M:%S}{offset.strip()}", "%Y-%m-%d %H:%M:%S%z").astimezone(LOCAL_TZ)
        except ValueError:
            pass
    return naive.replace(tzinfo=LOCAL_TZ)


def _gps(exif) -> tuple[float, float] | None:
    gps = exif.get_ifd(GPS_IFD)
    if not gps or 2 not in gps or 4 not in gps:
        return None

    def deg(v) -> float:
        d, m, s = (float(x) for x in v)
        return d + m / 60 + s / 3600

    try:
        lat, lon = deg(gps[2]), deg(gps[4])
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if gps.get(1) == "S":
        lat = -lat
    if gps.get(3) == "W":
        lon = -lon
    if lat == 0 and lon == 0:
        return None
    return round(lat, 6), round(lon, 6)


def read_photo(path: Path) -> Photo:
    with Image.open(path) as im:
        exif = im.getexif()
    sub = exif.get_ifd(EXIF_IFD)
    gps = _gps(exif)
    raw = sub.get(DATETIME_ORIGINAL) or exif.get(DATETIME)
    if raw:
        when = _parse_exif_time(str(raw), sub.get(OFFSET_TIME_ORIGINAL))
        if when:
            return Photo(path, when, "exif", gps)
    when = stamp_from_name(path.name)
    if when:
        return Photo(path, when, "filename", gps)
    mtime = datetime.fromtimestamp(path.stat().st_mtime, LOCAL_TZ)
    return Photo(path, mtime, "file mtime", gps)


def read_recording(path: Path, override: datetime | None = None) -> Recording:
    with av.open(str(path)) as container:
        duration = float(container.duration or 0) / av.time_base
        if not duration and container.streams.audio:
            s = container.streams.audio[0]
            duration = float(s.duration * s.time_base) if s.duration else 0.0
        created = container.metadata.get("creation_time")
    if override:
        return Recording(path, override, duration, "walk.toml")
    when = stamp_from_name(path.name)
    if when:
        return Recording(path, when, duration, "filename")
    if created:
        try:
            utc = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if utc.tzinfo is None:
                utc = utc.replace(tzinfo=timezone.utc)
            # Some recorders stamp creation_time when they finish, not when they start.
            return Recording(path, utc.astimezone(LOCAL_TZ), duration, "audio metadata")
        except ValueError:
            pass
    mtime = datetime.fromtimestamp(path.stat().st_mtime, LOCAL_TZ)
    return Recording(path, mtime - timedelta(seconds=duration), duration, "file mtime minus duration")


def scan_walk(folder: Path, audio_start: datetime | None = None) -> tuple[list[Photo], list[Recording]]:
    photos, recordings = [], []
    for p in sorted(folder.iterdir()):
        if p.name.startswith(".") or not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext in PHOTO_EXT:
            photos.append(read_photo(p))
        elif ext in AUDIO_EXT:
            recordings.append(read_recording(p, audio_start if not recordings else None))
    photos.sort(key=lambda ph: ph.taken_at)
    recordings.sort(key=lambda r: r.started_at)
    return photos, recordings


def load_image(path: Path, max_side: int) -> Image.Image:
    """Open a photo upright and RGB, shrunk so its longest side is `max_side`."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((max_side, max_side))
        return im
