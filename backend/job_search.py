"""
Job search over LinkedIn: turn a raw job-search result blob into a clean list,
score jobs against a resume heuristically (pure) and via one batched LLM call.
"""

import concurrent.futures
import json
import logging
import re

import job_sources
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


def _keep_titled(rows):
    """Drop rows with an empty/whitespace title.

    LinkedIn returns more job_ids than have real data; those trailing ids parse
    into title-less rows (the "Untitled role" garbage). Pure, no network.
    """
    return [r for r in rows if (r.get("title") or "").strip()]


def search(keywords, location=None, work_type=None, experience_level=None,
           job_type=None, date_posted=None, limit=25):
    """Search jobs across browser-free sources; return
    [{li_job_id, title, company, location, url, posted, source}].

    Sources (LinkedIn jobs-guest + freehire) run concurrently and are merged +
    deduped. One source failing degrades gracefully to the other. No stealth
    browser is used. experience_level/job_type are accepted for API
    compatibility but not all sources filter on them.
    """
    remote = (work_type or "").lower() == "remote"
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f_li = ex.submit(
            job_sources.search_linkedin_guest, keywords,
            location=location, work_type=work_type,
            date_posted=date_posted, limit=limit,
        )
        f_fh = ex.submit(
            job_sources.search_freehire, keywords,
            location=location, remote=remote, limit=limit,
        )
        li_rows = f_li.result() or []
        fh_rows = f_fh.result() or []

    # Surface a silently-dead source: 0 rows from one source is not an error, but
    # if it stays 0 across searches it means the endpoint got blocked/changed.
    logger.info("job sources: linkedin=%d freehire=%d", len(li_rows), len(fh_rows))
    if not li_rows and not fh_rows:
        logger.warning("ALL job sources returned 0 rows for %r @ %r", keywords, location)

    merged = job_sources.merge_dedup(li_rows, fh_rows)
    return _keep_titled(merged)[:limit]


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


def score_all(resume_text, jobs, chunk_size=6, max_workers=4):
    """Score every job by fanning batch_llm_scores over chunks concurrently.

    Splits `jobs` into groups of `chunk_size`, runs `batch_llm_scores` on each
    group in parallel (ThreadPoolExecutor), and merges results, remapping each
    chunk's LOCAL indices back to GLOBAL indices into `jobs`.

    Returns [{index, score, reason}] with global indices, one entry per scored
    job (jobs the LLM omits simply don't appear), sorted by index.
    """
    if not resume_text or not jobs:
        return []
    chunks = [(start, jobs[start:start + chunk_size])
              for start in range(0, len(jobs), chunk_size)]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {}
        for start, chunk in chunks:
            fut = ex.submit(batch_llm_scores, resume_text, chunk)
            futures[fut] = (start, len(chunk))
        for fut in concurrent.futures.as_completed(futures):
            start, chunk_len = futures[fut]
            try:
                local_scores = fut.result()
            except Exception as e:  # noqa: BLE001
                logger.warning("score chunk at %d failed: %s", start, e)
                continue
            for s in local_scores:
                idx = s.get("index")
                if not isinstance(idx, int) or not (0 <= idx < chunk_len):
                    continue
                results.append({
                    "index": start + idx,
                    "score": s.get("score"),
                    "reason": (s.get("reason") or ""),
                })
    results.sort(key=lambda r: r["index"])
    return results


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

    # _keep_titled (pure): empty/whitespace-title rows are dropped
    rows = [
        {"li_job_id": "1", "title": "Engineer", "company": "A"},
        {"li_job_id": "2", "title": "   ", "company": "B"},
        {"li_job_id": "3", "title": "", "company": "C"},
        {"li_job_id": "4", "title": "Manager"},
        {"li_job_id": "5", "company": "D"},  # missing title entirely
    ]
    kept = _keep_titled(rows)
    assert [r["li_job_id"] for r in kept] == ["1", "4"], kept

    # score_all remaps chunk-local indices to global indices (stubbed, no LLM).
    # Stub returns local index i -> score i, reason = the job title it saw, so a
    # correct global remap means results[g].reason == title of jobs[g].
    _orig_batch = batch_llm_scores
    jobs15 = [{"title": f"J{n}", "company": "C", "location": "L"} for n in range(15)]

    def _stub_batch(resume_text, chunk):
        return [{"index": i, "score": float(i), "reason": chunk[i]["title"]}
                for i in range(len(chunk))]

    batch_llm_scores = _stub_batch
    try:
        res = score_all("some resume text", jobs15, chunk_size=6, max_workers=4)
    finally:
        batch_llm_scores = _orig_batch
    assert len(res) == 15, res
    assert [r["index"] for r in res] == list(range(15)), res
    for r in res:
        assert r["reason"] == f"J{r['index']}", r  # index remapped to right job
    # chunk-local score i means global job g in chunk starting at s has score g-s
    assert res[0]["score"] == 0.0 and res[6]["score"] == 0.0 and res[12]["score"] == 0.0, res
    assert res[7]["score"] == 1.0, res

    # score_all short-circuits with no resume or no jobs
    assert score_all("", jobs15) == []
    assert score_all("resume", []) == []

    print("job_search self-check OK")
