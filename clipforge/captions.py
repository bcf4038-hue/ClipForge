"""Build word-by-word animated captions as an .ass subtitle file for FFmpeg."""
from . import styles


def _ass_color(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def _override_color(hex_color):
    h = hex_color.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def _ts(t):
    t = max(t, 0)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs % 360000 // 6000:02d}:{cs % 6000 // 100:02d}.{cs % 100:02d}"


def _escape(text):
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def clip_words(words, start, end, edited_text=None):
    """Words inside [start, end] with times relative to the clip start.

    If the user edited the caption text, the new words are spread over the
    original word timings so they stay in sync with the speech.
    """
    inside = [w for w in words if w["s"] >= start - 0.05 and w["s"] < end]
    rel = [{"w": w["w"], "s": w["s"] - start, "e": min(w["e"], end) - start} for w in inside]
    if edited_text is None or not rel:
        return rel
    new = edited_text.split()
    if not new:
        return []
    out = []
    n_old, n_new = len(rel), len(new)
    for i, text in enumerate(new):
        a = rel[min(int(i * n_old / n_new), n_old - 1)]
        b = rel[min(int((i + 1) * n_old / n_new) - 1, n_old - 1)]
        if b["s"] < a["s"]:
            b = a
        out.append({"w": text, "s": a["s"], "e": b["e"]})
    # Several new words can share one old slot: split that slot evenly.
    i = 0
    while i < len(out):
        j = i
        while j + 1 < len(out) and out[j + 1]["s"] == out[i]["s"]:
            j += 1
        if j > i:
            s, e = out[i]["s"], out[j]["e"]
            step = (e - s) / (j - i + 1)
            for k in range(i, j + 1):
                out[k]["s"] = s + step * (k - i)
                out[k]["e"] = s + step * (k - i + 1)
        i = j + 1
    return out


def _chunks(words, per_chunk):
    chunk = []
    for w in words:
        if chunk and (len(chunk) >= per_chunk or w["s"] - chunk[-1]["e"] > 0.6):
            yield chunk
            chunk = []
        chunk.append(w)
    if chunk:
        yield chunk


POSITIONS = {"bottom": (2, 420), "middle": (5, 0), "top": (8, 300)}


def _alpha_color(hex_color, opacity=1.0):
    """ASS colour with transparency: &HAABBGGRR, where AA=00 is solid."""
    h = hex_color.lstrip("#")
    alpha = int(round((1 - max(0.0, min(1.0, float(opacity)))) * 255))
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _overlay_styles(overlays):
    """Title / Rank / Label styles for top-list videos, taken from the overlay's Style."""
    if not overlays:
        return ""
    st = styles.merged(overlays.get("style"))
    t, r, l = st["title"], st["rank"], st["label"]
    if t.get("box"):
        title = (f"Style: Title,{t['font']},{int(t['size'])},{_ass_color(t['color'])},{_ass_color(t['color'])},"
                 f"{_alpha_color(t['box_color'], t.get('box_opacity', 0.8))},&H00000000,-1,0,0,0,100,100,0,0,3,22,0,8,60,60,0,1")
    else:
        title = (f"Style: Title,{t['font']},{int(t['size'])},{_ass_color(t['color'])},{_ass_color(t['color'])},"
                 f"{_ass_color(t['outline_color'])},&H80000000,-1,0,0,0,100,100,0,0,1,{int(t['outline'])},3,8,60,60,0,1")
    rank = (f"Style: Rank,{r['font']},{int(r['size'])},{_ass_color(r['color'])},{_ass_color(r['color'])},"
            f"{_ass_color(r['outline_color'])},&H80000000,-1,0,0,0,100,100,0,0,1,{int(r['outline'])},6,5,60,60,0,1")
    label = (f"Style: Label,{l['font']},{int(l['size'])},{_ass_color(l['color'])},{_ass_color(l['color'])},"
             f"{_ass_color(l['outline_color'])},&H80000000,-1,0,0,0,100,100,0,0,1,{int(l['outline'])},3,5,80,80,0,1")
    return "\n".join([title, rank, label])


def build_ass(words, style, duration, overlays=None):
    """overlays: None or {"title": str, "ranks": [{"start", "end", "rank", "label"}]} for top-list videos."""
    font = style.get("font", "Arial Black")
    size = int(style.get("size", 90))
    color = _ass_color(style.get("color", "#FFFFFF"))
    highlight = _override_color(style.get("highlight", "#FFE600"))
    upper = style.get("uppercase", True)
    per_chunk = max(1, int(style.get("words_per_line", 3)))
    align, margin_v = POSITIONS.get(style.get("position", "bottom"), POSITIONS["bottom"])

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{color},{color},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{max(3, size // 14)},3,{align},60,60,{margin_v},1
{_overlay_styles(overlays)}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    chunks = list(_chunks(words, per_chunk))
    for ci, chunk in enumerate(chunks):
        # Keep the chunk on screen until the next one starts (small gaps only).
        chunk_end = chunk[-1]["e"]
        if ci + 1 < len(chunks) and chunks[ci + 1][0]["s"] - chunk_end < 0.4:
            chunk_end = chunks[ci + 1][0]["s"]
        chunk_end = min(chunk_end, duration)
        texts = [_escape(w["w"].upper() if upper else w["w"]) for w in chunk]
        for wi, w in enumerate(chunk):
            start = w["s"]
            end = chunk[wi + 1]["s"] if wi + 1 < len(chunk) else chunk_end
            if end <= start:
                continue
            parts = []
            for k, t in enumerate(texts):
                if k == wi:
                    pop = r"\t(0,80,\fscx112\fscy112)" if style.get("pop", True) else ""
                    parts.append(f"{{\\c{highlight}\\fscx100\\fscy100{pop}}}{t}{{\\r}}")
                else:
                    parts.append(t)
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{' '.join(parts)}")
    if overlays:
        st = styles.merged(overlays.get("style"))
        t, rk, lb = st["title"], st["rank"], st["label"]
        H = 1920
        if overlays.get("title") and t.get("show", True):
            text = overlays["title"].upper() if t.get("uppercase", True) else overlays["title"]
            lines.append(f"Dialogue: 1,{_ts(0)},{_ts(duration)},Title,,0,0,0,,"
                         f"{{\\an8\\pos(540,{int(float(t['y']) * H)})\\fad(250,0)}}{_escape(text)}")
        anim = {"pop": "\\fscx35\\fscy35\\t(0,200,\\fscx100\\fscy100)", "fade": "\\fad(200,0)", "none": ""}
        for r in overlays.get("ranks", []):
            start, end = float(r["start"]), min(float(r["end"]), duration)
            if end <= start:
                continue
            # The number pops in, the label fades in just after it.
            lines.append(f"Dialogue: 2,{_ts(start)},{_ts(end)},Rank,,0,0,0,,"
                         f"{{\\an5\\pos(540,{int(float(rk['y']) * H)}){anim.get(rk.get('animation'), anim['pop'])}}}"
                         f"{_escape(rk.get('prefix', '#'))}{int(r['rank'])}")
            if r.get("label") and lb.get("show", True):
                text = r["label"].upper() if lb.get("uppercase", True) else r["label"]
                lines.append(f"Dialogue: 2,{_ts(start + 0.15)},{_ts(end)},Label,,0,0,0,,"
                             f"{{\\an5\\pos(540,{int(float(lb['y']) * H)})\\fad(200,0)}}{_escape(text)}")
    return header + "\n".join(lines) + "\n"
