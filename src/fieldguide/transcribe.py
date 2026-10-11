"""Transcribe the walk recording with Whisper, locally, and cache the result.

A walk is mostly silence with bursts of talk. Each burst is transcribed on its
own (short VAD chunks), and the words are regrouped into utterances at pauses,
so that every sentence can be matched to the photo it belongs to.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .media import Recording

# Priming Whisper with plant names it will hear makes it spell them the way people say them.
DEFAULT_PROMPT = "नानी के साथ बगीचे में सैर। नीम, तुलसी, पीपल, बरगद, आम, अमरूद, गुड़हल, करी पत्ता, मेहंदी, एलोवेरा।"
CACHE_VERSION = 2
PAUSE = 0.8  # seconds of silence that end an utterance
MAX_UTTERANCE = 12.0  # split long run-ons at the next comma after this many seconds
ENDS = ("।", ".", "?", "!", "॥")


@dataclass
class Segment:
    start: float  # seconds from the start of its recording
    end: float
    text: str


def _cache_key(rec: Recording, model: str, prompt: str) -> str:
    st = rec.path.stat()
    return f"v{CACHE_VERSION}|{rec.path.name}|{st.st_size}|{int(st.st_mtime)}|{model}|{prompt}"


def _utterances(words) -> list[Segment]:
    out: list[Segment] = []
    cur: list = []

    def flush():
        if cur:
            text = "".join(w.word for w in cur).replace("�", "").strip()
            if text:
                out.append(Segment(round(cur[0].start, 2), round(cur[-1].end, 2), text))
            cur.clear()

    for w in words:
        if cur:
            prev = cur[-1].word.strip()
            gap = w.start - cur[-1].end
            long_enough = cur[-1].end - cur[0].start > MAX_UTTERANCE and prev.endswith(",")
            if gap > PAUSE or prev.endswith(ENDS) or long_enough:
                flush()
        cur.append(w)
    flush()
    return out


def transcribe(
    rec: Recording,
    cache_dir: Path,
    model: str = "large-v3-turbo",
    language: str = "hi",
    prompt: str = DEFAULT_PROMPT,
    log=print,
) -> list[Segment]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"transcript-{rec.path.stem}.json"
    key = _cache_key(rec, model, prompt)
    if cache.exists():
        data = json.loads(cache.read_text())
        if data.get("key") == key:
            return [Segment(**s) for s in data["segments"]]

    from faster_whisper import BatchedInferencePipeline, WhisperModel

    log(f"  loading Whisper {model} (CPU, int8)")
    wm = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
    pipe = BatchedInferencePipeline(wm)
    segments, info = pipe.transcribe(
        str(rec.path),
        language=language or None,
        initial_prompt=prompt or None,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 300},
        chunk_length=15,
        batch_size=8,
        beam_size=5,
        word_timestamps=True,
        condition_on_previous_text=False,
    )
    out: list[Segment] = []
    for s in segments:
        for u in _utterances(s.words or []):
            out.append(u)
            log(f"  [{u.start:7.1f}s] {u.text}")
    cache.write_text(json.dumps({"key": key, "language": info.language, "segments": [asdict(s) for s in out]}, ensure_ascii=False, indent=1))
    return out
