"""
LinkedIn optimizer: one gpt-4o-mini call that audits a LinkedIn profile from a
recruiter/hiring lens, grounded in the person's parsed resume and their latest
(GitHub-informed) analysis. Returns section-by-section, ready-to-paste
improvements plus a prioritized checklist.

Everything is best-effort: the audit still runs if the resume or analysis is
absent, and always returns a valid dict (defensive normalization) even when the
LLM output is malformed.
"""

import json
import logging

from llm_utils import initialize_llm_provider, extract_json_from_response
from prompt import DEFAULT_MODEL, MODEL_PARAMETERS

logger = logging.getLogger(__name__)

SECTION_KEYS = {
    "headline",
    "about",
    "experience",
    "skills",
    "featured_projects",
    "keywords",
    "completeness",
}
VERDICTS = {"good", "improve", "missing"}
PRIORITIES = {"high", "medium", "low"}

AUDIT_PROMPT = """You are a senior technical recruiter and LinkedIn strategist. Audit the candidate's LinkedIn profile the way a recruiter sourcing for roles would read it, and return concrete, ready-to-paste improvements.

RECRUITER LENS (follow strictly):
- Compare the LINKEDIN PROFILE against what the RESUME and the EVALUATION actually prove. Your job is to make the profile reflect the strongest TRUTHFUL version of this person.
- Surface strong, provable material the profile is hiding: metrics, shipped/production impact, notable projects, open-source work, and skills that appear in the resume or evaluation but are absent or buried on the profile.
- Fix a weak, generic, or empty HEADLINE and ABOUT with concrete rewrites the person can paste directly. Lead with role + specialization + proof (real numbers/tech from the source material).
- Recommend the keywords recruiters actually search for that this person TRUTHFULLY matches (languages, frameworks, domains, seniority terms), so the profile surfaces in searches.
- Flag missing skills the resume proves but the profile omits.
- Suggest Featured items / Projects drawn from real resume or GitHub/open-source projects.
- NEVER invent experience, employers, titles, metrics, or skills. Every suggested rewrite must be truthful to the RESUME / EVALUATION / PROFILE. If the source material is thin, say so and keep suggestions modest rather than fabricating.
- readiness_score is the recruiter-readiness of the profile as it stands now (0-100): does it clearly present a hireable, searchable, proof-backed candidate?

LINKEDIN PROFILE (scraped or PDF export):
{profile_text}

CANDIDATE RESUME (parsed JSON, source of truth; may be empty):
{resume}

LATEST EVALUATION (GitHub-informed analysis of the candidate; may be empty):
{analysis}

Respond ONLY with valid JSON in exactly this shape (keep all keys, use empty strings/arrays when nothing applies):
{{
  "readiness_score": <integer 0-100>,
  "summary": "<2-3 sentence recruiter take on the profile>",
  "sections": [
    {{
      "key": "<headline|about|experience|skills|featured_projects|keywords|completeness>",
      "title": "<human title, e.g. Headline>",
      "verdict": "<good|improve|missing>",
      "current": "<short quote/paraphrase of what's there now; empty string if missing>",
      "suggested": "<ready-to-paste rewrite or recommendation the user can copy>",
      "priority": "<high|medium|low>",
      "why": "<why a recruiter cares / what gap this closes>"
    }}
  ],
  "checklist": [
    {{"text": "<one concrete change to make>", "priority": "<high|medium|low>"}}
  ]
}}"""


def _clamp_score(value) -> int:
    """Coerce anything to an int in [0, 100]."""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, n))


def _str(value) -> str:
    if value is None:
        return ""
    return str(value)


def _one_of(value, allowed, default) -> str:
    v = _str(value).strip().lower()
    return v if v in allowed else default


def _normalize(raw) -> dict:
    """Turn a raw (possibly malformed) LLM dict into the exact audit shape.

    Always returns a valid dict: clamped readiness_score, coerced/defaulted
    fields, and lists of well-formed section/checklist items. Garbage or empty
    input yields a minimal valid dict (score 0, empty lists).
    """
    if not isinstance(raw, dict):
        raw = {}

    sections = []
    for item in raw.get("sections") or []:
        if not isinstance(item, dict):
            continue
        sections.append(
            {
                "key": _one_of(item.get("key"), SECTION_KEYS, "completeness"),
                "title": _str(item.get("title")).strip(),
                "verdict": _one_of(item.get("verdict"), VERDICTS, "improve"),
                "current": _str(item.get("current")),
                "suggested": _str(item.get("suggested")),
                "priority": _one_of(item.get("priority"), PRIORITIES, "medium"),
                "why": _str(item.get("why")),
            }
        )

    checklist = []
    for item in raw.get("checklist") or []:
        if isinstance(item, dict):
            text = _str(item.get("text")).strip()
            priority = _one_of(item.get("priority"), PRIORITIES, "medium")
        else:
            text = _str(item).strip()
            priority = "medium"
        if text:
            checklist.append({"text": text, "priority": priority})

    return {
        "readiness_score": _clamp_score(raw.get("readiness_score")),
        "summary": _str(raw.get("summary")).strip(),
        "sections": sections,
        "checklist": checklist,
    }


def _minimal() -> dict:
    """A valid, empty audit used when there is nothing usable to return."""
    return {"readiness_score": 0, "summary": "", "sections": [], "checklist": []}


def audit(profile_text, resume_dict, analysis_result) -> dict:
    """Audit a LinkedIn profile from a recruiter lens in one LLM call.

    - profile_text: scraped/PDF LinkedIn text (required for a useful audit).
    - resume_dict: the candidate's parsed resume dict (may be None/empty).
    - analysis_result: the latest analysis result dict (may be None); its
      evaluation reflects the GitHub enrichment run at Analyze time.

    Always returns a valid dict of the documented shape.
    """
    profile_text = _str(profile_text).strip()
    if not profile_text:
        return _minimal()

    resume_dict = resume_dict if isinstance(resume_dict, dict) else {}
    # Prefer the evaluation slice of the analysis if present; else the whole dict.
    analysis_payload = None
    if isinstance(analysis_result, dict):
        analysis_payload = analysis_result.get("evaluation") or analysis_result

    prompt = AUDIT_PROMPT.format(
        profile_text=profile_text[:16000],
        resume=json.dumps(resume_dict, indent=2, default=str) if resume_dict else "(none provided)",
        analysis=json.dumps(analysis_payload, indent=2, default=str) if analysis_payload else "(none provided)",
    )

    try:
        provider = initialize_llm_provider(DEFAULT_MODEL)
        params = MODEL_PARAMETERS.get(DEFAULT_MODEL, {"temperature": 0.1, "top_p": 0.9})
        response = provider.chat(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "You are a precise technical recruiter who never fabricates facts."},
                {"role": "user", "content": prompt},
            ],
            options={"stream": False, **params},
            format="json",
        )
        raw = json.loads(extract_json_from_response(response["message"]["content"]))
        return _normalize(raw)
    except Exception:
        logger.exception("linkedin audit LLM call/parse failed")
        return _minimal()


if __name__ == "__main__":
    # a) prompt formats without KeyError and carries the recruiter lens.
    p = AUDIT_PROMPT.format(
        profile_text="Headline: Software Engineer\nAbout: I like code.",
        resume="(none provided)",
        analysis="(none provided)",
    )
    assert "RECRUITER LENS" in p
    assert "NEVER invent" in p
    assert "ready-to-paste" in p
    assert "Software Engineer" in p

    # b) a stubbed raw dict normalizes to the exact shape, clamped + defaulted.
    stub = {
        "readiness_score": 175,
        "summary": "  Strong engineer, thin profile.  ",
        "sections": [
            {
                "key": "headline",
                "title": "Headline",
                "verdict": "improve",
                "current": "Software Engineer",
                "suggested": "Backend Engineer | Python, Go | cut API latency 40%",
                "priority": "high",
                "why": "A recruiter scans the headline first.",
            },
            {"key": "bogus_key", "verdict": "nonsense", "priority": "urgent"},  # coerced
            "not-a-dict",  # skipped
        ],
        "checklist": [
            {"text": "Rewrite the headline", "priority": "high"},
            "Add a Featured project",  # bare string -> defaulted priority
            {"text": "   ", "priority": "low"},  # empty text -> dropped
        ],
    }
    norm = _normalize(stub)
    assert norm["readiness_score"] == 100  # clamped from 175
    assert norm["summary"] == "Strong engineer, thin profile."
    assert set(norm.keys()) == {"readiness_score", "summary", "sections", "checklist"}
    assert len(norm["sections"]) == 2  # non-dict dropped
    assert norm["sections"][0]["key"] == "headline"
    s2 = norm["sections"][1]
    assert s2["key"] == "completeness"  # bogus key defaulted
    assert s2["verdict"] == "improve"  # bad verdict defaulted
    assert s2["priority"] == "medium"  # bad priority defaulted
    assert s2["title"] == "" and s2["current"] == "" and s2["suggested"] == ""
    assert len(norm["checklist"]) == 2  # empty-text item dropped
    assert norm["checklist"][1] == {"text": "Add a Featured project", "priority": "medium"}
    for item in norm["sections"]:
        assert set(item.keys()) == {"key", "title", "verdict", "current", "suggested", "priority", "why"}
    for item in norm["checklist"]:
        assert set(item.keys()) == {"text", "priority"}

    # negative and non-numeric scores clamp safely.
    assert _normalize({"readiness_score": -20})["readiness_score"] == 0
    assert _normalize({"readiness_score": "abc"})["readiness_score"] == 0
    assert _normalize({"readiness_score": "88"})["readiness_score"] == 88

    # c) empty / garbage raw -> minimal valid dict.
    for bad in (None, {}, [], "garbage", 42):
        m = _normalize(bad)
        assert m == {"readiness_score": 0, "summary": "", "sections": [], "checklist": []}

    # audit with empty profile short-circuits to a minimal valid dict (no LLM call).
    assert audit("", {"basics": {"name": "x"}}, None) == _minimal()
    assert audit(None, None, None) == _minimal()

    print("linkedin_optimizer self-check OK")
