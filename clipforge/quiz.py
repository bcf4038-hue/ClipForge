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
- Mix easy and hard questions; start with an easy one so viewers keep watching.
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
            "properties": {"hook": {"type": "string", "description": "Opening line read aloud, under 10 words, e.g. "
                                                                     "'Only real Roblox fans get all of these!'"},
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


# ---------- the Editor project ----------

ORANGE, TEAL, YELLOW, GREEN, RED = "#FF7A1A", "#19C3B5", "#FFE600", "#22C55E", "#EF4444"


def _text(text, start, end, y, **look):
    t = {**TEXT_DEFAULT, "id": new_id(), "text": text, "start": round(start, 3), "end": round(end, 3),
         "x": 0.5, "y": y}
    t.update(look)
    return t


def _wrap(text, width):
    return "\n".join(textwrap.wrap(text, width)) or text


def build(kind, questions, hook, voice, sfx, music, bg_media, bg_duration, name):
    """Lay the quiz out on a timeline.

    voice: {line key: (sound path, seconds)}; sfx: {"tick", "ding", "whoosh", "pop": sound path or None}.
    """
    p = new_project()
    p["name"] = name
    texts, sounds = p["texts"], p["sounds"]

    def say(key, at):
        path, secs = voice[key]
        sounds.append({"id": new_id(), "sound": path, "start": round(at, 3), "volume": 1.0})
        return secs

    def fx(name_, at, volume=0.7):
        if sfx.get(name_):
            sounds.append({"id": new_id(), "sound": sfx[name_], "start": round(at, 3), "volume": volume})

    count = len(questions)
    # Intro: the hook.
    hook_len = max(2.2, voice["hook"][1] + 0.4)
    fx("pop", 0.0)
    texts.append(_text(_wrap(TYPES[kind]["title"], 16), 0, hook_len, 0.36, size=96, color="#FFFFFF",
                       outline=10, anim="pop"))
    texts.append(_text(f"CAN YOU GET ALL {count}?", 0.4, hook_len, 0.56, size=72, color="#0D1B20", box=True,
                       box_color=YELLOW, box_opacity=1, anim="pop"))
    say("hook", 0.15)
    t = hook_len

    for i, q in enumerate(questions, 1):
        qs = t
        fx("whoosh", qs, 0.6)
        ask = say(f"q{i}", qs + 0.25)
        timer_at = qs + 0.25 + ask + 0.25
        reveal = timer_at + TIMER
        ans = say(f"a{i}", reveal + 0.35)
        end = reveal + 0.35 + ans + 0.6
        end = max(end, reveal + 1.8)

        texts.append(_text(f"{i}/{count}", qs, end, 0.2, size=80, color=ORANGE, outline=8))
        if kind == "emoji":
            texts.append(_text(q["emojis"], qs, end, 0.4, size=210, outline=0, uppercase=False))
            answer = q["answer"]
            texts.append(_text(_wrap(answer, 16), reveal, end, 0.68, size=84, color="#FFFFFF", box=True,
                               box_color=GREEN, box_opacity=1))
        elif kind == "truefalse":
            texts.append(_text(_wrap(q["statement"], 18), qs, end, 0.4, size=78, color="#FFFFFF", outline=7))
            verdict = "TRUE" if q["answer"] else "FALSE"
            texts.append(_text(verdict, reveal, end, 0.66, size=130, color="#FFFFFF", box=True,
                               box_color=GREEN if q["answer"] else RED, box_opacity=1))
            texts.append(_text(_wrap(q["fact"], 24), reveal + 0.3, end, 0.78, size=56, color="#FFFFFF", outline=5,
                               anim="fade", uppercase=False))
        else:
            word = "OLDER" if q["kind"] == "older" else "MORE POPULAR"
            texts.append(_text(f"WHICH IS {word}?", qs, end, 0.3, size=72, color=YELLOW, outline=7))
            for key, y in (("a", 0.4), ("b", 0.54)):
                texts.append(_text(_wrap(q[key], 16), qs, reveal, y, size=88, color="#FFFFFF", box=True,
                                   box_color=TEAL, box_opacity=1))
                win = key == q["answer"]
                texts.append(_text(_wrap(q[key], 16) + (" ✅" if win else ""), reveal, end, y, size=88,
                                   color="#FFFFFF", box=True, box_color=GREEN if win else "#3A4A50",
                                   box_opacity=1 if win else 0.85, anim="none", uppercase=True))
            texts.append(_text("VS", qs, end, 0.47, size=80, color=ORANGE, outline=8))
            texts.append(_text(_wrap(q["fact"], 24), reveal + 0.3, end, 0.66, size=56, color="#FFFFFF",
                               outline=5, anim="fade", uppercase=False))
        # Countdown 3, 2, 1 with a tick each second, then the reveal sound.
        for k in range(TIMER):
            texts.append(_text(str(TIMER - k), timer_at + k, timer_at + k + 1, 0.68 if kind != "truefalse" else 0.66,
                               size=190, color=YELLOW, outline=12))
            fx("tick", timer_at + k, 0.8)
        fx("ding", reveal, 0.8)
        t = end

    outro = max(2.6, voice["outro"][1] + 0.8)
    fx("pop", t)
    texts.append(_text("HOW MANY DID\nYOU GET? 👇", t, t + outro, 0.42, size=96, color="#FFFFFF", outline=10))
    texts.append(_text("COMMENT YOUR SCORE", t + 0.3, t + outro, 0.56, size=60, color="#0D1B20", box=True,
                       box_color=YELLOW, box_opacity=1))
    say("outro", t + 0.2)
    t += outro

    texts.insert(0, _text(TYPES[kind]["header"], hook_len, t, 0.09, size=66, color="#FFFFFF", box=True,
                          box_color=ORANGE, box_opacity=1, anim="none"))
    total = round(min(t, bg_duration), 3)
    p["clips"] = [{"id": new_id(), "media": bg_media, "in": 0, "out": total, "volume": 0, "audio": "mute",
                   "framing": "fill", "media_duration": bg_duration}]
    if music:
        p["music"] = {"sound": music, "volume": 0.12}
    return p
