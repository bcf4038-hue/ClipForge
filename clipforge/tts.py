"""AI voiceover with free Microsoft neural voices, through the unofficial edge-tts tool."""
import asyncio
import hashlib
import json
import os

# A short list of natural-sounding English voices that suit Shorts.
VOICES = [
    ("en-US-ChristopherNeural", "Christopher: deep US male"),
    ("en-US-AndrewNeural", "Andrew: warm US male"),
    ("en-US-BrianNeural", "Brian: casual US male"),
    ("en-US-GuyNeural", "Guy: announcer US male"),
    ("en-US-EricNeural", "Eric: US male"),
    ("en-US-JennyNeural", "Jenny: friendly US female"),
    ("en-US-AriaNeural", "Aria: confident US female"),
    ("en-US-AvaNeural", "Ava: US female"),
    ("en-US-EmmaNeural", "Emma: US female"),
    ("en-GB-RyanNeural", "Ryan: British male"),
    ("en-GB-SoniaNeural", "Sonia: British female"),
]


def list_voices(timeout=8):
    """Curated voices first, then every other English voice the service offers.

    The online list gets `timeout` seconds; if it's slow or down, the curated list is enough.
    """
    out = [{"id": v, "name": n} for v, n in VOICES]
    try:
        import edge_tts
        known = {v for v, _ in VOICES}
        extra = asyncio.run(asyncio.wait_for(edge_tts.list_voices(), timeout))
        for v in sorted(extra, key=lambda x: x["ShortName"]):
            if v["Locale"].startswith("en-") and v["ShortName"] not in known:
                out.append({"id": v["ShortName"], "name": f"{v['ShortName']} ({v.get('Gender', '')})"})
    except Exception:
        pass  # offline or service changed: the curated list still works
    return out


def synthesize(text, voice, rate, out_dir):
    """Speak `text` to an mp3. Returns {"path", "words": [{w, s, e}], "duration"}."""
    os.makedirs(out_dir, exist_ok=True)
    key = hashlib.sha1(f"{voice}|{rate}|{text}".encode("utf-8")).hexdigest()[:16]
    mp3 = os.path.join(out_dir, f"vo_{key}.mp3")
    meta = os.path.join(out_dir, f"vo_{key}.json")
    if os.path.exists(mp3) and os.path.exists(meta):
        with open(meta) as f:
            return json.load(f)

    import edge_tts

    async def run():
        comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
        words = []
        with open(mp3, "wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / 1e7  # 100-nanosecond units
                    words.append({"w": chunk["text"], "s": round(start, 3),
                                  "e": round(start + chunk["duration"] / 1e7, 3)})
        return words

    try:
        words = asyncio.run(run())
    except Exception as e:
        if os.path.exists(mp3):
            os.remove(mp3)
        raise RuntimeError(f"The AI voice failed ({e.__class__.__name__}: {e}). Check your internet, try a "
                           "different voice, or close ClipForge and open start.bat again to update it.") from e
    result = {"path": mp3, "words": words, "duration": (words[-1]["e"] + 0.3) if words else 0}
    with open(meta, "w") as f:
        json.dump(result, f)
    return result
