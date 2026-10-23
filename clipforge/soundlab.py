"""Sound Lab: turn any video or audio into sound effects and music for the library."""
import os
import re
import subprocess

import numpy as np

PEAK_BINS = 3000


def prepare(src, out_dir, ffmpeg="ffmpeg"):
    """Make a browser-playable preview and waveform peaks for a source file."""
    preview = os.path.join(out_dir, "preview.mp3")
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", src, "-vn", "-ac", "2", "-b:a", "128k", preview],
                   check=True)
    # Decode a low-rate mono copy just to draw the waveform.
    raw = subprocess.run([ffmpeg, "-loglevel", "error", "-i", src, "-vn", "-ac", "1", "-ar", "8000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    samples = np.abs(np.frombuffer(raw, dtype="<i2").astype(np.float32)) / 32768
    duration = len(samples) / 8000
    if len(samples) == 0:
        raise RuntimeError("This file has no audio.")
    bins = np.array_split(samples, min(PEAK_BINS, len(samples)))
    peaks = [round(float(b.max()), 3) for b in bins]
    return {"duration": duration, "peaks": peaks}


def find_sounds(src, threshold_db=-35, min_silence=0.3, min_len=0.005, max_len=20.0, ffmpeg="ffmpeg"):
    """Split audio wherever there's silence. Returns [{start, end}] in seconds."""
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-i", src, "-vn",
         "-af", f"silencedetect=noise={threshold_db}dB:d={min_silence}", "-f", "null", "-"],
        capture_output=True, text=True)
    log = proc.stderr
    dur_match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", log)
    duration = (int(dur_match[1]) * 3600 + int(dur_match[2]) * 60 + float(dur_match[3])) if dur_match else None
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]

    # Sound lives between the end of one silence and the start of the next.
    edges = [0.0] + ends
    stops = starts + ([duration] if duration and len(starts) == len(ends) else [])
    out = []
    for a, b in zip(edges, stops):
        if b - a < min_len:
            continue
        a, b = max(a - 0.03, 0), b + 0.05  # a little air so nothing gets clipped
        if duration:
            b = min(b, duration)
        out.append({"start": round(a, 3), "end": round(min(b, a + max_len), 3)})
    return out


def export(src, start, end, out_path, normalize=True, ffmpeg="ffmpeg"):
    """Cut [start, end] out as an mp3 with tiny fades so it doesn't click."""
    length = end - start
    fade = min(0.02, length / 4)
    af = f"afade=t=in:d={fade:.3f},afade=t=out:st={max(length - fade, 0):.3f}:d={fade:.3f}"
    if normalize:
        af += ",loudnorm=I=-16:TP=-1.5:LRA=11"
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
                    "-i", src, "-vn", "-af", af, "-ar", "48000", "-ac", "2", "-b:a", "192k", out_path],
                   check=True)
    return out_path
