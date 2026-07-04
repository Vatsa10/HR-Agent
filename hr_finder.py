"""
Find recruiters / talent-acquisition contacts at a company via LinkedIn.

Best-effort: tries company_employees(keywords='recruiter') first, then falls
back to a people search. Always returns a list (possibly empty); never raises.
"""

import logging

import linkedin_service

logger = logging.getLogger(__name__)

_LI_BASE = "https://www.linkedin.com"


def _abs_url(url):
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return _LI_BASE + ("" if url.startswith("/") else "/") + url


def _parse_people(result, cap=6):
    """Parse references.search_results (profiles) into [{name, headline, profile_url}]."""
    if not isinstance(result, dict):
        return []
    refs = (result.get("references") or {}).get("search_results") or []
    out = []
    for r in refs:
        if not isinstance(r, dict):
            continue
        url = r.get("url", "") or ""
        if "/in/" not in url:
            continue
        name = (r.get("text") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "headline": (r.get("headline") or r.get("subtitle") or "").strip(),
            "profile_url": _abs_url(url),
        })
        if len(out) >= cap:
            break
    return out


def find_recruiters(company_name, location=None):
    """Return up to 6 recruiter-ish contacts at company_name. Best-effort, [] on failure."""
    try:
        res = linkedin_service.company_employees(company_name, keywords="recruiter")
        people = _parse_people(res)
        if people:
            return people
    except Exception as e:  # noqa: BLE001
        logger.warning("company_employees failed for %s: %s", company_name, e)

    try:
        res = linkedin_service.search_people(
            "recruiter OR talent acquisition " + company_name, location=location
        )
        return _parse_people(res)
    except Exception as e:  # noqa: BLE001
        logger.warning("search_people fallback failed for %s: %s", company_name, e)
        return []


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8")

    fake = {
        "references": {
            "search_results": [
                {"url": "/in/jane-doe/", "text": "Jane Doe", "headline": "Technical Recruiter"},
                {"url": "/jobs/view/1/", "text": "Not a person"},
                {"url": "/in/no-name/", "text": ""},
                {"url": "https://www.linkedin.com/in/john/", "text": "John Roe"},
            ]
        }
    }
    people = _parse_people(fake)
    assert len(people) == 2, people
    assert people[0]["name"] == "Jane Doe"
    assert people[0]["profile_url"] == "https://www.linkedin.com/in/jane-doe/"
    assert people[0]["headline"] == "Technical Recruiter"
    assert people[1]["profile_url"] == "https://www.linkedin.com/in/john/"
    # cap
    big = {"references": {"search_results": [
        {"url": f"/in/p{i}/", "text": f"P{i}"} for i in range(10)]}}
    assert len(_parse_people(big)) == 6
    # junk input
    assert _parse_people(None) == []
    assert _parse_people({}) == []

    print("hr_finder self-check OK")
