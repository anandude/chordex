#!/usr/bin/env python3
"""A2: convert HF Whisper fine-tunes to CTranslate2 for faster-whisper.

The Indic fine-tunes (adalat-ai/*) are transformers checkpoints; running them
through the transformers pipeline is fp32 on CPU / unbatched. Converted, they
use the same batched faster-whisper path as stock models.

Only the root weights are fetched — these repos also hold multi-GB
training checkpoints (checkpoint-*/, optimizer.pt) that are never needed.

Usage (from backend/):
    .venv/bin/python scripts/convert_ct2.py                       # hi + ml defaults
    .venv/bin/python scripts/convert_ct2.py org/model [...] --quantization float16

Output: models/ct2/<org>--<model>/ — picked up automatically by
LyricsConfig.asr_model_for when present (override dir: LYRICS_CT2_DIR).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from pipeline import hf_setup  # noqa: E402,F401  (xet off before downloads)
from pipeline.config import ct2_dir_for  # noqa: E402

DEFAULTS = ["adalat-ai/whisper-medium-hi-high-lr", "adalat-ai/whisper-medium-ml-rmft"]
ROOT_FILES = ["*.json", "*.txt", "model.safetensors", "*.model", "merges.txt", "vocab.json"]


def convert(repo: str, quantization: str, force: bool) -> Path:
    from ctranslate2.converters import TransformersConverter
    from huggingface_hub import snapshot_download

    out = ct2_dir_for(repo)
    if out.exists() and not force:
        print(f"exists: {out}")
        return out
    src = Path(snapshot_download(repo, allow_patterns=ROOT_FILES))
    if not (src / "tokenizer.json").exists():
        # faster-whisper needs tokenizer.json; build it from the slow files
        from transformers import WhisperTokenizerFast

        WhisperTokenizerFast.from_pretrained(str(src)).save_pretrained(str(src))
    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    copy = [f for f in ("tokenizer.json", "preprocessor_config.json") if (src / f).exists()]
    TransformersConverter(str(src), copy_files=copy).convert(
        str(tmp), quantization=quantization, force=True)
    shutil.rmtree(out, ignore_errors=True)
    tmp.rename(out)
    print(f"converted {repo} -> {out}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repos", nargs="*", default=DEFAULTS)
    ap.add_argument("--quantization", default="float16",
                    help="stored precision; runtime compute type is chosen per device")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    for repo in args.repos:
        convert(repo, args.quantization, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
