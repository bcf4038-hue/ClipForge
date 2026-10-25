"""ElevenLabs voices (paid, your own API key). Uses their plain web API, no extra package.

Every request is cached by voice + text, so remaking a video never spends credits twice.
"""
import hashlib
import json
import os
import urllib.error
import urllib.request

API = "https://api.elevenlabs.io"
MODEL = "eleven_multilingual_v2"  # their most natural model; about 1 credit per character


def _call(key, path, body=None, timeout=60):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"xi-api-key": key, "Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(_friendly(e.code, e.read().decode("utf-8", "replace"))) from e
    except urllib.error.URLError as e:
        raise RuntimeError("Couldn't reach ElevenLabs. Check your internet connection.") from e


def _friendly(code, text):
    try:
        detail = json.loads(text).get("detail")
    except ValueError:
        detail = None
    status = detail.get("status", "") if isinstance(detail, dict) else ""
    message = detail.get("message", "") if isinstance(detail, dict) else str(detail or text)[:300]
    if code == 401 and status != "quota_exceeded" and "quota" not in message.lower():
        return ("ElevenLabs rejected your API key. Make a new one at elevenlabs.io (Developers > API Keys) "
                "and paste it in Settings.")
    if status == "quota_exceeded" or "quota" in message.lower() or "credits" in message.lower():
        return "You're out of ElevenLabs credits for this month. Nothing more was charged. " + message
    if status == "voice_not_found" or code == 404:
        return "That ElevenLabs voice wasn't found. Pick another voice, or add it to My Voices on elevenlabs.io."
    if status == "detected_unusual_activity":
        return "ElevenLabs blocked free-plan use from this connection. A paid plan fixes this. " + message
    return f"ElevenLabs error ({code}): {message}"


def list_voices(key):
    """Voices in the account's My Voices (including ones added from the Voice Library), then ElevenLabs' own."""
    voices, token = [], None
    for _ in range(5):
        path = "/v2/voices?page_size=100" + (f"&next_page_token={token}" if token else "")
        data = json.loads(_call(key, path, timeout=20))
        voices += data.get("voices", [])
        token = data.get("next_page_token")
        if not data.get("has_more") or not token:
            break
    out = []
    for v in voices:
        labels = v.get("labels") or {}
        extra = ", ".join(x for x in (labels.get("gender"), labels.get("accent"), labels.get("age")) if x)
        out.append({"id": "el:" + v["voice_id"], "name": v.get("name") or v["voice_id"],
                    "detail": extra, "mine": v.get("category") != "premade",
                    "preview": v.get("preview_url") or ""})
    out.sort(key=lambda v: (not v["mine"], v["name"].lower()))
    return out


def credits(key):
    s = json.loads(_call(key, "/v1/user/subscription", timeout=20))
    return {"tier": s.get("tier", ""), "used": s.get("character_count", 0), "limit": s.get("character_limit", 0),
            "left": max(0, s.get("character_limit", 0) - s.get("character_count", 0)),
            "resets": s.get("next_character_count_reset_unix")}


def cached_path(voice_id, text, out_dir):
    key = hashlib.sha1(f"{MODEL}|{voice_id}|{text}".encode("utf-8")).hexdigest()[:16]
    return os.path.join(out_dir, f"el_{key}.mp3")


def synthesize(key, voice_id, text, out_dir):
    """Speak `text` to an mp3 and return its path. Cached: the same line is only paid for once."""
    os.makedirs(out_dir, exist_ok=True)
    path = cached_path(voice_id, text, out_dir)
    if os.path.exists(path):
        return path
    audio = _call(key, f"/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128",
                  {"text": text, "model_id": MODEL}, timeout=120)
    with open(path + ".tmp", "wb") as f:
        f.write(audio)
    os.replace(path + ".tmp", path)
    return path
