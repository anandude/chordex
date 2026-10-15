"""
Tests for the Phase 1–5 lyrics pipeline. All heavy backends are optional:
tests exercise pure logic plus graceful-fallback paths, so they pass on a
bare checkout (demucs/audio-separator/transformers/aligner NOT required).
"""

import json
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND.parent / "eval"))


# ── config ────────────────────────────────────────────────────────────────

def test_config_defaults_and_routing(monkeypatch):
    from pipeline.config import LyricsConfig

    for var in ("LYRICS_SEPARATION_BACKEND", "WHISPER_MODEL_OVERRIDES",
                "SEPARATE_VOCALS", "LYRICS_LRCLIB", "LYRICS_ALIGNMENT",
                "LYRICS_LLM_CLEANUP"):
        monkeypatch.delenv(var, raising=False)
    cfg = LyricsConfig.from_env()
    assert cfg.separation_backend == "demucs"
    assert cfg.demucs_model == "htdemucs"
    assert cfg.asr_model_for("ml") == "adalat-ai/whisper-medium-ml-rmft"
    assert cfg.asr_model_for("hi") == "adalat-ai/whisper-medium-hi-high-lr"
    assert cfg.asr_model_for(None) == "small"
    assert cfg.lrclib_enabled and cfg.alignment_enabled
    assert not cfg.llm_cleanup_enabled
    assert "sep=demucs" in cfg.describe()


def test_config_env_overrides_win(monkeypatch):
    from pipeline.config import LyricsConfig

    monkeypatch.setenv("LYRICS_SEPARATION_BACKEND", "roformer")
    monkeypatch.setenv("SEPARATE_VOCALS", "0")  # legacy kill-switch wins
    assert LyricsConfig.from_env().separation_backend == "none"
    monkeypatch.setenv("SEPARATE_VOCALS", "1")
    monkeypatch.setenv("WHISPER_MODEL_OVERRIDES", '{"ml": "tiny"}')
    assert LyricsConfig.from_env().asr_model_for("ml") == "tiny"


# ── cache ─────────────────────────────────────────────────────────────────

def test_cache_roundtrip_and_ttl(tmp_path):
    from pipeline import cache

    f = tmp_path / "a.wav"
    f.write_bytes(b"\0" * 100 + b"audio-bytes")
    p = cache.stage_cache_path(tmp_path, "sep", f, "demucs", "v1", ext=".wav")
    assert p.parent.exists()
    payload = {"words": [{"word": "ഹലോ"}]}
    jp = cache.stage_cache_path(tmp_path, "asr", f, "m", ext=".json")
    cache.write_json(jp, payload)
    assert cache.read_json(jp) == payload
    assert cache.read_json(jp, max_age_s=0) == payload
    import time

    old = time.time() - 100
    import os

    os.utime(jp, (old, old))
    assert cache.read_json(jp, max_age_s=10) is None
    assert cache.content_hash(f) == cache.content_hash(f)


# ── Phase 2: lookup ───────────────────────────────────────────────────────

def test_lrc_parse_and_even_split():
    from pipeline.lyrics_lookup import parse_synced_lyrics, words_even_split

    lines = parse_synced_lyrics("[00:27.93] hello world\n[00:31.10] second line\n")
    assert len(lines) == 2
    assert abs(lines[0]["timestamp"] - 27.93) < 1e-6
    assert lines[0]["end"] == lines[1]["timestamp"]
    assert lines[0]["text"] == "hello world"
    words = words_even_split(lines)
    assert [w["word"] for w in words] == ["hello", "world", "second", "line"]
    assert all(w["end"] > w["timestamp"] for w in words)


def test_lookup_match_validation():
    from pipeline.lyrics_lookup import _accept

    good = {"trackName": "Song", "artistName": "Singer", "duration": 200.0,
            "instrumental": False, "plainLyrics": "la la"}
    meta = {"title": "Song", "artist": "Singer"}
    assert _accept(good, meta, 201.0)
    assert not _accept({**good, "instrumental": True}, meta, 201.0)
    assert not _accept(good, meta, 220.0)  # duration ±3 s
    assert not _accept(good, {"title": "Totally Different Name Here", "artist": "X"},
                       201.0)  # wrong-song reject
    assert not _accept({"trackName": "Song", "duration": 200.0}, meta, 201.0)  # no lyrics


def test_metadata_filename_heuristics(tmp_path):
    from pipeline.lyrics_lookup import get_metadata

    m = get_metadata(tmp_path / "A. Rahman - Munbe Vaa.mp3")
    assert m["artist"] == "A. Rahman" and m["title"] == "Munbe Vaa"
    m2 = get_metadata(tmp_path / "Kesariya (Brahmastra).mp3")
    assert m2["title"] == "Kesariya" and m2["album"] == "Brahmastra"
    m3 = get_metadata(tmp_path / "x.mp3", title_hint="T", artist_hint="A")
    assert (m3["title"], m3["artist"]) == ("T", "A")  # UI hints win


# ── Phase 3: asr helpers ──────────────────────────────────────────────────

def test_seam_dedupe_and_repeat_loops():
    from pipeline.asr import _dedupe_seams, _drop_repeat_loops

    words = [
        {"timestamp": 0.0, "end": 1.0, "word": "a"},
        {"timestamp": 0.5, "end": 1.5, "word": "a"},  # seam re-decode
        {"timestamp": 1.5, "end": 2.0, "word": "b"},
    ]
    assert [w["word"] for w in _dedupe_seams(words, 2.0)] == ["a", "b"]
    loop = [{"timestamp": float(i), "end": float(i + 1), "word": w}
            for i, w in enumerate("x y z w ".split() * 1 + ["la"] * 8 + ["end"])]
    deduped = _drop_repeat_loops(loop)
    assert len(deduped) < len(loop)
    assert deduped[-1]["word"] == "end"


# ── HF download plumbing ──────────────────────────────────────────────────

def test_xet_is_disabled_unless_explicitly_opted_in(monkeypatch):
    """hf-xet 1.5.x stalls on some networks (measured here: 17 KB written in
    40 s, vs 20 MB in 40 s without it). A stalled transfer never raises — it
    just never finishes, which made a first-run ASR job look hung until RQ
    killed it at job_timeout + 60 s."""
    from pipeline import hf_setup

    monkeypatch.delenv("HF_HUB_DISABLE_XET", raising=False)
    assert hf_setup.disable_xet() is True
    assert os.environ["HF_HUB_DISABLE_XET"] == "1"

    monkeypatch.setenv("HF_HUB_DISABLE_XET", "0")  # opt back in after an upgrade
    assert hf_setup.disable_xet() is False
    assert os.environ["HF_HUB_DISABLE_XET"] == "0"


def test_repo_cache_state_flags_partial_downloads(tmp_path, monkeypatch):
    """A killed download leaves config.json + a `*.incomplete` blob behind, and
    `snapshot_download(local_files_only=True)` still reports success for that
    state — which made prewarm think the big models were already cached."""
    from pipeline import hf_setup

    monkeypatch.setattr(hf_setup, "hf_cache_dir", lambda: tmp_path)
    repo_id = "adalat-ai/whisper-medium-hi-high-lr"
    repo = tmp_path / ("models--" + repo_id.replace("/", "--"))
    (repo / "blobs").mkdir(parents=True)
    (repo / "snapshots" / "rev").mkdir(parents=True)
    (repo / "blobs" / "etag.1234.incomplete").write_bytes(b"x" * 100)
    assert hf_setup.repo_cache_state(repo_id) == (False, 100.0)

    (repo / "blobs" / "etag.1234.incomplete").unlink()
    (repo / "blobs" / "etag").write_bytes(b"y" * 2000)
    (repo / "snapshots" / "rev" / "model.safetensors").write_bytes(b"y" * 2000)
    assert hf_setup.repo_cache_state(repo_id) == (True, 2000.0)

    assert hf_setup.repo_cache_state("nobody/nothing") == (False, 0.0)


def test_asr_announces_download_vs_load(monkeypatch):
    from pipeline import asr

    events: list[tuple[str, float]] = []
    monkeypatch.setattr(asr, "repo_cache_state", lambda repo: (False, 0.0))
    asr._announce_model("adalat-ai/whisper-medium-hi-high-lr",
                        lambda stage, pct: events.append((stage, pct)))
    assert events and events[-1][0] == "downloading_model"

    events.clear()
    monkeypatch.setattr(asr, "repo_cache_state", lambda repo: (True, 1.5e9))
    asr._announce_model("adalat-ai/whisper-medium-hi-high-lr",
                        lambda stage, pct: events.append((stage, pct)))
    assert events and events[-1][0] == "loading_model"

    # stock CTranslate2 names resolve to the repo faster-whisper itself uses
    assert asr.fw_repo("small") == "Systran/faster-whisper-small"
    assert asr.fw_repo("org/model") == "org/model"


def test_transcribe_asr_reports_model_and_chunk_progress(tmp_path, monkeypatch):
    import numpy as np

    from pipeline import asr
    from pipeline.config import LyricsConfig

    monkeypatch.setattr(asr, "repo_cache_state", lambda repo: (True, 1.0))

    def fake_hf(y, lang, model, cfg, on_progress=None):
        on_progress(0.5)
        on_progress(1.0)
        return (
            [{"timestamp": 0.0, "end": 1.0, "word": "la"}],
            [{"timestamp": 0.0, "end": 1.0, "text": "la"}],
            "hi",
        )

    monkeypatch.setattr(asr, "_transcribe_hf", fake_hf)
    events: list[tuple[str, float]] = []
    out = asr.transcribe_asr(
        tmp_path / "vocals.wav", language="hi",
        cfg=LyricsConfig(whisper_model="small", cache_dir=str(tmp_path)),
        progress=lambda stage, pct: events.append((stage, pct)),
        audio=np.zeros(16000, dtype=np.float32),
    )

    assert [s for s, _ in events] == ["loading_model", "transcribing",
                                      "transcribing", "transcribing"]
    assert events[-1][1] == 0.78  # hands the 0.8 alignment band back on time
    assert out["model"] == "adalat-ai/whisper-medium-hi-high-lr"
    assert out["lines"][0]["text"] == "la"


def test_auto_language_is_detected_before_model_routing(tmp_path, monkeypatch):
    """A1: with no hint, LID runs first so hi/ml get their fine-tunes (the old
    flow routed 'auto' to the default model and the Indic models never ran)."""
    import numpy as np

    from pipeline import asr
    from pipeline.config import LyricsConfig

    monkeypatch.setattr(asr, "repo_cache_state", lambda repo: (True, 1.0))
    monkeypatch.setattr(asr, "detect_language", lambda y, cfg: ("ml", 0.7))
    seen = {}

    def fake_hf(y, lang, model, cfg, on_progress=None):
        seen["model"], seen["lang"] = model, lang
        return [], [], lang

    monkeypatch.setattr(asr, "_transcribe_hf", fake_hf)
    out = asr.transcribe_asr(
        tmp_path / "v.wav", language=None,
        cfg=LyricsConfig(whisper_model="small", cache_dir=str(tmp_path)),
        audio=np.zeros(16000, dtype=np.float32),
    )
    assert seen == {"model": "adalat-ai/whisper-medium-ml-rmft", "lang": "ml"}
    assert out["language"] == "ml" and out["language_prob"] == 0.7


def test_pick_language_biases_toward_candidates():
    from pipeline.asr import pick_language

    cands = ("hi", "ml", "en")
    # Malayalam singing misread as Tamil → best candidate wins
    probs = [("ta", 0.55), ("ml", 0.30), ("hi", 0.05)]
    assert pick_language("ta", 0.55, probs, cands) == ("ml", 0.30)
    # Whisper very sure about a non-candidate → keep it
    probs = [("es", 0.95), ("en", 0.02)]
    assert pick_language("es", 0.95, probs, cands) == ("es", 0.95)
    # candidate detected → untouched
    assert pick_language("hi", 0.6, [("hi", 0.6)], cands) == ("hi", 0.6)
    # no candidates configured → raw Whisper answer
    assert pick_language("ta", 0.5, probs, ()) == ("ta", 0.5)


def test_job_timeout_covers_first_run_downloads(monkeypatch):
    """RQ SIGKILLs the work horse once a job runs past job_timeout + 60 s. The
    old 1800 s deadline meant every first run in a new language died mid
    model-download with "Work-horse terminated unexpectedly"."""
    import main

    monkeypatch.delenv("JOB_TIMEOUT_S", raising=False)
    assert main._job_timeout() == 7200

    monkeypatch.setenv("JOB_TIMEOUT_S", "3600")
    assert main._job_timeout() == 3600

    monkeypatch.setenv("JOB_TIMEOUT_S", "not-a-number")
    assert main._job_timeout() == 7200


# ── Phase 1: separation fallbacks ─────────────────────────────────────────

def test_separation_backend_none_passthrough(tmp_path):
    from pipeline.config import LyricsConfig
    from pipeline.separation import separate_vocals

    f = tmp_path / "song.wav"
    f.write_bytes(b"fake")
    cfg = LyricsConfig(separation_backend="none")
    assert separate_vocals(f, cfg=cfg) == f


def test_separation_unknown_backend_falls_back(tmp_path):
    from pipeline.config import LyricsConfig
    from pipeline.separation import separate_vocals

    f = tmp_path / "song.wav"
    f.write_bytes(b"fake")
    cfg = LyricsConfig(separation_backend="wat", cache_dir=str(tmp_path / "c"))
    assert separate_vocals(f, cfg=cfg) == f


def test_separation_cache_hit(tmp_path):
    from pipeline.config import LyricsConfig
    from pipeline import cache
    from pipeline.separation import separate_vocals

    f = tmp_path / "song.wav"
    f.write_bytes(b"fake-audio")
    cfg = LyricsConfig(separation_backend="demucs", demucs_model="htdemucs_ft",
                       cache_dir=str(tmp_path / "c"))
    hit = cache.stage_cache_path(cfg.cache_dir, "separation", f, "demucs",
                                 "htdemucs_ft", "dereverb=0", ext=".wav")
    hit.write_bytes(b"cached-stem")
    assert separate_vocals(f, cfg=cfg) == hit


def test_analysis_never_deletes_the_upload(tmp_path, monkeypatch):
    """Regression: separate_vocals returns the ORIGINAL upload (as a Path) on
    every fallback. The cleanup compared that Path against the str file_path,
    always read as "owned", and unlinked the uploaded audio when the job
    finished — so /api/audio/{job} 404'd and the player showed
    "Could not load audio"."""
    import lyrics_transcriber as lt
    from pipeline import asr, lyrics_lookup

    monkeypatch.setenv("ENABLE_LYRICS", "1")
    monkeypatch.setenv("LYRICS_SEPARATION_BACKEND", "none")
    monkeypatch.setenv("LYRICS_ALIGNMENT", "0")
    monkeypatch.setenv("LYRICS_LRCLIB", "0")
    monkeypatch.setattr(lyrics_lookup, "get_metadata", lambda *a, **k: {})
    monkeypatch.setattr(lyrics_lookup, "lookup_lyrics", lambda *a, **k: None)
    monkeypatch.setattr(
        asr,
        "transcribe_asr",
        lambda *a, **k: {
            "lyrics": [{"timestamp": 0.0, "end": 1.0, "word": "la"}],
            "lines": [{"timestamp": 0.0, "end": 1.0, "text": "la"}],
            "language": "en",
            "model": "stub",
        },
    )

    upload = tmp_path / "audio.wav"
    upload.write_bytes(b"fake-audio")
    out = lt.transcribe_lyrics(str(upload), language="en")

    assert out["source"] == "asr"
    assert out["lines"][0]["text"] == "la"
    assert upload.exists(), "the uploaded audio must survive analysis"


def test_roformer_checkpoint_resolution_offline():
    from pipeline.separation import (
        _DEFAULT_ROFORMER_CANDIDATES,
        _resolve_roformer_checkpoint,
    )

    out = _resolve_roformer_checkpoint("")
    # Resolves from the installed audio-separator model list when present
    # (a real vocals ckpt), else the default candidate — never crashes.
    assert out.endswith(".ckpt")
    try:
        import audio_separator  # noqa: F401

        assert out in _DEFAULT_ROFORMER_CANDIDATES or "vocal" in out.lower()
    except ImportError:
        assert out == _DEFAULT_ROFORMER_CANDIDATES[0]


# ── Phase 4: alignment fallback + timebase ────────────────────────────────

def test_alignment_timebase_with_synthetic_emissions(tmp_path, monkeypatch):
    """Full align() path offline: LRCLIB-style timed line → per-word times
    from the CTC path, on the stem's timebase (seconds from 0)."""
    import numpy as np

    from pipeline import alignment
    from pipeline.config import LyricsConfig

    vocab = {"-": 0, "a": 1, "b": 2, "c": 3, "d": 4}
    T = 100  # 2 s at 50 fps
    lp = np.full((T, 5), np.log(0.025))
    lp[:, 0] = np.log(0.9)
    for f, c in [(20, 1), (25, 2), (50, 3), (55, 4)]:  # "ab" @0.4 s, "cd" @1.0 s
        lp[f, :] = np.log(0.025)
        lp[f, c] = np.log(0.9)
    monkeypatch.setattr(alignment, "compute_emissions", lambda y, cfg: (lp, vocab))
    monkeypatch.setattr(alignment, "_romanise",
                        lambda w, l, v: {"ഹലോ": "ab", "ലോകം": "cd"}[w])
    lines = [{"timestamp": 0.2, "end": 1.8, "text": "ഹലോ ലോകം"}]
    out = alignment.align(tmp_path / "v.wav", lines=lines, language="ml",
                          cfg=LyricsConfig(alignment_enabled=True),
                          audio=np.zeros(2 * 16000, dtype=np.float32))
    assert out["backend"] == "mms-fa"
    w = out["words"]
    assert [x["word"] for x in w] == ["ഹലോ", "ലോകം"]
    assert (w[0]["timestamp"], w[1]["timestamp"]) == (0.4, 1.0)
    assert w[0]["end"] <= w[1]["timestamp"] and w[1]["end"] <= 2.0
    assert out["lines"][0]["timestamp"] == 0.4 and out["lines"][0]["w1"] == 1


def test_alignment_untrusted_line_keeps_rough_timing(tmp_path, monkeypatch):
    """Garbage evidence (uniform emissions) must not move words — the even
    split / Whisper times survive instead of being scrambled."""
    import numpy as np

    from pipeline import alignment
    from pipeline.config import LyricsConfig

    vocab = {"-": 0, "a": 1, "b": 2, **{f"z{i}": i + 3 for i in range(25)}}  # 28 classes
    monkeypatch.setattr(alignment, "compute_emissions",
                        lambda y, cfg: (np.full((100, 28), np.log(1 / 28)), vocab))
    monkeypatch.setattr(alignment, "_romanise", lambda w, l, v: "ab")
    words = [{"word": "x", "timestamp": 0.3, "end": 0.6},
             {"word": "y", "timestamp": 0.9, "end": 1.2}]
    out = alignment.align(tmp_path / "v.wav", words=words, language="en",
                          cfg=LyricsConfig(alignment_enabled=True),
                          audio=np.zeros(2 * 16000, dtype=np.float32))
    assert [(x["timestamp"], x["confidence"]) for x in out["words"]] == [
        (0.3, None), (0.9, None)]


# ── Phase 5 ───────────────────────────────────────────────────────────────

def test_cleanup_disabled_and_llm_hook():
    from pipeline import cleanup
    from pipeline.config import LyricsConfig

    lines = [{"timestamp": 0.0, "end": 1.0, "text": "raw"}]
    off = cleanup.cleanup_text(lines, "hi", cfg=LyricsConfig(llm_cleanup_enabled=False))
    assert off["cleaned"] is False and off["lines"] == lines
    cleanup.LLM_FN = lambda prompt, **kw: "fixed line"
    try:
        on = cleanup.cleanup_text(lines, "hi", cfg=LyricsConfig(llm_cleanup_enabled=True))
        assert on["cleaned"] is True and on["lines"][0]["text"] == "fixed line"
        assert on["raw_lines"] == lines  # raw kept for diffing
    finally:
        cleanup.LLM_FN = None


def test_romanise_fallback_without_engine():
    from pipeline import cleanup

    lines = [{"timestamp": 0.0, "end": 1.0, "text": "ഹലോ"}]
    # Unknown language → native text preserved, never raises.
    assert cleanup.romanise_lines(lines, "xx") == lines


def test_romanise_indic_backend():
    indic = pytest.importorskip("indic_transliteration")
    from pipeline import cleanup

    lines = [{"timestamp": 0.0, "end": 1.0, "text": "ഹലോ ലോകം"}]
    out = cleanup.romanise_lines(lines, "ml")
    assert out[0]["roman"] == "halo lokaM"
    assert out[0]["text"] == "ഹലോ ലോകം"  # canonical stays native


# ── orchestrator ──────────────────────────────────────────────────────────

def test_transcribe_disabled_path(monkeypatch):
    import lyrics_transcriber as lt

    monkeypatch.setenv("ENABLE_LYRICS", "0")
    out = lt.transcribe_lyrics("/nonexistent.wav", language="ml")
    assert out["lyrics"] == [] and "disabled" in out["error"]
    monkeypatch.delenv("ENABLE_LYRICS", raising=False)


def test_metadata_uses_original_upload_filename(tmp_path):
    """S2: uploads are stored as audio.<ext>; the original name must drive
    the LRCLIB lookup (it used to search for the title 'audio')."""
    from pipeline.lyrics_lookup import get_metadata

    stored = tmp_path / "audio.mp3"
    m = get_metadata(stored, filename="Chahun Main Ya Naa Aashiqui 2 320 Kbps.mp3")
    assert m["title"] == "Chahun Main Ya Naa Aashiqui 2"
    m = get_metadata(
        stored,
        filename="Mazha Njaan Arinjirunnilla  Dr. Patient  Hariharan  Bennet Veetraag.mp3",
    )
    assert m == {"title": "Mazha Njaan Arinjirunnilla"}  # no guessed artist
    m = get_metadata(stored, filename="Arijit_Singh - Kesariya [Official Video].mp3")
    assert m["artist"] == "Arijit Singh" and m["title"] == "Kesariya"
    # no hint: the stored name "audio" is noise, so no bogus lookup happens
    assert "title" not in get_metadata(stored)
