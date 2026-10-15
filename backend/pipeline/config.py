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


#: Default model per language. ml: Bodhan AI / AI4Bharat Indic-Transcribe-core
#: (Voice of India Malayalam OIWER 11.5 vs IndicConformer 28.2; on our
#: Malayalam test song it produced clean, correct lyrics where the Whisper
#: fine-tune produced fragments). Gated — needs HF login + accepted terms;
#: falls back to _FALLBACK_ROUTES when unavailable.
_BUILTIN_ROUTES = {
    "ml": "bodhan-ai/indic-transcribe-core",
    "hi": "adalat-ai/whisper-medium-hi-high-lr",
}
_FALLBACK_ROUTES = {
    "ml": "adalat-ai/whisper-medium-ml-rmft",
}


def ct2_dir_for(model_id: str) -> "Path":
    """Local CTranslate2 conversion dir for an HF model id (scripts/convert_ct2.py)."""
    from pathlib import Path

    base = Path(os.getenv("LYRICS_CT2_DIR", "").strip()
                or Path(__file__).resolve().parent.parent / "models" / "ct2")
    return base / model_id.replace("/", "--")


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
    # htdemucs (single model) by default: htdemucs_ft is a bag of 4 models,
    # ~4x the compute for a small vocal-quality gain. Opt in via env.
    demucs_model: str = "htdemucs"
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
    whisper_device: str = "auto"  # auto | cpu | cuda (see pipeline/gpu.py)
    whisper_compute_type: str = ""  # empty → int8_float16 on cuda, int8 on cpu
    # A1: language ID runs on the stem BEFORE model routing. Candidates bias
    # detection toward the languages we serve (singing confuses ml↔ta); a
    # non-candidate wins only when Whisper is very sure (see asr.py).
    lid_model: str = "small"
    lang_candidates: tuple[str, ...] = ("hi", "ml", "en")
    asr_batch_size: int = 8
    # beam 1 measured ~38% faster than 5 with the hi medium fine-tune on the
    # GTX 1650 (20.7 s vs 33.4 s per 5-min song); accuracy impact unmeasured
    # until reference lyrics exist, so default stays 5.
    asr_beam_size: int = 5
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
    device: str = "auto"  # torch models (demucs, aligner): auto | cpu | cuda[:n]
    cache_dir: str = "/tmp/chordex_lyrics_cache"
    user_agent: str = "ChordLens/2.0 (lyrics eval; contact: owner)"

    @classmethod
    def from_env(cls) -> "LyricsConfig":
        overrides_raw = _env("WHISPER_MODEL_OVERRIDES", "")
        compute = _env("WHISPER_COMPUTE_TYPE", "")
        device = _env("WHISPER_DEVICE", "auto").lower()
        cands = tuple(
            c.strip().lower()
            for c in _env("LYRICS_LANG_CANDIDATES", "hi,ml,en").split(",")
            if c.strip()
        )
        sep = _env("LYRICS_SEPARATION_BACKEND", "demucs").lower()
        if _env("SEPARATE_VOCALS", "1").lower() in {"0", "false", "no", "off"}:
            sep = "none"
        return cls(
            separation_backend=sep,
            demucs_model=_env("LYRICS_DEMUCS_MODEL", "htdemucs"),
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
            lid_model=_env("LYRICS_LID_MODEL", "small"),
            lang_candidates=cands,
            asr_batch_size=int(_env("LYRICS_ASR_BATCH", "8")),
            asr_beam_size=int(_env("LYRICS_ASR_BEAM", "5")),
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
            device=_env("LYRICS_DEVICE", "auto").lower(),
        )

    def torch_device(self) -> str:
        """Resolve ``device`` for torch models: ``auto`` → cuda when a GPU is
        usable, else cpu. Explicit cuda without a GPU degrades to cpu."""
        pref = self.device or "auto"
        if pref == "cpu":
            return "cpu"
        try:
            import torch

            if torch.cuda.is_available():
                return pref if pref.startswith("cuda") else "cuda"
        except Exception:
            pass
        return "cpu"

    def asr_model_for(self, language: str | None) -> str:
        """Phase 3 routing table. HF fine-tunes contain '/' and load via the
        transformers runtime; plain names (small, large-v3-turbo) use
        faster-whisper. Env JSON overrides win over built-ins."""
        builtin = dict(_BUILTIN_ROUTES)
        if self.whisper_model_overrides_json:
            try:
                parsed = json.loads(self.whisper_model_overrides_json)
                builtin.update({str(k): str(v) for k, v in parsed.items()})
            except (ValueError, TypeError):
                pass
        name = builtin[language] if language and language in builtin else self.whisper_model
        # A2: prefer a local CTranslate2 conversion (batched faster-whisper)
        # over the transformers runtime for HF fine-tunes.
        if "/" in name:
            ct2 = ct2_dir_for(name)
            if (ct2 / "model.bin").exists():
                return str(ct2)
        return name

    def asr_fallback_for(self, language: str | None) -> str:
        """Model to retry with when the routed model fails (e.g. a gated repo
        without access): the language's previous fine-tune, else WHISPER_MODEL."""
        name = _FALLBACK_ROUTES.get(language or "", self.whisper_model)
        if "/" in name:
            ct2 = ct2_dir_for(name)
            if (ct2 / "model.bin").exists():
                return str(ct2)
        return name

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
        parts.append(f"device={self.device}")
        if self.dereverb:
            parts.append("dereverb=on")
        return "|".join(parts)
