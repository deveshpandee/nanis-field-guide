"""Turn one stop (photos + what was said) into a field-guide entry with a local Gemma.

The elder is the authority. Gemma files what they said, puts a botanical name
next to it, and translates. Small models do better with small jobs, so an entry
is a handful of short calls: clean the transcript, identify the plant (and look its
binomial up again as text), translate, pull out what was taught, suggest questions.
Every sentence Gemma keeps is checked against the recording's transcript, so
nothing is put in the elder's mouth.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
from difflib import SequenceMatcher

import httpx

from .align import Stop
from .media import load_image

DEFAULT_MODEL = "gemma4:e4b-it-qat"
KIN = "नानी = Nani (mother's mother), नाना = Nana (mother's father), दादी = Dadi (father's mother), दादा = Dada (father's father), बेटा/बिटिया = dear child"


def ollama_host() -> str:
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
    return host if host.startswith("http") else f"http://{host}"


def _chat(model: str, system: str, user: str, images: list[str] | None = None, schema: dict | None = None, temperature: float = 0.2):
    msg = {"role": "user", "content": user}
    if images:
        msg["images"] = images
    body = {"model": model, "stream": False, "think": False, "options": {"temperature": temperature, "num_ctx": 8192},
            "messages": [{"role": "system", "content": system}, msg]}
    if schema:
        body["format"] = schema
    r = httpx.post(f"{ollama_host()}/api/chat", json=body, timeout=600)
    r.raise_for_status()
    content = r.json()["message"]["content"].strip()
    return json.loads(content) if schema else content


def _image_b64(path) -> str:
    im = load_image(path, 896)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


# --- keeping Gemma honest ---------------------------------------------------

def _words(s: str) -> list[str]:
    return re.findall(r"[\wऀ-ॿ]+", s.lower())


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[।.!?॥])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def grounded(sentence: str, transcript: str) -> float:
    """Share of the sentence's words that the transcript actually contains, in order."""
    a, b = _words(sentence), _words(transcript)
    if not a:
        return 0.0
    matched = sum(m.size for m in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
    return matched / len(a)


def keep_grounded(cleaned: str, transcript: str, threshold: float = 0.6) -> tuple[str, int]:
    """Drop any sentence the cleaner made up; return the rest and how many were dropped.
    Corrections of single misheard words pass."""
    kept, dropped = [], 0
    for s in _sentences(cleaned):
        if grounded(s, transcript) >= threshold:
            kept.append(s)
        else:
            dropped += 1
    return " ".join(kept), dropped


# --- the small jobs ---------------------------------------------------------

CLEAN = """You correct automatic Hindi speech transcripts recorded on a walk with a grandparent.
1. Fix words the speech recognizer misheard, using the context of plants and village life (for example अमरुत → अमरूद, पत्ति → पत्ती, करते ते → करते थे).
2. Remove sentences that are not about the plant they are standing at, like "let's go this way" or "did you bring water?".
3. Keep every sentence about the plant, word for word. Never add words or new sentences.
Reply with the corrected Hindi only. If nothing is about the plant, reply with an empty line."""

TRANSLATE = f"""Translate what a grandparent said in Hindi into plain, warm English.
Keep Hindi plant names and kinship words as they are: {KIN}.
Reply with the English translation only."""

IDENTIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "local_name": {"type": "string", "description": "Only the plant's name as the elder said it, in Devanagari, e.g. नीम (not नीम का पेड़). Empty if not named."},
        "local_name_roman": {"type": "string", "description": "local_name in Latin letters, e.g. Neem"},
        "scientific_name": {"type": "string", "description": "Genus and species"},
        "english_name": {"type": "string", "description": "The usual English name of that species, e.g. Ficus religiosa: Sacred fig"},
        "id_confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "id_basis": {"type": "string", "description": "One sentence: the name the elder used and what in the photo agrees or disagrees."},
    },
    "required": ["local_name", "local_name_roman", "english_name", "scientific_name", "id_confidence", "id_basis"],
}

IDENTIFY = """You identify plants for a family field guide made on a walk in India.
The grandparent is the authority on the name. Use the name they said to identify the species, and use the photo to check it.
id_confidence: high when they named it and the photo agrees; medium when the photo is unclear or the name has several possible species; low when they did not name it or the photo disagrees."""

NOTES_SCHEMA = {
    "type": "object",
    "properties": {
        "teachings": {"type": "array", "items": {"type": "string"}, "description": "Each use, custom or fact the grandparent taught, as a short English line."},
        "memory": {"type": "string", "description": "Any memory or family story (childhood, the village, a relative's saying), retold in one or two English sentences. Empty if none."},
        "family_remedy": {"type": "boolean", "description": "True if they described using it for health, teeth, hair, skin or illness."},
    },
    "required": ["teachings", "memory", "family_remedy"],
}

NOTES = f"""You write the notes section of a family field guide from what a grandparent said about one plant.
- teachings: only uses, customs and facts the grandparent actually said, rewritten as short English lines, e.g. "The twigs were used as a toothbrush (datun)." Skip the sentence that just names the plant. Never add your own knowledge.
- memory: a personal or family memory they shared, in English, in the third person ("{{elder}} remembers..."). Empty if none.
- family_remedy: true if any use for the body or health was mentioned.
Kinship words: {KIN}."""


QUESTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {"type": "object", "properties": {"hi": {"type": "string"}, "en": {"type": "string"}}, "required": ["hi", "en"]},
        }
    },
    "required": ["questions"],
}

QUESTIONS = """A grandchild is making a field guide from walks with their grandparent.
Suggest two questions the grandchild can ask on the next walk, about things the grandparent mentioned but did not fully explain.
Write each question in simple spoken Hindi (Devanagari script) as "hi", with its English translation as "en".

Example. The grandparent said: "We put tulsi leaves in tea when someone had a cold."
{"questions": [{"hi": "तुलसी वाली चाय में और क्या-क्या डालते थे?", "en": "What else did you put in the tulsi tea?"}, {"hi": "ये नुस्खा आपको किसने सिखाया था?", "en": "Who taught you this remedy?"}]}"""

BODY_WORDS = re.compile(r"दाँत|दांत|बाल|खाँसी|खांसी|बुखार|दवा|घाव|पेट|त्वचा|सर्दी|जुकाम|चोट|teeth|tooth|hair|cough|fever|medicine|wound|stomach|skin|cold|heal", re.I)
NAME_TAIL = re.compile(r"\s+(का|की|के)\s+(पेड़|पेड़|पेड|फूल|पौधा|पौधे|बेल|पत्ता|पत्ती|झाड़)$")
ROMAN_TAIL = re.compile(r"\s+(tree|plant|flower|ka ped|ki bel|ka phool|ka paudha)$", re.I)


BINOMIAL = re.compile(r"\b([A-Z][a-z]+ (?:× ?)?[a-z]+(?:-[a-z]+)?)\b")
NOT_LATIN = {"the", "this", "it", "its", "a", "an", "is", "of", "scientific", "botanical", "binomial", "answer", "name", "plant", "common", "genus", "species"}


def pick_binomial(reply: str) -> str | None:
    """'Hibiscus rosa-sinensis' out of a reply like 'The binomial is **Hibiscus rosa-sinensis**.'"""
    emphasised = re.findall(r"\*{1,2}([^*]+)\*{1,2}", reply)
    for chunk in emphasised + [reply.replace("*", "")]:
        for m in BINOMIAL.finditer(chunk):
            words = m.group(1).lower().split()
            if words[0] not in NOT_LATIN and words[-1] not in NOT_LATIN:
                return m.group(1)
    return None


def botanical_name(local: str, english: str, model: str) -> str | None:
    """Look the name up again as plain text. With a photo and a JSON schema in play,
    the small model sometimes garbles a binomial it knows perfectly well."""
    named = f"{english} ({local})" if local else english
    reply = _chat(model, "You are a botanist.", f"What is the scientific name of the {named} plant? Reply with only the genus and species.", temperature=0.0)
    return pick_binomial(reply)


def questions(hindi: str, english: str, model: str) -> list[dict]:
    out = _chat(model, QUESTIONS, f'The grandparent said: "{hindi}"\n(In English: "{english}")', schema=QUESTIONS_SCHEMA, temperature=0.4)
    qs = [q for q in out.get("questions", []) if re.search(r"[\u0900-\u097F]", q.get("hi", "")) and len(q.get("en", "")) > 12]
    return qs[:2]


def clean(transcript: str, model: str) -> str:
    return _chat(model, CLEAN, transcript, temperature=0.1)


def translate(hindi: str, model: str = DEFAULT_MODEL) -> str:
    return _chat(model, TRANSLATE, hindi, temperature=0.1)


def identify(images: list[str], hindi: str, model: str) -> dict:
    said = hindi or "(they did not say anything about it)"
    return _chat(model, IDENTIFY, f"What the grandparent said here:\n{said}\n\nIdentify the plant in the photo.", images, IDENTIFY_SCHEMA, temperature=0.0)


def notes(english: str, hindi: str, elder: str, model: str) -> dict:
    user = f"What {elder} said (Hindi):\n{hindi}\n\nIn English:\n{english}"
    return _chat(model, NOTES.replace("{elder}", elder), user, schema=NOTES_SCHEMA)


def write_entry(stop: Stop, elder: str = "Nani", model: str = DEFAULT_MODEL) -> dict:
    images = [_image_b64(p.path) for p in stop.photos[:2]]
    raw = stop.text
    hindi, dropped = "", 0
    if raw:
        hindi, dropped = keep_grounded(clean(raw, model), raw)
        if not hindi:
            # The cleaner threw everything away; fall back to the recording's own words.
            hindi = raw
    entry = identify(images, hindi, model)
    entry["local_name"] = NAME_TAIL.sub("", entry.get("local_name", "").strip())
    entry["local_name_roman"] = ROMAN_TAIL.sub("", entry.get("local_name_roman", "").strip())
    if entry.get("english_name") and entry.get("id_confidence") != "low":
        looked_up = botanical_name(entry["local_name"], entry["english_name"], model)
        if looked_up and looked_up.lower() != entry.get("scientific_name", "").lower():
            entry["scientific_name_draft"], entry["scientific_name"] = entry.get("scientific_name", ""), looked_up
    entry["transcript_raw"] = raw
    entry["quote_hi"] = hindi
    entry["quote_dropped"] = dropped
    entry["quote_en"] = translate(hindi, model) if hindi else ""
    if hindi:
        entry.update(notes(entry["quote_en"], hindi, elder, model))
        memory = entry.get("memory", "").strip()
        if len(memory) < 25 or memory.endswith(("...", "…")):
            entry["memory"] = ""
        entry["family_remedy"] = bool(entry.get("family_remedy")) or bool(BODY_WORDS.search(hindi + " " + entry["quote_en"]))
        entry["ask_next_time"] = questions(hindi, entry["quote_en"], model)
    else:
        entry.update({"teachings": [], "memory": "", "family_remedy": False, "ask_next_time": []})
    return entry
