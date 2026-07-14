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

import numpy as np
import librosa

from postprocess import build_result

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

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


def _viterbi(log_emission: np.ndarray, self_bias: float = 2.5) -> np.ndarray:
    """
    Simple HMM Viterbi over chord labels.
    Transition: prefer staying on same chord (self_bias in log-space).
    log_emission: (T, N) log-probabilities / scores.
    """
    t_steps, n_states = log_emission.shape
    if t_steps == 0:
        return np.array([], dtype=int)

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

        hop_length = 2048  # ~93 ms at 22.05 kHz — tighter than old 4096@44.1k
        chroma = librosa.feature.chroma_cqt(
            y=y_harm, sr=sr, hop_length=hop_length, n_chroma=12
        )
        # Mild temporal smoothing on continuous chroma (not discrete labels).
        # Fall back to raw chroma if the clip is too short for nn_filter.
        try:
            if chroma.shape[1] >= 8:
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

        path = _viterbi(log_emission, self_bias=3.0)
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
            snap_to_beats=True,
        )
