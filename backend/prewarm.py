"""
prewarm.py
----------
Download the heavy lyrics models *before* the first job needs them.

Usage (from ``backend/``):

    python prewarm.py                 # every language in the ASR routing table
    python prewarm.py ml hi           # only these languages
    python prewarm.py --demucs        # also fetch the separation weights
    python prewarm.py --all           # languages + demucs + chord engine deps

Why this exists: the ASR weights are ~0.5–1.5 GB per language and were being
fetched *inside* the RQ job. On a slow link that blocks the queue for half an
hour and (with a fixed ``job_timeout``) gets the job killed mid-download. There
is nothing job-specific about a model download, so do it here once.

The models are the same ones ``LyricsConfig.asr_model_for()`` routes to, so a
prewarmed language is a cache hit for the job.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from pipeline import hf_setup  # noqa: F401  (must precede huggingface_hub use)
from pipeline.config import LyricsConfig
from pipeline.hf_setup import repo_cache_state

logger = logging.getLogger("prewarm")

#: Routing-table languages worth prewarming by default.
DEFAULT_LANGUAGES = ("ml", "hi")


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def fw_repo(name: str) -> str:
    """CTranslate2 model name → its HF repo (faster-whisper's own resolution)."""
    return name if "/" in name else f"Systran/faster-whisper-{name}"


#: Fallback patterns when the repo file list can't be listed (no network).
FALLBACK_PATTERNS = ("*.safetensors", "*.json", "*.txt", "*.model", "*.bin")


def inference_files(repo_id: str) -> tuple[list[str] | None, float]:
    """Root-level (inference) files of a repo, plus their total bytes.

    ``snapshot_download(repo_id)`` with no filter pulls the ENTIRE repo,
    including training checkpoints: adalat-ai/whisper-medium-hi-high-lr is
    20.7 GB that way, but only 1.5 GB of root-level files are needed to run it.
    (transformers/``from_pretrained`` already fetches just what it needs — this
    explicit list is for prewarm, which uses snapshot_download.)
    """
    try:
        from huggingface_hub import HfApi

        info = HfApi().model_info(repo_id, files_metadata=True)
        root = [f for f in info.siblings if "/" not in f.rfilename]
        if root:
            return [f.rfilename for f in root], float(sum(f.size or 0 for f in root))
    except Exception as exc:
        logger.warning("could not list %s (%s) — falling back to patterns", repo_id, exc)
    return None, 0.0


def download(repo_id: str) -> bool:
    """Fetch a repo's inference files into the HF cache. True on success."""
    cached, size = repo_cache_state(repo_id)
    if cached:
        logger.info("cached   %s (%s)", repo_id, _fmt_bytes(size))
        return True

    patterns, expected = inference_files(repo_id)
    where = f"{_fmt_bytes(size)} already on disk, " if size else ""
    logger.info(
        "fetching %s (%sinference files %s) …",
        repo_id, where, _fmt_bytes(expected) if expected else "(all)",
    )
    t0 = time.time()
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id,
            allow_patterns=list(patterns) if patterns else list(FALLBACK_PATTERNS),
        )
    except Exception as exc:
        logger.error("failed   %s: %s", repo_id, exc)
        return False
    _, size = repo_cache_state(repo_id)
    elapsed = max(0.001, time.time() - t0)
    logger.info(
        "ok       %s — %s in %.1fs (%.0f KB/s)",
        repo_id, _fmt_bytes(size), elapsed, (size / 1024) / elapsed,
    )
    return True


def targets_for(languages: tuple[str, ...]) -> list[str]:
    """Repos needed by these languages, plus the default (auto/en) model."""
    cfg = LyricsConfig.from_env()
    targets: list[str] = []
    for lang in languages:
        repo = fw_repo(cfg.asr_model_for(lang))
        logger.info("language %-4s -> %s", lang, repo)
        if repo not in targets:
            targets.append(repo)
    default_repo = fw_repo(cfg.whisper_model)
    if default_repo not in targets:
        logger.info("language auto -> %s", default_repo)
        targets.append(default_repo)
    return targets


def prewarm(
    languages: tuple[str, ...], demucs: bool = False, dry_run: bool = False
) -> list[str]:
    """Fetch every model the given languages need. Returns the failed repo ids."""
    targets = targets_for(languages)

    if dry_run:
        for repo in targets:
            cached, size = repo_cache_state(repo)
            _, expected = inference_files(repo)
            logger.info(
                "%-42s %s",
                repo,
                f"cached ({_fmt_bytes(size)})" if cached
                else f"would fetch {_fmt_bytes(expected)}",
            )
        return []

    failed = [repo for repo in targets if not download(repo)]

    if demucs:
        try:
            logger.info("fetching demucs weights (%s) …", cfg.demucs_model)
            from demucs.pretrained import get_model

            get_model(cfg.demucs_model)
            logger.info("ok       demucs %s", cfg.demucs_model)
        except Exception as exc:
            logger.error("failed   demucs %s: %s", cfg.demucs_model, exc)
            failed.append(f"demucs:{cfg.demucs_model}")

    return failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[2])
    parser.add_argument("languages", nargs="*", help="ISO codes (default: ml hi)")
    parser.add_argument("--demucs", action="store_true",
                        help="also fetch the vocal-separation weights")
    parser.add_argument("--all", action="store_true",
                        help="languages + demucs")
    parser.add_argument("--dry-run", action="store_true",
                        help="say what would be fetched, download nothing")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    languages = tuple(args.languages) or DEFAULT_LANGUAGES
    failed = prewarm(languages, demucs=args.demucs or args.all, dry_run=args.dry_run)
    if failed:
        logger.error("prewarm finished with %d failure(s): %s", len(failed), failed)
        return 1
    logger.info("prewarm complete — first job per language is now a cache hit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
