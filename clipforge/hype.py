"""Find hype moments in gameplay by listening for volume spikes. Free, no AI."""
import subprocess

import numpy as np

STEP = 0.5  # seconds per loudness reading


def loudness(audio_path, ffmpeg="ffmpeg"):
    raw = subprocess.run([ffmpeg, "-loglevel", "error", "-i", audio_path, "-vn", "-ac", "1", "-ar", "8000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    hop = int(8000 * STEP)
    n = len(x) // hop
    if n == 0:
        raise RuntimeError("This video has no audio to listen to.")
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1))
    return 20 * np.log10(rms + 1e-5)


def _rolling_median(values, window):
    half = window // 2
    return np.array([np.median(values[max(0, i - half): i + half + 1]) for i in range(len(values))])


def hype_moments(audio_path, count=12, clip_len=30.0, lead_in=8.0, ffmpeg="ffmpeg"):
    """Return the moments that are loudest compared with what's around them.

    Each clip starts `lead_in` seconds before the spike, so the build-up is included.
    """
    db = loudness(audio_path, ffmpeg)
    duration = len(db) * STEP
    # "Normal" loudness for each moment = median of the surrounding minute (cheap, block-wise).
    block = int(10 / STEP)
    blocks = [np.median(db[i:i + block]) for i in range(0, len(db), block)]
    base_blocks = _rolling_median(np.array(blocks), 7)
    baseline = np.repeat(base_blocks, block)[: len(db)]
    excitement = db - baseline
    smooth = np.convolve(excitement, np.ones(6) / 6, mode="same")  # ~3 second average

    taken = np.zeros(len(db), dtype=bool)
    span = int(clip_len / STEP)
    moments = []
    while len(moments) < count:
        candidates = np.where(taken, -np.inf, smooth)
        i = int(np.argmax(candidates))
        if not np.isfinite(candidates[i]) or candidates[i] < 3:  # nothing clearly louder than normal
            break
        t = i * STEP
        start = max(0.0, t - lead_in)
        end = min(duration, start + clip_len)
        taken[max(0, i - span): i + span] = True
        moments.append({"start": round(start, 2), "end": round(end, 2), "peak": t, "jump": float(candidates[i])})

    out = []
    for n, m in enumerate(moments):
        mins, secs = divmod(int(m["peak"]), 60)
        hrs, mins = divmod(mins, 60)
        stamp = f"{hrs}:{mins:02d}:{secs:02d}" if hrs else f"{mins}:{secs:02d}"
        out.append({
            "id": f"hype{n + 1}",
            "title": f"Hype moment at {stamp}",
            "start": m["start"], "end": m["end"],
            "hook": f"Volume jumps about {m['jump']:.0f} dB above normal around {stamp}. Preview it to check it's good.",
            "score": int(min(10, max(1, round(m["jump"] / 2)))),
        })
    return out
