"""Synthesize the bundled starter sounds. Everything here is generated from scratch,
so the sounds are free to use on any channel."""
import os
import subprocess
import wave

import numpy as np

SR = 44100
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sounds", "starter")
rng = np.random.default_rng(7)


def t(sec):
    return np.arange(int(SR * sec)) / SR


def lowpass(x, cutoff):
    """One-pole lowpass; cutoff may be an array (Hz per sample)."""
    cutoff = np.broadcast_to(cutoff, x.shape)
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.zeros_like(x)
    prev = 0.0
    for i in range(len(x)):
        prev = (1 - a[i]) * x[i] + a[i] * prev
        y[i] = prev
    return y


def norm(x, peak=0.9):
    return x / (np.max(np.abs(x)) + 1e-9) * peak


def write_wav(path, x):
    x = np.atleast_2d(x)
    if x.shape[0] == 1:
        x = np.vstack([x, x])
    data = (np.clip(x.T, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


def whoosh():
    tt = t(0.7)
    env = np.sin(np.pi * tt / tt[-1]) ** 2
    noise = rng.standard_normal(len(tt))
    sweep = 300 + 5000 * env
    band = lowpass(noise, sweep) - lowpass(noise, sweep * 0.25)
    pan = np.linspace(-1, 1, len(tt))
    x = norm(band * env)
    return np.vstack([x * (1 - pan) / 2 + x * 0.3, x * (1 + pan) / 2 + x * 0.3])


def pop():
    tt = t(0.12)
    freq = 900 * np.exp(-tt * 40) + 200
    phase = 2 * np.pi * np.cumsum(freq) / SR
    return norm(np.sin(phase) * np.exp(-tt * 45))


def ding():
    tt = t(1.6)
    f = 1318.5
    x = sum(a * np.sin(2 * np.pi * f * m * tt) * np.exp(-tt * d)
            for m, a, d in [(1, 1.0, 3), (2.01, 0.4, 5), (3.0, 0.2, 8), (4.2, 0.1, 12)])
    return norm(x * (1 - np.exp(-tt * 400)), 0.8)


def boom():
    tt = t(1.8)
    freq = 110 * np.exp(-tt * 6) + 38
    sub = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-tt * 2.2)
    hit = lowpass(rng.standard_normal(len(tt)), 600) * np.exp(-tt * 18)
    return norm(np.tanh(2 * (sub + hit * 2)))


def click():
    tt = t(0.03)
    x = rng.standard_normal(len(tt)) * np.exp(-tt * 300)
    return norm(x - lowpass(x, 1500), 0.7)


# ---------- music beds ----------

def note(freq, dur, kind="pad"):
    tt = t(dur)
    if kind == "pad":
        x = sum(np.sin(2 * np.pi * freq * d * tt) for d in (1, 1.003, 0.997, 2.0 * 0.5))
        env = np.minimum(1, tt / 0.4) * np.minimum(1, (dur - tt) / 0.4)
    elif kind == "pluck":
        x = np.sign(np.sin(2 * np.pi * freq * tt)) * 0.4 + np.sin(2 * np.pi * freq * tt)
        x = lowpass(x, 2500)
        env = np.exp(-tt * 7)
    else:  # bass
        x = np.sin(2 * np.pi * freq * tt) + 0.3 * np.sin(4 * np.pi * freq * tt)
        env = np.minimum(1, tt / 0.01) * np.exp(-tt * 2)
    return x * env


def kick(dur=0.35):
    tt = t(dur)
    freq = 120 * np.exp(-tt * 25) + 45
    return np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-tt * 9)


def hat(dur=0.06):
    tt = t(dur)
    x = rng.standard_normal(len(tt))
    return (x - lowpass(x, 7000)) * np.exp(-tt * 60) * 0.5


def mtof(m):
    return 440 * 2 ** ((m - 69) / 12)


def bed(bpm, chords, bass_roots, beat, pluck_pattern):
    beat_s = 60 / bpm
    bar = beat_s * 4
    total = bar * len(chords) * 2
    out = np.zeros(int(SR * total) + SR)

    def add(x, at, gain):
        i = int(at * SR)
        out[i:i + len(x)] += x[: len(out) - i] * gain

    for rep in range(2):
        for b, (chord, root) in enumerate(zip(chords, bass_roots)):
            t0 = (rep * len(chords) + b) * bar
            for m in chord:
                add(note(mtof(m), bar, "pad"), t0, 0.06)
            for q in range(4):
                add(note(mtof(root), beat_s * 0.9, "bass"), t0 + q * beat_s, 0.18)
            for step, idx in enumerate(pluck_pattern):
                if idx is not None:
                    add(note(mtof(chord[idx] + 12), beat_s, "pluck"), t0 + step * beat_s / 2, 0.08)
            if beat:
                for q in range(4):
                    if q % 2 == 0 or beat == "upbeat":
                        add(kick(), t0 + q * beat_s, 0.5)
                    add(hat(), t0 + q * beat_s + beat_s / 2, 0.25)
    out = out[: int(SR * total)]
    # Gentle tone shaping and soft clip.
    out = np.tanh(lowpass(out, 6000) * 1.5)
    stereo = np.vstack([out, np.roll(out, int(SR * 0.012))])
    return norm(stereo, 0.85)


def to_mp3(wav_path):
    mp3 = wav_path[:-4] + ".mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav_path, "-b:a", "160k", mp3], check=True)
    os.remove(wav_path)


if __name__ == "__main__":
    sfx_dir = os.path.join(ROOT, "sfx")
    music_dir = os.path.join(ROOT, "music")
    os.makedirs(sfx_dir, exist_ok=True)
    os.makedirs(music_dir, exist_ok=True)
    for name, fn in [("whoosh", whoosh), ("pop", pop), ("ding", ding), ("boom", boom), ("click", click)]:
        write_wav(os.path.join(sfx_dir, f"{name}.wav"), fn())
    # Am - F - C - G and C - G - Am - F, original progressions.
    chill = bed(84, [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]], [45, 41, 36, 43],
                "chill", [0, None, 1, 2, None, 1, 0, None])
    upbeat = bed(118, [[60, 64, 67], [55, 59, 62], [57, 60, 64], [53, 57, 60]], [36, 43, 45, 41],
                 "upbeat", [0, 1, 2, 1, 0, 1, 2, 1])
    for name, x in [("chill_lofi_loop", chill), ("upbeat_loop", upbeat)]:
        p = os.path.join(music_dir, name + ".wav")
        write_wav(p, x)
        to_mp3(p)
    print("Starter sounds written to", os.path.abspath(ROOT))
