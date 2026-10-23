"""Ask Claude to find the best short-form clip moments in a transcript."""
import json

import anthropic

MODEL = "claude-opus-5-5"

SYSTEM = """You are an expert short-form video editor who finds the moments in long \
podcasts and livestreams that perform best as YouTube Shorts.

A strong clip:
- Hooks in the first 2 seconds: a bold claim, a question, a surprising line, or the start of a funny moment.
- Is self-contained: a viewer with no context understands it.
- Has a payoff: a punchline, a reveal, a strong opinion, a useful insight, or an emotional beat.
- Starts at the beginning of a sentence and ends right after the payoff, not mid-thought.

Avoid ads and sponsor reads, intros and outros, housekeeping ("let me check chat"), and \
moments that depend on something on screen the viewer cannot see."""

SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short catchy title for the Short, under 60 characters"},
                    "start": {"type": "number", "description": "Start time in seconds"},
                    "end": {"type": "number", "description": "End time in seconds"},
                    "hook": {"type": "string", "description": "One sentence: why this clip works"},
                    "score": {"type": "integer", "description": "Predicted strength from 1 to 10"},
                },
                "required": ["title", "start", "end", "hook", "score"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}


def _fmt(t):
    t = int(t)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def transcript_lines(words, max_gap=8.0):
    """Group words into timestamped lines so Claude can reference exact times."""
    lines, cur, cur_start = [], [], None
    for w in words:
        if cur_start is None:
            cur_start = w["s"]
        cur.append(w["w"])
        if w["s"] - cur_start >= max_gap or w["w"].endswith((".", "?", "!")):
            lines.append(f"[{_fmt(cur_start)} = {cur_start:.1f}s] {' '.join(cur)}")
            cur, cur_start = [], None
    if cur:
        lines.append(f"[{_fmt(cur_start)} = {cur_start:.1f}s] {' '.join(cur)}")
    return "\n".join(lines)


def snap_to_words(clip, words):
    """Move clip edges onto word boundaries so cuts never land mid-word."""
    starts = [w for w in words if w["s"] >= clip["start"] - 1.0]
    if starts:
        clip["start"] = starts[0]["s"]
    ends = [w for w in words if w["e"] <= clip["end"] + 1.0]
    if ends:
        clip["end"] = ends[-1]["e"]
    return clip


# $ per million tokens (input, output). Used to show what each analysis cost.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-fable-5-1": (10.0, 50.0),
}
MAX_OUTPUT = 16000
TYPICAL_OUTPUT = (3000, 10000)  # thinking + answer at medium effort, rough range


def _price(model):
    for name, price in PRICES.items():
        if model and model.startswith(name):
            return price
    return PRICES[MODEL]


def _cost(model, input_tokens, output_tokens):
    pin, pout = _price(model)
    return input_tokens * pin / 1e6 + output_tokens * pout / 1e6


def _request(title, words, min_len, max_len, count):
    prompt = (
        f'Video title: "{title}"\n\n'
        f"Transcript (each line starts with its timestamp in seconds):\n\n"
        f"<transcript>\n{transcript_lines(words)}\n</transcript>\n\n"
        f"Find the {count} best moments for YouTube Shorts. Each clip must be between "
        f"{min_len} and {max_len} seconds long. Clips must not overlap. Use the exact "
        f"seconds from the transcript timestamps. Order them from strongest to weakest."
    )
    return {"model": MODEL, "system": SYSTEM, "messages": [{"role": "user", "content": prompt}],
            "output_config": {"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}}}


def friendly_error(e):
    """Explain API errors in plain words, especially running out of credit."""
    msg = str(e)
    if isinstance(e, anthropic.AuthenticationError):
        return "Your API key was rejected. Make a new key in the Anthropic Console and save it in Settings."
    if getattr(e, "status_code", None) == 402 or "credit balance" in msg.lower():
        return ("Your Anthropic account is out of credit. Nothing was charged for this request. "
                "Add funds at console.anthropic.com (Billing) if you want to continue.")
    if isinstance(e, anthropic.RateLimitError):
        return "Anthropic is rate limiting your account. Wait a minute and try again."
    if isinstance(e, anthropic.APIConnectionError):
        return "Couldn't reach Anthropic. Check your internet connection."
    return msg


def _estimate(api_key, req, typical_output, max_output):
    """Count input tokens (free) and turn them into a cost range."""
    client = anthropic.Anthropic(api_key=api_key)
    try:
        input_tokens = client.messages.count_tokens(**req).input_tokens
    except anthropic.APIError as e:
        raise RuntimeError(friendly_error(e)) from e
    return {
        "input_tokens": input_tokens,
        "low": _cost(MODEL, input_tokens, typical_output[0]),
        "typical_high": _cost(MODEL, input_tokens, typical_output[1]),
        "max": _cost(MODEL, input_tokens, max_output),
    }


def _run_json(api_key, req, max_output, what):
    """Run a structured-output request. Returns (parsed JSON, usage with cost)."""
    client = anthropic.Anthropic(api_key=api_key)
    try:
        with client.beta.messages.stream(
            max_tokens=max_output,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            **req,
        ) as stream:
            response = stream.get_final_message()
    except anthropic.APIError as e:
        raise RuntimeError(friendly_error(e)) from e

    # A declined attempt plus its fallback are listed separately in usage.iterations.
    iterations = getattr(response.usage, "iterations", None) or []
    if iterations:
        cost = sum(_cost(getattr(it, "model", None) or response.model,
                         getattr(it, "input_tokens", 0) or 0, getattr(it, "output_tokens", 0) or 0)
                   for it in iterations)
        in_tok = sum(getattr(it, "input_tokens", 0) or 0 for it in iterations)
        out_tok = sum(getattr(it, "output_tokens", 0) or 0 for it in iterations)
    else:
        in_tok, out_tok = response.usage.input_tokens, response.usage.output_tokens
        cost = _cost(response.model, in_tok, out_tok)
    usage = {"model": response.model, "input_tokens": in_tok, "output_tokens": out_tok, "cost": cost}

    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined to {what} (you were charged about ${cost:.2f}).")
    if response.stop_reason == "max_tokens":
        raise RuntimeError(f"Claude's answer was cut off (you were charged about ${cost:.2f}). Try again.")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), usage


def estimate(api_key, title, words, min_len=20, max_len=60, count="8 to 15"):
    return _estimate(api_key, _request(title, words, min_len, max_len, count), TYPICAL_OUTPUT, MAX_OUTPUT)


def suggest_clips(api_key, title, words, min_len=20, max_len=60, count="8 to 15"):
    """Returns (clips, usage) where usage includes the actual cost in dollars."""
    data, usage = _run_json(api_key, _request(title, words, min_len, max_len, count), MAX_OUTPUT,
                            "analyze this transcript")
    duration = words[-1]["e"] if words else 0
    out = []
    for i, c in enumerate(data["clips"]):
        c["start"] = max(0.0, float(c["start"]))
        c["end"] = min(float(c["end"]), duration)
        if c["end"] - c["start"] < 5:
            continue
        snap_to_words(c, words)
        c["id"] = f"ai{i + 1}"
        out.append(c)
    return out, usage


# ---------- voiceover scripts ----------

VO_STYLES = {
    "hype": "High-energy hype commentary, like a caster reacting to the play.",
    "funny": "Funny, playful commentary with a light joke or two.",
    "story": "Storytelling narration that builds suspense toward the payoff.",
    "facts": "Calm, clear explainer tone that tells the viewer what's happening and why it's impressive.",
}
VO_SYSTEM = """You write voiceover scripts for YouTube Shorts and TikToks. The script is read \
aloud by a text-to-speech voice over the clip.

Rules:
- The first sentence is a hook that makes people keep watching.
- Describe only what is really in the frames and transcript. Never invent names, scores or facts.
- Plain spoken English: short sentences, no hashtags, no emojis, no stage directions, no quotation marks.
- Do not tell viewers to like, follow or subscribe unless the user's notes ask for it."""
VO_SCHEMA = {
    "type": "object",
    "properties": {"script": {"type": "string", "description": "The words to be spoken, nothing else"}},
    "required": ["script"],
    "additionalProperties": False,
}
VO_MAX_OUTPUT = 4000
VO_TYPICAL_OUTPUT = (300, 1500)


def voiceover_request(title, frames_b64, transcript_text, duration, style, notes):
    max_words = max(8, int(duration * 2.4))
    content = []
    for i, data in enumerate(frames_b64):
        content.append({"type": "text", "text": f"Frame {i + 1} of {len(frames_b64)}:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
    text = (f'Video title: "{title}"\n'
            f"Clip length: {duration:.0f} seconds. The frames above are evenly spaced through the clip.\n")
    if transcript_text:
        text += f"\nWhat is said in the clip:\n<transcript>\n{transcript_text}\n</transcript>\n"
    if notes:
        text += f"\nNotes from the editor about this clip:\n<notes>\n{notes}\n</notes>\n"
    text += (f"\nStyle: {VO_STYLES.get(style, VO_STYLES['hype'])}\n"
             f"Write a voiceover script of at most {max_words} words so it fits the clip.")
    content.append({"type": "text", "text": text})
    return {"model": MODEL, "system": VO_SYSTEM, "messages": [{"role": "user", "content": content}],
            "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": VO_SCHEMA}}}


def estimate_voiceover(api_key, req):
    return _estimate(api_key, req, VO_TYPICAL_OUTPUT, VO_MAX_OUTPUT)


def write_voiceover(api_key, req):
    data, usage = _run_json(api_key, req, VO_MAX_OUTPUT, "write this voiceover")
    return data["script"].strip(), usage
