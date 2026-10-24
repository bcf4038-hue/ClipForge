"""ClipForge Editor: timeline projects, rendering them to 9:16 video, and learning the user's habits.

A project is plain JSON:
    clips:  video track, played in order   {id, media, in, out, volume, audio, framing}
            audio: "keep" (everything), "voice" (background music removed) or "mute"
    texts:  text overlays                  {id, text, start, end, font, size, color, outline,
                                            outline_color, box, box_color, box_opacity, x, y, anim, uppercase}
    sounds: sound effects                  {id, sound, start, volume}
    music:  background track or None       {sound, volume}
"""
import json
import os
import statistics
import subprocess
import time
import uuid
from collections import Counter

from . import captions, crop
from .render import probe

W, H = crop.OUT_W, crop.OUT_H

TEXT_DEFAULT = {"text": "Your text", "font": "Arial Black", "size": 90, "color": "#FFFFFF", "outline": 8,
                "outline_color": "#000000", "box": False, "box_color": "#000000", "box_opacity": 0.6,
                "x": 0.5, "y": 0.2, "anim": "pop", "uppercase": True}


def new_id():
    return uuid.uuid4().hex[:8]


def new_project():
    return {"id": uuid.uuid4().hex[:10], "name": "Untitled", "clips": [], "texts": [], "sounds": [],
            "music": None, "updated": time.time()}


def audio_mode(c):
    """keep / voice / mute; older projects only had a "muted" flag."""
    return c.get("audio") or ("mute" if c.get("muted") else "keep")


def clip_len(c):
    return max(0.0, float(c["out"]) - float(c["in"]))


def duration(p):
    return sum(clip_len(c) for c in p["clips"])


def cut_times(p):
    out, t = [], 0.0
    for c in p["clips"][:-1]:
        t += clip_len(c)
        out.append(round(t, 3))
    return out


# ---------- rendering ----------

def _text_style(i, t):
    font, size = t.get("font", "Arial Black"), int(t.get("size", 90))
    color = captions._ass_color(t.get("color", "#FFFFFF"))
    if t.get("box"):
        back = captions._alpha_color(t.get("box_color", "#000000"), t.get("box_opacity", 0.6))
        return f"Style: T{i},{font},{size},{color},{color},{back},&H00000000,-1,0,0,0,100,100,0,0,3,18,0,5,40,40,0,1"
    outline = captions._ass_color(t.get("outline_color", "#000000"))
    return (f"Style: T{i},{font},{size},{color},{color},{outline},&H80000000,-1,0,0,0,100,100,0,0,1,"
            f"{int(t.get('outline', 8))},3,5,40,40,0,1")


def build_ass(p, total):
    styles, lines = [], []
    anims = {"pop": r"\fscx35\fscy35\t(0,180,\fscx100\fscy100)", "fade": r"\fad(200,200)", "none": ""}
    for i, t in enumerate(p.get("texts", [])):
        start, end = max(0.0, float(t["start"])), min(float(t["end"]), total)
        if end <= start or not str(t.get("text", "")).strip():
            continue
        styles.append(_text_style(i, t))
        text = t["text"].upper() if t.get("uppercase", True) else t["text"]
        text = captions._escape(text).replace("\n", r"\N")
        pos = f"\\an5\\pos({int(float(t.get('x', 0.5)) * W)},{int(float(t.get('y', 0.2)) * H)})"
        lines.append(f"Dialogue: {i},{captions._ts(start)},{captions._ts(end)},T{i},,0,0,0,,"
                     f"{{{pos}{anims.get(t.get('anim'), '')}}}{text}")
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{chr(10).join(styles)}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{chr(10).join(lines)}
"""


def render_project(p, media_path, sound_path, out_path, workdir, ffmpeg="ffmpeg", ffprobe="ffprobe",
                   fonts_dir=None, progress=lambda f: None, voice_path=None, text_images=None):
    """Render the whole timeline to a 1080x1920 MP4.

    text_images: {text id: png path}. The editor draws each text in the browser exactly as the
    preview shows it (fonts, outline, color emoji), and those images are placed here at the same
    spot and time. Texts without an image fall back to the subtitle renderer.
    """
    text_images = text_images or {}
    if not p["clips"]:
        raise RuntimeError("Add at least one clip to the timeline first.")
    os.makedirs(workdir, exist_ok=True)
    total = duration(p)
    fmt = "aformat=sample_rates=48000:channel_layouts=stereo"
    inputs, filters, joined = [], [], []
    for i, c in enumerate(p["clips"]):
        path = media_path(c["media"])
        _, _, _, has_audio = probe(path, ffprobe)
        idx = inputs.count("-i")  # next input's number
        inputs += ["-i", os.path.abspath(path)]
        a, b = float(c["in"]), float(c["out"])
        cover = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
        if c.get("framing") == "fit":
            # Whole frame in the middle, blurred copy filling the background.
            filters.append(f"[{idx}:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS,split=2[bg{i}][fg{i}];"
                           f"[bg{i}]{cover},boxblur=25:2[bgb{i}];"
                           f"[fg{i}]scale={W}:{H}:force_original_aspect_ratio=decrease[fgs{i}];"
                           f"[bgb{i}][fgs{i}]overlay=(W-w)/2:(H-h)/2,fps=30,setsar=1,format=yuv420p[v{i}]")
        else:
            filters.append(f"[{idx}:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS,{cover},fps=30,setsar=1,"
                           f"format=yuv420p[v{i}]")
        mode = audio_mode(c)
        volume = 0.0 if mode == "mute" else float(c.get("volume", 1.0))
        voices = voice_path(c["media"]) if (mode == "voice" and voice_path) else None
        if voices and volume > 0:
            # Same timeline as the source, so the same trim lines it up.
            vidx = inputs.count("-i")  # next input's number
            inputs += ["-i", os.path.abspath(voices)]
            filters.append(f"[{vidx}:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,{fmt},volume={volume:.3f}[a{i}]")
        elif has_audio and volume > 0:
            filters.append(f"[{idx}:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,{fmt},volume={volume:.3f}[a{i}]")
        else:
            filters.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{b - a:.3f}[a{i}]")
        joined.append(f"[v{i}][a{i}]")
    filters.append(f"{''.join(joined)}concat=n={len(joined)}:v=1:a=1[vcat][acat]")

    fallback = {**p, "texts": [t for t in p.get("texts", []) if t["id"] not in text_images]}
    with open(os.path.join(workdir, "texts.ass"), "w", encoding="utf-8") as f:
        f.write(build_ass(fallback, total))
    vf = "[vcat]ass=texts.ass"
    if fonts_dir and os.path.isdir(fonts_dir):
        vf += ":fontsdir=" + os.path.relpath(fonts_dir, workdir).replace("\\", "/")
    filters.append(vf + "[vtxt]")
    current = "[vtxt]"
    for k, t in enumerate(p.get("texts", [])):
        img = text_images.get(t["id"])
        start, end = max(0.0, float(t["start"])), min(float(t["end"]), total)
        if not img or end <= start:
            continue
        idx = inputs.count("-i")  # next input's number
        inputs += ["-loop", "1", "-framerate", "30", "-t", f"{total:.3f}", "-i", os.path.abspath(img)]
        anim = t.get("anim", "pop")
        if anim == "pop":
            # Grows from 35% to full size in 0.18 s, like the preview.
            grow = f"min(1\\,0.35+0.65*max(0\\,t-{start:.3f})/0.18)"
            prep = f"format=rgba,scale=w='max(2\\,trunc(iw*{grow}/2)*2)':h=-2:eval=frame"
        elif anim == "fade":
            prep = (f"format=rgba,fade=t=in:st={start:.3f}:d=0.2:alpha=1,"
                    f"fade=t=out:st={max(start, end - 0.2):.3f}:d=0.2:alpha=1")
        else:
            prep = "format=rgba"
        x, y = float(t.get("x", 0.5)) * W, float(t.get("y", 0.2)) * H
        filters.append(f"[{idx}:v]{prep}[img{k}]")
        filters.append(f"{current}[img{k}]overlay=x='{x:.1f}-w/2':y='{y:.1f}-h/2':eval=frame:"
                       f"enable='between(t\\,{start:.3f}\\,{end:.3f})'[vo{k}]")
        current = f"[vo{k}]"
    filters.append(f"{current}format=yuv420p[v]")

    mix = ["[acat]"]
    for k, s in enumerate(p.get("sounds", [])):
        if float(s["start"]) >= total:
            continue
        idx = inputs.count("-i")  # next input's number
        inputs += ["-i", os.path.abspath(sound_path(s["sound"]))]
        delay = int(max(float(s["start"]), 0) * 1000)
        filters.append(f"[{idx}:a]{fmt},volume={float(s.get('volume', 0.8)):.3f},adelay=delays={delay}:all=1[s{k}]")
        mix.append(f"[s{k}]")
    music = p.get("music")
    if music and music.get("sound"):
        idx = inputs.count("-i")  # next input's number
        inputs += ["-stream_loop", "-1", "-i", os.path.abspath(sound_path(music["sound"]))]
        filters.append(f"[{idx}:a]{fmt},volume={float(music.get('volume', 0.2)):.3f},atrim=0:{total:.3f},"
                       f"afade=t=in:d=0.4,afade=t=out:st={max(total - 1.2, 0):.3f}:d=1.2[mus]")
        mix.append("[mus]")
    filters.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=first,alimiter=limit=0.95[a]")

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats", *inputs,
           "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", os.path.abspath(out_path)]
    proc = subprocess.Popen(cmd, cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in proc.stdout:
        if line.startswith("out_time_us=") and line.strip() != "out_time_us=N/A":
            progress(min(int(line.split("=")[1]) / 1e6 / total, 1.0))
    err = proc.stderr.read()
    if proc.wait() != 0:
        raise RuntimeError("Rendering failed: " + err.strip()[-600:])
    return out_path


# ---------- learning from the user's own edits ----------

STYLE_KEYS = ("font", "size", "color", "outline", "outline_color", "box", "box_color", "box_opacity",
              "x", "y", "anim", "uppercase")


def summarize(p):
    """What this finished project says about the user's editing habits."""
    total = duration(p) or 1
    cuts = cut_times(p)
    texts = []
    for t in p.get("texts", []):
        span = float(t["end"]) - float(t["start"])
        texts.append({"role": "title" if span >= 0.7 * total else "per_clip",
                      "numbered": str(t.get("text", "")).strip().startswith("#"),
                      "style": {k: t.get(k, TEXT_DEFAULT[k]) for k in STYLE_KEYS}})
    sounds = []
    for s in p.get("sounds", []):
        start = float(s["start"])
        where = "cut" if any(abs(start - c) <= 0.4 for c in cuts) else "start" if start < 0.6 else "other"
        sounds.append({"sound": s["sound"], "where": where, "lead": round(min((c - start for c in cuts if
                       abs(start - c) <= 0.4), default=0.0, key=abs), 2), "volume": float(s.get("volume", 0.8))})
    music = p.get("music") or {}
    return {"id": p["id"], "when": time.time(), "clip_lengths": [round(clip_len(c), 2) for c in p["clips"]],
            "audio": [audio_mode(c) for c in p["clips"]],
            "framing": [c.get("framing", "fill") for c in p["clips"]], "texts": texts, "sounds": sounds,
            "music": {"sound": music.get("sound"), "volume": music.get("volume")} if music.get("sound") else None}


def record(profile_path, p):
    if not p.get("clips"):
        return
    try:
        with open(profile_path) as f:
            history = json.load(f)
    except (OSError, ValueError):
        history = []
    history = [h for h in history if h.get("id") != p["id"]] + [summarize(p)]
    with open(profile_path, "w") as f:
        json.dump(history[-30:], f)


def _most_common_style(items):
    if not items:
        return None
    key = lambda s: (s["font"], s["color"], s["box"], s["outline_color"])
    winner = Counter(key(s) for s in items).most_common(1)[0][0]
    return [s for s in items if key(s) == winner][-1]  # the latest version of that look


def my_style(profile_path):
    """The user's habits, averaged over their saved projects. None until they have saved one."""
    try:
        with open(profile_path) as f:
            history = json.load(f)
    except (OSError, ValueError):
        history = []
    if not history:
        return None
    n = len(history)
    lengths = [x for h in history for x in h["clip_lengths"]]
    # Older history entries stored a muted flag instead of an audio mode.
    audio = [x for h in history for x in h.get("audio") or ["mute" if m else "keep" for m in h.get("muted", [])]]
    framing = [x for h in history for x in h.get("framing", [])]
    titles = [t["style"] for h in history for t in h["texts"] if t["role"] == "title"]
    per_clip = [t for h in history for t in h["texts"] if t["role"] == "per_clip"]

    def habit(where):
        """A sound the user puts at `where` in at least half their projects."""
        used = Counter(s["sound"] for h in history for s in {x["sound"]: x for x in h["sounds"]
                                                             if x["where"] == where}.values())
        if not used:
            return None
        sound, count = used.most_common(1)[0]
        if count < max(1, n / 2):
            return None
        hits = [s for h in history for s in h["sounds"] if s["where"] == where and s["sound"] == sound]
        return {"sound": sound, "volume": statistics.median(s["volume"] for s in hits),
                "lead": statistics.median(s.get("lead", 0.0) for s in hits)}

    musics = [h["music"] for h in history if h.get("music")]
    music = None
    if len(musics) >= max(1, n / 2):
        track = Counter(m["sound"] for m in musics).most_common(1)[0][0]
        music = {"sound": track, "volume": statistics.median(m["volume"] for m in musics)}
    return {
        "projects": n,
        "clip_length": round(statistics.median(lengths), 1) if lengths else 5.0,
        "audio": Counter(audio).most_common(1)[0][0] if audio else "keep",
        "framing": Counter(framing).most_common(1)[0][0] if framing else "fill",
        "title": _most_common_style(titles) if len(titles) >= max(1, n / 2) else None,
        "per_clip": _most_common_style([t["style"] for t in per_clip]) if per_clip else None,
        "numbered": bool(per_clip) and sum(t["numbered"] for t in per_clip) > len(per_clip) / 2,
        "cut_sound": habit("cut"),
        "start_sound": habit("start"),
        "music": music,
    }


def arrange(p, style, picks=None):
    """Apply the user's learned style to a project's clips: lengths, texts, sounds, music."""
    picks = picks or {}
    for c in p["clips"]:
        start = picks.get(c["id"], float(c["in"]))
        c["in"] = round(start, 2)
        c["out"] = round(min(start + style["clip_length"], c.get("media_duration", start + style["clip_length"])), 2)
        c["audio"] = style.get("audio", "keep")
        c.pop("muted", None)
        c["framing"] = style["framing"]
    total = duration(p)
    p["texts"], p["sounds"] = [], []
    if style.get("title"):
        p["texts"].append({**TEXT_DEFAULT, **style["title"], "id": new_id(), "text": p.get("name") or "Title",
                           "start": 0.0, "end": round(total, 2)})
    if style.get("per_clip"):
        t, n = 0.0, len(p["clips"])
        for i, c in enumerate(p["clips"]):
            label = f"#{n - i}" if style.get("numbered") else f"Clip {i + 1}"
            p["texts"].append({**TEXT_DEFAULT, **style["per_clip"], "id": new_id(), "text": label,
                               "start": round(t, 2), "end": round(t + clip_len(c), 2)})
            t += clip_len(c)
    if style.get("start_sound"):
        s = style["start_sound"]
        p["sounds"].append({"id": new_id(), "sound": s["sound"], "start": 0.0, "volume": s["volume"]})
    if style.get("cut_sound"):
        s = style["cut_sound"]
        for c in cut_times(p):
            p["sounds"].append({"id": new_id(), "sound": s["sound"], "start": round(max(0.0, c - s["lead"]), 2),
                                "volume": s["volume"]})
    if style.get("music"):
        p["music"] = dict(style["music"])
    return p
