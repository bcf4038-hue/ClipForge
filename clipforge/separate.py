"""Remove background music from a clip, keeping the voices (Demucs, runs on the CPU, free).

Audio goes in and out through FFmpeg as raw samples, so the only thing used from
Demucs is the model itself. The model (~80 MB) downloads on first use.
"""
import subprocess

import numpy as np

_model = None


def _load_model():
    global _model
    if _model is None:
        from demucs.pretrained import get_model
        _model = get_model("htdemucs")
        _model.eval()
    return _model


def keep_voices(src, out_wav, ffmpeg="ffmpeg", progress=lambda f: None, model=None):
    """Write the voices-only track of `src` (same length and timing) to `out_wav`."""
    import torch
    from demucs.apply import apply_model

    model = model or _load_model()
    sr = model.samplerate
    raw = subprocess.run([ffmpeg, "-v", "error", "-i", src, "-vn", "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    samples = np.frombuffer(raw, dtype=np.float32)
    if samples.size < sr // 10:
        raise RuntimeError("This clip has no audio to clean up.")
    wav = torch.from_numpy(samples.reshape(-1, 2).T.copy())
    # Demucs expects normalized input; undo the scaling afterwards.
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    progress(0.1)
    with torch.no_grad():
        sources = apply_model(model, ((wav - mean) / std)[None], device="cpu", split=True, overlap=0.25,
                              progress=False)[0]
    progress(0.9)
    voices = sources[list(model.sources).index("vocals")] * std + mean
    pcm = voices.clamp(-1, 1).T.contiguous().numpy().astype(np.float32).tobytes()
    subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "f32le", "-ar", str(sr), "-ac", "2", "-i", "-",
                    "-c:a", "pcm_s16le", out_wav], input=pcm, check=True)
    progress(1.0)
    return out_wav
