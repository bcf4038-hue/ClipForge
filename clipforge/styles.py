"""Saved Top List styles: how the title, rank numbers, labels and cuts look.

A style is plain JSON so it can be edited in the app, copied from a reference
video by Claude, and reused for every Top List.
"""
import copy
import json
import os
import struct

BASE_FONTS = ["Arial Black", "Impact", "Segoe UI Black", "Bahnschrift", "Trebuchet MS",
              "Comic Sans MS", "Verdana", "Georgia", "Arial"]

DEFAULT = {
    "name": "Classic",
    "seconds_per_clip": 6,
    "framing": "center",
    "cut": {"whoosh": True, "flash": False, "zoom": False},
    "title": {"show": True, "font": "Arial Black", "size": 70, "color": "#FFFFFF", "outline_color": "#000000",
              "outline": 0, "box": True, "box_color": "#101010", "box_opacity": 0.8, "y": 0.08, "uppercase": True},
    "rank": {"font": "Arial Black", "size": 230, "color": "#FFE600", "outline_color": "#000000", "outline": 12,
             "y": 0.25, "prefix": "#", "animation": "pop"},
    "label": {"show": True, "font": "Arial Black", "size": 70, "color": "#FFFFFF", "outline_color": "#000000",
              "outline": 6, "y": 0.36, "uppercase": True},
}


def merged(style):
    """Fill any missing field from the default so older or partial styles still render."""
    out = copy.deepcopy(DEFAULT)
    for key, value in (style or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key].update(value)
        else:
            out[key] = value
    return out


def load_all(path):
    try:
        with open(path) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = []
    return [merged(DEFAULT)] + [merged(s) for s in saved if s.get("name") != DEFAULT["name"]]


def save(path, style):
    style = merged(style)
    try:
        with open(path) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = []
    saved = [s for s in saved if s.get("name") != style["name"]] + [style]
    with open(path, "w") as f:
        json.dump(saved, f, indent=2)
    return style


def delete(path, name):
    try:
        with open(path) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return
    with open(path, "w") as f:
        json.dump([s for s in saved if s.get("name") != name], f, indent=2)


def font_family(path):
    """Family name from a .ttf/.otf 'name' table (what the subtitle renderer looks fonts up by)."""
    with open(path, "rb") as f:
        data = f.read()
    num_tables = struct.unpack(">H", data[4:6])[0]
    for i in range(num_tables):
        tag, _, offset, _ = struct.unpack(">4sIII", data[12 + 16 * i: 28 + 16 * i])
        if tag != b"name":
            continue
        _, count, strings = struct.unpack(">HHH", data[offset:offset + 6])
        best = None
        for j in range(count):
            platform, encoding, _, name_id, length, str_off = struct.unpack(
                ">HHHHHH", data[offset + 6 + 12 * j: offset + 18 + 12 * j])
            if name_id != 1:
                continue
            raw = data[offset + strings + str_off: offset + strings + str_off + length]
            name = raw.decode("utf-16-be" if platform in (0, 3) else "latin-1", errors="ignore")
            if platform == 3 or best is None:
                best = name
        return best
    return None


def available_fonts(fonts_dir):
    """Windows fonts every PC has, plus any font files dropped into the fonts folder."""
    names = list(BASE_FONTS)
    if os.path.isdir(fonts_dir):
        for fname in sorted(os.listdir(fonts_dir)):
            if fname.lower().endswith((".ttf", ".otf")):
                try:
                    family = font_family(os.path.join(fonts_dir, fname))
                except (OSError, struct.error):
                    family = None
                if family and family not in names:
                    names.append(family)
    return names
