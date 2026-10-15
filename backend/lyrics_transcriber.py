"""
lyrics_transcriber.py
---------------------
Word-level lyrics. Two layers:

* Pipeline orchestration (``transcribe_lyrics``) — Phase 1→5 chain:
  separate → lookup/ASR → align → clean. Each stage is config-flagged,
  independently cached, and degrades to the next option on failure.

Env (see pipeline/config.py for the full block):
  ENABLE_LYRICS=1|0          default 1
  WHISPER_MODEL=small|...    default small (Phase 3 Indic fine-tunes for hi/ml
                             unless overridden; falls back to turbo on error)
  WHISPER_MODEL_OVERRIDES    JSON dict lang->model (wins over built-ins)
  WHISPER_LANGUAGE=en|hi|ml  hard override used when no per-job language is given
  WHISPER_DEVICE=cpu|cuda    default cpu
  WHISPER_COMPUTE_TYPE=int8|float16|float32  default int8 on cpu
  LYRICS_SEPARATION_BACKEND=none|demucs|roformer  default demucs
  LYRICS_LRCLIB=1|0          default 1 (lookup before ASR)
  LYRICS_ALIGNMENT=1|0       default 1 (CTC re-align, even-split fallback)
  LYRICS_LLM_CLEANUP=1|0     default 0
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_WORD_GAP = 0.55  # silence that splits lyric lines
_MAX_LINE_WORDS = 12


def lyrics_enabled() -> bool:
    return os.getenv("ENABLE_LYRICS", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _lines_from_words(
    words: list[dict[str, Any]], segments: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Group word timings into lyric lines on singing pauses.

    Whisper segments are 30-s VAD chunks, not lyric lines — so when word
    timings exist we regroup; otherwise fall back to segments.
    """
    if not words:
        return segments

    lines: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for w in words:
        if current:
            prev = current[-1]
            pause = w["timestamp"] - prev.get("end", prev["timestamp"])
            if pause > _WORD_GAP or len(current) >= _MAX_LINE_WORDS:
                lines.append(current)
                current = []
        current.append(w)
    if current:
        lines.append(current)

    return [
        {
            "timestamp": group[0]["timestamp"],
            "end": group[-1].get("end", group[-1]["timestamp"]),
            "text": " ".join(w["word"] for w in group),
        }
        for group in lines
    ]


def transcribe_lyrics(
    file_path: str,
    language: str | None = None,
    *,
    title: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    duration: float | None = None,
    progress: Any = None,
    filename: str | None = None,
) -> dict[str, Any]:
    """
    Full lyrics chain: separate → lookup/ASR → align → clean.

    Args:
      file_path: local audio file
      language: optional ISO code hint from the upload ("en", "hi", "ml", ...)
      title/artist/album: optional UI metadata (dramatically raises LRCLIB hits)
      duration: optional audio duration in seconds (else probed)
      filename: original upload filename (the stored copy is audio.<ext>)
      progress: optional callable(stage: str, pct: float) for job observability

    Returns:
      {
        "lyrics": [{"timestamp": float, "end": float, "word": str}, ...],
        "lines":  [{"timestamp": float, "end": float, "text": str}, ...],
        "language": str | None,
        "source": "lrclib_synced" | "lrclib_plain" | "asr",
        "stages": {stage: seconds},   # observability
        "models": {...},              # model versions used
        "error": str | None,
      }
    """
    import time as _time

    from pipeline.config import LyricsConfig

    cfg = LyricsConfig.from_env()
    stages: dict[str, float] = {}
    models: dict[str, str] = {}

    def _report(stage: str, pct: float) -> None:
        if progress:
            try:
                progress(stage, pct)
            except Exception:
                pass

    if not lyrics_enabled():
        return {
            "lyrics": [],
            "lines": [],
            "language": None,
            "source": "asr",
            "stages": stages,
            "models": models,
            "error": "lyrics disabled (ENABLE_LYRICS=0)",
        }

    lang_hint = (language or os.getenv("WHISPER_LANGUAGE", "").strip() or None)
    lang_prob: float | None = None  # set when the language was auto-detected

    # ── Phase 2 first: the best transcription is the one you skip ──
    _report("fetching_lyrics", 0.05)
    t0 = _time.time()
    lookup_text: str | None = None
    lookup_lines: list[dict[str, Any]] | None = None
    source = "asr"
    metadata: dict[str, str] = {}
    try:
        from pipeline.lyrics_lookup import get_metadata, lookup_lyrics

        metadata = get_metadata(file_path, title, artist, album, filename)
        hit = lookup_lyrics(
            file_path, title=title, artist=artist, album=album,
            duration=duration, cfg=cfg, filename=filename,
        )
        if hit:
            source = hit["source"]
            lookup_lines = hit["lines"]
            lookup_text = "\n".join(l["text"] for l in lookup_lines)
            from pipeline.lyrics_lookup import script_language

            # cached hits pre-date the language field → infer from the script
            lang_hint = (hit.get("language") or lang_hint
                         or script_language(lookup_text or ""))
    except Exception as exc:
        logger.warning("lyrics lookup failed (%s) — ASR fallback", exc)
    stages["lookup"] = round(_time.time() - t0, 2)

    # ── Phase 1: isolate vocals (always: ASR and forced alignment both use
    # the stem, including after an LRCLIB hit) ──
    from pipeline.separation import separate_vocals

    _report("separating", 0.15)
    t0 = _time.time()
    vocal_path = separate_vocals(file_path, cfg=cfg)
    stages["separation"] = round(_time.time() - t0, 2)
    models["separation"] = cfg.separation_backend
    # NOTE: separate_vocals returns either the shared stage cache (a hit or a
    # fresh stem) or — on every fallback — the *original upload* as a Path.
    # Neither is owned by this call, so nothing here is deleted afterwards: a
    # `owns_vocal = vocal_path != file_path` check used to compare a Path
    # against a str, always read as "owned", and unlinked the user's upload at
    # the end of the job (breaking playback). The cache is meant to be reused.

    _stem: list = []

    def _stem_audio():
        """Decode the 16 kHz stem once; ASR and alignment share the array."""
        if not _stem:
            from pipeline.asr import load_stem

            try:
                _stem.append(load_stem(vocal_path))
            except Exception as exc:  # stages load (and report) it themselves
                logger.warning("stem decode failed (%s)", exc)
                _stem.append(None)
        return _stem[0]

    try:
        # ── Phase 3: transcribe (miss only) ──
        if lookup_lines is None:
            _report("transcribing", 0.45)
            t0 = _time.time()
            from pipeline.asr import transcribe_asr

            # progress is threaded through so a first-run model download (or a
            # slow CPU decode) shows up as a moving stage instead of a stall
            asr_out = transcribe_asr(
                vocal_path, language=lang_hint, cfg=cfg, progress=_report,
                audio=_stem_audio(),
            )
            stages["transcription"] = round(_time.time() - t0, 2)
            models["asr"] = str(asr_out.get("model", ""))
            if asr_out.get("error") and not asr_out.get("lyrics") \
                    and asr_out.get("model") != cfg.asr_fallback_for(
                        asr_out.get("language") or lang_hint):
                # Routed model failed (gated repo, missing weights/dep)? Retry
                # with the language's fallback model — never fail the job.
                fb_model = cfg.asr_fallback_for(asr_out.get("language") or lang_hint)
                logger.warning("ASR with %s failed (%s) — retrying with %s",
                               asr_out.get("model"), asr_out.get("error"), fb_model)
                import dataclasses

                t_fb = _time.time()
                # pin the language detected on the first try so the retry
                # doesn't route straight back to the failed fine-tune
                fb_lang = asr_out.get("language") or lang_hint
                fb_cfg = dataclasses.replace(cfg, whisper_model_overrides_json=json.dumps(
                    {fb_lang or "_": fb_model}))
                failed_model = asr_out.get("model", "?")
                asr_out = transcribe_asr(vocal_path, language=fb_lang, cfg=fb_cfg,
                                         progress=_report, audio=_stem_audio())
                stages["transcription_fallback"] = round(_time.time() - t_fb, 2)
                models["asr"] = f"{failed_model}→{asr_out.get('model', '')}"
            words = asr_out.get("lyrics", [])
            lines = asr_out.get("lines", [])
            lang_hint = asr_out.get("language") or lang_hint
            lang_prob = asr_out.get("language_prob")
            raw_text: str | None = None
            if asr_out.get("timing") == "window":
                # Text-only ASR (Indic-Transcribe): its words are evenly spread
                # guesses. Align each decoded window as a timed line instead —
                # the window span is exact — then regroup lines at pauses.
                lookup_lines = None
                window_lines = asr_out.get("segments") or []
            else:
                window_lines = None
        else:
            words = []
            lines = lookup_lines
            raw_text = lookup_text
            window_lines = None

        # ── Phase 4: (re-)align to the chord timebase ──
        _report("aligning", 0.8)
        t0 = _time.time()
        if cfg.alignment_enabled and (raw_text or words or window_lines):
            from pipeline.alignment import align

            if window_lines:
                aligned = align(vocal_path, None, language=lang_hint,
                                lines=window_lines, duration=duration, cfg=cfg,
                                audio=_stem_audio())
                words = aligned.get("words", words)
                # windows are up to 30 s — regroup display lines at vocal pauses
                lines = _lines_from_words(words, window_lines)
            else:
                aligned = align(
                    vocal_path,
                    raw_text if lookup_lines is not None else None,
                    language=lang_hint,
                    lines=lines if lookup_lines is not None else None,
                    words=words or None,
                    duration=duration,
                    cfg=cfg,
                    audio=_stem_audio(),
                )
                words = aligned.get("words", words)
                # aligned lines are timed from their words (w0..w1 index range),
                # for LRCLIB and ASR alike — one timebase for lines, words, chords
                lines = aligned.get("lines") or lines
            models["alignment"] = str(aligned.get("backend", ""))
            if aligned.get("error"):
                logger.info("alignment note: %s", aligned["error"])
        stages["alignment"] = round(_time.time() - t0, 2)

        # ── Phase 5a: LLM cleanup (ASR text only, never LRCLIB) ──
        cleaned_flag = False
        if lookup_lines is None and cfg.llm_cleanup_enabled:
            from pipeline.cleanup import cleanup_text

            _report("cleaning", 0.92)
            t0 = _time.time()
            clean = cleanup_text(lines, lang_hint, metadata, cfg)
            lines, cleaned_flag = clean["lines"], clean["cleaned"]
            if clean.get("realigned"):
                from pipeline.alignment import align as _realign

                re_al = _realign(vocal_path, "\n".join(l["text"] for l in lines),
                                 language=lang_hint, lines=lines,
                                 duration=duration, cfg=cfg)
                words, lines = re_al.get("words", words), re_al.get("lines", lines)
            stages["cleanup"] = round(_time.time() - t0, 2)

        _report("done", 1.0)
        logger.info("lyrics done source=%s lang=%s words=%d stages=%s models=%s",
                    source, lang_hint, len(words), stages, models)
        return {
            "lyrics": words,
            "lines": lines,
            "language": lang_hint,
            "language_prob": lang_prob,
            "source": source,
            "cleaned": cleaned_flag,
            "stages": stages,
            "models": models,
            "error": None,
        }
    finally:
        # nothing to clean up — the stem lives in the shared stage cache
        pass
