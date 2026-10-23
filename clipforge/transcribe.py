"""Fallback transcription with Whisper when a video has no YouTube captions."""


def transcribe(audio_path, duration, progress=lambda p, msg: None, model_size="small"):
    from faster_whisper import WhisperModel  # imported lazily: slow to load

    progress(0.0, f"Loading Whisper '{model_size}' model (first run downloads ~500 MB)...")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(audio_path, word_timestamps=True, vad_filter=True)
    words = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append({"w": text, "s": round(w.start, 3), "e": round(w.end, 3)})
        if duration:
            pct = min(seg.end / duration, 1.0)
            progress(pct, f"Transcribing with Whisper: {int(pct * 100)}%")
    return words
