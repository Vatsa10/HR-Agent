"""
Job search over LinkedIn: turn a raw job-search result blob into a clean list,
score jobs against a resume heuristically (pure) and via one batched LLM call.
"""

import json
import logging
import re

import linkedin_service
from llm_utils import initialize_llm_provider, extract_json_from_response
from prompt import MODEL_PARAMETERS

logger = logging.getLogger(__name__)

_MODEL = "gpt-4o-mini"
_LI_BASE = "https://www.linkedin.com"


def _llm_json(system, user):
    """One gpt-4o-mini call in JSON mode; returns parsed object or None."""
    provider = initialize_llm_provider(_MODEL)
    params = MODEL_PARAMETERS.get(_MODEL, {"temperature": 0.1, "top_p": 0.9})
    resp = provider.chat(
        model=_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        options={"stream": False, **params},
        format="json",
    )
    raw = extract_json_from_response(resp["message"]["content"])
    return json.loads(raw)


def _abs_url(url):
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return _LI_BASE + ("" if url.startswith("/") else "/") + url


SEARCH_PROMPT = """You are parsing LinkedIn job-search output into structured records.

Below are three inputs:
1. JOB_IDS: an ordered list of LinkedIn job ids.
2. REFERENCES: an ordered list of {{url, text}} where text is usually the job title; order matches JOB_IDS.
3. SEARCH_BLOB: a text dump that lists, per job in the same order, a title line, a "<title> with verification" line, a company line, and a location line (e.g. "Bengaluru, Karnataka, India (On-site)").

Produce one record per job id, in order. Use the blob to recover company and location; use references/blob for the title. If a field is unknown use an empty string.

JOB_IDS:
{job_ids}

REFERENCES:
{references}

SEARCH_BLOB:
{blob}

Respond ONLY with JSON of this shape:
{{"jobs": [{{"li_job_id": "<id>", "title": "<title>", "company": "<company>", "location": "<location>"}}]}}"""


def search(keywords, location=None):
    """Search LinkedIn jobs and parse into [{li_job_id, title, company, location, url}]."""
    raw = linkedin_service.search_jobs(keywords, location=location)
    refs = (raw.get("references") or {}).get("search_results") or []
    job_ids = raw.get("job_ids") or []
    blob = (raw.get("sections") or {}).get("search_results") or ""

    # url lookup by index from references (url like '/jobs/view/<id>/')
    ref_urls = [r.get("url", "") for r in refs]

    try:
        parsed = _llm_json(
            "You extract structured job records. Respond only with JSON.",
            SEARCH_PROMPT.format(
                job_ids=json.dumps(job_ids[:25]),
                references=json.dumps(
                    [{"url": r.get("url", ""), "text": r.get("text", "")} for r in refs[:25]]
                ),
                blob=blob[:8000],
            ),
        )
        rows = parsed.get("jobs", []) if isinstance(parsed, dict) else []
    except Exception as e:  # noqa: BLE001
        logger.warning("job search parse failed: %s", e)
        rows = []

    out = []
    for i, row in enumerate(rows[:25]):
        jid = str(row.get("li_job_id") or (job_ids[i] if i < len(job_ids) else "")).strip()
        if not jid:
            continue
        url = ""
        if i < len(ref_urls) and ref_urls[i]:
            url = ref_urls[i]
        elif jid:
            url = f"/jobs/view/{jid}/"
        out.append({
            "li_job_id": jid,
            "title": (row.get("title") or "").strip(),
            "company": (row.get("company") or "").strip(),
            "location": (row.get("location") or "").strip(),
            "url": _abs_url(url),
        })
    return out


_WORD = re.compile(r"[a-z0-9+#]+")


def _tokens(text):
    return set(_WORD.findall((text or "").lower()))


def heuristic_scores(resume_dict, jobs):
    """Pure 0-100 keyword-overlap score of resume skills+titles vs job fields."""
    skills = resume_dict.get("skills") or []
    flat_skills = []
    for s in skills:
        if isinstance(s, dict):
            flat_skills.append(s.get("name", ""))
            flat_skills.extend(s.get("keywords", []) or [])
        else:
            flat_skills.append(str(s))
    titles = []
    for w in resume_dict.get("work", []) or []:
        if isinstance(w, dict):
            titles.append(w.get("position", ""))
    label = (resume_dict.get("basics") or {}).get("label", "")
    resume_tokens = _tokens(" ".join(flat_skills + titles + [label]))

    scored = []
    for job in jobs:
        job_tokens = _tokens(
            " ".join([job.get("title", ""), job.get("company", ""), job.get("location", "")])
        )
        if not job_tokens:
            score = 0.0
        else:
            overlap = len(resume_tokens & job_tokens)
            score = round(min(100.0, 100.0 * overlap / len(job_tokens)), 1)
        out = dict(job)
        out["heuristic_score"] = score
        scored.append(out)
    return scored


BATCH_PROMPT = """You are a technical recruiter scoring how well a candidate fits each job.

CANDIDATE RESUME:
{resume}

JOBS (indexed):
{jobs}

For each job index, give a fit score 0-100 and a one-line reason.
Respond ONLY with JSON: {{"scores": [{{"index": <int>, "score": <0-100>, "reason": "<one line>"}}]}}"""


def batch_llm_scores(resume_text, jobs):
    """One gpt-4o-mini call scoring up to 6 jobs. Returns [{index, score, reason}]."""
    jobs = jobs[:6]
    if not jobs:
        return []
    listing = "\n".join(
        f"{i}. {j.get('title','')} at {j.get('company','')} ({j.get('location','')})"
        for i, j in enumerate(jobs)
    )
    try:
        parsed = _llm_json(
            "You score candidate-job fit. Respond only with JSON.",
            BATCH_PROMPT.format(resume=(resume_text or "")[:6000], jobs=listing),
        )
        scores = parsed.get("scores", []) if isinstance(parsed, dict) else []
    except Exception as e:  # noqa: BLE001
        logger.warning("batch llm score failed: %s", e)
        return []
    out = []
    for s in scores:
        try:
            out.append({
                "index": int(s.get("index")),
                "score": float(s.get("score")),
                "reason": (s.get("reason") or "").strip(),
            })
        except (TypeError, ValueError):
            continue
    return out


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8")

    # _abs_url
    assert _abs_url("/jobs/view/123/") == "https://www.linkedin.com/jobs/view/123/"
    assert _abs_url("https://x.com/a") == "https://x.com/a"
    assert _abs_url("jobs/view/9/") == "https://www.linkedin.com/jobs/view/9/"

    # heuristic_scores (pure)
    resume = {
        "basics": {"label": "Backend Engineer"},
        "skills": [{"name": "Python", "keywords": ["FastAPI", "Postgres"]}],
        "work": [{"position": "Software Engineer"}],
    }
    jobs = [
        {"title": "Python Backend Engineer", "company": "Acme", "location": "Remote"},
        {"title": "Marketing Lead", "company": "Zeta", "location": "NYC"},
    ]
    scored = heuristic_scores(resume, jobs)
    assert scored[0]["heuristic_score"] > scored[1]["heuristic_score"], scored
    assert all("heuristic_score" in j for j in scored)
    # empty job tokens -> 0
    assert heuristic_scores(resume, [{"title": "", "company": "", "location": ""}])[0]["heuristic_score"] == 0.0

    print("job_search self-check OK")
