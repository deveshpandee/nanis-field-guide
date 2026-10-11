"""fieldguide: turn a walk with an elder into a family field guide, offline."""

from __future__ import annotations

import argparse
import json
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path

from . import align, booklet, gemma, media, transcribe

WALK_TOML = """\
# About this walk. Everything here is optional.
elder = "Nani"                 # what you call them; used throughout the book
elder_name = ""                # their name, for the cover
author = ""                    # your name, for the cover
place = ""                     # e.g. "the colony park, Lucknow"
title_hi = "नानी की किताब"
title_en = "Nani's Field Guide"
cover = ""                     # photo file for the cover (default: the first photo)
foreword = \"\"\"
\"\"\"

# If the photos and the talk don't line up, set when the recording really started:
audio_start = ""               # "2026-10-11 17:15:03"

language = "hi"
vocabulary = ""                # extra names to prime Whisper with, e.g. "अपराजिता, सदाबहार"
whisper_model = "large-v3-turbo"
gemma_model = "gemma4:e2b-it-qat"
include_audio = true           # put each plant's clip in the booklet
show_route = true              # draw the route from photo GPS (no map, no coordinates)
"""

DEFAULTS = tomllib.loads(WALK_TOML)
STATE = ".fieldguide/entries.json"


def load_cfg(walk: Path) -> dict:
    cfg = dict(DEFAULTS)
    p = walk / "walk.toml"
    if p.exists():
        cfg.update(tomllib.loads(p.read_text()))
    return cfg


def parse_when(value: str) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=media.LOCAL_TZ) if "+" not in value else datetime.fromisoformat(value)


def gather(walk: Path, cfg: dict, log=print):
    photos, recs = media.scan_walk(walk, parse_when(cfg.get("audio_start", "")))
    if not photos:
        sys.exit(f"No photos found in {walk}")
    prompt = transcribe.DEFAULT_PROMPT + (" " + cfg["vocabulary"] if cfg.get("vocabulary") else "")
    transcripts = []
    for r in recs:
        log(f"Transcribing {r.path.name} ({r.duration / 60:.1f} min)")
        t0 = time.time()
        transcripts.append(transcribe.transcribe(r, walk / ".fieldguide", cfg["whisper_model"], cfg["language"], prompt, log=log))
        log(f"  done in {time.time() - t0:.0f}s, {len(transcripts[-1])} segments")
    return photos, recs, transcripts, align.build_stops(photos, recs, transcripts)


def cmd_init(a) -> None:
    p = Path(a.walk) / "walk.toml"
    if p.exists():
        print(f"{p} already exists")
        return
    p.write_text(WALK_TOML)
    print(f"Wrote {p}. Fill in who you walked with, then run: fieldguide check {a.walk}")


def cmd_check(a) -> None:
    walk = Path(a.walk)
    cfg = load_cfg(walk)
    photos, recs, transcripts, stops = gather(walk, cfg)
    print("\nRecordings")
    for r in recs:
        print(f"  {r.path.name}: {r.started_at:%H:%M:%S} to {r.ended_at:%H:%M:%S} ({r.duration / 60:.1f} min; start from {r.time_source})")
    print("\nPhotos")
    for ph in photos:
        where = ""
        for r in recs:
            off = r.offset(ph.taken_at)
            if 0 <= off <= r.duration:
                where = f"{off / 60:5.1f} min into {r.path.name}"
        print(f"  {ph.taken_at:%H:%M:%S}  {ph.path.name:<34} {ph.time_source:<10} {'GPS' if ph.gps else '   '}  {where or 'NOT DURING ANY RECORDING'}")
    print("\nStops")
    for st in stops:
        print(f"  {st.number:2d}. {st.photos[0].taken_at:%H:%M:%S}  {len(st.photos)} photo(s)  heard: {st.text[:110] or '(nothing)'}")
    left = align.unplaced(stops, recs, transcripts)
    outside = [ph for ph in photos if recs and not any(0 <= r.offset(ph.taken_at) <= r.duration for r in recs)]
    print(f"\n{len(left)} bits of speech between stops (walking chatter is normal).")
    if outside:
        print(f"Warning: {len(outside)} photo(s) were taken outside the recording. If that's wrong, the recording's start time is off: set audio_start in walk.toml.")


def _stop_record(st: align.Stop, recs: list[media.Recording]) -> dict:
    gps = next((ph.gps for ph in st.photos if ph.gps), None)
    return {
        "number": st.number,
        "photos": [ph.path.name for ph in st.photos],
        "time": st.photos[0].taken_at.isoformat(),
        "gps": list(gps) if gps else None,
        "clip": list(st.clip) if st.clip else None,
        "transcript": st.text,
    }


def _stats(walk: Path, cfg: dict, recs, stops: list[dict], photos) -> dict:
    if recs:
        minutes = round(sum(r.duration for r in recs) / 60)
    else:
        minutes = round((photos[-1].taken_at - photos[0].taken_at).total_seconds() / 60)
    entries = [s["entry"] for s in stops if s.get("entry")]
    quoted = [e for e in entries if e.get("quote_hi")]
    label = cfg["gemma_model"]
    if label.startswith("gemma4:"):
        label = "Gemma 4 " + label.split(":")[1].split("-")[0].upper()
    return {
        "minutes": max(minutes, 1),
        "date": photos[0].taken_at.strftime("%-d %B %Y"),
        "photos": len(photos),
        "whisper": f"Whisper {cfg['whisper_model']}",
        "gemma": label,
        "quotes_total": len(quoted),
        "dropped": sum(e.get("quote_dropped", 0) for e in quoted),
    }


def cmd_process(a) -> None:
    walk = Path(a.walk)
    cfg = load_cfg(walk)
    photos, recs, transcripts, stops = gather(walk, cfg)
    state_path = walk / STATE
    old = {}
    if state_path.exists():
        for s in json.loads(state_path.read_text())["stops"]:
            old[tuple(s["photos"])] = s

    records = []
    for st in stops:
        rec = _stop_record(st, recs)
        prev = old.get(tuple(rec["photos"]))
        if prev and prev.get("entry") and not a.redo and (prev.get("edited") or prev.get("transcript") == rec["transcript"]):
            rec["entry"], rec["edited"] = prev["entry"], prev.get("edited", False)
        else:
            t0 = time.time()
            print(f"Stop {st.number}/{len(stops)}: asking {cfg['gemma_model']}")
            rec["entry"] = gemma.write_entry(st, cfg["elder"], cfg["gemma_model"])
            e = rec["entry"]
            dropped = f"  [{e['quote_dropped']} made-up sentence(s) dropped]" if e.get("quote_dropped") else ""
            print(f"  {e.get('local_name') or '?'} / {e.get('english_name')} ({e.get('scientific_name')}, {e.get('id_confidence')}){dropped}  {time.time() - t0:.0f}s")
            rec["edited"] = False
        records.append(rec)
        _save(state_path, recs, records, _stats(walk, cfg, recs, records, photos))

    out = booklet.render(walk, cfg, records, _rec_meta(recs), _stats(walk, cfg, recs, records, photos))
    print(f"\nBooklet: {out}")


def _rec_meta(recs) -> list[dict]:
    return [{"file": r.path.name, "started_at": r.started_at.isoformat(), "duration": r.duration, "time_source": r.time_source} for r in recs]


def _save(path: Path, recs, records, stats) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"recordings": _rec_meta(recs), "stops": records, "stats": stats}, ensure_ascii=False, indent=1))


def cmd_render(a) -> None:
    walk = Path(a.walk)
    state = json.loads((walk / STATE).read_text())
    out = booklet.render(walk, load_cfg(walk), state["stops"], state["recordings"], state["stats"])
    print(f"Booklet: {out}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="fieldguide", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, helptext in [
        ("init", cmd_init, "write a walk.toml to fill in"),
        ("check", cmd_check, "show how photos and speech line up, before asking Gemma"),
        ("process", cmd_process, "transcribe, write entries with Gemma, render the booklet"),
        ("render", cmd_render, "re-render the booklet after editing .fieldguide/entries.json"),
    ]:
        p = sub.add_parser(name, help=helptext)
        p.add_argument("walk", help="folder with the walk's photos and recording")
        if name == "process":
            p.add_argument("--redo", action="store_true", help="rewrite every entry, even ones you edited")
        p.set_defaults(fn=fn)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
