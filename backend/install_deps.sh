#!/usr/bin/env bash
# Reliable install for ChordLens backend (handles vamp/chord-extractor quirks).
set -euo pipefail
cd "$(dirname "$0")"

python -m pip install -U 'pip' 'wheel'
python -m pip install 'numpy==1.26.4' 'setuptools>=69,<81'
# vamp's setup.py imports numpy; disable build isolation
python -m pip install -r requirements.txt --no-build-isolation

echo "Installed. Quick import check:"
python - <<'PY'
import librosa, fastapi, redis, rq
print("  core: ok")
try:
    from chord_extractor.extractors import Chordino
    Chordino(roll_on=1)
    print("  chordino: ok")
except Exception as e:
    print("  chordino: unavailable —", e)
    print("  (template-HMM engine will be used as fallback)")
PY
