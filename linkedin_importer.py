"""LinkedIn import helpers: profile -> JSONResume dict, job posting -> JD text.

Scraping runs via the bundled linkedin_scraper package (Playwright, async).
import_profile/import_job use asyncio.run and are safe to call from worker
threads (never from a running event loop).
"""

import asyncio

from linkedin_common import (
    ensure_scraper_importable as _ensure_scraper_importable,
    has_session,
    patch_rate_limit,
    session_path,
)


def _require_session():
    if not has_session():
        raise RuntimeError(
            "LinkedIn session not found. Run linkedin_scraper/samples/create_session.py first."
        )


def _clean(v):
    if isinstance(v, str):
        v = v.strip()
    return v or None


def map_person_to_resume(person) -> dict:
    """Pure mapping: scraped Person-like object -> JSONResume-shaped dict."""
    resume: dict = {}

    name = _clean(getattr(person, "name", None)) or "Unknown"
    basics: dict = {"name": name}

    label = _clean(getattr(person, "headline", None)) or _clean(getattr(person, "job_title", None))
    if label:
        basics["label"] = label
    summary = _clean(getattr(person, "about", None))
    if summary:
        basics["summary"] = summary
    loc = _clean(getattr(person, "location", None))
    if loc:
        basics["location"] = {"city": loc}
    url = _clean(getattr(person, "linkedin_url", None))
    if url:
        basics["profiles"] = [{"network": "LinkedIn", "url": url}]
    resume["basics"] = basics

    work = []
    for exp in getattr(person, "experiences", None) or []:
        entry = {}
        for src, dst in (
            ("institution_name", "name"),
            ("position_title", "position"),
            ("from_date", "startDate"),
            ("to_date", "endDate"),
            ("location", "location"),
            ("description", "summary"),
        ):
            v = _clean(getattr(exp, src, None))
            if v:
                entry[dst] = v
        if entry:
            work.append(entry)
    if work:
        resume["work"] = work

    education = []
    for edu in getattr(person, "educations", None) or []:
        entry = {}
        for src, dst in (
            ("institution_name", "institution"),
            ("degree", "studyType"),
            ("from_date", "startDate"),
            ("to_date", "endDate"),
        ):
            v = _clean(getattr(edu, src, None))
            if v:
                entry[dst] = v
        if entry:
            education.append(entry)
    if education:
        resume["education"] = education

    skills = [s for s in (_clean(s) for s in (getattr(person, "skills", None) or [])) if s]
    if skills:
        resume["skills"] = [{"name": "Skills", "keywords": skills}]

    return resume


import re
from types import SimpleNamespace

_DEGREE_RE = re.compile(r"^·?\s*(1st|2nd|3rd|\d+(?:st|nd|rd|th))\b", re.I)


async def _card_text(page, suffix: str) -> str:
    """Inner text of a profile SDUI card by stable componentkey suffix."""
    loc = page.locator(f'[componentkey$="{suffix}"]')
    try:
        if await loc.count():
            return (await loc.first.inner_text()).strip()
    except Exception:
        pass
    return ""


async def _extract_profile_sdui(page):
    """Extract a Person-like object from LinkedIn's SDUI profile DOM.

    LinkedIn uses server-driven UI with rotating hashed class names, so we
    anchor on things that do NOT rotate: the page <title>, and profile-card
    componentkey suffixes (Topcard, About, Experience, Education). Topcard and
    About are served consistently; Experience/Education are lazy-loaded and
    only present when the logged-in session can see them, so they are
    best-effort.
    """
    # Name: the page title is "<Name> | LinkedIn" and never rotates.
    name = (await page.title()).rsplit("|", 1)[0].strip() or "Unknown"

    # Topcard: name, connection degree, headline, location, in that order.
    top = await _card_text(page, "Topcard")
    lines = [l.strip() for l in top.splitlines() if l.strip() and l.strip() != "·"]
    headline = location = None
    rest = []
    for l in lines:
        if l == name or _DEGREE_RE.match(l):
            continue
        rest.append(l)
    # rest[0] = headline, next place-looking line = location (before "Contact info")
    if rest:
        headline = rest[0]
    for l in rest[1:]:
        if l.lower().startswith("contact info"):
            break
        if "," in l and not l.lower().startswith(("message", "more", "connect")):
            location = l
            break

    about = await _card_text(page, "About")
    about = re.sub(r"^About\s*", "", about).strip() or None

    experiences = await _extract_entries(page, "Experience")
    educations = await _extract_entries(page, "Education")

    return SimpleNamespace(
        name=name,
        headline=headline,
        job_title=headline,
        about=about,
        location=location,
        linkedin_url=page.url.split("?")[0],
        experiences=experiences,
        educations=educations,
        skills=[],
    )


async def _extract_entries(page, suffix: str):
    """Best-effort list-item extraction from an Experience/Education card.

    Returns Experience/Education-shaped SimpleNamespaces. Empty when the card
    is not served (limited profile view or lazy chunk not loaded)."""
    loc = page.locator(f'[componentkey$="{suffix}"]')
    if not await loc.count():
        return []
    entries = []
    # Each entry links to /company/ or /school/ or /in/; grab bolded title + subtitle lines.
    items = loc.first.locator("li")
    try:
        count = await items.count()
    except Exception:
        count = 0
    for i in range(min(count, 15)):
        try:
            text = (await items.nth(i).inner_text()).strip()
        except Exception:
            continue
        parts = [p.strip() for p in text.splitlines() if p.strip()]
        # de-dup consecutive repeats LinkedIn renders for a11y
        dedup = []
        for p in parts:
            if not dedup or dedup[-1] != p:
                dedup.append(p)
        if len(dedup) < 2:
            continue
        if suffix == "Experience":
            entries.append(SimpleNamespace(
                position_title=dedup[0], institution_name=dedup[1] if len(dedup) > 1 else None,
                from_date=None, to_date=None, location=None,
                description=" ".join(dedup[3:])[:1000] or None,
            ))
        else:
            entries.append(SimpleNamespace(
                institution_name=dedup[0], degree=dedup[1] if len(dedup) > 1 else None,
                from_date=None, to_date=None,
            ))
    return entries


async def _scrape_person(profile_url: str):
    _ensure_scraper_importable()
    patch_rate_limit()
    from linkedin_scraper import BrowserManager

    async with BrowserManager(headless=True) as browser:
        await browser.load_session(session_path())
        page = browser.page
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
        # Patiently scroll to trigger lazy SDUI chunks (experience/education).
        for _ in range(12):
            await page.mouse.wheel(0, 1600)
            await asyncio.sleep(0.6)
        await asyncio.sleep(1.0)
        return await _extract_profile_sdui(page)


async def _scrape_job(job_url: str):
    _ensure_scraper_importable()
    patch_rate_limit()
    from linkedin_scraper import BrowserManager, JobScraper

    async with BrowserManager(headless=True) as browser:
        await browser.load_session(session_path())
        scraper = JobScraper(browser.page)
        return await scraper.scrape(job_url)


def import_profile(profile_url: str) -> dict:
    """Scrape a LinkedIn profile and return a JSONResume-shaped dict."""
    _require_session()
    person = asyncio.run(_scrape_person(profile_url))
    return map_person_to_resume(person)


def import_job(job_url: str) -> str:
    """Scrape a LinkedIn job posting and return a plain-text JD."""
    _require_session()
    job = asyncio.run(_scrape_job(job_url))
    parts = []
    title = _clean(getattr(job, "job_title", None))
    company = _clean(getattr(job, "company", None))
    if title and company:
        parts.append(f"{title} at {company}")
    elif title or company:
        parts.append(title or company)
    location = _clean(getattr(job, "location", None))
    if location:
        parts.append(f"Location: {location}")
    description = _clean(getattr(job, "job_description", None))
    if description:
        parts.append(description)
    return "\n\n".join(parts)


if __name__ == "__main__":
    # Self-check: mapping only, no browser/network.
    from types import SimpleNamespace

    from models import JSONResume

    fake = SimpleNamespace(
        name="Jane Doe",
        headline=None,
        job_title="Senior Engineer",
        about="Builds things.",
        location="Ahmedabad, India",
        linkedin_url="https://www.linkedin.com/in/janedoe/",
        experiences=[
            SimpleNamespace(
                institution_name="Acme Corp",
                position_title="Senior Engineer",
                from_date="2021",
                to_date="Present",
                location="Remote",
                description="Led platform work.",
            ),
            SimpleNamespace(
                institution_name=None,
                position_title=None,
                from_date=None,
                to_date=None,
                location=None,
                description=None,
            ),
        ],
        educations=[
            SimpleNamespace(
                institution_name="IIT",
                degree="B.Tech",
                from_date="2015",
                to_date="2019",
            )
        ],
        skills=["Python", "  ", "FastAPI"],
    )

    result = map_person_to_resume(fake)
    parsed = JSONResume(**result)
    assert parsed.basics.name == "Jane Doe"
    assert parsed.basics.label == "Senior Engineer"
    assert parsed.basics.location.city == "Ahmedabad, India"
    assert parsed.basics.profiles[0].url.startswith("https://www.linkedin.com/in/")
    assert len(result["work"]) == 1 and result["work"][0]["name"] == "Acme Corp"
    assert result["education"][0]["institution"] == "IIT"
    assert result["skills"] == [{"name": "Skills", "keywords": ["Python", "FastAPI"]}]
    print("linkedin_importer self-check OK")
