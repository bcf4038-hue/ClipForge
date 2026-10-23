"""YouTube access: video info, captions with word timings, and clip-section downloads."""
import glob
import json
import os

import yt_dlp
from yt_dlp.utils import download_range_func


_auth = {}


def set_auth(browser=None, cookie_file=None):
    """Borrow YouTube login cookies so YouTube doesn't block us as a bot."""
    _auth.clear()
    if cookie_file:
        _auth["cookiefile"] = cookie_file
    elif browser:
        _auth["cookiesfrombrowser"] = (browser,)


_impersonate = None  # cached: the "pretend to be Chrome" option, or {} if unavailable


def _impersonate_opts():
    """TikTok blocks plain downloaders; yt-dlp can pose as Chrome if curl-cffi is installed."""
    global _impersonate
    if _impersonate is None:
        try:
            from yt_dlp.networking.impersonate import ImpersonateTarget
            opts = {"impersonate": ImpersonateTarget.from_str("chrome")}
            with yt_dlp.YoutubeDL({**opts, "quiet": True}):
                pass  # raises if no backend can impersonate
            _impersonate = opts
        except Exception:
            _impersonate = {}
    return _impersonate


def _base_opts(url=None):
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True, **_auth}
    if url and "tiktok.com" in url:
        opts.update(_impersonate_opts())
    return opts


def get_info(url):
    with yt_dlp.YoutubeDL({**_base_opts(url), "skip_download": True}) as ydl:
        return ydl.sanitize_info(ydl.extract_info(url, download=False))


def _pick_track(tracks, lang):
    """Pick the best json3 caption URL for the video's own language."""
    if not tracks:
        return None
    candidates = [f"{lang}-orig", lang] if lang else []
    candidates += [k for k in tracks if k.endswith("-orig")]
    candidates += [k for k in tracks if k.startswith("en")]
    candidates += list(tracks)
    for key in candidates:
        for fmt in tracks.get(key) or []:
            if fmt.get("ext") == "json3":
                return fmt["url"]
    return None


def _parse_json3(data):
    """Turn YouTube json3 captions into [{w, s, e}] words (seconds)."""
    words = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        t0 = ev.get("tStartMs", 0)
        dur = ev.get("dDurationMs", 0)
        pieces = []
        for seg in segs:
            text = seg.get("utf8", "").strip()
            if text:
                pieces.append((t0 + seg.get("tOffsetMs", 0), text.split()))
        # Manual captions put a whole line in one segment: spread its words evenly.
        for i, (start, parts) in enumerate(pieces):
            nxt = pieces[i + 1][0] if i + 1 < len(pieces) else t0 + dur
            span = max(nxt - start, 1)
            for k, part in enumerate(parts):
                if part.startswith("[") and part.endswith("]"):
                    continue  # [Music], [Applause]
                words.append({"w": part, "s": (start + span * k / len(parts)) / 1000})
    words.sort(key=lambda w: w["s"])
    for i, w in enumerate(words):
        nxt = words[i + 1]["s"] if i + 1 < len(words) else w["s"] + 0.6
        w["e"] = round(min(nxt, w["s"] + 1.2), 3)
        w["s"] = round(w["s"], 3)
    return words


def get_caption_words(url, info):
    """Return (words, source) using YouTube's captions, or (None, None) if there are none."""
    lang = (info.get("language") or "").split("-")[0] or None
    with yt_dlp.YoutubeDL(_base_opts(url)) as ydl:
        # Auto captions carry per-word timing; uploaded captions only have per-line timing.
        for source, tracks in (("youtube-auto", info.get("automatic_captions")),
                               ("youtube-manual", info.get("subtitles"))):
            track_url = _pick_track(tracks, lang)
            if not track_url:
                continue
            data = json.loads(ydl.urlopen(track_url).read().decode("utf-8"))
            words = _parse_json3(data)
            if len(words) > 20:
                return words, source
    return None, None


def download_audio(url, out_dir):
    opts = {**_base_opts(url), "format": "bestaudio/best",
            "outtmpl": os.path.join(out_dir, "audio.%(ext)s")}
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    return glob.glob(os.path.join(out_dir, "audio.*"))[0]


def download_video(url, out_base):
    """Download a whole video as an mp4 (up to 1080p)."""
    opts = {
        **_base_opts(url),
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": out_base + ".%(ext)s",
        "overwrites": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    files = glob.glob(out_base + ".*")
    if not files:
        raise RuntimeError("Download failed: no file was produced.")
    return files[0]


def download_section(url, start, end, out_base):
    """Download just [start, end] seconds of the video as an mp4 (up to 1080p)."""
    existing = glob.glob(out_base + ".mp4")
    if existing:
        return existing[0]
    opts = {
        **_base_opts(url),
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "download_ranges": download_range_func(None, [(start, end)]),
        "force_keyframes_at_cuts": True,  # frame-accurate cut so captions stay in sync
        "merge_output_format": "mp4",
        "outtmpl": out_base + ".%(ext)s",
        "overwrites": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    files = glob.glob(out_base + ".*")
    if not files:
        raise RuntimeError("Download failed: no file was produced.")
    return files[0]
