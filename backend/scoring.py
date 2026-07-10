"""
Pure scoring helpers shared by jd_matcher and job_search. No LLM, no network —
so the fit number is auditable and cheap. The LLM produces per-dimension scores;
this module turns them into an overall, a verdict band, and applies deterministic
deal-breaker vetoes.
"""

# Weighted contribution of each fit dimension to the overall (must sum to 100).
WEIGHTS = {"technical": 30, "experience": 25, "behavioral": 15, "career": 30}

# Overall score -> verdict band.
_SHORTLIST = 70
_BELOW = 45


def weighted_overall(dimensions) -> int:
    """Combine per-dimension scores into a 0-100 overall via WEIGHTS.

    `dimensions` is a list of {name, score} (score 0-100). Unknown names are
    ignored; missing known dimensions are treated as 0. Result rounds to int.
    """
    by_name = {}
    for d in dimensions or []:
        name = str(d.get("name", "")).strip().lower()
        try:
            by_name[name] = max(0.0, min(100.0, float(d.get("score"))))
        except (TypeError, ValueError):
            continue
    total = sum(WEIGHTS.values())
    acc = sum(by_name.get(name, 0.0) * w for name, w in WEIGHTS.items())
    return round(acc / total)


def verdict_band(overall) -> str:
    """shortlist (>=70) / below (45-69) / excluded (<45)."""
    try:
        o = float(overall)
    except (TypeError, ValueError):
        return "excluded"
    if o >= _SHORTLIST:
        return "shortlist"
    if o >= _BELOW:
        return "below"
    return "excluded"


def apply_vetoes(job, deal_breakers) -> str:
    """Deterministic deal-breaker check on a job's location/work_type.

    deal_breakers: {"locations": [...], "work_types": [...]} — substrings that,
    if matched, veto the job. Returns:
      "FAIL"  -> a hard deal-breaker matched (force excluded regardless of score)
      "PASS"  -> no deal-breaker matched
    (A "FLAG" tier is reserved for soft concerns; not used yet.)
    """
    if not deal_breakers:
        return "PASS"
    loc = (job.get("location") or "").lower()
    wt = (job.get("work_type") or job.get("source") or "").lower()
    hay_loc = loc
    for bad in deal_breakers.get("locations") or []:
        if bad and bad.lower().strip() in hay_loc:
            return "FAIL"
    # work_type deal-breakers also scan the location string (LinkedIn often
    # bakes "(On-site)" / "(Remote)" into location text).
    for bad in deal_breakers.get("work_types") or []:
        b = (bad or "").lower().strip()
        if b and (b in wt or b in loc):
            return "FAIL"
    return "PASS"


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8")

    assert sum(WEIGHTS.values()) == 100

    dims = [
        {"name": "technical", "score": 90},
        {"name": "experience", "score": 80},
        {"name": "behavioral", "score": 60},
        {"name": "career", "score": 100},
    ]
    # (90*30 + 80*25 + 60*15 + 100*30) / 100 = (2700+2000+900+3000)/100 = 86
    assert weighted_overall(dims) == 86, weighted_overall(dims)
    # missing dimension treated as 0
    assert weighted_overall([{"name": "technical", "score": 100}]) == 30
    # junk ignored, clamps
    assert weighted_overall([{"name": "technical", "score": 999}]) == 30
    assert weighted_overall([]) == 0

    assert verdict_band(86) == "shortlist"
    assert verdict_band(70) == "shortlist"
    assert verdict_band(69) == "below"
    assert verdict_band(45) == "below"
    assert verdict_band(44) == "excluded"
    assert verdict_band(None) == "excluded"

    # vetoes
    db = {"locations": ["New York"], "work_types": ["on-site"]}
    assert apply_vetoes({"location": "New York, NY"}, db) == "FAIL"
    assert apply_vetoes({"location": "Remote", "work_type": "remote"}, db) == "PASS"
    assert apply_vetoes({"location": "Austin (On-site)"}, db) == "FAIL"  # wt in loc text
    assert apply_vetoes({"location": "Austin"}, None) == "PASS"
    assert apply_vetoes({"location": "Austin"}, {}) == "PASS"

    print("scoring self-check OK")
