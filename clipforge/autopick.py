"""Pick the most exciting part of each clip for a montage. Free, no AI.

Every half second gets a score from loudness (hits, explosions) plus motion
(how much the picture changes: big ability effects, flashes, fast action).
"""
import subprocess

import numpy as np

from .hype import STEP, loudness


def motion(path, ffmpeg="ffmpeg"):
    """Average pixel change between frames, one value per STEP seconds."""
    w, h = 64, 36
    raw = subprocess.run([ffmpeg, "-loglevel", "error", "-i", path, "-vf", f"fps={1 / STEP},scale={w}:{h},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, dtype=np.uint8)[: len(raw) // (w * h) * w * h].reshape(-1, h, w).astype(np.float32)
    if len(frames) < 2:
        return np.zeros(max(len(frames), 1))
    diff = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
    return np.concatenate([[diff[0]], diff])


def _signals(path, ffmpeg):
    mot = motion(path, ffmpeg)
    try:
        aud = loudness(path, ffmpeg)
    except (RuntimeError, subprocess.CalledProcessError):
        aud = np.full(len(mot), -60.0)  # no audio track
    n = min(len(mot), len(aud))
    return mot[:n], aud[:n]


def pick(paths, target_total=30.0, ffmpeg="ffmpeg"):
    """Return [{start, end, score}] per path (same order) plus the suggested order, best first."""
    signals = [_signals(p, ffmpeg) for p in paths]
    # Score against all clips together, so the order reflects which clip is strongest overall.
    all_mot = np.concatenate([m for m, _ in signals])
    all_aud = np.concatenate([a for _, a in signals])

    def z(x, ref):
        return (x - ref.mean()) / (ref.std() + 1e-6)

    each = max(3.0, target_total / max(len(paths), 1))
    picks = []
    for mot, aud in signals:
        score = z(mot, all_mot) + 0.7 * z(aud, all_aud)
        duration = len(score) * STEP
        win = int(min(each, duration) / STEP)
        if win < 1 or len(score) == 0:
            picks.append({"start": 0.0, "end": round(duration, 2), "score": 0.0})
            continue
        sums = np.convolve(score, np.ones(win), mode="valid")
        i = int(np.argmax(sums))
        picks.append({"start": round(i * STEP, 2), "end": round(min((i + win) * STEP, duration), 2),
                      "score": round(float(sums[i] / win), 2)})
    order = sorted(range(len(paths)), key=lambda k: -picks[k]["score"])
    return picks, order
