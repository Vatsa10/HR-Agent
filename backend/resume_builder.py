"""
Resume builder: one LLM call to produce an improved JSON-Resume-shaped dict,
plus a pure-python markdown renderer.
"""

import json
import logging
import re
from typing import Optional

import style_guardrails
from llm_utils import initialize_llm_provider, extract_json_from_response
from prompt import DEFAULT_MODEL, MODEL_PARAMETERS

logger = logging.getLogger(__name__)

BUILD_PROMPT = """You are an expert resume writer. Improve the candidate's resume below and return it as a JSON Resume shaped object.

Rules (follow strictly):
- Rewrite every work/project bullet impact-first: strong action verb + what was done + measurable outcome where the source material supports it.
- Keep facts truthful. NEVER invent employers, job titles, dates, metrics, degrees, or skills not present in the provided material.
- If a JOB DESCRIPTION is provided, front-load the skills and experience matching its must-have requirements (order skills and highlights so JD matches appear first). Do not fabricate matches.
- The CURRENT RESUME is the single source of truth for the main sections (summary, work, projects, education, skills). GITHUB DATA and LINKEDIN DATA are SECONDARY CONTEXT ONLY: use them to enrich or fill gaps the resume omits (a missing bullet, date, metric, project, or skill), never to replace or contradict the resume's own facts, and never as main content on their own.
- If GITHUB DATA is provided, fold its top projects into the "projects" section when they are missing from the resume, using only real repo names/descriptions/languages.
- If LINKEDIN DATA is provided, use it only to supplement the resume: recover a bullet, date, location, or skill that the resume left out but LinkedIn confirms. Do not add whole sections from LinkedIn that the candidate did not put on the resume, and never fabricate.
- If EXTRA SECTIONS are provided, merge each entry as an additional section under a top-level "extras" object: {{"<section name>": <content>}}.
- If a JD MATCH ANALYSIS is provided, use it as a tailoring plan:
  * For every requirement with status "partial" or "missing" and kind "must_have": if the candidate's REAL experience in the source material can truthfully support it, surface that buried evidence prominently (rewrite the relevant bullet, summary, or skills entry to make it explicit). NEVER fabricate experience to cover a requirement the material does not support; leave unsupported gaps alone.
  * Inject the ats_keywords.absent terms into the summary, skills, or bullets wherever they are truthful descriptions of the candidate's actual work. Skip any keyword the material does not honestly support.
  * Reorder skills, projects, and bullet highlights so items backing "met" requirements appear first.
- Alongside the resume, produce "tailoring_notes": a list of short strings, each explaining one concrete change you made and why (e.g. "Moved Kubernetes to top of skills: met must-have requirement"). Keep them factual and specific. Empty list if no JD match analysis was provided.

{style_rules}

LENGTH DIRECTIVE:
{length_directive}

Output shape (JSON object with "resume" holding a JSON Resume style object; keep keys even if arrays are empty):
{{
  "resume": {{
    "basics": {{"name": "", "label": "", "email": "", "phone": "", "url": "", "summary": "", "location": {{}}, "profiles": []}},
    "skills": [{{"name": "", "keywords": []}}],
    "work": [{{"name": "", "position": "", "location": "", "startDate": "", "endDate": "", "highlights": []}}],
    "projects": [{{"name": "", "description": "", "highlights": [], "url": ""}}],
    "education": [{{"institution": "", "area": "", "studyType": "", "startDate": "", "endDate": ""}}],
    "awards": [{{"title": "", "date": "", "awarder": "", "summary": ""}}],
    "extras": {{}}
  }},
  "tailoring_notes": ["<what was changed and why>", ...]
}}

CURRENT RESUME (parsed JSON):
{parsed}

JOB DESCRIPTION:
{jd}

JD MATCH ANALYSIS:
{jd_match}

GITHUB DATA (secondary context):
{github}

LINKEDIN DATA (secondary context):
{linkedin}

EXTRA SECTIONS:
{extras}

Respond ONLY with the valid JSON object."""


LENGTH_DIRECTIVE_ONE = (
    "Target ONE A4 page. Keep ONLY the most impactful content: the top ~3-4 most "
    "recent or JD-relevant roles, terse metric-first bullets (max ~3 per role), a "
    "single compact skills line, and the top ~2-3 projects. Drop older, weaker, or "
    "redundant items entirely. The result must fit on one A4 page: be ruthless about "
    "cutting anything that does not earn its space."
)

LENGTH_DIRECTIVE_TWO = (
    "Target TWO A4 pages. Provide fuller detail: more roles, more bullets per role, "
    "and more projects are allowed, but stay tight and impact-first. Do not pad with "
    "filler; every bullet still leads with impact and a metric where the material supports it."
)


def _fmt_dates(item: dict) -> str:
    start = item.get("startDate") or ""
    end = item.get("endDate") or ("Present" if start else "")
    if start or end:
        return f"{start} - {end}" if start and end else (start or end)
    return ""


def _render_value(value, depth=0) -> list:
    """Render an arbitrary extras value into markdown lines."""
    lines = []
    if isinstance(value, dict):
        for k, v in value.items():
            sub = _render_value(v, depth + 1)
            if len(sub) == 1 and not sub[0].startswith("-"):
                lines.append(f"- **{k}**: {sub[0].lstrip('- ')}")
            else:
                lines.append(f"- **{k}**:")
                lines.extend("  " + s for s in sub)
    elif isinstance(value, list):
        for v in value:
            if isinstance(v, (dict, list)):
                lines.extend(_render_value(v, depth + 1))
            else:
                lines.append(f"- {v}")
    else:
        lines.append(f"- {value}" if depth else str(value))
    return lines


def json_resume_to_markdown(content: dict) -> str:
    """Render a JSON-Resume-shaped dict to markdown. Pure python, no LLM.

    Keys starting with an underscore (e.g. '_tailoring_notes') are internal
    metadata and are never rendered.
    """
    content = {k: v for k, v in content.items() if not str(k).startswith("_")}
    out = []
    basics = content.get("basics") or {}
    name = basics.get("name") or "Resume"
    out.append(f"# {name}")
    if basics.get("label"):
        out.append(f"*{basics['label']}*")
    contact = [
        basics.get(k)
        for k in ("email", "phone", "url")
        if basics.get(k)
    ]
    loc = basics.get("location") or {}
    if isinstance(loc, dict):
        loc_str = ", ".join(str(v) for v in [loc.get("city"), loc.get("region"), loc.get("countryCode")] if v)
        if loc_str:
            contact.append(loc_str)
    for p in basics.get("profiles") or []:
        if isinstance(p, dict) and p.get("url"):
            contact.append(p["url"])
    if contact:
        out.append(" | ".join(str(c) for c in contact))

    if basics.get("summary"):
        out.append("\n## Summary\n")
        out.append(basics["summary"])

    skills = content.get("skills") or []
    if skills:
        out.append("\n## Skills\n")
        for s in skills:
            if isinstance(s, dict):
                kws = ", ".join(s.get("keywords") or [])
                out.append(f"- **{s.get('name', 'Skills')}**: {kws}" if kws else f"- {s.get('name', '')}")
            else:
                out.append(f"- {s}")

    work = content.get("work") or []
    if work:
        out.append("\n## Experience\n")
        for w in work:
            company = w.get("name") or w.get("company") or ""
            if company and w.get("location"):
                company = f"{company}, {w['location']}"
            header = f"### {w.get('position', '')} | {company}".strip(" |")
            out.append(header)
            dates = _fmt_dates(w)
            if dates:
                out.append(f"*{dates}*")
            for h in w.get("highlights") or []:
                out.append(f"- {h}")
            out.append("")

    projects = content.get("projects") or []
    if projects:
        out.append("\n## Projects\n")
        for p in projects:
            title = p.get("name", "")
            if p.get("url"):
                title = f"[{title}]({p['url']})"
            out.append(f"### {title}")
            if p.get("description"):
                out.append(p["description"])
            for h in p.get("highlights") or []:
                out.append(f"- {h}")
            out.append("")

    education = content.get("education") or []
    if education:
        out.append("\n## Education\n")
        for e in education:
            degree = " in ".join(x for x in [e.get("studyType"), e.get("area")] if x)
            line = f"### {e.get('institution', '')}"
            out.append(line)
            if degree:
                out.append(degree)
            dates = _fmt_dates(e)
            if dates:
                out.append(f"*{dates}*")
            out.append("")

    awards = content.get("awards") or []
    if awards:
        out.append("\n## Awards\n")
        for a in awards:
            bits = " - ".join(x for x in [a.get("title"), a.get("awarder"), a.get("date")] if x)
            out.append(f"- **{bits}**" if bits else "")
            if a.get("summary"):
                out.append(f"  {a['summary']}")

    for sec in content.get("custom_sections") or []:
        if isinstance(sec, dict) and (sec.get("title") or sec.get("body")):
            out.append(f"\n## {sec.get('title', 'Section')}\n")
            out.append(str(sec.get("body", "")))

    extras = content.get("extras") or {}
    if isinstance(extras, dict):
        for section, value in extras.items():
            if str(section).startswith("_"):
                continue
            out.append(f"\n## {section}\n")
            out.extend(_render_value(value))

    md = "\n".join(out)
    while "\n\n\n" in md:
        md = md.replace("\n\n\n", "\n\n")
    return md.strip() + "\n"


def _resume_text(content: dict) -> str:
    """Flatten a JSON-Resume dict to the text an ATS parser would read."""
    parts = []
    b = content.get("basics") or {}
    parts.append(b.get("summary") or "")
    for s in content.get("skills") or []:
        if isinstance(s, dict):
            parts.append(s.get("name") or "")
            parts.extend(s.get("keywords") or [])
    for w in content.get("work") or []:
        parts.append(w.get("position") or "")
        parts.extend(w.get("highlights") or [])
    for p in content.get("projects") or []:
        parts.append(p.get("description") or "")
        parts.extend(p.get("highlights") or [])
    return " \n".join(str(x) for x in parts if x)


def ats_coverage(content: dict, jd_match: Optional[dict]) -> dict:
    """Which JD ATS keywords the built resume text actually contains.

    Pure, no LLM: scans the rendered resume text for each keyword the JD match
    flagged (present + absent), word-boundary + case-insensitive. Returns
    {covered: [...], missing: [...]}. Empty when there is no jd_match.
    """
    if not jd_match:
        return {"covered": [], "missing": []}
    ats = jd_match.get("ats_keywords") or {}
    keywords = list(dict.fromkeys((ats.get("present") or []) + (ats.get("absent") or [])))
    text = _resume_text(content).lower()
    covered, missing = [], []
    for kw in keywords:
        k = (kw or "").strip().lower()
        if not k:
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", text):
            covered.append(kw)
        else:
            missing.append(kw)
    return {"covered": covered, "missing": missing}


REVIEW_PROMPT = """You are a skeptical hiring manager reviewing a candidate's tailored resume before it goes out. Find weak, generic, or potentially-fabricated content and propose precise fixes.

TARGET JOB DESCRIPTION:
{jd}

CANDIDATE PROFILE (source of truth — nothing may claim more than this supports):
{profile}

BUILT RESUME (JSON Resume):
{resume}

Return ONLY JSON:
{{
  "edits": [
    {{"old": "<exact substring currently in a bullet/summary>", "new": "<stronger truthful rewrite>", "reason": "<why>"}}
  ],
  "per_bullet": [
    {{"text": "<the bullet text>", "tag": "<safe | stretch | fabrication>", "why": "<one line>"}}
  ]
}}

Rules:
- Every "old" MUST be an exact substring of the built resume so it can be applied mechanically. If you cannot quote it exactly, do not propose that edit.
- "safe" = fully supported by the profile. "stretch" = plausible but thinly supported. "fabrication" = not supported by the profile at all (flag these; never invent support).
- Do not add em-dashes or clichés. Keep edits truthful. Empty arrays if nothing needs changing."""


def _apply_edits(content: dict, edits: list) -> int:
    """Apply reviewer {old,new} edits to the resume's free-text fields in place.

    Deterministic exact-substring replace across summary/highlights/descriptions.
    Returns the number of edits actually applied.
    """
    applied = 0

    def _sub_field(get, setf):
        nonlocal applied
        val = get()
        if not isinstance(val, str):
            return
        for e in edits:
            old, new = e.get("old"), e.get("new")
            if old and new and old in val:
                val = val.replace(old, new)
                applied += 1
        setf(val)

    b = content.get("basics") or {}
    if b.get("summary"):
        _sub_field(lambda: b["summary"], lambda v: b.__setitem__("summary", v))
    for w in content.get("work") or []:
        hs = w.get("highlights") or []
        for i in range(len(hs)):
            _sub_field(lambda i=i, hs=hs: hs[i], lambda v, i=i, hs=hs: hs.__setitem__(i, v))
    for p in content.get("projects") or []:
        hs = p.get("highlights") or []
        for i in range(len(hs)):
            _sub_field(lambda i=i, hs=hs: hs[i], lambda v, i=i, hs=hs: hs.__setitem__(i, v))
        if p.get("description"):
            _sub_field(lambda p=p: p["description"], lambda v, p=p: p.__setitem__("description", v))
    return applied


def review_resume(content: dict, jd_text: str, profile_text: str) -> dict:
    """Second LLM pass: critique the built resume, apply truthful edits.

    Returns {"critique": {edits, per_bullet, applied}, "content": <edited>}.
    Never fabricates: edits only replace existing substrings. On any failure the
    content is returned unchanged with an empty critique.
    """
    empty = {"critique": {"edits": [], "per_bullet": [], "applied": 0}, "content": content}
    if not jd_text:
        return empty
    provider = initialize_llm_provider(DEFAULT_MODEL)
    params = MODEL_PARAMETERS.get(DEFAULT_MODEL, {"temperature": 0.1, "top_p": 0.9})
    try:
        resp = provider.chat(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "You are a skeptical hiring manager. Respond only with JSON."},
                {"role": "user", "content": REVIEW_PROMPT.format(
                    jd=(jd_text or "")[:8000],
                    profile=(profile_text or "")[:8000],
                    resume=json.dumps(content, default=str)[:12000],
                )},
            ],
            options={"stream": False, **params},
            format="json",
        )
        data = json.loads(extract_json_from_response(resp["message"]["content"]))
    except Exception:
        logger.exception("review_resume failed; returning unedited resume")
        return empty
    edits = data.get("edits") if isinstance(data, dict) else None
    per_bullet = data.get("per_bullet") if isinstance(data, dict) else None
    edits = edits if isinstance(edits, list) else []
    applied = _apply_edits(content, edits)
    return {
        "critique": {
            "edits": edits,
            "per_bullet": per_bullet if isinstance(per_bullet, list) else [],
            "applied": applied,
        },
        "content": content,
    }


def build_resume(
    parsed: dict,
    jd_text: Optional[str] = None,
    github_data: Optional[dict] = None,
    extras: Optional[dict] = None,
    jd_match: Optional[dict] = None,
    linkedin_text: Optional[str] = None,
    page_count: int = 1,
) -> dict:
    """Improve a parsed resume via one LLM call.

    jd_match, when provided, is a stored JD match analysis dict (fit_score,
    requirements, ats_keywords, ...) used as a tailoring plan.

    Returns {'content': <JSON Resume dict>, 'markdown': <str>,
    'tailoring_notes': <list[str]>}.
    """
    page_count = 2 if int(page_count or 1) == 2 else 1
    provider = initialize_llm_provider(DEFAULT_MODEL)
    params = MODEL_PARAMETERS.get(DEFAULT_MODEL, {"temperature": 0.1, "top_p": 0.9})
    prompt = BUILD_PROMPT.format(
        parsed=json.dumps(parsed, indent=2, default=str),
        jd=jd_text or "(none provided)",
        jd_match=json.dumps(jd_match, indent=2, default=str) if jd_match else "(none provided)",
        github=json.dumps(github_data, indent=2, default=str) if github_data else "(none provided)",
        linkedin=linkedin_text or "(none provided)",
        extras=json.dumps(extras, indent=2, default=str) if extras else "(none provided)",
        style_rules=style_guardrails.STYLE_RULES,
        length_directive=LENGTH_DIRECTIVE_ONE if page_count == 1 else LENGTH_DIRECTIVE_TWO,
    )
    content = None
    tailoring_notes: list = []
    try:
        response = provider.chat(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "You are an expert resume writer who never fabricates facts."},
                {"role": "user", "content": prompt},
            ],
            options={"stream": False, **params},
            format="json",
        )
        raw = extract_json_from_response(response["message"]["content"])
        candidate = json.loads(raw)
        if isinstance(candidate, dict):
            # New shape: {"resume": {...}, "tailoring_notes": [...]}
            if isinstance(candidate.get("resume"), dict) and candidate["resume"].get("basics") is not None:
                content = candidate["resume"]
                notes = candidate.get("tailoring_notes")
                if isinstance(notes, list):
                    tailoring_notes = [str(n) for n in notes]
            # Legacy flat shape
            elif candidate.get("basics") is not None:
                content = candidate
        if content is None:
            logger.warning("LLM output missing 'basics'; falling back to parsed resume")
    except Exception:
        logger.exception("build_resume LLM call/parse failed; falling back to parsed resume")

    if content is None:
        content = dict(parsed)
        if extras:
            content.setdefault("extras", {}).update(extras)

    # Drafter -> reviewer: a second skeptical pass proposes truthful edits and
    # tags each bullet safe/stretch/fabrication. Only runs with a JD to review
    # against. Edits are applied deterministically (exact-substring).
    critique = {"edits": [], "per_bullet": [], "applied": 0}
    if jd_text:
        try:
            profile_text = json.dumps(parsed, default=str)
            reviewed = review_resume(content, jd_text, profile_text)
            content = reviewed["content"]
            critique = reviewed["critique"]
        except Exception:
            logger.exception("reviewer pass failed; keeping drafter output")

    # Style linter: strip em-dashes / clichés the model left in.
    content, style_removed = style_guardrails.lint_resume(content)

    content["_page_count"] = page_count

    return {
        "content": content,
        "markdown": json_resume_to_markdown(content),
        "tailoring_notes": tailoring_notes,
        "critique": critique,
        "ats_coverage": ats_coverage(content, jd_match),
        "style_removed": style_removed,
    }


if __name__ == "__main__":
    sample = {
        "basics": {
            "name": "Jane Doe",
            "label": "Backend Engineer",
            "email": "jane@example.com",
            "phone": "555-0101",
            "url": "https://jane.dev",
            "summary": "Backend engineer with 5 years building APIs.",
            "location": {"city": "Austin", "region": "TX"},
            "profiles": [{"network": "GitHub", "url": "https://github.com/janedoe"}],
        },
        "skills": [{"name": "Languages", "keywords": ["Python", "Go"]}],
        "work": [
            {
                "name": "Acme Corp",
                "position": "Senior Engineer",
                "location": "Remote",
                "startDate": "2021-03",
                "endDate": "",
                "highlights": ["Cut API latency 40% by adding caching"],
            }
        ],
        "projects": [
            {"name": "hr-agent", "description": "Resume analyzer", "url": "https://github.com/janedoe/hr-agent", "highlights": ["Built LangGraph pipeline"]}
        ],
        "education": [
            {"institution": "UT Austin", "studyType": "BS", "area": "Computer Science", "startDate": "2014", "endDate": "2018"}
        ],
        "awards": [{"title": "Hackathon Winner", "date": "2020", "awarder": "PyCon", "summary": "First place"}],
        "extras": {"Certifications": ["AWS SAA"], "Languages Spoken": ["English", "Hindi"], "_hidden": ["nope"]},
        "_tailoring_notes": ["Moved Python first: met must-have"],
    }
    md = json_resume_to_markdown(sample)
    assert md.startswith("# Jane Doe")
    assert "*Backend Engineer*" in md
    assert "jane@example.com | 555-0101 | https://jane.dev" in md
    assert "Austin, TX" in md
    assert "## Summary" in md and "5 years building APIs" in md
    assert "- **Languages**: Python, Go" in md
    assert "### Senior Engineer | Acme Corp, Remote" in md
    assert "*2021-03 - Present*" in md
    assert "- Cut API latency 40% by adding caching" in md
    assert "[hr-agent](https://github.com/janedoe/hr-agent)" in md
    assert "### UT Austin" in md and "BS in Computer Science" in md
    assert "*2014 - 2018*" in md
    assert "- **Hackathon Winner - PyCon - 2020**" in md
    assert "## Certifications" in md and "- AWS SAA" in md
    assert "## Languages Spoken" in md and "- Hindi" in md
    assert "_tailoring_notes" not in md and "Moved Python first" not in md
    assert "_hidden" not in md and "nope" not in md
    assert "\n\n\n" not in md
    # empty-ish resume should not crash
    md2 = json_resume_to_markdown({})
    assert md2.startswith("# Resume")

    # length directive: 1-page vs 2-page prompt text differs
    def _prompt(pc):
        return BUILD_PROMPT.format(
            parsed="{}", jd="(none)", jd_match="(none)", github="(none)",
            linkedin="(none)", extras="(none)", style_rules=style_guardrails.STYLE_RULES,
            length_directive=LENGTH_DIRECTIVE_ONE if pc == 1 else LENGTH_DIRECTIVE_TWO,
        )
    p1, p2 = _prompt(1), _prompt(2)
    assert p1 != p2
    assert "ONE A4 page" in p1 and "ONE A4 page" not in p2
    assert "TWO A4 pages" in p2
    assert "No em-dashes" in p1  # style rules injected

    # ats_coverage (pure): covered vs missing against jd_match keywords
    cov = ats_coverage(
        sample,
        {"ats_keywords": {"present": ["Python"], "absent": ["Kubernetes", "Go"]}},
    )
    assert "Python" in cov["covered"] and "Go" in cov["covered"], cov
    assert "Kubernetes" in cov["missing"], cov

    # _apply_edits (pure): exact-substring replace across fields
    c2 = {"basics": {"summary": "Built APIs."},
          "work": [{"highlights": ["Cut latency"]}]}
    n = _apply_edits(c2, [{"old": "Cut latency", "new": "Cut p99 latency 40%"},
                          {"old": "nope", "new": "x"}])
    assert n == 1 and c2["work"][0]["highlights"][0] == "Cut p99 latency 40%", c2

    # _page_count is set in content and ignored by the markdown renderer
    built_content = dict(sample)
    built_content["_page_count"] = 1
    md3 = json_resume_to_markdown(built_content)
    assert md3.startswith("# Jane Doe")
    assert "_page_count" not in md3 and "page_count" not in md3
    print("resume_builder self-check OK")
