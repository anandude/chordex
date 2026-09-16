"""
pipeline/config.py
------------------
Single config object for the whole lyrics chain. Every stage reads its flags
from here (env-backed, so each stage is toggleable and A/B comparable).
Eval rows name the config that produced them via ``describe()``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


@dataclass
class LyricsConfig:
    # Phase 1 — separation
    separation_backend: str = "demucs"  # none | demucs | roformer
    demucs_model: str = "htdemucs_ft"
    roformer_model: str = ""  # empty = resolve from audio-separator model list at runtime
    dereverb: bool = False
    dereverb_model: str = ""
    separate_vocals_legacy: bool = True  # honour legacy SEPARATE_VOCALS=0
    separation_timeout_s: int = 600

    # Phase 2 — LRCLIB lookup
    lrclib_enabled: bool = True
    lrclib_timeout_s: int = 10
    lrclib_cache_ttl_s: int = 7 * 24 * 3600

    # Phase 3 — ASR
    whisper_model: str = "small"
    whisper_model_overrides_json: str = ""
    whisper_device: str = "cpu"
    whisper_compute_type: str = ""
    asr_chunk_length_s: int = 12  # 10–15 s: Indic scripts are token-dense,
    asr_chunk_overlap_s: int = 2  # 30 s windows risk 448-token truncation
    asr_rms_threshold: float = 0.01  # skip near-silent chunks (instrumental)
    hf_token: str = ""  # needed for gated models (indic-conformer)

    # Phase 4 — alignment
    alignment_enabled: bool = True
    alignment_model: str = "MahmoudAshraf/mms-300m-1130-forced-aligner"

    # Phase 5 — cleanup / romanisation
    llm_cleanup_enabled: bool = False
    romanisation_enabled: bool = True  # display toggle default; storage stays native

    # Cross-cutting
    cache_dir: str = "/tmp/chordex_lyrics_cache"
    user_agent: str = "ChordLens/2.0 (lyrics eval; contact: owner)"

    @classmethod
    def from_env(cls) -> "LyricsConfig":
        overrides_raw = _env("WHISPER_MODEL_OVERRIDES", "")
        compute = _env("WHISPER_COMPUTE_TYPE", "")
        device = _env("WHISPER_DEVICE", "cpu")
        if not compute:
            compute = "int8" if device == "cpu" else "float16"
        sep = _env("LYRICS_SEPARATION_BACKEND", "demucs").lower()
        if _env("SEPARATE_VOCALS", "1").lower() in {"0", "false", "no", "off"}:
            sep = "none"
        return cls(
            separation_backend=sep,
            demucs_model=_env("LYRICS_DEMUCS_MODEL", "htdemucs_ft"),
            roformer_model=_env("LYRICS_ROFORMER_MODEL", ""),
            dereverb=_env_flag("LYRICS_DEREVERB", False),
            dereverb_model=_env("LYRICS_DEREVERB_MODEL", ""),
            separation_timeout_s=int(_env("LYRICS_SEPARATION_TIMEOUT_S", "600")),
            lrclib_enabled=_env_flag("LYRICS_LRCLIB", True),
            lrclib_timeout_s=int(_env("LYRICS_LRCLIB_TIMEOUT_S", "10")),
            whisper_model=_env("WHISPER_MODEL", "small"),
            whisper_model_overrides_json=overrides_raw,
            whisper_device=device,
            whisper_compute_type=compute,
            asr_chunk_length_s=int(_env("LYRICS_ASR_CHUNK_S", "12")),
            asr_chunk_overlap_s=int(_env("LYRICS_ASR_OVERLAP_S", "2")),
            hf_token=_env("HF_TOKEN", ""),
            alignment_enabled=_env_flag("LYRICS_ALIGNMENT", True),
            alignment_model=_env(
                "LYRICS_ALIGNMENT_MODEL",
                "MahmoudAshraf/mms-300m-1130-forced-aligner",
            ),
            llm_cleanup_enabled=_env_flag("LYRICS_LLM_CLEANUP", False),
            cache_dir=_env("LYRICS_CACHE_DIR", "/tmp/chordex_lyrics_cache"),
        )

    def asr_model_for(self, language: str | None) -> str:
        """Phase 3 routing table. HF fine-tunes contain '/' and load via the
        transformers runtime; plain names (small, large-v3-turbo) use
        faster-whisper. Env JSON overrides win over built-ins."""
        builtin = {
            "ml": "adalat-ai/whisper-medium-ml-rmft",
            "hi": "adalat-ai/whisper-medium-hi-high-lr",
        }
        if self.whisper_model_overrides_json:
            try:
                parsed = json.loads(self.whisper_model_overrides_json)
                builtin.update({str(k): str(v) for k, v in parsed.items()})
            except (ValueError, TypeError):
                pass
        if language and language in builtin:
            return builtin[language]
        return self.whisper_model

    def describe(self) -> str:
        parts = [
            f"sep={self.separation_backend}",
            f"asr_ml={self.asr_model_for('ml')}",
            f"asr_hi={self.asr_model_for('hi')}",
            f"chunk={self.asr_chunk_length_s}+{self.asr_chunk_overlap_s}",
            f"lrclib={'on' if self.lrclib_enabled else 'off'}",
            f"align={'on' if self.alignment_enabled else 'off'}",
            f"cleanup={'on' if self.llm_cleanup_enabled else 'off'}",
        ]
        if self.separation_backend == "demucs":
            parts.append(f"demucs={self.demucs_model}")
        if self.dereverb:
            parts.append("dereverb=on")
        return "|".join(parts)
