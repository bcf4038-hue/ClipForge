"""Quiz Shorts: Claude writes Roblox quiz questions, and they're laid out as an Editor project.

Three quiz types:
    emoji     guess the game from emojis
    truefalse true or false statements
    versus    which of two games is older / more popular
The finished project opens in the Editor, so every text, sound and timing can still be changed.
"""
import textwrap

from . import ai
from .editor import TEXT_DEFAULT, new_id, new_project

TYPES = {
    "emoji": {"title": "GUESS THE ROBLOX GAME FROM THE EMOJIS",
              "header": "GUESS THE GAME"},
    "truefalse": {"title": "ROBLOX TRUE OR FALSE", "header": "TRUE OR FALSE?"},
    "versus": {"title": "WHICH ROBLOX GAME IS OLDER OR MORE POPULAR", "header": "WHICH ONE?"},
}
# Questions used for each length, plus a few spares to swap in when reviewing.
LENGTHS = {"short": {"count": 3, "spares": 2, "label": "about 30 seconds"},
           "long": {"count": 8, "spares": 3, "label": "60 to 75 seconds"}}
TIMER = 3  # seconds to answer
SECONDS_PER_QUESTION = 7.8  # rough average, used for the length estimate before the voice exists

SYSTEM = """You write quiz questions for Roblox YouTube Shorts and TikToks, aimed at Roblox players \
aged 13 to 25.

Rules:
- Only use facts you are confident about. Popular, well-known games (Adopt Me!, Brookhaven, Blox Fruits, \
Doors, Pet Simulator 99, Tower of Hell, Murder Mystery 2, Arsenal, Jailbreak, Natural Disaster Survival, \
Grow a Garden and similar) are safest.
- Set "sure" to false for any question whose answer you are not certain of, especially anything about \
recent updates, exact dates or player counts. The creator checks those by hand.
- Order the questions from easiest to hardest. The first is easy so viewers keep watching; the last is genuinely hard (the video calls it IMPOSSIBLE).
- Spoken text is read aloud by a text-to-speech voice: plain words, no emojis, no hashtags, no stage directions.
- Never repeat a game as an answer in the same quiz."""

_STR = {"type": "string"}
_BOOL = {"type": "boolean"}
_QUESTION_SCHEMAS = {
    "emoji": {
        "emojis": {"type": "string", "description": "2 to 4 emojis that hint at the game, no words"},
        "answer": {"type": "string", "description": "The game's name as players know it"},
        "sure": _BOOL,
    },
    "truefalse": {
        "statement": {"type": "string", "description": "A short statement about Roblox, under 90 characters"},
        "answer": {"type": "boolean", "description": "true if the statement is true"},
        "fact": {"type": "string", "description": "Why, in under 12 words"},
        "sure": _BOOL,
    },
    "versus": {
        "kind": {"type": "string", "enum": ["older", "popular"],
                 "description": "older = which came out first; popular = which has more total visits"},
        "a": {"type": "string", "description": "First game"},
        "b": {"type": "string", "description": "Second game"},
        "answer": {"type": "string", "enum": ["a", "b"]},
        "fact": {"type": "string", "description": "The proof, in under 12 words"},
        "sure": _BOOL,
    },
}


def schema(kind):
    item = {"type": "object", "additionalProperties": False, "properties": _QUESTION_SCHEMAS[kind],
            "required": list(_QUESTION_SCHEMAS[kind])}
    return {"type": "object", "additionalProperties": False,
            "properties": {"hook": {"type": "string", "description": "Opening challenge read aloud in the first 2 seconds, under 9 words, e.g. "
                                                                     "'Only 1 percent of Roblox players get all of these!'"},
                           "questions": {"type": "array", "items": item}},
            "required": ["hook", "questions"]}


def request(kind, length, topic):
    n = LENGTHS[length]["count"] + LENGTHS[length]["spares"]
    what = {"emoji": "Guess the Roblox game from emojis",
            "truefalse": "Roblox true or false",
            "versus": "Which Roblox game is older, or which is more popular (mix both kinds)"}[kind]
    prompt = f"Quiz type: {what}.\nWrite exactly {n} questions."
    if topic:
        prompt += f"\nTopic from the creator:\n<topic>\n{topic}\n</topic>"
    return {"model": ai.MODEL, "system": SYSTEM, "messages": [{"role": "user", "content": prompt}],
            "output_config": {"effort": "medium", "format": {"type": "json_schema", "schema": schema(kind)}}}


def estimate(api_key, req):
    return ai._estimate(api_key, req, (1000, 4000), 8000)


def write(api_key, req):
    return ai._run_json(api_key, req, 8000, "write these quiz questions")


# ---------- turning questions into words to say ----------

ORDINAL = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"]


def lines(kind, questions, hook, count):
    """What the voice says: [(key, text)]. Keys: hook, q1, a1, q2, a2..., outro."""
    out = [("hook", hook.strip() or f"Can you get all {count}?")]
    for i, q in enumerate(questions, 1):
        num = f"Number {ORDINAL[i - 1] if i <= len(ORDINAL) else i}."
        if kind == "emoji":
            ask = f"{num} What game is this?" if i == 1 else num
            say = f"It's {q['answer'].strip().rstrip('!.')}!"
        elif kind == "truefalse":
            ask = f"{num} {q['statement'].strip()}"
            say = f"{'True' if q['answer'] else 'False'}! {q['fact'].strip()}"
        else:
            word = "older" if q["kind"] == "older" else "more popular"
            ask = f"{num} Which is {word}: {q['a'].strip()}, or {q['b'].strip()}?"
            say = f"{q[q['answer']].strip()}! {q['fact'].strip()}"
        out += [(f"q{i}", ask), (f"a{i}", say)]
    out.append(("outro", "How many did you get? Comment your score!"))
    return out


# ---------- looks ----------
# Every theme keeps the RoRush feel (same fonts, layout and branding) and changes the colors,
# background and sounds. "bg" is the two gradient colors of the moving background.
THEMES = {
    "rorush": {"name": "RoRush (orange + teal)", "bg": ("0F5560", "2A1450"), "accent": "#FF7A1A",
               "box": "#FF7A1A", "hl": "#19C3B5", "timer": "#FFE600"},
    "neon": {"name": "Neon", "bg": ("1B0B3A", "0B4F6C"), "accent": "#FF2EC4", "box": "#7C3AED",
             "hl": "#22D3EE", "timer": "#22D3EE"},
    "horror": {"name": "Horror", "bg": ("2A0505", "050505"), "accent": "#EF4444", "box": "#B91C1C",
               "hl": "#7F1D1D", "timer": "#F87171", "boom": True},
    "candy": {"name": "Candy", "bg": ("C2367A", "5B3FD1"), "accent": "#FFE600", "box": "#FF4FA3",
              "hl": "#7C5CFF", "timer": "#FFE600"},
    "gold": {"name": "Gold", "bg": ("1C1406", "5A3E0A"), "accent": "#FFC83D", "box": "#B8860B",
             "hl": "#8A6512", "timer": "#FFC83D"},
    "ice": {"name": "Ice", "bg": ("0B3A5C", "3C8DBC"), "accent": "#7DD3FC", "box": "#0EA5E9",
            "hl": "#0369A1", "timer": "#E0F2FE"},
    "toxic": {"name": "Toxic", "bg": ("0A1F0A", "2F5D12"), "accent": "#A3E635", "box": "#4D7C0F",
              "hl": "#365314", "timer": "#D9F99D"},
    "sunset": {"name": "Sunset", "bg": ("C2410C", "4C1D5C"), "accent": "#FFE600", "box": "#E11D48",
               "hl": "#9D174D", "timer": "#FFE600"},
}
# Topic words that pick a theme automatically.
THEME_WORDS = {
    "horror": ("horror", "scary", "doors", "pressure", "piggy", "evade", "creepy", "dead", "zombie", "halloween"),
    "candy": ("pet", "simulator", "adopt", "cute", "brookhaven", "royale high", "dress"),
    "gold": ("rich", "money", "rare", "expensive", "robux", "limited", "legendary", "best"),
    "ice": ("winter", "christmas", "snow", "ice", "cold"),
    "toxic": ("hard", "impossible", "obby", "tower", "parkour"),
    "neon": ("anime", "fight", "blox fruits", "combat", "pvp", "battle", "arsenal"),
    "sunset": ("old", "history", "classic", "nostalgia", "first"),
}


def pick_theme(topic, choice=None):
    import random
    if choice in THEMES:
        return choice
    words = (topic or "").lower()
    for theme, keys in THEME_WORDS.items():
        if any(k in words for k in keys):
            return theme
    return random.choice(list(THEMES))


def difficulty(i, count):
    """EASY -> MEDIUM -> HARD, and the last one is IMPOSSIBLE (questions come easiest first)."""
    if count >= 4 and i == count:
        return "IMPOSSIBLE", "#EF4444"
    f = (i - 1) / max(count - 1, 1)
    return ("EASY", "#22C55E") if f < 0.34 else ("MEDIUM", "#EAB308") if f < 0.67 else ("HARD", "#F97316")


# ---------- the Editor project ----------

GREEN, RED, DARK = "#22C55E", "#EF4444", "#0D1B20"
BAR_W = 760  # progress and timer bar width in pixels (frame is 1080 wide)


def _text(text, start, end, y, **look):
    t = {**TEXT_DEFAULT, "id": new_id(), "text": text, "start": round(start, 3), "end": round(end, 3),
         "x": 0.5, "y": y}
    t.update(look)
    return t


def _bar(start, end, y, width, height, color, x=0.5, anim="none"):
    return _text("", start, end, y, shape="bar", bar_w=round(width), bar_h=height, color=color, outline=0,
                 x=round(x, 4), anim=anim)


def _wrap(text, width):
    return "\n".join(textwrap.wrap(text, width)) or text


def build(kind, questions, hook, voice, sfx, music, bg_media, bg_duration, name, theme="rorush"):
    """Lay the quiz out on a timeline.

    voice: {line key: (sound path, seconds)}; sfx: {name: sound path or None} for tick, correct, wrong,
    whoosh, pop, boom and riser.
    """
    th = THEMES.get(theme) or THEMES["rorush"]
    p = new_project()
    p["name"] = name
    p["effects"] = []
    texts, sounds, effects = p["texts"], p["sounds"], p["effects"]

    def say(key, at):
        path, secs = voice[key]
        sounds.append({"id": new_id(), "sound": path, "start": round(at, 3), "volume": 1.0})
        return secs

    def fx(name_, at, volume=0.7):
        if sfx.get(name_):
            sounds.append({"id": new_id(), "sound": sfx[name_], "start": round(max(at, 0), 3), "volume": volume})

    def effect(type_, at, color=None):
        effects.append({"id": new_id(), "type": type_, "start": round(at, 3), **({"color": color} if color else {})})

    count = len(questions)
    # Hook: straight into a challenge, with a hit, so people stop scrolling in the first second.
    hook_len = max(1.8, voice["hook"][1] + 0.35)
    fx("boom" if th.get("boom") else "pop", 0.0, 0.8)
    effect("punch", 0.0)
    effect("flash", 0.0, th["accent"])
    texts.append(_text(_wrap(hook.strip().upper() or f"CAN YOU GET ALL {count}?", 14), 0, hook_len, 0.4, size=104,
                       color="#FFFFFF", outline=12, anim="pop"))
    if count >= 4:
        texts.append(_text(f"WAIT FOR #{count} 😱", 0.45, hook_len, 0.58, size=64, color=DARK, box=True,
                           box_color=th["accent"], box_opacity=1, anim="pop"))
    say("hook", 0.1)
    t = hook_len

    for i, q in enumerate(questions, 1):
        if i == count and count >= 4:
            # Build-up before the last question.
            fx("riser", t, 0.5)
            effect("flash", t + 1.0, "#FFFFFF")
            texts.append(_text("FINAL\nQUESTION 😱", t, t + 1.1, 0.42, size=120, color="#FFFFFF", outline=12,
                               anim="pop"))
            t += 1.1
        qs = t
        fx("whoosh", qs, 0.5)
        ask = say(f"q{i}", qs + 0.2)
        timer_at = qs + 0.2 + ask + 0.2
        reveal = timer_at + TIMER
        ans = say(f"a{i}", reveal + 0.35)
        end = max(reveal + 0.35 + ans + 0.5, reveal + 1.7)

        # Progress, question number and difficulty.
        texts.append(_bar(qs, end, 0.118, BAR_W, 16, "#081014", anim="none"))
        fill = BAR_W * i / count
        texts.append(_bar(qs, end, 0.118, fill, 16, th["accent"], x=(540 - BAR_W / 2 + fill / 2) / 1080))
        texts.append(_text(f"QUESTION {i}/{count}", qs, end, 0.168, size=54, color="#FFFFFF", outline=7, anim="none"))
        level, level_color = difficulty(i, count)
        texts.append(_text(level, qs, end, 0.215, size=40, color="#FFFFFF", box=True, box_color=level_color,
                           box_opacity=1))
        if i == 1:
            texts.append(_text("KEEP SCORE 👀", qs + 0.3, qs + 2.6, 0.29, size=42, color=th["timer"], outline=5,
                               anim="fade"))

        good = True
        if kind == "emoji":
            texts.append(_text(q["emojis"], qs, end, 0.42, size=220, outline=0, uppercase=False))
            texts.append(_text(_wrap(q["answer"], 16), reveal, end, 0.66, size=88, color="#FFFFFF", box=True,
                               box_color=GREEN, box_opacity=1))
        elif kind == "truefalse":
            good = bool(q["answer"])
            texts.append(_text(_wrap(q["statement"], 18), qs, end, 0.42, size=78, color="#FFFFFF", outline=8))
            texts.append(_text("TRUE" if good else "FALSE", reveal, end, 0.64, size=130, color="#FFFFFF", box=True,
                               box_color=GREEN if good else RED, box_opacity=1))
            texts.append(_text(_wrap(q["fact"], 24), reveal + 0.3, end, 0.75, size=56, color="#FFFFFF", outline=5,
                               anim="fade", uppercase=False))
        else:
            word = "OLDER" if q["kind"] == "older" else "MORE POPULAR"
            texts.append(_text(f"WHICH IS {word}?", qs, end, 0.3, size=72, color=th["timer"], outline=7))
            for key, y in (("a", 0.4), ("b", 0.54)):
                texts.append(_text(_wrap(q[key], 16), qs, reveal, y, size=88, color="#FFFFFF", box=True,
                                   box_color=th["hl"], box_opacity=1))
                win = key == q["answer"]
                texts.append(_text(_wrap(q[key], 16) + (" ✅" if win else ""), reveal, end, y, size=88,
                                   color="#FFFFFF", box=True, box_color=GREEN if win else "#3A4A50",
                                   box_opacity=1 if win else 0.85, anim="none"))
            texts.append(_text("VS", qs, end, 0.47, size=80, color=th["accent"], outline=8))
            texts.append(_text(_wrap(q["fact"], 24), reveal + 0.3, end, 0.66, size=56, color="#FFFFFF",
                               outline=5, anim="fade", uppercase=False))

        # Timer: a draining bar plus 3, 2, 1 with a tick each second.
        timer_y = 0.64 if kind == "truefalse" else 0.66
        texts.append(_bar(timer_at, reveal, 0.755, BAR_W, 26, th["timer"], anim="drain"))
        for k in range(TIMER):
            texts.append(_text(str(TIMER - k), timer_at + k, timer_at + k + 1, timer_y, size=190, color=th["timer"],
                               outline=12))
            fx("tick", timer_at + k, 0.8)
        # Reveal: sound, zoom punch and a green (or red) flash.
        fx("correct" if good else "wrong", reveal, 0.7 if good else 0.45)
        effect("punch", reveal)
        effect("flash", reveal, GREEN if good else RED)
        t = end

    outro = max(2.6, voice["outro"][1] + 0.8)
    fx("pop", t)
    effect("punch", t)
    texts.append(_text("HOW MANY DID\nYOU GET? 👇", t, t + outro, 0.42, size=96, color="#FFFFFF", outline=10))
    texts.append(_text("COMMENT YOUR SCORE", t + 0.3, t + outro, 0.56, size=60, color=DARK, box=True,
                       box_color=th["timer"], box_opacity=1))
    say("outro", t + 0.2)
    t += outro

    # Branding that stays the same on every theme.
    texts.insert(0, _text(TYPES[kind]["header"], 0, t, 0.07, size=62, color="#FFFFFF", box=True,
                          box_color=th["box"], box_opacity=1, anim="none"))
    texts.append(_text("RORUSH CLIPS", 0, t, 0.835, size=32, color=th["accent"], outline=4, anim="none"))
    total = round(min(t, bg_duration), 3)
    p["clips"] = [{"id": new_id(), "media": bg_media, "in": 0, "out": total, "volume": 0, "audio": "mute",
                   "framing": "fill", "media_duration": bg_duration}]
    if music:
        p["music"] = {"sound": music, "volume": 0.12}
    p["theme"] = theme
    return p
