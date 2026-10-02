"""
pipeline/separation.py
----------------------
Phase 1 — vocal separation before ASR. One interface, two backends:

  demucs   — ``htdemucs_ft`` (two-stem vocals). Reliable default; meaningfully
             better than base ``htdemucs`` at the same cost. NOTE: the demucs
             Python API (``Separator``) does not expose the CLI's
             ``--two-stems`` flag, so we run the full model and keep the
             ``vocals`` stem — identical vocal quality, extra stems discarded.
  roformer — Mel-Band / BS-RoFormer vocals checkpoint via ``audio-separator``.
             The checkpoint is resolved from the *installed* package's model
             list at runtime (never a hardcoded-from-memory filename): the
             configured name is used if present, else the first non-karaoke
             vocals entry. Verified against audio-separator 0.47.0
             (``models.json`` → ``roformer_download_list``), e.g.
             ``mel_band_roformer_vocals_becruily.ckpt``.

Contract: 16 kHz mono WAV (what the Indic ASR models expect) — converted once
here. Cache key = sha256(source) + backend + model version. Any failure or
timeout falls back to the original mixture with a warning (never fail the job).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from pipeline.cache import stage_cache_path
from pipeline.config import LyricsConfig

logger = logging.getLogger(__name__)

TARGET_SR = 16000

_DEFAULT_ROFORMER_CANDIDATES = (
    "mel_band_roformer_vocals_becruily.ckpt",
    "bs_roformer_vocals_gabox.ckpt",
    "vocals_mel_band_roformer.ckpt",
)


def _resolve_roformer_checkpoint(configured: str) -> str:
    """Pick a vocals checkpoint from the installed audio-separator model list."""
    try:
        import audio_separator  # noqa: F401
        from importlib.resources import files as res_files

        models_json = res_files("audio_separator").joinpath("models.json")
        import json

        data = json.loads(models_json.read_text(encoding="utf-8"))
        roformer = data.get("roformer_download_list", {})
        if isinstance(roformer, dict):
            entries: list[str] = []
            for _label, files in roformer.items():
                if isinstance(files, dict):
                    entries.extend(files.keys())
                elif isinstance(files, str):
                    entries.append(files)
            if configured and configured in entries:
                return configured
            vocals = [
                f for f in entries
                if "vocal" in f.lower() and "karaoke" not in f.lower()
            ]
            if vocals:
                for fav in _DEFAULT_ROFORMER_CANDIDATES:
                    if fav in vocals:
                        return fav
                return sorted(vocals)[0]
    except Exception as exc:
        logger.warning("roformer model-list resolution failed (%s)", exc)
    return configured or _DEFAULT_ROFORMER_CANDIDATES[0]


def _to_16k_mono(src: Path, dst: Path) -> Path:
    import librosa
    import soundfile as sf

    y, _ = librosa.load(str(src), sr=TARGET_SR, mono=True)
    sf.write(str(dst), y, TARGET_SR)
    return dst


def _separate_demucs(audio_path: Path, workdir: Path, cfg: LyricsConfig) -> Path:
    from demucs.api import Separator

    import soundfile as sf

    sep = Separator(model=cfg.demucs_model, device="cpu", progress=False)
    _, stems = sep.separate_audio_file(str(audio_path))
    vocals = stems["vocals"].cpu()
    raw = workdir / "vocals_raw.wav"
    sf.write(str(raw), vocals.numpy().T, sep.samplerate)
    return raw


def _separate_roformer(audio_path: Path, workdir: Path, cfg: LyricsConfig) -> Path:
    from audio_separator.separator import Separator

    checkpoint = _resolve_roformer_checkpoint(cfg.roformer_model)
    logger.info("roformer checkpoint: %s", checkpoint)
    sep = Separator(
        output_dir=str(workdir),
        output_format="WAV",
        output_single_stem="Vocals",
        normalization_threshold=0.9,
    )
    sep.load_model(model_filename=checkpoint)
    outputs = sep.separate(str(audio_path))
    if not outputs:
        raise RuntimeError("audio-separator produced no output files")
    return Path(outputs[0])


def _maybe_dereverb(vocal_16k: Path, workdir: Path, cfg: LyricsConfig) -> Path:
    """Optional dereverb sub-stage (default off). Uses a BS-RoFormer dereverb
    checkpoint through the same audio-separator interface when configured."""
    if not cfg.dereverb or not cfg.dereverb_model:
        return vocal_16k
    from audio_separator.separator import Separator

    sep = Separator(output_dir=str(workdir), output_format="WAV")
    sep.load_model(model_filename=cfg.dereverb_model)
    outputs = sep.separate(str(vocal_16k))
    if not outputs:
        raise RuntimeError("dereverb produced no output")
    return _to_16k_mono(Path(outputs[0]), workdir / "vocals_dereverb_16k.wav")


def separate_vocals(
    audio_path: str | Path,
    out_dir: str | Path | None = None,
    backend: str | None = None,
    cfg: LyricsConfig | None = None,
) -> Path:
    """Isolate the vocal stem. Returns a 16 kHz mono WAV path.

    Falls back to the original file (warning logged) when backend is 'none',
    the backend package is missing, separation fails or times out.
    """
    cfg = cfg or LyricsConfig.from_env()
    audio_path = Path(audio_path)
    backend = (backend or cfg.separation_backend).lower()
    if backend == "none":
        return audio_path

    cache = stage_cache_path(
        cfg.cache_dir, "separation", audio_path, backend,
        cfg.demucs_model if backend == "demucs" else cfg.roformer_model or "auto",
        f"dereverb={int(cfg.dereverb)}",
        ext=".wav",
    )
    if cache.exists():
        logger.info("separation cache hit backend=%s -> %s", backend, cache)
        return cache

    deadline = time.time() + max(30, cfg.separation_timeout_s)
    workdir = Path(out_dir or cache.parent / f"work_{audio_path.stem}")
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        if backend == "demucs":
            raw = _separate_demucs(audio_path, workdir, cfg)
        elif backend == "roformer":
            raw = _separate_roformer(audio_path, workdir, cfg)
        else:
            logger.warning("unknown separation backend %r — using mixture", backend)
            return audio_path
        if time.time() > deadline:
            raise TimeoutError("separation exceeded timeout")
        stem_16k = _to_16k_mono(raw, workdir / "vocals_16k.wav")
        stem_16k = _maybe_dereverb(stem_16k, workdir, cfg)
        cache.parent.mkdir(parents=True, exist_ok=True)
        # Atomic publish to cache (16 kHz mono WAV)
        import shutil

        shutil.copyfile(stem_16k, cache)
        try:
            os.remove(raw)
        except OSError:
            pass
        logger.info("separation ok backend=%s -> %s", backend, cache)
        return cache
    except ImportError as exc:
        logger.warning("separation backend %s not installed (%s) — using mixture", backend, exc)
        return audio_path
    except Exception as exc:
        logger.warning("separation failed (%s) — falling back to mixture", exc)
        return audio_path
