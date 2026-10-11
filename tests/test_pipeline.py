from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from fieldguide import align, gemma, media, transcribe
from fieldguide.media import LOCAL_TZ, Photo, Recording
from fieldguide.transcribe import Segment

T0 = datetime(2026, 10, 11, 17, 15, 0, tzinfo=LOCAL_TZ)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def photo(seconds: float, name: str = "") -> Photo:
    return Photo(Path(name or f"p{seconds}.jpg"), at(seconds), "exif")


def test_stamp_from_name_local_and_pixel_utc():
    assert media.stamp_from_name("Recording_20261011_171503.m4a") == datetime(2026, 10, 11, 17, 15, 3, tzinfo=LOCAL_TZ)
    assert media.stamp_from_name("IMG_20261011_171622.jpg").minute == 16
    pixel = media.stamp_from_name("PXL_20261011_114530123.jpg")
    assert pixel.utcoffset() == LOCAL_TZ.utcoffset(None) or pixel.tzinfo is not None
    assert pixel.astimezone(LOCAL_TZ) == datetime(2026, 10, 11, 11, 45, 30, tzinfo=media.timezone.utc).astimezone(LOCAL_TZ)
    assert media.stamp_from_name("Voice 001.m4a") is None


def test_recording_stamped_at_its_end_is_shifted_back():
    rec = Recording(Path("Voice 001.m4a"), at(600), 600, "audio metadata")
    notes = media.fix_start_times([rec], [photo(60), photo(200), photo(420)])
    assert notes and rec.started_at == at(0)


def test_recording_with_correct_start_is_left_alone():
    rec = Recording(Path("Recording_20261011_171500.m4a"), at(0), 600, "filename")
    assert media.fix_start_times([rec], [photo(60), photo(200), photo(420)]) == []
    assert rec.started_at == at(0)


def test_photos_close_in_time_are_one_stop():
    groups = align.group_photos([photo(30), photo(40), photo(128), photo(208)])
    assert [len(g) for g in groups] == [2, 1, 1]


def test_speech_goes_to_the_nearest_stop():
    rec = Recording(Path("walk.m4a"), T0, 260, "filename")
    segs = [
        Segment(25, 38, "ये नीम का पेड़ है।"),
        Segment(120, 133, "ये पीपल है।"),
        Segment(200, 210, "ये गुड़हल का फूल है।"),
    ]
    stops = align.build_stops([photo(30), photo(40), photo(128), photo(208)], [rec], [segs])
    assert [s.text for s in stops] == ["ये नीम का पेड़ है।", "ये पीपल है।", "ये गुड़हल का फूल है।"]
    assert stops[1].clip == (0, 119.6, 133.4)


def test_utterances_split_at_pauses_and_sentence_ends():
    W = lambda w, s, e: SimpleNamespace(word=w, start=s, end=e)  # noqa: E731
    words = [W(" ये", 0, 0.3), W(" नीम", 0.3, 0.6), W(" है।", 0.6, 0.9), W(" दातुन", 1.0, 1.4), W(" करते", 3.0, 3.3), W(" थे", 3.3, 3.6)]
    utts = transcribe._utterances(words)
    assert [u.text for u in utts] == ["ये नीम है।", "दातुन", "करते थे"]


def test_grounding_keeps_corrections_and_drops_inventions():
    raw = "ये नीन का पेड है, बेता, इसकी टहनी से हम दातुं करते थे।"
    cleaned = "ये नीम का पेड़ है, बेटा, इसकी टहनी से हम दातुन करते थे। नीम की पत्तियाँ बुखार में भी दी जाती थीं।"
    kept, dropped = gemma.keep_grounded(cleaned, raw)
    assert dropped == 1
    assert "बुखार" not in kept and "दातुन" in kept


def test_lookup_repairs_but_does_not_swap_genus():
    assert gemma.prefer_name("Hibiscus rosa-hihibiscus", "Hibiscus rosa-sinensis") == "Hibiscus rosa-sinensis"
    assert gemma.prefer_name("Murraya paniculata", "Murraya koenigii") == "Murraya koenigii"
    assert gemma.prefer_name("Tagetes spp.", "Tagetes erecta") == "Tagetes erecta"
    assert gemma.prefer_name("Hibiscus", "Hibiscus rosa-sinensis") == "Hibiscus rosa-sinensis"
    assert gemma.prefer_name("Catharanthus roseus", "Vinca minor") == "Catharanthus roseus"
    assert gemma.prefer_name("Azadirachta indica", None) == "Azadirachta indica"


def test_binomial_lookup_parsing():
    assert gemma.pick_binomial("Hibiscus rosa-sinensis") == "Hibiscus rosa-sinensis"
    assert gemma.pick_binomial("The binomial scientific name for gudhal is **Hibiscus rosa-sinensis**.") == "Hibiscus rosa-sinensis"
    assert gemma.pick_binomial("The scientific name is Azadirachta indica.") == "Azadirachta indica"
    assert gemma.pick_binomial("I am not sure.") is None
