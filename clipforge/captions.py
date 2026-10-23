"""Build word-by-word animated captions as an .ass subtitle file for FFmpeg."""


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
Style: Title,{font},70,&H00FFFFFF,&H00FFFFFF,&H30101010,&H00000000,-1,0,0,0,100,100,0,0,3,22,0,8,70,70,150,1
Style: Rank,{font},230,{_ass_color(style.get("highlight", "#FFE600"))},&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,12,6,8,60,60,330,1
Style: Label,{font},70,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,3,8,80,80,600,1

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
        if overlays.get("title"):
            title = _escape(overlays["title"].upper() if upper else overlays["title"])
            lines.append(f"Dialogue: 1,{_ts(0)},{_ts(duration)},Title,,0,0,0,,{{\\fad(250,0)}}{title}")
        for r in overlays.get("ranks", []):
            start, end = float(r["start"]), min(float(r["end"]), duration)
            if end <= start:
                continue
            # The number pops in from small, the label fades in just after it.
            lines.append(f"Dialogue: 2,{_ts(start)},{_ts(end)},Rank,,0,0,0,,"
                         f"{{\\fscx35\\fscy35\\t(0,200,\\fscx100\\fscy100)}}#{int(r['rank'])}")
            if r.get("label"):
                label = _escape(r["label"].upper() if upper else r["label"])
                lines.append(f"Dialogue: 2,{_ts(start + 0.15)},{_ts(end)},Label,,0,0,0,,{{\\fad(200,0)}}{label}")
    return header + "\n".join(lines) + "\n"
