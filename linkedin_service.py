"""LinkedIn data access via the vendored linkedin-mcp-server extractor.

The extractor navigates LinkedIn's dedicated detail pages and is maintained
against LinkedIn's DOM churn, returning full profile/job/people data.

PERFORMANCE: a warm browser. One persistent Patchright context lives on a
dedicated background event-loop thread and is reused across every call, so we
pay the ~2-4s Chromium cold start once instead of per request. A small pool of
pages allows a couple of scrapes to run in parallel. If the warm browser fails
to boot (e.g. no session), calls fall back to a per-call cold context.

All public functions are synchronous and safe to call from FastAPI worker
threads: they submit a coroutine onto the warm loop and block for the result.
"""

import asyncio
import atexit
import json
import logging
import os
import threading

from linkedin_common import has_session, session_path

logger = logging.getLogger(__name__)

_POOL_SIZE = int(os.environ.get("LI_POOL_SIZE", "3"))


def _require_session():
    if not has_session():
        raise RuntimeError(
            "LinkedIn session not found. Create linkedin_session.json first "
            "(create_session_from_cookie.py)."
        )


def _profile_dir():
    return os.path.join(os.environ.get("TEMP", "/tmp"), "hr_agent_li_profile")


class _WarmBrowser:
    """A persistent Patchright browser on its own event-loop thread."""

    def __init__(self):
        self._loop = None
        self._thread = None
        self._ready = threading.Event()
        self._boot_error = None
        self._ctx = None
        self._pw = None
        self._pages = None  # asyncio.Queue[Page]
        self._start_lock = threading.Lock()
        self._started = False

    def _ensure_started(self):
        with self._start_lock:
            if self._started:
                return
            self._thread = threading.Thread(
                target=self._thread_main, name="linkedin-browser", daemon=True
            )
            self._thread.start()
            self._ready.wait()  # boot done (success or failure)
            self._started = True
        if self._boot_error is not None:
            raise self._boot_error

    def _thread_main(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._boot())
        except Exception as e:  # noqa: BLE001
            self._boot_error = e
            logger.warning("warm browser boot failed, will use cold fallback: %s", e)
            self._ready.set()
            return
        self._ready.set()
        self._loop.run_forever()

    async def _boot(self):
        from patchright.async_api import async_playwright

        state = json.loads(open(session_path(), encoding="utf-8").read())
        self._pw = await async_playwright().start()
        self._ctx = await self._pw.chromium.launch_persistent_context(
            user_data_dir=_profile_dir(), headless=True
        )
        await self._ctx.add_cookies(state.get("cookies", []))
        self._pages = asyncio.Queue()
        pages = list(self._ctx.pages)
        while len(pages) < _POOL_SIZE:
            pages.append(await self._ctx.new_page())
        for pg in pages[:_POOL_SIZE]:
            self._pages.put_nowait(pg)
        logger.info("warm LinkedIn browser ready (%d pages)", _POOL_SIZE)

    async def _call(self, fn):
        from linkedin_mcp_server.scraping.extractor import LinkedInExtractor

        page = await self._pages.get()
        try:
            return await fn(LinkedInExtractor(page))
        finally:
            self._pages.put_nowait(page)

    def run(self, fn):
        self._ensure_started()
        fut = asyncio.run_coroutine_threadsafe(self._call(fn), self._loop)
        return fut.result()

    def shutdown(self):
        if self._loop and self._loop.is_running():
            async def _close():
                try:
                    if self._ctx:
                        await self._ctx.close()
                    if self._pw:
                        await self._pw.stop()
                except Exception:  # noqa: BLE001
                    pass
            try:
                asyncio.run_coroutine_threadsafe(_close(), self._loop).result(timeout=10)
            except Exception:  # noqa: BLE001
                pass


_warm = _WarmBrowser()
atexit.register(_warm.shutdown)


async def _cold_call(fn):
    """Fallback: fresh per-call context (used only if the warm browser fails)."""
    from patchright.async_api import async_playwright

    state = json.loads(open(session_path(), encoding="utf-8").read())
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=_profile_dir() + "_cold", headless=True
        )
        try:
            from linkedin_mcp_server.scraping.extractor import LinkedInExtractor

            await ctx.add_cookies(state.get("cookies", []))
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            return await fn(LinkedInExtractor(page))
        finally:
            await ctx.close()


def _run(fn):
    _require_session()
    try:
        return _warm.run(fn)
    except Exception as e:  # noqa: BLE001
        logger.warning("warm browser call failed, cold fallback: %s", e)
        return asyncio.run(_cold_call(fn))


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


def search_jobs(
    keywords: str,
    location: str = None,
    work_type: str = None,
    experience_level: str = None,
    job_type: str = None,
    date_posted: str = None,
    limit: int = 25,
) -> dict:
    """Search LinkedIn jobs. Returns {job_ids, references, sections}.

    Optional filters map straight onto the extractor's search_jobs tokens:
    - work_type: "on_site" | "remote" | "hybrid" (comma-separated allowed)
    - experience_level: internship|entry|associate|mid_senior|director|executive
    - job_type: full_time|part_time|contract|temporary|internship|volunteer|other
    - date_posted: past_hour|past_24_hours|past_week|past_month
    A None/empty filter is omitted so the extractor applies no constraint.
    """
    return _run(
        lambda ext: ext.search_jobs(
            keywords=keywords,
            location=location,
            work_type=work_type,
            experience_level=experience_level,
            job_type=job_type,
            date_posted=date_posted,
        )
    )


def search_people(keywords: str, location: str = None, current_company: str = None) -> dict:
    """Search LinkedIn people (recruiters etc.)."""
    return _run(
        lambda ext: ext.search_people(
            keywords=keywords, location=location, current_company=current_company
        )
    )


def company_employees(company_name: str, keywords: str = None) -> dict:
    """List employees at a company (optionally keyword-filtered)."""
    return _run(lambda ext: ext.get_company_employees(company_name, keywords=keywords))


def job_details(job_id: str) -> dict:
    """Full details for a single job posting by id."""
    return _run(lambda ext: ext.scrape_job(job_id))


if __name__ == "__main__":
    import sys as _sys
    import time as _time

    _sys.stdout.reconfigure(encoding="utf-8")
    logging.disable(logging.WARNING)
    if not has_session():
        print("no session; skipping live check")
    else:
        t0 = _time.perf_counter()
        r = profile_sections("vatsa-joshi", {"experience"})
        t1 = _time.perf_counter()
        r2 = profile_sections("vatsa-joshi", {"experience"})
        t2 = _time.perf_counter()
        print(f"first call (incl. browser boot): {t1 - t0:.1f}s")
        print(f"second call (warm): {t2 - t1:.1f}s")
        assert r.get("sections", {}).get("experience"), "experience empty"
        assert (t2 - t1) < (t1 - t0), "warm call should be faster than cold boot"
        print("linkedin_service warm-browser check OK")
