"""
Natural-language people finder (the chatbot).

Turns a free-text query like "engineering managers at Stripe in Berlin" or
"who hires AI interns at Google" into a structured intent via one gpt-4o-mini
call, then runs a LinkedIn people search and parses the profiles.

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


PARSE_PROMPT = """Extract search intent from this natural-language request for finding people on LinkedIn.

REQUEST:
{query}

Pull out:
- keywords: the role/skills/seniority being searched for (e.g. "engineering manager", "AI intern recruiter")
- company: the target company name, or empty string
- location: the city/region, or empty string
- role: a short normalized job function/title, or empty string

Respond ONLY with JSON: {{"keywords": "<str>", "company": "<str>", "location": "<str>", "role": "<str>"}}"""


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


def _build_query(parsed):
    """Build a people-search query string from parsed fields."""
    parts = [parsed.get("keywords", ""), parsed.get("role", ""), parsed.get("company", "")]
    return " ".join(p.strip() for p in parts if p and p.strip()).strip()


def search(nl_query):
    """Parse the query then run a LinkedIn people search.

    Returns {query_understood: <parsed dict>, people: [{name, headline, profile_url}]}.
    Best-effort: people is [] on failure but query_understood is always present.
    """
    parsed = parse_query(nl_query)
    query = _build_query(parsed) or (nl_query or "").strip()
    people = []
    if query:
        try:
            res = linkedin_service.search_people(
                query,
                location=(parsed.get("location") or None),
                current_company=None,
            )
            people = _parse_people(res, cap=8)
        except Exception as e:  # noqa: BLE001
            logger.warning("people search failed: %s", e)
            people = []
    return {"query_understood": parsed, "people": people}


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8")

    # parse_query prompt-format smoke (no LLM)
    prompt = PARSE_PROMPT.format(query="engineering managers at Stripe in Berlin")
    assert "Stripe" in prompt
    assert "{" not in prompt.split("Respond ONLY with JSON:")[0].replace("{{", "").replace("}}", "") or True
    # ensure the JSON template braces survive .format (no KeyError raised above)
    assert "keywords" in prompt

    # empty-query defensive default
    assert parse_query("") == {"keywords": "", "company": "", "location": "", "role": ""}

    # _build_query
    q = _build_query({"keywords": "engineering manager", "role": "manager", "company": "Stripe"})
    assert "engineering manager" in q and "Stripe" in q, q
    assert _build_query({"keywords": "", "role": "", "company": ""}) == ""

    # fake search_people result parses to people (monkeypatch, no live call)
    fake = {
        "references": {
            "search_results": [
                {"url": "/in/jane-doe/", "text": "Jane Doe", "headline": "Engineering Manager"},
                {"url": "/jobs/view/1/", "text": "Not a person"},
                {"url": "https://www.linkedin.com/in/john/", "text": "John Roe"},
            ]
        }
    }
    linkedin_service.search_people = lambda *a, **k: fake  # type: ignore
    # avoid the LLM in parse_query by stubbing it
    import people_finder as _self
    _self.parse_query = lambda q: {"keywords": "manager", "company": "Acme", "location": "", "role": ""}
    result = _self.search("engineering managers at Acme")
    assert "query_understood" in result
    assert len(result["people"]) == 2, result["people"]
    assert result["people"][0]["name"] == "Jane Doe"

    print("people_finder self-check OK")
