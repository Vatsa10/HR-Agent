"""
Natural-language people finder (the chatbot).

Turns a free-text query like "engineering managers at Stripe in Berlin" or
"who hires AI interns at Google" into a structured intent via one gpt-4o-mini
call, then runs a LinkedIn people search and parses the profiles into rich
records (name, headline, company, location, profile_url).

Best-effort: search() always returns {query_understood, people}; people is []
on any failure but the parsed intent is always included.
"""

import json
import logging

import linkedin_service
from hr_finder import _parse_people
from llm_utils import initialize_llm_provider, extract_json_from_response
from prompt import MODEL_PARAMETERS

logger = logging.getLogger(__name__)

_MODEL = "gpt-4o-mini"
_LI_BASE = "https://www.linkedin.com"


PARSE_PROMPT = """Extract search intent from this natural-language request for finding people on LinkedIn.

REQUEST:
{query}

Pull out:
- keywords: the role/skills/seniority being searched for (e.g. "engineering manager", "AI intern recruiter")
- company: the target company name, or empty string
- location: the city/region, or empty string
- role: a short normalized job function/title, or empty string

Respond ONLY with JSON: {{"keywords": "<str>", "company": "<str>", "location": "<str>", "role": "<str>"}}"""


BLOB_PROMPT = """You are parsing a LinkedIn people-search results page into structured records.

You get two inputs:
1. REFERENCES: an ordered list of {{name, url}} where url is that person's profile path.
2. RESULTS_BLOB: a text dump that lists, per person, their name, a headline line
   (their title, e.g. "Technical Recruiter at Google") and a location line
   (e.g. "San Francisco Bay Area").

Produce one record per person you can identify, preferring the people in REFERENCES.
For each person:
- name: the person's full name.
- headline: their title line from the blob (e.g. "Technical Recruiter at Google"), or empty string.
- company: the employer taken from the headline (the part after "at"/"@"), or empty string if unclear.
- location: their location line, or empty string.
- profile_url: the url from REFERENCES whose name matches this person; empty string if there is no match.

REFERENCES:
{references}

RESULTS_BLOB:
{blob}

Respond ONLY with JSON of this shape:
{{"people": [{{"name": "<name>", "headline": "<headline>", "company": "<company>", "location": "<location>", "profile_url": "<url>"}}]}}"""


def _llm_json(system, user):
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
    """Return an absolute https LinkedIn URL for a possibly-relative path."""
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return _LI_BASE + ("" if url.startswith("/") else "/") + url


def _norm(name):
    """Normalize a name for matching (lowercased, whitespace-collapsed)."""
    return " ".join((name or "").lower().split())


def _sections_text(res):
    """Pull the results text blob out of a linkedin_service result dict."""
    if not isinstance(res, dict):
        return ""
    return (res.get("sections") or {}).get("search_results") or ""


def _refs(res):
    """Pull the references list out of a linkedin_service result dict."""
    if not isinstance(res, dict):
        return []
    return (res.get("references") or {}).get("search_results") or []


def parse_query(nl_query):
    """Parse a natural-language query into {keywords, company, location, role}.

    One gpt-4o-mini call. Defensive: empty-string defaults on any failure.
    """
    default = {"keywords": "", "company": "", "location": "", "role": ""}
    if not (nl_query or "").strip():
        return default
    try:
        parsed = _llm_json(
            "You extract structured search intent. Respond only with JSON.",
            PARSE_PROMPT.format(query=nl_query.strip()[:1000]),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("parse_query failed: %s", e)
        return default
    if not isinstance(parsed, dict):
        return default
    return {
        "keywords": (parsed.get("keywords") or "").strip(),
        "company": (parsed.get("company") or "").strip(),
        "location": (parsed.get("location") or "").strip(),
        "role": (parsed.get("role") or "").strip(),
    }


def _fallback_people(references):
    """Reuse hr_finder._parse_people (name+url only) and pad to the full shape."""
    basic = _parse_people({"references": {"search_results": references or []}}, cap=8)
    return [
        {
            "name": p.get("name", ""),
            "headline": p.get("headline", ""),
            "company": "",
            "location": "",
            "profile_url": p.get("profile_url", ""),
        }
        for p in basic
    ]


def parse_people_blob(sections_text, references):
    """Parse a people-search results blob into rich records.

    ONE gpt-4o-mini call that reads the results TEXT BLOB plus the references
    (name+url list) and returns up to 8 records with name, headline, company
    (extracted from the headline), location and profile_url (matched back to a
    reference by name, absolutized to an https URL).

    Defensive: on any failure falls back to hr_finder._parse_people (name+url
    only, headline/company empty) so people still render.
    """
    references = references or []
    try:
        parsed = _llm_json(
            "You extract structured people records. Respond only with JSON.",
            BLOB_PROMPT.format(
                references=json.dumps(
                    [
                        {"name": (r.get("text") or "").strip(), "url": r.get("url", "")}
                        for r in references[:12]
                        if isinstance(r, dict)
                    ]
                ),
                blob=(sections_text or "")[:8000],
            ),
        )
        rows = parsed.get("people", []) if isinstance(parsed, dict) else []
        if not rows:
            raise ValueError("no people rows")

        # url lookup by normalized name from references (ground truth).
        by_name = {}
        for r in references:
            if not isinstance(r, dict):
                continue
            nm = _norm(r.get("text"))
            if nm and nm not in by_name:
                by_name[nm] = r.get("url", "")

        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = (row.get("name") or "").strip()
            if not name:
                continue
            url = by_name.get(_norm(name)) or (row.get("profile_url") or "")
            out.append({
                "name": name,
                "headline": (row.get("headline") or "").strip(),
                "company": (row.get("company") or "").strip(),
                "location": (row.get("location") or "").strip(),
                "profile_url": _abs_url(url),
            })
            if len(out) >= 8:
                break
        if not out:
            raise ValueError("no usable people rows")
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("parse_people_blob failed, falling back: %s", e)
        return _fallback_people(references)


def _build_query(parsed):
    """Build a people-search query string from parsed fields."""
    parts = [parsed.get("keywords", ""), parsed.get("role", ""), parsed.get("company", "")]
    return " ".join(p.strip() for p in parts if p and p.strip()).strip()


def search(nl_query):
    """Parse the query then run a LinkedIn people search.

    Branches on the parsed company:
    - company set: list that company's employees (keyword-biased to the desired
      role) via linkedin_service.company_employees, which is far more accurate
      for "recruiters AT <company>". If it yields at least one person, use it.
    - otherwise (or if company_employees yielded nothing): a free
      linkedin_service.search_people over the built query, location-filtered.

    Returns {query_understood: <parsed dict>, people: [{name, headline, company,
    location, profile_url}]}. Best-effort: people is [] on total failure but
    query_understood is always present.
    """
    parsed = parse_query(nl_query)
    query = _build_query(parsed) or (nl_query or "").strip()
    company = parsed.get("company") or ""
    people = []

    if company:
        kw = parsed.get("role") or parsed.get("keywords") or "recruiter"
        try:
            res = linkedin_service.company_employees(company, keywords=kw)
            people = parse_people_blob(_sections_text(res), _refs(res))
        except Exception as e:  # noqa: BLE001
            logger.warning("company_employees failed for %s: %s", company, e)
            people = []

    if not people and query:
        try:
            res = linkedin_service.search_people(
                query, location=(parsed.get("location") or None)
            )
            people = parse_people_blob(_sections_text(res), _refs(res))
        except Exception as e:  # noqa: BLE001
            logger.warning("people search failed: %s", e)
            people = []

    return {"query_understood": parsed, "people": people}


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8")

    import people_finder as _self

    # parse_query prompt-format smoke (no LLM)
    prompt = PARSE_PROMPT.format(query="engineering managers at Stripe in Berlin")
    assert "Stripe" in prompt
    assert "keywords" in prompt  # JSON template braces survived .format (no KeyError)

    # empty-query defensive default
    assert parse_query("") == {"keywords": "", "company": "", "location": "", "role": ""}

    # _build_query
    q = _build_query({"keywords": "engineering manager", "role": "manager", "company": "Stripe"})
    assert "engineering manager" in q and "Stripe" in q, q
    assert _build_query({"keywords": "", "role": "", "company": ""}) == ""

    # _abs_url helper
    assert _abs_url("/in/jane/") == "https://www.linkedin.com/in/jane/"
    assert _abs_url("https://x.com/a") == "https://x.com/a"
    assert _abs_url("") == ""

    # ---- parse_people_blob: rich records from a stubbed LLM call (no live LLM) ----
    refs = [
        {"url": "/in/jane-doe/", "text": "Jane Doe"},
        {"url": "https://www.linkedin.com/in/john-roe/", "text": "John Roe"},
    ]
    _orig_llm_json = _self._llm_json
    _self._llm_json = lambda system, user: {  # type: ignore
        "people": [
            {"name": "Jane Doe", "headline": "Technical Recruiter at Google",
             "company": "Google", "location": "Bengaluru", "profile_url": "/in/jane-doe/"},
            # profile_url intentionally blank -> must be recovered from references by name
            {"name": "John Roe", "headline": "Talent Partner at Stripe",
             "company": "Stripe", "location": "Berlin", "profile_url": ""},
        ]
    }
    try:
        ppl = _self.parse_people_blob("results blob text", refs)
    finally:
        _self._llm_json = _orig_llm_json
    assert len(ppl) == 2, ppl
    assert ppl[0]["name"] == "Jane Doe"
    assert ppl[0]["headline"] == "Technical Recruiter at Google"
    assert ppl[0]["company"] == "Google"
    assert ppl[0]["location"] == "Bengaluru"
    assert ppl[0]["profile_url"] == "https://www.linkedin.com/in/jane-doe/", ppl[0]
    # matched from references by name and absolutized
    assert ppl[1]["profile_url"] == "https://www.linkedin.com/in/john-roe/", ppl[1]
    assert ppl[1]["company"] == "Stripe"

    # ---- parse_people_blob: falls back to _parse_people on LLM failure ----
    def _boom(system, user):
        raise RuntimeError("no LLM here")

    _self._llm_json = _boom  # type: ignore
    try:
        fb = _self.parse_people_blob("blob", refs)
    finally:
        _self._llm_json = _orig_llm_json
    assert len(fb) == 2, fb
    assert fb[0]["name"] == "Jane Doe"
    assert fb[0]["profile_url"] == "https://www.linkedin.com/in/jane-doe/"
    assert fb[0]["headline"] == "" and fb[0]["company"] == "", fb[0]

    # ---- search(): uses company_employees when a company is parsed (no live calls) ----
    calls = {"company": 0, "search": 0}

    def _fake_company(company_name, keywords=None):
        calls["company"] += 1
        assert company_name == "Google", company_name
        assert keywords == "technical recruiter", keywords  # role preferred as keyword bias
        return {"sections": {"search_results": "company blob"},
                "references": {"search_results": [{"url": "/in/a/", "text": "A"}]}}

    def _fake_search(query, location=None):
        calls["search"] += 1
        return {"sections": {"search_results": "search blob"},
                "references": {"search_results": [{"url": "/in/b/", "text": "B"}]}}

    _orig_company = linkedin_service.company_employees
    _orig_search = linkedin_service.search_people
    _orig_parse_query = _self.parse_query
    _orig_ppb = _self.parse_people_blob
    linkedin_service.company_employees = _fake_company  # type: ignore
    linkedin_service.search_people = _fake_search  # type: ignore
    _self.parse_query = lambda q: {  # type: ignore
        "keywords": "recruiter", "company": "Google", "location": "", "role": "technical recruiter",
    }
    _self.parse_people_blob = lambda sections, references: [  # type: ignore
        {"name": "A", "headline": "Technical Recruiter at Google", "company": "Google",
         "location": "", "profile_url": "https://www.linkedin.com/in/a/"}
    ]
    try:
        result = _self.search("technical recruiters at Google")
    finally:
        linkedin_service.company_employees = _orig_company
        linkedin_service.search_people = _orig_search
        _self.parse_query = _orig_parse_query
        _self.parse_people_blob = _orig_ppb
    assert "query_understood" in result
    assert calls["company"] == 1 and calls["search"] == 0, calls  # company path taken, no fallback
    assert len(result["people"]) == 1 and result["people"][0]["company"] == "Google", result

    # ---- search(): no company -> free people search path ----
    calls = {"company": 0, "search": 0}
    linkedin_service.company_employees = _fake_company  # type: ignore
    linkedin_service.search_people = _fake_search  # type: ignore
    _self.parse_query = lambda q: {  # type: ignore
        "keywords": "engineering manager", "company": "", "location": "Berlin", "role": "",
    }
    _self.parse_people_blob = lambda sections, references: [  # type: ignore
        {"name": "B", "headline": "Engineering Manager", "company": "",
         "location": "Berlin", "profile_url": "https://www.linkedin.com/in/b/"}
    ]
    try:
        result2 = _self.search("engineering managers in Berlin")
    finally:
        linkedin_service.company_employees = _orig_company
        linkedin_service.search_people = _orig_search
        _self.parse_query = _orig_parse_query
        _self.parse_people_blob = _orig_ppb
    assert calls["company"] == 0 and calls["search"] == 1, calls  # no company -> search path
    assert result2["people"][0]["name"] == "B", result2

    print("people_finder self-check OK")
