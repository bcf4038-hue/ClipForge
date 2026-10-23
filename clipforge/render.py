"""Render one finished Short with FFmpeg: crop, captions, music, and sound effects."""
import json
import os
import subprocess

from . import captions, crop


def probe(path, ffprobe="ffprobe"):
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
         "-of", "json", path], capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    has_audio = any(s["codec_type"] == "audio" for s in data["streams"])
    return int(video["width"]), int(video["height"]), float(data["format"]["duration"]), has_audio


def _video_filter(mode, src, w, h, track_cache):
    base = f"scale={crop.OUT_W}:{crop.OUT_H}:force_original_aspect_ratio=increase"
    if mode == "fit":
        return (f"[0:v]split=2[bg][fg];[bg]{base},crop={crop.OUT_W}:{crop.OUT_H},boxblur=25:2[bgb];"
                f"[fg]scale={crop.OUT_W}:-2[fgs];[bgb][fgs]overlay=(W-w)/2:(H-h)/2")
    if mode == "auto":
        if not os.path.exists(track_cache):
            samples, src_w = crop.face_centers(src)
            with open(track_cache, "w") as f:
                json.dump({"samples": samples, "src_w": src_w}, f)
        with open(track_cache) as f:
            data = json.load(f)
        segments = crop.crop_segments([tuple(s) for s in data["samples"]], data["src_w"])
        x = crop.crop_x_expr(segments, w, h)
    else:
        x = {"left": "0", "right": "iw-ow"}.get(mode, "(iw-ow)/2")
    return f"[0:v]{base},crop={crop.OUT_W}:{crop.OUT_H}:'{x}':'(ih-oh)/2'"


def _cut_effects(effects):
    """Quick zoom punch and/or white flash at each cut, applied after the 9:16 crop."""
    if not effects or not effects.get("cuts"):
        return ""
    cuts = [float(c) for c in effects["cuts"]]
    out = ""
    if effects.get("zoom"):
        # Scale jumps 12% at each cut and eases back over 0.3 s; commas escaped for the filter graph.
        punch = "+".join(f"max(0\\,1-abs(t-{c:.3f})/0.3)*gte(t\\,{c:.3f})" for c in cuts)
        out += (f",scale=w='trunc(1080*(1+0.12*({punch}))/2)*2':h=-2:eval=frame,"
                f"crop={crop.OUT_W}:{crop.OUT_H}")
    if effects.get("flash"):
        when = "+".join(f"between(t\\,{c - 0.03:.3f}\\,{c + 0.07:.3f})" for c in cuts)
        out += f",drawbox=color=white@0.85:t=fill:enable='{when}'"
    return out


def render(src, out_path, words, style, crop_mode, music, sfx, workdir,
           ffmpeg="ffmpeg", ffprobe="ffprobe", progress=lambda p: None, voiceover=None, overlays=None,
           effects=None, fonts_dir=None):
    """
    words:     clip-relative caption words [{w, s, e}]
    music:     None or {"path", "volume"} (volume 0..1)
    sfx:       [{"path", "at", "volume"}] with "at" in seconds from clip start
    voiceover: None or {"path", "at", "volume"}; the clip's own audio is lowered under it
    """
    w, h, duration, has_audio = probe(src, ffprobe)
    os.makedirs(workdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(src))[0]
    ass_name = base + ".ass"
    with open(os.path.join(workdir, ass_name), "w", encoding="utf-8") as f:
        f.write(captions.build_ass(words, style, duration, overlays))

    vf = _video_filter(crop_mode, src, w, h, os.path.join(workdir, base + ".faces.json"))
    vf += _cut_effects(effects)
    if words or overlays:
        vf += f",ass={ass_name}"
        if fonts_dir and os.path.isdir(fonts_dir):
            # Relative path with forward slashes: a Windows "C:\" path breaks FFmpeg's filter syntax.
            rel = os.path.relpath(fonts_dir, workdir).replace("\\", "/")
            vf += f":fontsdir={rel}"
    filters = [vf + ",format=yuv420p[v]"]

    inputs = ["-i", os.path.abspath(src)]
    fmt = "aformat=sample_rates=48000:channel_layouts=stereo"
    if has_audio:
        filters.append(f"[0:a]{fmt},asplit=2[voice][side]")
    else:
        filters.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{duration:.3f},asplit=2[voice][side]")
    idx = 1
    key = "[side]"  # what the music ducks under: the clip's own audio, or the voiceover
    if voiceover:
        inputs += ["-i", os.path.abspath(voiceover["path"])]
        delay = int(max(voiceover.get("at", 0), 0) * 1000)
        # Pad then trim to exactly the clip length: an endless stream would never let FFmpeg finish.
        branches = "[vo][vokey1][vokey2]" if music else "[vo][vokey1]"
        filters.append(f"[{idx}:a]{fmt},volume={float(voiceover.get('volume', 1.0)):.3f},"
                       f"adelay=delays={delay}:all=1,apad,atrim=0:{duration:.3f},"
                       f"asplit={2 if not music else 3}{branches}")
        # Game audio gets quieter whenever the AI voice is talking.
        filters.append("[voice][vokey1]sidechaincompress=threshold=0.02:ratio=12:attack=15:release=350[game]")
        filters.append("[side]anullsink")
        mix = ["[game]", "[vo]"]
        key = "[vokey2]" if music else None
        idx += 1
    else:
        mix = ["[voice]"]
    if music:
        inputs += ["-stream_loop", "-1", "-i", os.path.abspath(music["path"])]
        fade_at = max(duration - 1.5, 0)
        filters.append(
            f"[{idx}:a]{fmt},volume={float(music['volume']):.3f},atrim=0:{duration:.3f},"
            f"afade=t=in:d=0.5,afade=t=out:st={fade_at:.3f}:d=1.5[mus]")
        # Duck the music whenever someone is talking.
        filters.append(f"[mus]{key}sidechaincompress=threshold=0.03:ratio=6:attack=20:release=500[duck]")
        mix.append("[duck]")
        idx += 1
    elif key:
        filters.append(f"{key}anullsink")
    for k, fx in enumerate(sfx):
        if fx["at"] >= duration:
            continue
        inputs += ["-i", os.path.abspath(fx["path"])]
        delay = int(max(fx["at"], 0) * 1000)
        filters.append(f"[{idx}:a]{fmt},volume={float(fx['volume']):.3f},adelay=delays={delay}:all=1[fx{k}]")
        mix.append(f"[fx{k}]")
        idx += 1
    filters.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=first,alimiter=limit=0.95[a]")

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
           *inputs, "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
           "-t", f"{duration:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", os.path.abspath(out_path)]
    proc = subprocess.Popen(cmd, cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in proc.stdout:
        if line.startswith("out_time_us=") and line.strip() != "out_time_us=N/A":
            progress(min(int(line.split("=")[1]) / 1e6 / duration, 1.0))
    err = proc.stderr.read()
    if proc.wait() != 0:
        raise RuntimeError("FFmpeg failed: " + err.strip()[-800:])
    return out_path
