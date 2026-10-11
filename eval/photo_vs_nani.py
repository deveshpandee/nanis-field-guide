"""How much does the elder's one word help a small local model identify a plant?

For each plant: one photo from Wikimedia Commons, then ask Gemma for the species twice:
  A. photo only
  B. photo + what Nani says when she points at it ("ये नीम है।")
Scores the scientific name (genus + species, synonyms allowed).

  uv run python eval/photo_vs_nani.py            # downloads photos into eval/images/
"""

from __future__ import annotations

import base64
import io
import json
import sys
import time
from pathlib import Path

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fieldguide.gemma import DEFAULT_MODEL, botanical_name, ollama_host  # noqa: E402

MODEL = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL

PLANTS = [
    # Hindi name as an elder would say it, accepted scientific names, Commons search
    ("नीम", ["azadirachta indica"], "Azadirachta indica leaves"),
    ("पीपल", ["ficus religiosa"], "Ficus religiosa leaves"),
    ("बरगद", ["ficus benghalensis"], "Ficus benghalensis aerial roots"),
    ("तुलसी", ["ocimum tenuiflorum", "ocimum sanctum"], "Ocimum tenuiflorum plant"),
    ("गुड़हल", ["hibiscus rosa-sinensis", "hibiscus × rosa-sinensis", "hibiscus rosa sinensis"], "Hibiscus rosa-sinensis red flower"),
    ("आम", ["mangifera indica"], "Mangifera indica tree leaves"),
    ("अमरूद", ["psidium guajava"], "Psidium guajava leaves fruit"),
    ("करी पत्ता", ["murraya koenigii", "bergera koenigii"], "Murraya koenigii leaves"),
    ("सदाबहार", ["catharanthus roseus"], "Catharanthus roseus flowers"),
    ("गेंदा", ["tagetes erecta", "tagetes patula"], "Tagetes erecta flower"),
    ("मेहंदी", ["lawsonia inermis"], "Lawsonia inermis plant"),
    ("अपराजिता", ["clitoria ternatea"], "Clitoria ternatea flower"),
]

UA = {"User-Agent": "nanis-field-guide-eval/0.1 (https://github.com/deveshpandee)"}
SCHEMA = {
    "type": "object",
    "properties": {"english_name": {"type": "string"}, "scientific_name": {"type": "string"}, "confidence": {"type": "string", "enum": ["high", "medium", "low"]}},
    "required": ["english_name", "scientific_name", "confidence"],
}


def fetch(query: str, dst: Path) -> dict:
    meta = dst.with_suffix(".json")
    if dst.exists() and meta.exists():
        return json.loads(meta.read_text())
    r = httpx.get(
        "https://commons.wikimedia.org/w/api.php",
        params={"action": "query", "generator": "search", "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 1,
                "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 800, "format": "json"},
        headers=UA, timeout=30,
    )
    page = next(iter(r.json()["query"]["pages"].values()))
    info = page["imageinfo"][0]
    img = httpx.get(info["thumburl"], headers=UA, timeout=60, follow_redirects=True)
    Image.open(io.BytesIO(img.content)).convert("RGB").save(dst, "JPEG", quality=88)
    ext = info.get("extmetadata", {})
    m = {"title": page["title"], "url": info["descriptionurl"],
         "license": ext.get("LicenseShortName", {}).get("value", ""), "artist": ext.get("Artist", {}).get("value", "")}
    meta.write_text(json.dumps(m, ensure_ascii=False, indent=1))
    return m


def ask(image: Path, said: str | None) -> dict:
    b64 = base64.b64encode(image.read_bytes()).decode()
    if said:
        prompt = f"My grandmother pointed at this plant and said: \"{said}\". Identify the plant species."
    else:
        prompt = "Identify the plant species in this photo."
    body = {"model": MODEL, "stream": False, "think": False, "format": SCHEMA, "options": {"temperature": 0, "num_ctx": 4096},
            "messages": [{"role": "user", "content": prompt + " Reply as JSON.", "images": [b64]}]}
    r = httpx.post(f"{ollama_host()}/api/chat", json=body, timeout=300)
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])


def _binomial(name: str) -> list[str]:
    return name.lower().replace("×", "").replace("*", "").replace(" x ", " ").split()[:2]


def correct(answer: str, accepted: list[str]) -> bool:
    return any(_binomial(answer) == _binomial(acc) for acc in accepted)


def genus_ok(answer: str, accepted: list[str]) -> bool:
    a = _binomial(answer)
    return bool(a) and any(a[0] == _binomial(acc)[0] for acc in accepted)


CONDITIONS = ["photo_only", "with_nani", "pipeline"]


def main() -> None:
    here = Path(__file__).parent
    imgs = here / "images"
    imgs.mkdir(exist_ok=True)
    rows = []
    for hi, accepted, query in PLANTS:
        path = imgs / f"{accepted[0].replace(' ', '_')}.jpg"
        meta = fetch(query, path)
        t0 = time.time()
        a = ask(path, None)
        b = ask(path, f"ये {hi} है।")
        # What fieldguide actually does: the same call, then a text-only name lookup.
        looked_up = botanical_name(hi, b.get("english_name", ""), MODEL) if b.get("english_name") else None
        c = {**b, "scientific_name": looked_up or b["scientific_name"]}
        row = {"hindi": hi, "truth": accepted[0], "photo": meta}
        for cond, ans in zip(CONDITIONS, [a, b, c]):
            row[cond] = ans
            row[cond + "_ok"] = correct(ans["scientific_name"], accepted)
            row[cond + "_genus_ok"] = genus_ok(ans["scientific_name"], accepted)
        rows.append(row)
        marks = "   ".join(f"{cond}: {row[cond]['scientific_name'][:26]:<26} {'✓' if row[cond + '_ok'] else ('~' if row[cond + '_genus_ok'] else '✗')}" for cond in CONDITIONS)
        print(f"{hi:<10} {accepted[0]:<24} {marks}  ({time.time() - t0:.0f}s)", flush=True)
    n = len(rows)
    summary = {cond: {"species": sum(r[cond + "_ok"] for r in rows), "genus": sum(r[cond + "_genus_ok"] for r in rows)} for cond in CONDITIONS}
    print(f"\n{MODEL} (n={n}, species / genus correct)")
    for cond, s in summary.items():
        print(f"  {cond:<11} {s['species']:2d}/{n}   {s['genus']:2d}/{n}")
    (here / f"results-{MODEL.replace(":", "_")}.json").write_text(json.dumps({"model": MODEL, "n": n, "summary": summary, "rows": rows}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
