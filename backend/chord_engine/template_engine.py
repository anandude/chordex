"""
Improved template-matching chord engine with HMM smoothing.

Upgrades over the original KS-key-profile matcher:
  - Binary / harmonic chord templates (root, 3rd, 5th, 7th, …)
  - Extended vocabulary: maj, min, 7, maj7, min7, dim, aug, sus2, sus4, 5
  - Viterbi decoding with self-transition bias (sequence model)
  - Softmax confidence from cosine similarities
  - Shared postprocess (merge, key, tempo, beat snap)
"""

from __future__ import annotations

import os

import numpy as np
import librosa

from postprocess import build_result

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _chroma_config() -> tuple[str, int, bool]:
    """S4: tunable chroma frontend (env-driven, defaults = current behavior).

    - CHROMA_KIND: "cqt" (default) | "cens" | "stft"
    - CHROMA_HOP: hop length in samples (default 2048, ~93 ms @ 22.05 kHz)
    - CHROMA_NN_FILTER: "0" disables nn_filter temporal smoothing
    Unknown kinds fall back to "cqt" with a warning. These are profiling
    knobs — validate any non-default against the chord eval harness (A3)
    before shipping, since frontend choice moves accuracy ±1pp.
    """
    import logging as _logging

    kind = os.getenv("CHROMA_KIND", "cqt").strip().lower()
    if kind not in {"cqt", "cens", "stft"}:
        _logging.getLogger(__name__).warning(
            "Unknown CHROMA_KIND=%r, falling back to 'cqt'", kind
        )
        kind = "cqt"
    try:
        hop = int(os.getenv("CHROMA_HOP", "2048"))
    except ValueError:
        hop = 2048
    nn_filter = os.getenv("CHROMA_NN_FILTER", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    return kind, hop, nn_filter

# Chord quality → pitch-class offsets from root (weighted)
# Weights encourage root + fifth slightly over third for guitar mixes.
_QUALITIES: dict[str, list[tuple[int, float]]] = {
    "": [(0, 1.0), (4, 0.85), (7, 0.95)],                          # major
    "m": [(0, 1.0), (3, 0.85), (7, 0.95)],                          # minor
    "7": [(0, 1.0), (4, 0.75), (7, 0.9), (10, 0.8)],                # dominant 7
    "maj7": [(0, 1.0), (4, 0.75), (7, 0.85), (11, 0.8)],            # major 7
    "m7": [(0, 1.0), (3, 0.75), (7, 0.85), (10, 0.8)],              # minor 7
    "dim": [(0, 1.0), (3, 0.85), (6, 0.9)],                         # diminished
    "aug": [(0, 1.0), (4, 0.85), (8, 0.9)],                         # augmented
    "sus2": [(0, 1.0), (2, 0.85), (7, 0.95)],
    "sus4": [(0, 1.0), (5, 0.85), (7, 0.95)],
    "5": [(0, 1.0), (7, 1.0)],                                      # power chord
}


def _build_templates() -> tuple[list[str], np.ndarray]:
    names: list[str] = []
    rows: list[np.ndarray] = []
    for i, note in enumerate(NOTES):
        for quality, intervals in _QUALITIES.items():
            vec = np.zeros(12, dtype=np.float64)
            for offset, weight in intervals:
                vec[(i + offset) % 12] = weight
            # light overtone smear on root (helps real instruments)
            vec[(i + 12) % 12] = max(vec[i], 1.0)
            names.append(note + quality)
            rows.append(vec)
    # No-chord / noise template: flat chroma
    names.append("N")
    rows.append(np.ones(12, dtype=np.float64) * 0.15)
    mat = np.array(rows)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return names, mat / norms


_CHORD_NAMES, _TEMPLATE_NORM = _build_templates()
_N_CHORDS = len(_CHORD_NAMES)
_N_QUALITIES = 10  # templates per root in _build_templates order

# A2.1: key-conditioned transition priors (log-space nudges — deliberately
# small next to self_bias=3.0 so strong acoustic evidence always wins).
_IN_KEY_BONUS = 0.8
_OUT_KEY_PENALTY = 0.8
_QUALITY_NUDGE = 0.25
# Semitone offsets of diatonic roots for each key type.
_DIATONIC = {
    "major": {0, 2, 4, 5, 7, 9, 11},
    "minor": {0, 2, 3, 5, 7, 8, 10},  # natural minor
}
# Qualities that "belong" to each key type (dim/aug/sus/power stay neutral).
_MAJOR_QUALITY = {"", "maj7", "7", "sus2", "sus4", "5"}
_MINOR_QUALITY = {"m", "m7"}


def _split_name(name: str) -> tuple[int, str]:
    """Chord template name -> (root pitch class 0-11, quality suffix)."""
    if name == "N":
        return -1, "N"
    root_len = 2 if len(name) >= 2 and name[1] == "#" else 1
    return NOTES.index(name[:root_len]), name[root_len:]


def _key_aware_transitions(
    key: str, self_bias: float = 3.0
) -> np.ndarray | None:
    """Build an (N, N) log-transition matrix biased toward the estimated key.

    Diatonic target roots get +bonus, chromatic outsiders get -penalty, and
    key-family qualities (major triads in major keys, minor in minor) get a
    small nudge — fixing the classic C<->Am / G<->Em / sus<->maj flicker.
    Returns None for unparseable keys so callers fall back to uniform.
    """
    try:
        tonic_str, _, key_type = key.strip().partition(" ")
        tonic = NOTES.index(tonic_str)
        diatonic = _DIATONIC[key_type]
    except (ValueError, KeyError, AttributeError):
        return None

    log_trans = np.full((_N_CHORDS, _N_CHORDS), 0.0)
    np.fill_diagonal(log_trans, self_bias)
    for j, name in enumerate(_CHORD_NAMES):
        root, quality = _split_name(name)
        if root < 0:  # N target stays neutral
            continue
        in_key = (root - tonic) % 12 in diatonic
        prior = _IN_KEY_BONUS if in_key else -_OUT_KEY_PENALTY
        if key_type == "major" and quality in _MAJOR_QUALITY:
            prior += _QUALITY_NUDGE
        elif key_type == "minor" and quality in _MINOR_QUALITY:
            prior += _QUALITY_NUDGE
        log_trans[:, j] += prior
    return log_trans


def _key_aware_enabled() -> bool:
    """KEY_AWARE=1 enables two-pass decode (key first, then key-conditioned
    transitions). Default off until A2.2 validates it on the eval harness."""
    return os.getenv("KEY_AWARE", "0").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _viterbi(
    log_emission: np.ndarray,
    self_bias: float = 2.5,
    log_trans: np.ndarray | None = None,
) -> np.ndarray:
    """
    Simple HMM Viterbi over chord labels.
    Transition: prefer staying on same chord (self_bias in log-space).
    log_emission: (T, N) log-probabilities / scores.
    log_trans: optional (N, N) transition matrix (A2.1 key-aware); when None
      a uniform matrix with self_bias on the diagonal is used (legacy).
    """
    t_steps, n_states = log_emission.shape
    if t_steps == 0:
        return np.array([], dtype=int)

    if log_trans is None:
        # Transition matrix in log space: self_bias for stay, 0 for change
        # (uniform over changes — music theory transitions can be added later)
        log_trans = np.full((n_states, n_states), 0.0)
        np.fill_diagonal(log_trans, self_bias)

    # Uniform prior
    log_dp = np.empty((t_steps, n_states))
    back = np.zeros((t_steps, n_states), dtype=int)
    log_dp[0] = log_emission[0]

    for t in range(1, t_steps):
        # for each state j: max_i dp[t-1,i] + trans[i,j] + emission[t,j]
        scores = log_dp[t - 1][:, None] + log_trans  # (N, N)
        back[t] = np.argmax(scores, axis=0)
        log_dp[t] = scores[back[t], np.arange(n_states)] + log_emission[t]

    path = np.empty(t_steps, dtype=int)
    path[-1] = int(np.argmax(log_dp[-1]))
    for t in range(t_steps - 2, -1, -1):
        path[t] = back[t + 1, path[t + 1]]
    return path


class TemplateChordEngine:
    name = "template-hmm"

    def analyze(self, file_path: str) -> dict:
        y, sr = librosa.load(file_path, sr=22050, mono=True)
        y_harm, _ = librosa.effects.hpss(y)

        chroma_kind, hop_length, use_nn_filter = _chroma_config()
        if chroma_kind == "cens":
            # chroma_cens: CQT + L1-normalized temporal smoothing built in;
            # generally faster than raw CQT + nn_filter at similar quality.
            chroma = librosa.feature.chroma_cens(
                y=y_harm, sr=sr, hop_length=hop_length, n_chroma=12
            )
        elif chroma_kind == "stft":
            # chroma_stft: cheapest frontend; coarser pitch resolution.
            chroma = librosa.feature.chroma_stft(
                y=y_harm, sr=sr, hop_length=hop_length, n_chroma=12
            )
        else:
            chroma = librosa.feature.chroma_cqt(
                y=y_harm, sr=sr, hop_length=hop_length, n_chroma=12
            )
        # Mild temporal smoothing on continuous chroma (not discrete labels).
        # Fall back to raw chroma if the clip is too short for nn_filter.
        try:
            if use_nn_filter and chroma.shape[1] >= 8:
                chroma = librosa.decompose.nn_filter(
                    chroma, aggregate=np.median, metric="cosine"
                )
            chroma = librosa.util.normalize(chroma, axis=0)
        except Exception:
            chroma = librosa.util.normalize(chroma, axis=0)

        chroma_T = chroma.T  # (T, 12)
        norms = np.linalg.norm(chroma_T, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        chroma_norm = chroma_T / norms

        # Cosine similarities → (T, N)
        sims = chroma_norm @ _TEMPLATE_NORM.T
        # Softmax over chords for emission probabilities
        # temperature < 1 sharpens; > 1 softens
        temperature = 0.15
        sims_stable = sims - sims.max(axis=1, keepdims=True)
        exp_s = np.exp(sims_stable / temperature)
        probs = exp_s / exp_s.sum(axis=1, keepdims=True)
        log_emission = np.log(probs + 1e-12)

        # A2.1: two-pass decode. Pass 1 estimates the global key from the
        # already-computed chroma (no extra CQT); pass 2 decodes with
        # key-conditioned transitions. Off by default (KEY_AWARE=0).
        est_key: str | None = None
        log_trans: np.ndarray | None = None
        if _key_aware_enabled():
            try:
                from postprocess import key_from_chroma

                est_key = key_from_chroma(chroma.mean(axis=1))
                log_trans = _key_aware_transitions(est_key)
            except Exception:
                est_key, log_trans = None, None

        path = _viterbi(log_emission, self_bias=3.0, log_trans=log_trans)
        confidences = probs[np.arange(len(path)), path]

        frame_times = librosa.frames_to_time(
            np.arange(len(path)), sr=sr, hop_length=hop_length
        )
        total_duration = len(y) / sr

        # Run-length encode path
        raw_events: list[dict] = []
        i = 0
        n = len(path)
        while i < n:
            idx = int(path[i])
            j = i + 1
            conf_sum = float(confidences[i])
            while j < n and path[j] == idx:
                conf_sum += float(confidences[j])
                j += 1
            conf_avg = conf_sum / (j - i)
            start = float(frame_times[i])
            end = float(frame_times[j]) if j < n else total_duration
            # Low-confidence → N
            chord = _CHORD_NAMES[idx]
            if conf_avg < 0.12:
                chord = "N"
            raw_events.append(
                {
                    "timestamp": start,
                    "end": end,
                    "chord": chord,
                    "confidence": conf_avg,
                }
            )
            i = j

        return build_result(
            raw_events,
            y=y,
            sr=sr,
            engine=self.name,
            min_duration=0.45,
            snap_to_beats=None,
            key=est_key,  # skips build_result's own key CQT when known
        )
