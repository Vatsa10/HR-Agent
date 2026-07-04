"""LinkedIn data access via the vendored linkedin-mcp-server extractor.

The stickerdaniel/linkedin-mcp-server extractor navigates LinkedIn's dedicated
detail pages (/details/experience/ etc.) and is actively maintained against
LinkedIn's DOM churn, so it returns full profile sections, job search, and
people search where a hand-rolled card scraper does not.

We drive its LinkedInExtractor directly with a Patchright context seeded from
our existing linkedin_session.json cookie (no interactive --login needed).

All public functions are synchronous and safe to call from worker threads
(each wraps asyncio.run). ponytail: a fresh browser context per call adds
~2-3s cold-start; if per-job-detail loops need it, host one warm browser on a
dedicated event-loop thread.
"""

import asyncio
import json
import os

# linkedin_mcp_server is installed from PyPI (mcp-server-linkedin), see
# requirements.txt. Do not vendor its source into this repo.
from linkedin_common import has_session, session_path


def _require_session():
    if not has_session():
        raise RuntimeError(
            "LinkedIn session not found. Create linkedin_session.json first "
            "(create_session_from_cookie.py)."
        )


async def _with_extractor(fn):
    """Launch a cookie-seeded Patchright context, run fn(extractor), clean up."""
    from patchright.async_api import async_playwright
    from linkedin_mcp_server.scraping.extractor import LinkedInExtractor

    state = json.loads(open(session_path(), encoding="utf-8").read())
    profile_dir = os.path.join(
        os.environ.get("TEMP", "/tmp"), "hr_agent_li_profile"
    )
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=profile_dir, headless=True
        )
        try:
            await ctx.add_cookies(state.get("cookies", []))
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            return await fn(LinkedInExtractor(page))
        finally:
            await ctx.close()


def _run(fn):
    _require_session()
    return asyncio.run(_with_extractor(fn))


def _username_from_url(url: str) -> str:
    return url.rstrip("/").split("/in/")[-1].split("/")[0].split("?")[0]


# --- Public API -------------------------------------------------------------


def profile_sections(profile_url_or_username: str, sections=None) -> dict:
    """Return {url, sections: {main_profile, experience, education, skills, ...}}."""
    username = (
        _username_from_url(profile_url_or_username)
        if "/in/" in profile_url_or_username
        else profile_url_or_username
    )
    want = set(sections or {"experience", "education", "skills", "projects"})
    return _run(lambda ext: ext.scrape_person(username, want))


def search_jobs(keywords: str, location: str = None, limit: int = 25) -> dict:
    """Search LinkedIn jobs. Returns {jobs: [...]} with title/company/location/url."""
    return _run(lambda ext: ext.search_jobs(keywords=keywords, location=location))


def search_people(keywords: str, location: str = None, current_company: str = None) -> dict:
    """Search LinkedIn people (recruiters etc.). Returns {people: [...]}."""
    return _run(
        lambda ext: ext.search_people(
            keywords=keywords, location=location, current_company=current_company
        )
    )


def company_employees(company_name: str, keywords: str = None) -> dict:
    """List employees at a company (optionally keyword-filtered, e.g. 'recruiter')."""
    return _run(lambda ext: ext.get_company_employees(company_name, keywords=keywords))


def job_details(job_id: str) -> dict:
    """Full details for a single job posting by id."""
    return _run(lambda ext: ext.scrape_job(job_id))


if __name__ == "__main__":
    # Live smoke check (needs a valid session). Prints section sizes only.
    import sys as _sys

    _sys.stdout.reconfigure(encoding="utf-8")
    if not has_session():
        print("no session; skipping live check")
    else:
        r = profile_sections("vatsa-joshi", {"experience", "education"})
        secs = r.get("sections", {})
        print("sections:", {k: len(v) for k, v in secs.items()})
        assert secs.get("experience"), "experience section empty"
        print("linkedin_service live check OK")
