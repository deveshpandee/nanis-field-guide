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
from fieldguide.gemma import DEFAULT_MODEL, ollama_host  # noqa: E402

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
    body = {"model": DEFAULT_MODEL, "stream": False, "think": False, "format": SCHEMA, "options": {"temperature": 0, "num_ctx": 4096},
            "messages": [{"role": "user", "content": prompt + " Reply as JSON.", "images": [b64]}]}
    r = httpx.post(f"{ollama_host()}/api/chat", json=body, timeout=300)
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])


def correct(answer: str, accepted: list[str]) -> bool:
    a = " ".join(answer.lower().replace("×", "").replace("x ", "").split()[:2])
    return any(a == " ".join(acc.replace("×", "").split()[:2]) for acc in accepted)


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
        row = {"hindi": hi, "truth": accepted[0], "photo": meta,
               "photo_only": a, "photo_only_ok": correct(a["scientific_name"], accepted),
               "with_nani": b, "with_nani_ok": correct(b["scientific_name"], accepted)}
        rows.append(row)
        print(f"{hi:<10} {accepted[0]:<24} photo only: {a['scientific_name']:<28} {'✓' if row['photo_only_ok'] else '✗'}   "
              f"with Nani: {b['scientific_name']:<26} {'✓' if row['with_nani_ok'] else '✗'}  ({time.time() - t0:.0f}s)")
    n = len(rows)
    po, wn = sum(r["photo_only_ok"] for r in rows), sum(r["with_nani_ok"] for r in rows)
    print(f"\n{DEFAULT_MODEL}: photo only {po}/{n}, photo + Nani's word {wn}/{n}")
    (here / "results.json").write_text(json.dumps({"model": DEFAULT_MODEL, "photo_only": po, "with_nani": wn, "n": n, "rows": rows}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
