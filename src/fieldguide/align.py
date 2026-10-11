"""Group photos into stops and give each stop the words spoken around it.

On a walk you stop at a plant, they talk, you take a photo or three, you move on.
So photos close together in time are one stop, and the speech belongs to the
nearest stop: from a little before the first photo until halfway to the next stop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .media import Photo, Recording
from .transcribe import Segment

SAME_STOP_GAP = timedelta(seconds=40)
LOOK_BEFORE = timedelta(seconds=45)
LOOK_AFTER = timedelta(seconds=80)


@dataclass
class Heard:
    recording: int  # index into the walk's recordings
    start: float  # seconds into that recording
    end: float
    text: str
    at: datetime


@dataclass
class Stop:
    number: int
    photos: list[Photo]
    window: tuple[datetime, datetime]
    heard: list[Heard] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(h.text for h in self.heard)

    @property
    def clip(self) -> tuple[int, float, float] | None:
        """(recording index, start, end) covering everything heard at this stop."""
        if not self.heard:
            return None
        rec = self.heard[0].recording
        same = [h for h in self.heard if h.recording == rec]
        return rec, max(0.0, same[0].start - 0.4), same[-1].end + 0.4


def group_photos(photos: list[Photo]) -> list[list[Photo]]:
    groups: list[list[Photo]] = []
    for ph in photos:
        if groups and ph.taken_at - groups[-1][-1].taken_at <= SAME_STOP_GAP:
            groups[-1].append(ph)
        else:
            groups.append([ph])
    return groups


def build_stops(photos: list[Photo], recordings: list[Recording], transcripts: list[list[Segment]]) -> list[Stop]:
    groups = group_photos(photos)
    stops: list[Stop] = []
    for i, g in enumerate(groups):
        first, last = g[0].taken_at, g[-1].taken_at
        start, end = first - LOOK_BEFORE, last + LOOK_AFTER
        if i > 0:
            prev_last = groups[i - 1][-1].taken_at
            start = max(start, prev_last + (first - prev_last) / 2)
        if i + 1 < len(groups):
            next_first = groups[i + 1][0].taken_at
            end = min(end, last + (next_first - last) / 2)
        stops.append(Stop(i + 1, g, (start, end)))

    for r_i, (rec, segs) in enumerate(zip(recordings, transcripts)):
        for s in segs:
            mid = rec.started_at + timedelta(seconds=(s.start + s.end) / 2)
            for stop in stops:
                if stop.window[0] <= mid < stop.window[1]:
                    stop.heard.append(Heard(r_i, s.start, s.end, s.text, mid))
                    break
    return stops


def unplaced(stops: list[Stop], recordings: list[Recording], transcripts: list[list[Segment]]) -> list[Heard]:
    """Speech that fell outside every stop: walking chatter, or a sign the clocks disagree."""
    placed = {(h.recording, h.start) for st in stops for h in st.heard}
    out = []
    for r_i, (rec, segs) in enumerate(zip(recordings, transcripts)):
        for s in segs:
            if (r_i, s.start) not in placed:
                out.append(Heard(r_i, s.start, s.end, s.text, rec.started_at + timedelta(seconds=s.start)))
    return out
