"""
Browser-free job sources. Replaces the Patchright/stealth-browser path for job
SEARCH (profile scraping still uses the browser, on a separate host).

Two sources, merged and deduped by the caller:
- LinkedIn `jobs-guest` public endpoint (HTML cards, no auth).
- freehire.dev public JSON API (structured, no key).

Honesty note: LinkedIn's guest endpoint is unauthenticated and public, but
automated access still touches LinkedIn's Terms of Service. Keep volume low;
this is personal-use framing. Both sources degrade gracefully — one failing
never breaks a search.

Every source returns the SAME row shape the rest of the app expects:
    {li_job_id, title, company, location, url, posted, source}
"""

import logging
import os
import re
import time

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_LI_GUEST = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
)
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
# f_TPR: posted-within, in seconds. f_WT: 1 on-site, 2 remote, 3 hybrid.
_DATE_TPR = {"day": "r86400", "week": "r604800", "month": "r2592000"}
_WT = {"onsite": "1", "on-site": "1", "remote": "2", "hybrid": "3"}


def _urn_to_id(urn: str) -> str:
    """urn:li:jobPosting:1234567 -> 1234567."""
    if not urn:
        return ""
    return urn.rsplit(":", 1)[-1].strip()


def parse_linkedin_cards(html: str) -> list:
    """Parse the jobs-guest HTML card list into rows. Pure, no network."""
    soup = BeautifulSoup(html or "", "html.parser")
    rows = []
    for card in soup.select("li"):
        base = card.select_one("[data-entity-urn]") or card.find(
            attrs={"data-entity-urn": True}
        )
        jid = _urn_to_id(base.get("data-entity-urn")) if base else ""
        title_el = card.select_one(".base-search-card__title")
        company_el = card.select_one(".base-search-card__subtitle")
        loc_el = card.select_one(".job-search-card__location")
        link_el = card.select_one("a.base-card__full-link") or card.select_one("a[href]")
        time_el = card.select_one("time")
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            continue  # trailing/garbage cards
        url = (link_el.get("href") if link_el else "") or ""
        url = url.split("?")[0].strip()
        rows.append({
            "li_job_id": jid,
            "title": title,
            "company": company_el.get_text(strip=True) if company_el else "",
            "location": loc_el.get_text(strip=True) if loc_el else "",
            "url": url,
            "posted": (time_el.get("datetime") if time_el else "") or "",
            "source": "linkedin",
        })
    return rows


def search_linkedin_guest(keywords, location=None, work_type=None,
                          date_posted=None, start=0, limit=25, timeout=12):
    """Search LinkedIn public jobs-guest endpoint. Returns rows (may be empty)."""
    params = {"keywords": keywords or "", "start": int(start or 0)}
    if location:
        params["location"] = location
    wt = _WT.get((work_type or "").lower())
    if wt:
        params["f_WT"] = wt
    tpr = _DATE_TPR.get((date_posted or "").lower())
    if tpr:
        params["f_TPR"] = tpr
    try:
        resp = requests.get(
            _LI_GUEST, params=params,
            headers={"User-Agent": _UA, "Accept": "text/html"},
            timeout=timeout,
        )
        if resp.status_code == 429:
            logger.warning("linkedin guest 429; backing off")
            time.sleep(2)
            return []
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001
        logger.warning("linkedin guest fetch failed: %s", e)
        return []
    return parse_linkedin_cards(resp.text)[:limit]


def _freehire_url() -> str:
    base = os.environ.get("FREEHIRE_API_URL", "https://freehire.dev").rstrip("/")
    return f"{base}/api/v1/jobs/search"


def search_freehire(keywords, location=None, remote=None, limit=25, timeout=12):
    """Query the freehire.dev public JSON API. Best-effort; degrades to []."""
    params = {"q": keywords or "", "limit": limit}
    if location:
        params["location"] = location
    if remote is not None:
        params["remote"] = "true" if remote else "false"
    try:
        resp = requests.get(
            _freehire_url(), params=params,
            headers={"User-Agent": _UA, "Accept": "application/json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("freehire fetch failed (skipping): %s", e)
        return []
    jobs = data.get("jobs") or data.get("results") or data.get("data") or []
    rows = []
    for j in jobs[:limit]:
        if not isinstance(j, dict):
            continue
        title = (j.get("title") or j.get("role") or "").strip()
        if not title:
            continue
        rows.append({
            "li_job_id": str(j.get("id") or j.get("slug") or ""),
            "title": title,
            "company": (j.get("company") or j.get("company_name") or "").strip(),
            "location": (j.get("location") or j.get("region") or "").strip(),
            "url": (j.get("url") or j.get("apply_url") or "").strip(),
            "posted": (j.get("posted_at") or j.get("created_at") or "").strip(),
            "source": "freehire",
        })
    return rows


_NORM = re.compile(r"[^a-z0-9]+")


def _dedup_key(row) -> str:
    t = _NORM.sub(" ", (row.get("title") or "").lower()).strip()
    c = _NORM.sub(" ", (row.get("company") or "").lower()).strip()
    return f"{t}|{c}"


def merge_dedup(*sources) -> list:
    """Merge rows from multiple sources, dedup by normalized title+company.

    First occurrence wins (LinkedIn passed first = preferred). A row with no
    title+company key (both empty) is kept as-is (can't dedup it safely).
    """
    seen = set()
    out = []
    for rows in sources:
        for row in rows or []:
            key = _dedup_key(row)
            if key != "|" and key in seen:
                continue
            if key != "|":
                seen.add(key)
            out.append(row)
    return out


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8")

    assert _urn_to_id("urn:li:jobPosting:987654") == "987654"
    assert _urn_to_id("") == ""

    # Parse a representative jobs-guest fixture (no network).
    FIXTURE = """
    <ul>
      <li>
        <div class="base-card" data-entity-urn="urn:li:jobPosting:111">
          <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/111/?trk=x">link</a>
          <h3 class="base-search-card__title">Backend Engineer</h3>
          <h4 class="base-search-card__subtitle"><a>Acme Corp</a></h4>
          <span class="job-search-card__location">Bengaluru, Karnataka, India</span>
          <time datetime="2026-07-01">1 week ago</time>
        </div>
      </li>
      <li>
        <div class="base-card" data-entity-urn="urn:li:jobPosting:222">
          <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/222/">link</a>
          <h3 class="base-search-card__title">Data Scientist</h3>
          <h4 class="base-search-card__subtitle"><a>Zeta</a></h4>
          <span class="job-search-card__location">Remote</span>
        </div>
      </li>
      <li><div class="base-card"><h3 class="base-search-card__title"></h3></div></li>
    </ul>
    """
    rows = parse_linkedin_cards(FIXTURE)
    assert len(rows) == 2, rows  # empty-title card dropped
    assert rows[0]["li_job_id"] == "111", rows[0]
    assert rows[0]["title"] == "Backend Engineer"
    assert rows[0]["company"] == "Acme Corp"
    assert rows[0]["location"].startswith("Bengaluru")
    assert rows[0]["url"] == "https://www.linkedin.com/jobs/view/111/", rows[0]
    assert rows[0]["posted"] == "2026-07-01"
    assert rows[0]["source"] == "linkedin"

    # merge_dedup: same title+company from two sources collapses; first wins.
    a = [{"title": "Backend Engineer", "company": "Acme", "source": "linkedin"}]
    b = [
        {"title": "backend  engineer", "company": "ACME", "source": "freehire"},
        {"title": "ML Engineer", "company": "Beta", "source": "freehire"},
    ]
    merged = merge_dedup(a, b)
    assert len(merged) == 2, merged
    assert merged[0]["source"] == "linkedin"  # first wins
    assert merged[1]["title"] == "ML Engineer"

    # freehire param mapping tolerant of shape (no network): just the URL builder
    os.environ["FREEHIRE_API_URL"] = "https://example.test/"
    assert _freehire_url() == "https://example.test/api/v1/jobs/search"

    print("job_sources self-check OK")
