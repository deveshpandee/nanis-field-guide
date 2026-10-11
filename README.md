# नानी की किताब · Nani's Field Guide

Take your grandparent for a walk. Let them point at the plants they know and tell you what they're called, what they were used for, and what they remember. Keep your phone in your pocket, recording.

When you get home, this turns the walk into a printable, bilingual family field guide: one page per plant, with your photo, their words in Hindi with an English translation, what they taught you, a clip of their voice, and questions to ask on your next walk.

Everything runs on your own laptop with open-weight models (Whisper and Gemma 4). No audio, photo or transcript leaves the house.

<!-- screenshot: docs/booklet.png -->

## Why

The people who know the local names of the plants, how to use neem twigs as a toothbrush, and when the peepal gets worshipped are getting old. Most of that knowledge was never written down, and it isn't in any plant-ID app. This is a reason to go outside together, and a way to keep what they tell you.

## How it works

```
phone (in your pocket)            laptop (offline)
──────────────────────            ─────────────────────────────────────────────────────────
voice recorder: one long   ──►  Whisper large-v3-turbo ── word timestamps ──┐
recording of the walk           (Hindi, CPU)                                 │
                                                                             ▼
camera: 1–3 photos per     ──►  EXIF time + GPS ──► group photos into stops, attach the
plant they talk about                               words spoken around each stop
                                                                             │
                                                                             ▼
                                Gemma 4 (Ollama), five small jobs per stop:
                                  1. clean    fix misheard words, drop small talk
                                  2. identify name they said + photo → species
                                  3. translate Hindi → English, kinship words kept
                                  4. notes    what they taught, a memory, remedies
                                  5. ask      two questions for the next walk
                                Every quoted sentence is checked against the
                                transcript; anything the model invented is dropped.
                                                                             │
                                                                             ▼
                                booklet/index.html: A5 pages, print or save as PDF,
                                each plant's audio clip only (not the whole walk),
                                photos re-encoded without EXIF/GPS
```

The elder is the classifier; Gemma is the librarian. A 4B model is unreliable at naming a plant from a photo alone. Given the one word your grandmother says while pointing at it, it gets the species right almost every time (see [eval](#does-the-elders-word-help)).

## Quickstart

You need [Ollama](https://ollama.com) 0.40 or newer and [uv](https://docs.astral.sh/uv/).

```sh
ollama pull gemma4:e4b-it-qat       # or gemma4:e2b-it-qat on smaller machines
git clone https://github.com/deveshpandee/nanis-field-guide && cd nanis-field-guide
uv sync
```

Do a walk ([WALK_GUIDE.md](WALK_GUIDE.md) has tips and good questions to ask), then copy the original photos and recording into a folder:

```sh
uv run fieldguide init walks/2026-10-11      # writes walk.toml: who, where, title
uv run fieldguide check walks/2026-10-11     # shows which words landed on which photo
uv run fieldguide process walks/2026-10-11   # transcribe, write entries, render
xdg-open walks/2026-10-11/booklet/index.html # print → A5 → save as PDF
```

Got something wrong? Sit with them, read the booklet together, fix `walks/…/.fieldguide/entries.json`, set `"edited": true` on that stop, and run `fieldguide render`. Edited stops are never overwritten.

If the photos and the speech don't line up, the recording's start time is off (some recorders don't put it in the filename). Set `audio_start` in `walk.toml`.

## Hardware

Built and tested on a 2020 gaming laptop: GTX 1650 with 4 GB VRAM, 14 GB RAM.

| step | model | time |
|---|---|---|
| transcribe 4 min of Hindi | Whisper large-v3-turbo, int8, CPU | 55 s |
| one plant entry | Gemma 4 E4B (QAT), GPU + CPU | ~35 s |
| one plant entry | Gemma 4 E2B (QAT), GPU | ~15 s |

E4B is noticeably better at Hindi: it fixes more misheard words and translates idioms correctly. E2B is fine if you're short on memory.

## Does the elder's word help?

`eval/photo_vs_nani.py` asks Gemma for the species of 12 common Indian plants (neem, peepal, banyan, tulsi, gudhal, mango, guava, curry leaf, sadabahar, marigold, mehndi, aparajita) three ways, each with one Wikimedia Commons photo:

1. **photo only**: "Identify the plant species in this photo."
2. **photo + elder**: the same photo, plus what a grandparent says while pointing at it ("ये नीम है।")
3. **pipeline**: what fieldguide does, i.e. (2) followed by a text-only lookup of the binomial

Species correct, out of 12 (genus correct in brackets):

| model | photo only | photo + elder | pipeline |
|---|---|---|---|
| Gemma 4 E2B | 2 (2) | 8 (10) | **10** (10) |
| Gemma 4 E4B | 2 (3) | 10 (12) | **11** (12) |

The lookup is only allowed to repair a draft: genus-only answers ("Tagetes spp." → *Tagetes erecta*) and same-genus fixes (*Murraya paniculata* → *Murraya koenigii*). A lookup that changes the genus is ignored, because it tends to pick the wrong look-alike (*Vinca minor* for sadabahar). E4B's one pipeline miss is a truncated epithet ("Clitoria ternate").

The photo-only answers are mostly confident and wrong: mango came back as *Ficus religiosa*, aparajita as a columbine, marigold as a gladiolus. With the elder's word, E2B's remaining misses were peepal (*Butea monosperma*, misled by a red young leaf) and sadabahar (*Vinca minor*, the wrong periwinkle). Twelve photos is a small test, but the direction is not subtle.

Run it yourself: `uv run python eval/photo_vs_nani.py gemma4:e4b-it-qat`.

## Privacy

- Nothing is uploaded. Whisper and Gemma run locally; the only network use is downloading the models once (and Google Fonts when you open the booklet).
- The booklet contains only the seconds of audio that belong to each plant, not the whole walk.
- Exported photos are re-encoded without EXIF, so no GPS coordinates or phone details end up in a shared booklet. The route page draws the shape of the walk with no map and no coordinates.
- Ask before you record. If they'd rather not be recorded, walk anyway and take photos.

## Credits

Whisper (MIT) via [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Gemma 4](https://ai.google.dev/gemma) (Gemma Terms of Use) via [Ollama](https://ollama.com), Fraunces, Kalam and Tiro Devanagari Hindi fonts (OFL). Code is MIT licensed.
