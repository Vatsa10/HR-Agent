"""
Resume builder: one LLM call to produce an improved JSON-Resume-shaped dict,
plus a pure-python markdown renderer.
"""

import json
import logging
from typing import Optional

from llm_utils import initialize_llm_provider, extract_json_from_response
from prompt import DEFAULT_MODEL, MODEL_PARAMETERS

logger = logging.getLogger(__name__)

BUILD_PROMPT = """You are an expert resume writer. Improve the candidate's resume below and return it as a JSON Resume shaped object.

Rules (follow strictly):
- Rewrite every work/project bullet impact-first: strong action verb + what was done + measurable outcome where the source material supports it.
- Keep facts truthful. NEVER invent employers, job titles, dates, metrics, degrees, or skills not present in the provided material.
- If a JOB DESCRIPTION is provided, front-load the skills and experience matching its must-have requirements (order skills and highlights so JD matches appear first). Do not fabricate matches.
- If GITHUB DATA is provided, fold its top projects into the "projects" section when they are missing from the resume, using only real repo names/descriptions/languages.
- If EXTRA SECTIONS are provided, merge each entry as an additional section under a top-level "extras" object: {{"<section name>": <content>}}.

Output shape (JSON Resume style, keep keys even if arrays are empty):
{{
  "basics": {{"name": "", "label": "", "email": "", "phone": "", "url": "", "summary": "", "location": {{}}, "profiles": []}},
  "skills": [{{"name": "", "keywords": []}}],
  "work": [{{"name": "", "position": "", "startDate": "", "endDate": "", "highlights": []}}],
  "projects": [{{"name": "", "description": "", "highlights": [], "url": ""}}],
  "education": [{{"institution": "", "area": "", "studyType": "", "startDate": "", "endDate": ""}}],
  "awards": [{{"title": "", "date": "", "awarder": "", "summary": ""}}],
  "extras": {{}}
}}

CURRENT RESUME (parsed JSON):
{parsed}

JOB DESCRIPTION:
{jd}

GITHUB DATA:
{github}

EXTRA SECTIONS:
{extras}

Respond ONLY with the valid JSON object."""


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
    """Render a JSON-Resume-shaped dict to markdown. Pure python, no LLM."""
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
            out.append(f"\n## {section}\n")
            out.extend(_render_value(value))

    md = "\n".join(out)
    while "\n\n\n" in md:
        md = md.replace("\n\n\n", "\n\n")
    return md.strip() + "\n"


def build_resume(
    parsed: dict,
    jd_text: Optional[str] = None,
    github_data: Optional[dict] = None,
    extras: Optional[dict] = None,
) -> dict:
    """Improve a parsed resume via one LLM call; return {'content', 'markdown'}."""
    provider = initialize_llm_provider(DEFAULT_MODEL)
    params = MODEL_PARAMETERS.get(DEFAULT_MODEL, {"temperature": 0.1, "top_p": 0.9})
    prompt = BUILD_PROMPT.format(
        parsed=json.dumps(parsed, indent=2, default=str),
        jd=jd_text or "(none provided)",
        github=json.dumps(github_data, indent=2, default=str) if github_data else "(none provided)",
        extras=json.dumps(extras, indent=2, default=str) if extras else "(none provided)",
    )
    content = None
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
        if isinstance(candidate, dict) and candidate.get("basics") is not None:
            content = candidate
        else:
            logger.warning("LLM output missing 'basics'; falling back to parsed resume")
    except Exception:
        logger.exception("build_resume LLM call/parse failed; falling back to parsed resume")

    if content is None:
        content = dict(parsed)
        if extras:
            content.setdefault("extras", {}).update(extras)

    return {"content": content, "markdown": json_resume_to_markdown(content)}


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
        "extras": {"Certifications": ["AWS SAA"], "Languages Spoken": ["English", "Hindi"]},
    }
    md = json_resume_to_markdown(sample)
    assert md.startswith("# Jane Doe")
    assert "*Backend Engineer*" in md
    assert "jane@example.com | 555-0101 | https://jane.dev" in md
    assert "Austin, TX" in md
    assert "## Summary" in md and "5 years building APIs" in md
    assert "- **Languages**: Python, Go" in md
    assert "### Senior Engineer | Acme Corp" in md
    assert "*2021-03 - Present*" in md
    assert "- Cut API latency 40% by adding caching" in md
    assert "[hr-agent](https://github.com/janedoe/hr-agent)" in md
    assert "### UT Austin" in md and "BS in Computer Science" in md
    assert "*2014 - 2018*" in md
    assert "- **Hackathon Winner - PyCon - 2020**" in md
    assert "## Certifications" in md and "- AWS SAA" in md
    assert "## Languages Spoken" in md and "- Hindi" in md
    assert "\n\n\n" not in md
    # empty-ish resume should not crash
    md2 = json_resume_to_markdown({})
    assert md2.startswith("# Resume")
    print("resume_builder self-check OK")
