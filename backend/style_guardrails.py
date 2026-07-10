"""
Shared writing-style guardrails for every place the app drafts prose (resume
bullets, cover letters, cold messages). One rules string goes into the prompts;
one cheap regex linter strips the tells the model leaves anyway.
"""

import re

# Injected into drafting prompts. Keep short — it rides on every call.
STYLE_RULES = """Writing style (follow strictly):
- No em-dashes (—). Use a period or comma.
- Active voice, past tense for past work. Lead with the action and the result.
- Show, don't tell: state what was done and the outcome, not adjectives about it.
- Ban these clichés and filler: "results-driven", "detail-oriented", "team player",
  "go-getter", "think outside the box", "synergy", "leverage" (as a verb),
  "passionate about", "dynamic", "seamless", "cutting-edge", "world-class",
  "spearheaded", "wheelhouse", "hit the ground running", "move the needle".
- No hedging ("responsible for", "helped with", "worked on") — name the concrete
  contribution instead."""

# Cliché phrases the linter deletes (case-insensitive, whole-phrase).
_CLICHES = [
    "results-driven", "results driven", "detail-oriented", "detail oriented",
    "team player", "go-getter", "think outside the box", "synergy",
    "passionate about", "world-class", "cutting-edge", "seamless",
    "hit the ground running", "move the needle", "wheelhouse",
]
_CLICHE_RE = re.compile("|".join(re.escape(c) for c in _CLICHES), re.IGNORECASE)
_WS_RE = re.compile(r"[ \t]{2,}")


def lint(text: str):
    """Strip em-dashes and clichés. Returns (cleaned_text, removed_count).

    Em-dash -> ' - '. Clichés -> removed. Not destructive to meaning; just kills
    the tells. Idempotent.
    """
    if not text:
        return text, 0
    removed = 0
    cleaned = text.replace("—", " - ").replace("--", " - ")

    def _sub(m):
        nonlocal removed
        removed += 1
        return ""

    cleaned = _CLICHE_RE.sub(_sub, cleaned)
    # tidy the double spaces / stray punctuation the deletions leave behind
    cleaned = _WS_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned, removed


def lint_resume(content: dict):
    """Lint every free-text field of a JSON-Resume dict in place-ish.

    Returns (new_content, total_removed). Only touches summary + highlights +
    descriptions — the prose fields. Structured fields (names, dates) untouched.
    """
    import copy
    c = copy.deepcopy(content or {})
    total = 0

    def _fix(s):
        nonlocal total
        out, n = lint(s)
        total += n
        return out

    basics = c.get("basics") or {}
    if basics.get("summary"):
        basics["summary"] = _fix(basics["summary"])
    for w in c.get("work") or []:
        w["highlights"] = [_fix(h) for h in (w.get("highlights") or [])]
    for p in c.get("projects") or []:
        if p.get("description"):
            p["description"] = _fix(p["description"])
        p["highlights"] = [_fix(h) for h in (p.get("highlights") or [])]
    return c, total


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8")

    out, n = lint("A results-driven engineer—passionate about seamless synergy.")
    assert "—" not in out, out
    assert "results-driven" not in out.lower()
    assert "passionate about" not in out.lower()
    assert n >= 3, (out, n)
    # idempotent
    out2, n2 = lint(out)
    assert n2 == 0, (out2, n2)
    # clean text untouched
    assert lint("Cut API latency 40% by adding a cache.") == ("Cut API latency 40% by adding a cache.", 0)

    content = {
        "basics": {"summary": "Detail-oriented dev—builds things."},
        "work": [{"highlights": ["Spearheaded nothing", "Cut costs 30%"]}],
    }
    fixed, total = lint_resume(content)
    assert "—" not in fixed["basics"]["summary"]
    assert "detail-oriented" not in fixed["basics"]["summary"].lower()
    assert total >= 1
    print("style_guardrails self-check OK")
