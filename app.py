"""ClipForge: turn long YouTube videos into captioned Shorts. Run with start.bat."""
import base64
import json
import os
import re
import shutil
import subprocess
import threading
import time
import traceback
import uuid
import webbrowser

from flask import Flask, abort, jsonify, request, send_from_directory

from clipforge import ai, autopick, captions, hype, render, soundlab, styles, tts, youtube

ROOT = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(ROOT, "work")
OUTPUT = os.path.join(ROOT, "output")
SOUNDS = os.path.join(ROOT, "sounds")
CONFIG = os.path.join(ROOT, "config.json")
COOKIES = os.path.join(ROOT, "cookies.txt")
USAGE = os.path.join(ROOT, "usage.json")
DEFAULT_BUDGET = 20.0
STYLES = os.path.join(ROOT, "styles.json")
FONTS = os.path.join(ROOT, "fonts")
BROWSERS = ("firefox", "chrome", "edge", "brave")
SOUND_DIRS = {
    "sfx": [("starter", "starter/sfx"), ("mine", "my_sfx")],
    "music": [("starter", "starter/music"), ("mine", "my_music")],
}
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")
PORT = 5173

# winget puts ffmpeg and deno here; add it in case PATH wasn't refreshed yet.
_links = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links")
if os.path.isdir(_links):
    os.environ["PATH"] = _links + os.pathsep + os.environ["PATH"]
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 ** 3  # allow big video uploads
jobs = {}
render_lock = threading.Lock()


def load_config():
    try:
        with open(CONFIG) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    with open(CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)


def load_ledger():
    try:
        with open(USAGE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def spending():
    budget = float(load_config().get("budget", DEFAULT_BUDGET))
    spent = sum(e["cost"] for e in load_ledger())
    return {"budget": budget, "spent": spent, "remaining": budget - spent}


def record_usage(video_id, title, usage):
    ledger = load_ledger()
    ledger.append({"time": time.strftime("%Y-%m-%d %H:%M"), "video_id": video_id, "title": title, **usage})
    with open(USAGE, "w") as f:
        json.dump(ledger, f, indent=2)


def start_job(fn, *args):
    job_id = uuid.uuid4().hex[:10]
    job = jobs[job_id] = {"status": "running", "progress": 0.0, "message": "Starting...",
                          "result": None, "error": None}

    def update(progress=None, message=None):
        if progress is not None:
            job["progress"] = progress
        if message is not None:
            job["message"] = message

    def ask(info):
        """Pause the job until the user approves or cancels in the browser."""
        job["approval"] = info
        job["answer"] = threading.Event()
        job["status"] = "needs_approval"
        answered = job["answer"].wait(timeout=1800)
        approved = answered and job.get("approved")
        job["status"] = "running"
        job.pop("approval", None)
        return approved

    update.ask = ask

    def run():
        cfg = load_config()
        youtube.set_auth(cfg.get("yt_browser"), COOKIES if os.path.exists(COOKIES) else None)
        try:
            job["result"] = fn(update, *args)
            job["status"] = "done"
            job["progress"] = 1.0
        except Exception as e:  # report every failure to the browser
            traceback.print_exc()
            job["status"] = "error"
            job["error"] = str(e) or e.__class__.__name__
            if "confirm you" in job["error"] and "not a bot" in job["error"]:
                job["error"] = ("YouTube wants to check you're not a bot. Open Settings and choose "
                                "\"YouTube sign-in\" (Firefox works best), or upload a cookies.txt file.")
            elif "cookie" in job["error"].lower() and load_config().get("yt_browser"):
                job["error"] = ("Couldn't read your YouTube login from that browser. Make sure it's "
                                "installed and signed in to YouTube, close it completely, and try again. "
                                "If it still fails, pick another browser or upload a cookies.txt file. "
                                "Details: " + job["error"][:300])

    threading.Thread(target=run, daemon=True).start()
    return job_id


def safe_name(text, fallback="clip"):
    text = re.sub(r"[^\w\- ]+", "", text).strip().replace(" ", "_")
    return text[:60] or fallback


# ---------- analysis ----------

def local_file(vid):
    """The uploaded video for a local project, or None for YouTube projects."""
    if not vid.startswith("local_"):
        return None
    vdir = os.path.join(WORK, vid)
    for name in os.listdir(vdir):
        if name.startswith("source."):
            return os.path.join(vdir, name)
    raise RuntimeError("The uploaded video is missing. Upload it again.")


def _get_audio(url, vdir):
    """Full audio track, downloaded once and kept for gameplay analysis."""
    local = local_file(os.path.basename(vdir))
    if local:
        return local
    for name in os.listdir(vdir):
        if name.startswith("audio."):
            return os.path.join(vdir, name)
    return youtube.download_audio(url, vdir)


def analyze(update, url, force, mode="talk", clip_len=30, local_id=None):
    update(0.02, "Reading video info...")
    if local_id:
        with open(os.path.join(WORK, local_id, "meta.json")) as f:
            info = json.load(f)
    else:
        info = youtube.get_info(url)
    vid = info["id"]
    vdir = os.path.join(WORK, vid)
    os.makedirs(vdir, exist_ok=True)
    tpath = os.path.join(vdir, "transcript.json")

    words, source = None, None
    if os.path.exists(tpath):
        with open(tpath) as f:
            t = json.load(f)
        words, source = t["words"], t["source"]
    if words is None and not local_id:
        update(0.1, "Fetching YouTube captions...")
        words, source = youtube.get_caption_words(url, info)
    if not words and mode == "talk" and source != "whisper":
        update(0.1, "No captions on this video. Downloading audio for Whisper...")
        audio = _get_audio(url, vdir)
        from clipforge import transcribe
        words = transcribe.transcribe(audio, info.get("duration"), lambda p, m: update(0.1 + 0.6 * p, m))
        source = "whisper"
    words = words or []
    with open(tpath, "w") as f:
        json.dump({"words": words, "source": source or "none"}, f)

    if mode == "hype":
        spath = os.path.join(vdir, f"hype_{int(clip_len)}.json")
        if os.path.exists(spath) and not force:
            with open(spath) as f:
                clips = json.load(f)
        else:
            update(0.4, "Downloading the audio to listen for hype moments (free)...")
            audio = _get_audio(url, vdir)
            update(0.8, "Listening for the loudest, most exciting moments...")
            clips = hype.hype_moments(audio, clip_len=float(clip_len), ffmpeg=FFMPEG)
            if not clips:
                raise RuntimeError("Couldn't find any clear hype moments in this video. Try Talking mode "
                                   "or add your own clips.")
            with open(spath, "w") as f:
                json.dump(clips, f)
    else:
        if not words:
            raise RuntimeError("Couldn't find any speech in this video. For gameplay, choose "
                               "\"Gameplay: find hype moments\" instead.")
        spath = os.path.join(vdir, "suggestions.json")
        if os.path.exists(spath) and not force:
            update(0.95, "Loading saved suggestions...")
            with open(spath) as f:
                clips = json.load(f)
        else:
            key = require_key()
            update(0.72, "Working out the cost (this check is free)...")
            est = ai.estimate(key, info.get("title", ""), words)
            est.update(spending())
            update(0.72, "Waiting for your approval...")
            if not update.ask(est):
                raise RuntimeError("Cancelled. Nothing was charged.")
            update(0.75, "Claude is reading the transcript and picking clips (about 1 to 3 minutes)...")
            clips, usage = ai.suggest_clips(key, info.get("title", ""), words)
            record_usage(vid, info.get("title", ""), usage)
            with open(spath, "w") as f:
                json.dump(clips, f)

    return {"video_id": vid, "url": info.get("webpage_url", url), "title": info.get("title"),
            "duration": info.get("duration"), "caption_source": source or "none", "mode": mode,
            "words": words, "clips": clips}


def require_key():
    key = load_config().get("api_key")
    if not key:
        raise RuntimeError("Add your Anthropic API key in Settings first.")
    return key


# ---------- rendering ----------

def resolve_sound(rel):
    path = os.path.normpath(os.path.join(SOUNDS, rel))
    if not path.startswith(SOUNDS) or not os.path.isfile(path):
        raise RuntimeError(f"Sound not found: {rel}")
    return path


def clip_source(url, vid, start, end):
    vdir = os.path.join(WORK, vid)
    os.makedirs(vdir, exist_ok=True)
    base = os.path.join(vdir, f"src_{start:.2f}_{end:.2f}")
    local = local_file(vid)
    if not local:
        return youtube.download_section(url, start, end, base)
    out = base + ".mp4"
    if not os.path.exists(out):
        # Re-encode so the cut lands exactly on the chosen frames.
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", local,
                        "-t", f"{end - start:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                        "-c:a", "aac", "-b:a", "192k", out], check=True)
    return out


def render_all(update, payload):
    with render_lock:
        vid = payload["video_id"]
        url = payload["url"]
        vdir = os.path.join(WORK, vid)
        with open(os.path.join(vdir, "transcript.json")) as f:
            words = json.load(f)["words"]
        style = payload.get("style", {})
        crop_mode = payload.get("crop_mode", "auto")
        music = None
        if payload.get("music", {}).get("sound"):
            music = {"path": resolve_sound(payload["music"]["sound"]),
                     "volume": payload["music"].get("volume", 0.15)}
        os.makedirs(OUTPUT, exist_ok=True)
        clips = payload["clips"]
        results = []
        for n, clip in enumerate(clips):
            share = 1 / len(clips)
            done = n * share
            label = f"Clip {n + 1} of {len(clips)}"
            start, end = float(clip["start"]), float(clip["end"])
            update(done, f"{label}: downloading section...")
            src = clip_source(url, vid, start, end)
            cw = captions.clip_words(words, start, end, clip.get("caption_text"))

            voiceover = None
            vo = clip.get("voiceover") or {}
            if vo.get("text", "").strip():
                update(done + share * 0.2, f"{label}: recording the AI voice...")
                spoken = tts.synthesize(vo["text"].strip(), vo.get("voice") or tts.VOICES[0][0],
                                        vo.get("rate", "+0%"), os.path.join(WORK, "tts"))
                at = float(vo.get("at", 0))
                voiceover = {"path": spoken["path"], "at": at, "volume": float(vo.get("volume", 1.0))}
                if vo.get("captions", "voice") == "voice":
                    cw = [{"w": w["w"], "s": w["s"] + at, "e": w["e"] + at}
                          for w in spoken["words"] if w["s"] + at < end - start]

            sfx = [{"path": resolve_sound(s["sound"]), "at": float(s["at"]), "volume": float(s.get("volume", 0.8))}
                   for s in clip.get("sfx", []) if s.get("sound")]
            out_name = f"{n + 1:02d}_{safe_name(clip.get('title', ''))}_{vid}.mp4"
            update(done + share * 0.3, f"{label}: rendering...")
            render.render(src, os.path.join(OUTPUT, out_name), cw, style, clip.get("crop_mode") or crop_mode,
                          music, sfx, vdir, FFMPEG, FFPROBE,
                          lambda p: update(done + share * (0.3 + 0.7 * p), f"{label}: rendering {int(p * 100)}%"),
                          voiceover=voiceover, overlays=clip.get("overlays"),
                          effects=clip.get("effects"), fonts_dir=FONTS)
            results.append({"id": clip.get("id"), "title": clip.get("title"), "file": out_name})
        return results


# ---------- voiceover ----------

def clip_frames(src, duration, out_dir, count=5):
    """Grab evenly spaced frames so Claude can see what happens in the clip."""
    frames = []
    for i in range(count):
        t = duration * (i + 0.5) / count
        path = os.path.join(out_dir, f"frame_{i}.jpg")
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", src, "-frames:v", "1",
                        "-vf", "scale=768:-2", "-q:v", "5", path], check=True)
        with open(path, "rb") as f:
            frames.append(base64.b64encode(f.read()).decode("ascii"))
    return frames


def write_script(update, body):
    key = require_key()
    vid, url = body["video_id"], body["url"]
    clip = body["clip"]
    start, end = float(clip["start"]), float(clip["end"])
    update(0.1, "Downloading the clip so Claude can see it...")
    src = clip_source(url, vid, start, end)
    duration = render.probe(src, FFPROBE)[2]
    frame_dir = os.path.join(WORK, vid, "frames")
    os.makedirs(frame_dir, exist_ok=True)
    frames = clip_frames(src, duration, frame_dir)
    with open(os.path.join(WORK, vid, "transcript.json")) as f:
        words = json.load(f)["words"]
    said = " ".join(w["w"] for w in captions.clip_words(words, start, end))
    req = ai.voiceover_request(body.get("title", ""), frames, said, duration,
                               body.get("style", "hype"), body.get("notes", ""))
    update(0.4, "Working out the cost (this check is free)...")
    est = ai.estimate_voiceover(key, req)
    est.update(spending())
    update(0.4, "Waiting for your approval...")
    if not update.ask(est):
        raise RuntimeError("Cancelled. Nothing was charged.")
    update(0.6, "Claude is writing the voiceover...")
    script, usage = ai.write_voiceover(key, req)
    record_usage(vid, f"Voiceover: {clip.get('title', '')}", usage)
    return {"script": script, "cost": usage["cost"]}


# ---------- routes ----------

@app.get("/")
def index():
    return send_from_directory(os.path.join(ROOT, "static"), "index.html")


@app.get("/api/status")
def status():
    cfg = load_config()
    key = cfg.get("api_key", "")
    return jsonify(ffmpeg=bool(FFMPEG and FFPROBE), has_key=bool(key),
                   key_hint=("..." + key[-4:]) if key else "",
                   yt_browser=cfg.get("yt_browser", ""), has_cookies=os.path.exists(COOKIES))


@app.post("/api/config")
def set_config():
    cfg = load_config()
    body = request.json or {}
    key = body.get("api_key", "").strip()
    if key:
        cfg["api_key"] = key
    if "budget" in body:
        try:
            cfg["budget"] = max(0.0, float(body["budget"]))
        except (TypeError, ValueError):
            pass
    if "yt_browser" in body:
        cfg["yt_browser"] = body["yt_browser"] if body["yt_browser"] in BROWSERS else ""
    save_config(cfg)
    return status()


@app.post("/api/cookies")
def upload_cookies():
    f = request.files.get("file")
    if f:
        f.save(COOKIES)
    elif os.path.exists(COOKIES):
        os.remove(COOKIES)
    return status()


@app.get("/api/sounds")
def list_sounds():
    out = {}
    for kind, dirs in SOUND_DIRS.items():
        items = []
        for source, sub in dirs:
            folder = os.path.join(SOUNDS, sub)
            os.makedirs(folder, exist_ok=True)
            for name in sorted(os.listdir(folder)):
                if name.lower().endswith(AUDIO_EXT):
                    items.append({"id": f"{sub}/{name}", "name": os.path.splitext(name)[0], "source": source})
        out[kind] = items
    return jsonify(out)


@app.post("/api/sounds/upload")
def upload_sound():
    kind = request.form.get("kind")
    if kind not in SOUND_DIRS:
        abort(400)
    saved = []
    for f in request.files.getlist("files"):
        base, ext = os.path.splitext(f.filename or "")
        if ext.lower() not in AUDIO_EXT:
            continue
        name = safe_name(base, "sound") + ext.lower()
        f.save(os.path.join(SOUNDS, SOUND_DIRS[kind][1][1], name))
        saved.append(name)
    return jsonify(saved=saved)


@app.get("/sounds/<path:rel>")
def serve_sound(rel):
    return send_from_directory(SOUNDS, rel)


@app.post("/api/upload-video")
def api_upload_video():
    f = request.files.get("file")
    if not f:
        abort(400)
    vid = "local_" + uuid.uuid4().hex[:10]
    vdir = os.path.join(WORK, vid)
    os.makedirs(vdir, exist_ok=True)
    ext = os.path.splitext(f.filename or "")[1].lower() or ".mp4"
    path = os.path.join(vdir, "source" + ext)
    f.save(path)
    try:
        duration = render.probe(path, FFPROBE)[2]
    except Exception:
        shutil.rmtree(vdir, ignore_errors=True)
        return jsonify(error="That file doesn't look like a video ClipForge can read."), 400
    title = os.path.splitext(os.path.basename(f.filename or "Uploaded video"))[0]
    with open(os.path.join(vdir, "meta.json"), "w") as out:
        json.dump({"id": vid, "title": title, "duration": duration, "webpage_url": ""}, out)
    body = request.form
    mode = "hype" if body.get("mode") == "hype" else "talk"
    return jsonify(job=start_job(analyze, "", True, mode, int(body.get("clip_len", 30)), vid))


def build_montage(update, vid, parts, whoosh, top_title=None, style=None):
    """Join several clips (each trimmed) into one 1920x1080 video, then open it as a project."""
    vdir = os.path.join(WORK, vid)
    inputs, filters, labels = [], [], []
    cuts, total, ranks = [], 0.0, []
    for i, part in enumerate(parts):
        w, h, dur, has_audio = render.probe(part["path"], FFPROBE)
        start = max(0.0, min(float(part.get("start", 0)), dur))
        end = min(float(part.get("end") or dur), dur)
        if end - start < 0.5:
            continue
        n = len(labels)
        inputs += ["-i", part["path"]]
        filters.append(
            f"[{len(inputs) // 2 - 1}:v]trim={start:.3f}:{end:.3f},setpts=PTS-STARTPTS,"
            f"scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
            f"setsar=1,fps=30,format=yuv420p[v{n}]")
        if has_audio:
            filters.append(f"[{len(inputs) // 2 - 1}:a]atrim={start:.3f}:{end:.3f},asetpts=PTS-STARTPTS,"
                           f"aformat=sample_rates=48000:channel_layouts=stereo[a{n}]")
        else:
            filters.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{end - start:.3f}[a{n}]")
        labels.append(f"[v{n}][a{n}]")
        if total > 0:
            cuts.append(round(total, 2))
        if part.get("rank"):
            ranks.append({"start": round(total, 2), "end": round(total + end - start, 2),
                          "rank": int(part["rank"]), "label": part.get("label", "")})
        total += end - start
    if not labels:
        raise RuntimeError("None of those clips had anything left after trimming.")
    filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=1[v][a]")
    update(0.2, f"Joining {len(labels)} clips ({total:.0f} seconds)...")
    out = os.path.join(vdir, "source.mp4")
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                    "-c:a", "aac", "-b:a", "192k", out], check=True)
    for part in parts:
        os.remove(part["path"])
    title = top_title or f"Montage of {len(labels)} clips"
    with open(os.path.join(vdir, "meta.json"), "w") as f:
        json.dump({"id": vid, "title": title, "duration": total, "webpage_url": ""}, f)
    with open(os.path.join(vdir, "transcript.json"), "w") as f:
        json.dump({"words": [], "source": "none"}, f)
    whoosh_id = "starter/sfx/whoosh.wav"
    sfx = ([{"sound": whoosh_id, "at": max(c - 0.35, 0), "volume": 0.7} for c in cuts]
           if whoosh and os.path.exists(os.path.join(SOUNDS, whoosh_id)) else [])
    clip = {"id": "montage", "title": title, "start": 0.0, "end": round(total, 2),
            "hook": f"Your montage. Cuts at {', '.join(f'{c:.1f}s' for c in cuts) or 'none'}.",
            "score": 0, "approved": True, "sfx": sfx}
    if top_title is not None:
        clip["overlays"] = {"title": top_title, "ranks": ranks, "style": style}
        if style:
            cut = styles.merged(style)["cut"]
            clip["effects"] = {"cuts": cuts, "flash": bool(cut.get("flash")), "zoom": bool(cut.get("zoom"))}
        clip["hook"] = f"Top {len(ranks)} countdown. #1 plays last at {ranks[-1]['start']:.1f}s." if ranks else clip["hook"]
    return {"video_id": vid, "url": "", "title": title, "duration": total, "caption_source": "none",
            "mode": "montage", "words": [], "clips": [clip]}


LINKS = os.path.join(WORK, "linkparts")
MAX_FULL_LINK = 20 * 60  # longer videos need a from/to range


def fetch_link(update, url, start, end):
    """Download a YouTube video (or just part of it) for use in a montage."""
    update(0.05, "Reading the video's info...")
    info = youtube.get_info(url)
    duration = info.get("duration") or 0
    has_range = end is not None and end > (start or 0)
    if not has_range and duration > MAX_FULL_LINK:
        raise RuntimeError(f"That video is {duration // 60} minutes long. Type a From and To time "
                           "so ClipForge only downloads the part you need.")
    part_id = uuid.uuid4().hex[:12]
    os.makedirs(LINKS, exist_ok=True)
    base = os.path.join(LINKS, part_id)
    update(0.2, "Downloading the part you picked..." if has_range else "Downloading the video...")
    try:
        path = (youtube.download_section(url, float(start or 0), float(end), base) if has_range
                else youtube.download_video(url, base))
    except Exception as e:
        if "instagram.com" in url:
            raise RuntimeError("Instagram blocked this download. It usually needs you to be logged in: open "
                               "Settings, and under \"Sign-in for downloads\" pick the browser where you're logged "
                               "in to Instagram (Firefox works best), then try again. Details: " + str(e)[:200]) from e
        if "tiktok.com" in url:
            raise RuntimeError("TikTok blocked this download. Wait a minute and try again. If it keeps failing, "
                               "close ClipForge and open start.bat again (it updates the downloader), or try "
                               "the link from TikTok's Share > Copy link. Details: " + str(e)[:200]) from e
        raise
    real = render.probe(path, FFPROBE)[2]
    return {"id": part_id, "title": info.get("title") or url, "duration": real,
            "media": f"/linkpart/{os.path.basename(path)}"}


@app.post("/api/montage/fetch")
def api_montage_fetch():
    body = request.json or {}
    url = (body.get("url") or "").strip()
    if not url:
        abort(400)
    to_num = lambda v: float(v) if v not in (None, "") else None
    return jsonify(job=start_job(fetch_link, url, to_num(body.get("start")), to_num(body.get("end"))))


@app.get("/linkpart/<name>")
def serve_linkpart(name):
    if not re.fullmatch(r"[0-9a-f]{12}\.[a-z0-9]{2,5}", name):
        abort(404)
    return send_from_directory(LINKS, name)


def link_path(part_id):
    if not re.fullmatch(r"[0-9a-f]{12}", part_id or ""):
        raise RuntimeError("Unknown linked clip.")
    for name in os.listdir(LINKS):
        if name.startswith(part_id + "."):
            return os.path.join(LINKS, name)
    raise RuntimeError("A linked clip is missing. Add it again.")


def montage_sources(dest_dir, copy_links):
    """Every montage item's file, in list order: uploaded files are saved, linked clips found."""
    files = request.files.getlist("files")
    try:
        items = json.loads(request.form.get("items", "null"))
    except ValueError:
        items = None
    if items is None:  # older page: only files
        items = [{"kind": "file", "index": i} for i in range(len(files))]
    paths = []
    for n, item in enumerate(items):
        if item.get("kind") == "link":
            src = link_path(item.get("id"))
            if copy_links:
                dst = os.path.join(dest_dir, f"part_{n:02d}{os.path.splitext(src)[1]}")
                shutil.copy(src, dst)
                src = dst
            paths.append(src)
        else:
            f = files[int(item["index"])]
            ext = os.path.splitext(f.filename or "")[1].lower() or ".mp4"
            path = os.path.join(dest_dir, f"part_{n:02d}{ext}")
            f.save(path)
            paths.append(path)
    return paths


@app.post("/api/montage/autopick")
def api_montage_autopick():
    tmp = os.path.join(WORK, "autopick_" + uuid.uuid4().hex[:10])
    os.makedirs(tmp, exist_ok=True)
    try:
        paths = montage_sources(tmp, copy_links=False)
        if not paths:
            abort(400)
        picks, order = autopick.pick(paths, float(request.form.get("target", 30)), FFMPEG)
    except subprocess.CalledProcessError:
        return jsonify(error="Couldn't read one of those videos."), 400
    except RuntimeError as e:
        return jsonify(error=str(e)), 400
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return jsonify(picks=picks, order=order)


@app.post("/api/montage")
def api_montage():
    try:
        trims = json.loads(request.form.get("trims", "[]"))
    except ValueError:
        trims = []
    vid = "local_" + uuid.uuid4().hex[:10]
    vdir = os.path.join(WORK, vid)
    os.makedirs(vdir, exist_ok=True)
    try:
        paths = montage_sources(vdir, copy_links=True)
    except RuntimeError as e:
        return jsonify(error=str(e)), 400
    if not paths:
        abort(400)
    parts = []
    for i, path in enumerate(paths):
        trim = trims[i] if i < len(trims) else {}
        parts.append({"path": path, "start": trim.get("start", 0), "end": trim.get("end"),
                      "rank": trim.get("rank"), "label": (trim.get("label") or "")[:60]})
    top_title = request.form.get("top_title") if request.form.get("format") == "top" else None
    try:
        style = json.loads(request.form.get("style") or "null")
    except ValueError:
        style = None
    return jsonify(job=start_job(build_montage, vid, parts, request.form.get("whoosh") == "1", top_title, style))


# ---------- styles ----------

STYLE_REF = os.path.join(WORK, "styleref")


@app.get("/api/styles")
def api_styles():
    return jsonify(styles=styles.load_all(STYLES), fonts=styles.available_fonts(FONTS))


@app.post("/api/styles")
def api_style_save():
    style = request.json or {}
    if not (style.get("name") or "").strip():
        return jsonify(error="Give the style a name first."), 400
    if style["name"].strip() == styles.DEFAULT["name"]:
        return jsonify(error="\"Classic\" is built in. Save your version under a different name."), 400
    style["name"] = style["name"].strip()[:40]
    return jsonify(style=styles.save(STYLES, style))


@app.post("/api/styles/delete")
def api_style_delete():
    styles.delete(STYLES, (request.json or {}).get("name", ""))
    return jsonify(ok=True)


@app.post("/api/styles/preview")
def api_style_preview():
    """One still frame showing the style's title, rank and label, for checking a style by eye."""
    body = request.json or {}
    style = styles.merged(body.get("style"))
    out_dir = os.path.join(WORK, "style_preview")
    os.makedirs(out_dir, exist_ok=True)
    overlays = {"title": body.get("title") or "Top 5 craziest Roblox moments",
                "ranks": [{"start": 0, "end": 5, "rank": 1, "label": body.get("label") or "Boss fight"}],
                "style": style}
    with open(os.path.join(out_dir, "preview.ass"), "w", encoding="utf-8") as f:
        f.write(captions.build_ass([], {}, 5, overlays))
    ref = body.get("ref") or ""
    frame = os.path.join(STYLE_REF, ref, "frame.jpg") if re.fullmatch(r"[0-9a-f]{10}", ref) else ""
    if frame and os.path.exists(frame):
        bg = ["-loop", "1", "-i", frame]
        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
    else:
        bg = ["-f", "lavfi", "-i", "color=c=0x1D3B44:s=1080x1920"]
        vf = ""
    vf += "ass=preview.ass"
    if os.path.isdir(FONTS):
        vf += ":fontsdir=" + os.path.relpath(FONTS, out_dir).replace("\\", "/")
    # Rank pops in from 35% size, so grab a frame after the animation (0.5 s).
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", *bg, "-ss", "0.5", "-vf", vf, "-frames:v", "1",
                    "preview.png"], cwd=out_dir, check=True)
    return send_from_directory(out_dir, "preview.png", max_age=0)


def measure_reference(src):
    """Cuts and pacing of an example video, measured with FFmpeg (free)."""
    w, h, duration, _ = render.probe(src, FFPROBE)
    log = subprocess.run([FFMPEG, "-hide_banner", "-i", src, "-vf", "select='gt(scene,0.35)',showinfo",
                          "-an", "-f", "null", "-"], capture_output=True, text=True).stderr
    cuts = [float(x) for x in re.findall(r"pts_time:([\d.]+)", log)]
    cuts = [c for i, c in enumerate(cuts) if c > 0.5 and (i == 0 or c - cuts[i - 1] > 0.8)]
    edges = [0.0] + cuts + [duration]
    lengths = sorted(b - a for a, b in zip(edges, edges[1:]) if b - a > 0.5)
    per = lengths[len(lengths) // 2] if lengths else duration
    # A flash shows up as a very bright frame right at a cut.
    stats = subprocess.run([FFMPEG, "-hide_banner", "-i", src, "-vf",
                            "fps=30,scale=64:-1,signalstats,metadata=print:key=lavfi.signalstats.YAVG",
                            "-an", "-f", "null", "-"], capture_output=True, text=True).stderr
    times = [float(x) for x in re.findall(r"pts_time:([\d.]+)", stats)]
    yavg = [float(x) for x in re.findall(r"YAVG=([\d.]+)", stats)]
    flashes = 0
    for c in cuts:
        near = [y for t, y in zip(times, yavg) if abs(t - c) < 0.15]
        if near and max(near) > 200:
            flashes += 1
    return {"duration": duration, "width": w, "height": h, "cuts": len(cuts), "cut_times": cuts,
            "seconds_per_clip": max(2.0, min(15.0, per)), "flash": bool(cuts) and flashes >= max(1, len(cuts) // 3)}


def analyze_style(update, ref, url):
    key = require_key()
    d = os.path.join(STYLE_REF, ref)
    if url:
        update(0.05, "Downloading the example video...")
        info = youtube.get_info(url)
        if (info.get("duration") or 0) > 600:
            raise RuntimeError("Use an example under 10 minutes long.")
        youtube.download_video(url, os.path.join(d, "source"))
    src = next(os.path.join(d, n) for n in os.listdir(d) if n.startswith("source."))
    update(0.3, "Measuring cuts and pacing (free)...")
    m = measure_reference(src)
    # Frames: just after the start (titles), and the middle of the first few entries.
    edges = [0.0] + m["cut_times"] + [m["duration"]]
    times = [min(0.6, m["duration"] / 2)] + [(a + b) / 2 for a, b in list(zip(edges, edges[1:]))[:5]]
    frames = []
    for i, t in enumerate(times[:6]):
        path = os.path.join(d, f"f{i}.jpg")
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", src, "-frames:v", "1",
                        "-vf", "scale=-2:900", "-q:v", "4", path], check=True)
        with open(path, "rb") as f:
            frames.append(base64.b64encode(f.read()).decode("ascii"))
    shutil.copy(os.path.join(d, "f1.jpg" if len(times) > 1 else "f0.jpg"), os.path.join(d, "frame.jpg"))
    req = ai.style_request(frames, styles.available_fonts(FONTS), m)
    update(0.5, "Working out the cost (this check is free)...")
    est = ai.estimate_style(key, req)
    est.update(spending())
    update(0.5, "Waiting for your approval...")
    if not update.ask(est):
        raise RuntimeError("Cancelled. Nothing was charged.")
    update(0.6, "Claude is studying the text design...")
    look, usage = ai.copy_style(key, req)
    record_usage("style", "Copy a style", usage)
    style = styles.merged({
        "name": "", "seconds_per_clip": round(m["seconds_per_clip"]), "framing": look["framing"],
        "cut": {"whoosh": True, "flash": m["flash"], "zoom": False},
        "title": look["title"], "rank": look["rank"], "label": look["label"],
    })
    return {"ref": ref, "style": style, "measured": {k: v for k, v in m.items() if k != "cut_times"},
            "notes": look.get("notes", ""), "cost": usage["cost"]}


@app.post("/api/styles/analyze")
def api_style_analyze():
    ref = uuid.uuid4().hex[:10]
    d = os.path.join(STYLE_REF, ref)
    os.makedirs(d, exist_ok=True)
    f = request.files.get("file")
    url = ""
    if f:
        ext = os.path.splitext(f.filename or "")[1].lower() or ".mp4"
        f.save(os.path.join(d, "source" + ext))
    else:
        url = (request.form.get("url") or "").strip()
        if not url:
            abort(400)
    return jsonify(job=start_job(analyze_style, ref, url))


@app.get("/media/<vid>")
def serve_media(vid):
    if not re.fullmatch(r"local_[0-9a-f]{10}", vid):
        abort(404)
    path = local_file(vid)
    return send_from_directory(os.path.dirname(path), os.path.basename(path))


@app.post("/api/analyze")
def api_analyze():
    body = request.json or {}
    url = body.get("url", "").strip()
    if not url:
        abort(400)
    mode = "hype" if body.get("mode") == "hype" else "talk"
    return jsonify(job=start_job(analyze, url, bool(body.get("force")), mode, int(body.get("clip_len", 30))))


@app.post("/api/render")
def api_render():
    if not (FFMPEG and FFPROBE):
        return jsonify(error="FFmpeg is not installed. Run install.bat again."), 400
    return jsonify(job=start_job(render_all, request.json))


@app.get("/api/job/<job_id>")
def api_job(job_id):
    job = jobs.get(job_id)
    if not job:
        abort(404)
    return jsonify({k: v for k, v in job.items() if k not in ("answer", "approved")})


@app.post("/api/job/<job_id>/answer")
def api_answer(job_id):
    job = jobs.get(job_id)
    if not job or "answer" not in job:
        abort(404)
    job["approved"] = bool((request.json or {}).get("approve"))
    job["answer"].set()
    return jsonify(ok=True)


@app.get("/api/usage")
def api_usage():
    return jsonify(**spending(), entries=load_ledger()[::-1][:20])


# ---------- sound lab ----------

LAB = os.path.join(WORK, "soundlab")


def lab_dir(source_id):
    if not re.fullmatch(r"[0-9a-f]{10}", source_id or ""):
        abort(400)
    return os.path.join(LAB, source_id)


def lab_source(source_id):
    d = lab_dir(source_id)
    files = [f for f in os.listdir(d) if f.startswith("source.")] if os.path.isdir(d) else []
    if not files:
        abort(404)
    return os.path.join(d, files[0])


def lab_prepare(update, source_id, url):
    d = lab_dir(source_id)
    title = "Uploaded file"
    if url:
        update(0.1, "Downloading audio from YouTube...")
        info = youtube.get_info(url)
        title = info.get("title") or title
        audio = youtube.download_audio(url, d)
        os.replace(audio, os.path.join(d, "source" + os.path.splitext(audio)[1]))
    update(0.6, "Reading the audio and drawing the waveform...")
    result = soundlab.prepare(lab_source(source_id), d, FFMPEG)
    return {"source_id": source_id, "title": title, **result}


@app.post("/api/soundlab/load")
def api_lab_load():
    source_id = uuid.uuid4().hex[:10]
    d = lab_dir(source_id)
    os.makedirs(d, exist_ok=True)
    url = ""
    f = request.files.get("file")
    if f:
        ext = os.path.splitext(f.filename or "")[1].lower() or ".bin"
        f.save(os.path.join(d, "source" + ext))
    else:
        url = (request.form.get("url") or "").strip()
        if not url:
            abort(400)
    return jsonify(job=start_job(lab_prepare, source_id, url))


@app.get("/soundlab/<source_id>/preview.mp3")
def api_lab_preview(source_id):
    return send_from_directory(lab_dir(source_id), "preview.mp3")


@app.post("/api/soundlab/split")
def api_lab_split():
    body = request.json or {}
    src = lab_source(body.get("source_id"))
    segments = soundlab.find_sounds(src, float(body.get("threshold_db", -35)),
                                    float(body.get("min_silence", 0.3)), ffmpeg=FFMPEG)
    return jsonify(segments=segments)


@app.post("/api/soundlab/save")
def api_lab_save():
    body = request.json or {}
    src = lab_source(body.get("source_id"))
    saved = []
    for item in body.get("items", []):
        kind = item.get("kind") if item.get("kind") in SOUND_DIRS else "sfx"
        folder = os.path.join(SOUNDS, SOUND_DIRS[kind][1][1])
        os.makedirs(folder, exist_ok=True)
        base = safe_name(item.get("name", ""), "sound")
        name, n = base + ".mp3", 2
        while os.path.exists(os.path.join(folder, name)):
            name, n = f"{base}_{n}.mp3", n + 1
        start, end = float(item["start"]), float(item["end"])
        if end - start < 0.05:
            continue
        soundlab.export(src, start, end, os.path.join(folder, name), item.get("normalize", True), FFMPEG)
        saved.append({"kind": kind, "name": name})
    return jsonify(saved=saved)


@app.get("/api/voices")
def api_voices():
    global _voices_cache
    if request.args.get("full") != "1":
        return jsonify(voices=[{"id": v, "name": n} for v, n in tts.VOICES])  # instant, works offline
    if not _voices_cache:
        _voices_cache = tts.list_voices()
    return jsonify(voices=_voices_cache)


_voices_cache = None


@app.post("/api/tts/preview")
def api_tts_preview():
    body = request.json or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify(error="Type something for the voice to say first."), 400
    try:
        spoken = tts.synthesize(text, body.get("voice") or tts.VOICES[0][0], body.get("rate", "+0%"),
                                os.path.join(WORK, "tts"))
    except RuntimeError as e:
        return jsonify(error=str(e)), 502
    return jsonify(url="/tts/" + os.path.basename(spoken["path"]), duration=spoken["duration"])


@app.get("/tts/<name>")
def serve_tts(name):
    return send_from_directory(os.path.join(WORK, "tts"), name)


@app.post("/api/voiceover/script")
def api_vo_script():
    return jsonify(job=start_job(write_script, request.json or {}))


@app.get("/output/<path:name>")
def serve_output(name):
    return send_from_directory(OUTPUT, name, as_attachment=request.args.get("download") == "1")


@app.post("/api/open-output")
def open_output():
    os.makedirs(OUTPUT, exist_ok=True)
    if hasattr(os, "startfile"):
        os.startfile(OUTPUT)
    return jsonify(ok=True)


if __name__ == "__main__":
    for kind in SOUND_DIRS.values():
        for _, sub in kind:
            os.makedirs(os.path.join(SOUNDS, sub), exist_ok=True)
    os.makedirs(FONTS, exist_ok=True)
    print(f"\n  ClipForge is running at http://127.0.0.1:{PORT}")
    print("  Keep this window open while you use the app. Close it to quit.\n")
    if not os.environ.get("CLIPFORGE_NO_BROWSER"):
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    app.run(host="127.0.0.1", port=PORT, threaded=True)
