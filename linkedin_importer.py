"""LinkedIn import helpers: profile -> JSONResume dict, job posting -> JD text.

Scraping runs via the bundled linkedin_scraper package (Playwright, async).
import_profile/import_job use asyncio.run and are safe to call from worker
threads (never from a running event loop).
"""

import asyncio
import os
import sys

# The repo checkout ships the scraper project at <repo>/linkedin_scraper, whose
# outer folder (no __init__.py) shadows the real package as a namespace package
# when the server runs from the repo root. Pin the inner project dir first.
_PKG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "linkedin_scraper")


def _ensure_scraper_importable():
    mod = sys.modules.get("linkedin_scraper")
    if mod is not None and getattr(mod, "__file__", None) is None:
        del sys.modules["linkedin_scraper"]  # bogus namespace package
        mod = None
    if mod is None and os.path.isdir(os.path.join(_PKG_DIR, "linkedin_scraper")):
        if _PKG_DIR not in sys.path:
            sys.path.insert(0, _PKG_DIR)


def session_path() -> str:
    return os.environ.get("LINKEDIN_SESSION_PATH", "linkedin_session.json")


def has_session() -> bool:
    return os.path.exists(session_path())


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


async def _scrape_person(profile_url: str):
    _ensure_scraper_importable()
    from linkedin_scraper import BrowserManager, PersonScraper

    async with BrowserManager(headless=True) as browser:
        await browser.load_session(session_path())
        scraper = PersonScraper(browser.page)
        return await scraper.scrape(profile_url)


async def _scrape_job(job_url: str):
    _ensure_scraper_importable()
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
