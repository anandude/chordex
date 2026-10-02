"""
lyrics_transcriber.py
---------------------
Word-level lyrics. Two layers:

* Legacy faster-whisper path (``_transcribe``) — unchanged behaviour, used as
  the ASR fallback and when the new pipeline is disabled.
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
import tempfile
from typing import Any

logger = logging.getLogger(__name__)

_models: dict[str, Any] = {}

# English does fine on `small`; Hindi/Malayalam get `large-v3-turbo` —
# close to large-v3 quality at a fraction of the decoder cost. First use
# of a new model downloads it (turbo is ~1.6 GB).
_DEFAULT_MODEL_OVERRIDES = {"hi": "large-v3-turbo", "ml": "large-v3-turbo"}

# Script/context bias for the decoder's first window — stops Devanagari/
# Malayalam output drifting into romanization or Urdu-script mixes.
_INITIAL_PROMPTS = {
    "hi": "यह एक हिंदी गाना है।",
    "ml": "ഇതൊരു മലയാളം ഗാനമാണ്.",
    "en": None,
}

_WORD_GAP = 0.55  # silence that splits lyric lines
_MAX_LINE_WORDS = 12


def lyrics_enabled() -> bool:
    return os.getenv("ENABLE_LYRICS", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _model_overrides() -> dict[str, str]:
    raw = os.getenv("WHISPER_MODEL_OVERRIDES", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            return {str(k): str(v) for k, v in parsed.items()}
        except (ValueError, TypeError):
            logger.warning("Invalid WHISPER_MODEL_OVERRIDES JSON, using defaults")
    return dict(_DEFAULT_MODEL_OVERRIDES)


def resolve_model_name(language: str | None) -> str:
    """Pick the model for a job: per-language override, else the default."""
    name = os.getenv("WHISPER_MODEL", "small").strip() or "small"
    if language:
        overrides = _model_overrides()
        name = overrides.get(language, name)
    return name


def _get_model(name: str):
    if name in _models:
        return _models[name]

    from faster_whisper import WhisperModel

    device = os.getenv("WHISPER_DEVICE", "cpu").strip()
    compute = os.getenv(
        "WHISPER_COMPUTE_TYPE",
        "int8" if device == "cpu" else "float16",
    ).strip()

    logger.info("Loading Whisper model=%s device=%s compute=%s", name, device, compute)
    _models[name] = WhisperModel(name, device=device, compute_type=compute)
    return _models[name]


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


def _separate_vocals(file_path: str) -> str:
    """Extract a vocals-only track with Demucs; returns the original path on
    any problem. Sung vocals buried in a full mix are the #1 cause of garbage
    lyrics — transcribing the isolated vocal fixes most of it."""
    if os.getenv("SEPARATE_VOCALS", "1").strip().lower() in {"0", "false", "no", "off"}:
        return file_path
    out_path: str | None = None
    try:
        import soundfile as sf
        from demucs.api import Separator

        sep = Separator(model="htdemucs", device="cpu", progress=False)
        _, stems = sep.separate_audio_file(file_path)
        vocals = stems["vocals"].cpu()
        fd, out_path = tempfile.mkstemp(suffix=".wav", prefix="chordex_vocals_")
        os.close(fd)
        sf.write(out_path, vocals.numpy().T, sep.samplerate)
        logger.info("Vocal separation ok -> %s", out_path)
        return out_path
    except ImportError:
        logger.info("demucs not installed — transcribing the full mix")
        return file_path
    except Exception as exc:
        logger.warning("Vocal separation failed (%s) — falling back to full mix", exc)
        if out_path and os.path.exists(out_path):
            try:
                os.unlink(out_path)
            except OSError:
                pass
        return file_path


def transcribe_lyrics(
    file_path: str,
    language: str | None = None,
    *,
    title: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    duration: float | None = None,
    progress: Any = None,
) -> dict[str, Any]:
    """
    Full lyrics chain: separate → lookup/ASR → align → clean.

    Args:
      file_path: local audio file
      language: optional ISO code hint from the upload ("en", "hi", "ml", ...)
      title/artist/album: optional UI metadata (dramatically raises LRCLIB hits)
      duration: optional audio duration in seconds (else probed)
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

    # ── Phase 2 first: the best transcription is the one you skip ──
    _report("fetching_lyrics", 0.05)
    t0 = _time.time()
    lookup_text: str | None = None
    lookup_lines: list[dict[str, Any]] | None = None
    source = "asr"
    metadata: dict[str, str] = {}
    try:
        from pipeline.lyrics_lookup import get_metadata, lookup_lyrics

        metadata = get_metadata(file_path, title, artist, album)
        hit = lookup_lyrics(
            file_path, title=title, artist=artist, album=album,
            duration=duration, cfg=cfg,
        )
        if hit:
            source = hit["source"]
            lookup_lines = hit["lines"]
            lookup_text = "\n".join(l["text"] for l in lookup_lines)
            lang_hint = hit.get("language") or lang_hint
    except Exception as exc:
        logger.warning("lyrics lookup failed (%s) — ASR fallback", exc)
    stages["lookup"] = round(_time.time() - t0, 2)

    # ── Phase 1: isolate vocals (skipped when LRCLIB gave synced lines AND
    # alignment is off — nothing left that needs audio) ──
    from pipeline.separation import separate_vocals

    _report("separating", 0.15)
    t0 = _time.time()
    vocal_path = separate_vocals(file_path, cfg=cfg)
    stages["separation"] = round(_time.time() - t0, 2)
    models["separation"] = cfg.separation_backend
    owns_vocal = vocal_path != file_path

    try:
        # ── Phase 3: transcribe (miss only) ──
        if lookup_lines is None:
            _report("transcribing", 0.45)
            t0 = _time.time()
            from pipeline.asr import transcribe_asr

            asr_out = transcribe_asr(vocal_path, language=lang_hint, cfg=cfg)
            stages["transcription"] = round(_time.time() - t0, 2)
            models["asr"] = str(asr_out.get("model", ""))
            if asr_out.get("error") and not asr_out.get("lyrics"):
                # HF fine-tune failed (missing dep/weights)? Fall back to the
                # legacy stock faster-whisper path — never fail the job.
                logger.warning("pipeline ASR failed (%s) — legacy fallback",
                               asr_out.get("error"))
                t_fb = _time.time()
                legacy = _transcribe(vocal_path, lang_hint)
                stages["transcription_fallback"] = round(_time.time() - t_fb, 2)
                models["asr"] = (
                    f"{asr_out.get('model', '?')}→{resolve_model_name(lang_hint)}"
                )
                legacy.update({"source": "asr", "stages": stages,
                               "models": models})
                return legacy
            words = asr_out.get("lyrics", [])
            lines = asr_out.get("lines", [])
            lang_hint = asr_out.get("language") or lang_hint
            raw_text: str | None = None
        else:
            words = []
            lines = lookup_lines
            raw_text = lookup_text

        # ── Phase 4: (re-)align to the chord timebase ──
        _report("aligning", 0.8)
        t0 = _time.time()
        if cfg.alignment_enabled and (raw_text or words):
            from pipeline.alignment import align

            aligned = align(
                vocal_path,
                raw_text if lookup_lines is not None else None,
                language=lang_hint,
                lines=lines if lookup_lines is not None else None,
                words=words or None,
                cfg=cfg,
            )
            words = aligned.get("words", words)
            if lookup_lines is None:
                lines = aligned.get("lines", lines)
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
                                 language=lang_hint, lines=lines, cfg=cfg)
                words, lines = re_al.get("words", words), re_al.get("lines", lines)
            stages["cleanup"] = round(_time.time() - t0, 2)

        _report("done", 1.0)
        logger.info("lyrics done source=%s lang=%s words=%d stages=%s models=%s",
                    source, lang_hint, len(words), stages, models)
        return {
            "lyrics": words,
            "lines": lines,
            "language": lang_hint,
            "source": source,
            "cleaned": cleaned_flag,
            "stages": stages,
            "models": models,
            "error": None,
        }
    finally:
        if owns_vocal:
            try:
                os.unlink(vocal_path)
            except OSError:
                pass


def _transcribe(file_path: str, lang_hint: str | None) -> dict[str, Any]:
    try:
        model_name = resolve_model_name(lang_hint)
        model = _get_model(model_name)
        logger.info(
            "Transcribing lyrics model=%s language=%s", model_name, lang_hint or "auto"
        )
        segments, info = model.transcribe(
            file_path,
            word_timestamps=True,
            language=lang_hint,
            vad_filter=True,
            # music-tuned decoding: beam search, no cross-window context
            # (repetition loops), hallucination guard, gentler VAD padding
            beam_size=5,
            condition_on_previous_text=False,
            hallucination_silence_threshold=2.0,
            vad_parameters={
                "min_silence_duration_ms": 1000,
                "speech_pad_ms": 200,
            },
            initial_prompt=_INITIAL_PROMPTS.get(lang_hint or ""),
        )

        words: list[dict[str, Any]] = []
        raw_lines: list[dict[str, Any]] = []

        for seg in segments:
            text = (seg.text or "").strip()
            if text:
                raw_lines.append(
                    {
                        "timestamp": round(float(seg.start or 0.0), 3),
                        "end": round(float(seg.end or 0.0), 3),
                        "text": text,
                    }
                )
            if seg.words:
                for w in seg.words:
                    token = (w.word or "").strip()
                    if not token:
                        continue
                    words.append(
                        {
                            "timestamp": round(float(w.start or 0.0), 3),
                            "end": round(float(w.end or 0.0), 3),
                            "word": token,
                        }
                    )

        lines = _lines_from_words(words, raw_lines)
        lang = getattr(info, "language", None)
        return {
            "lyrics": words,
            "lines": lines,
            "language": lang,
            "error": None,
        }
    except Exception as exc:
        logger.exception("Lyrics transcription failed")
        return {
            "lyrics": [],
            "lines": [],
            "language": None,
            "error": str(exc)[:500],
        }
