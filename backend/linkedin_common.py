"""Shared LinkedIn scraper plumbing: import guard + rate-limit patch.

The bundled linkedin_scraper flags a page as rate-limited whenever the body
text contains phrases like "rate limit" or "try again later". LinkedIn's own
chrome (footers, help links, cookie notices) contains those strings, so real
profile pages get false-positived and every scrape aborts.

patch_rate_limit() replaces the over-eager detector with one that trusts only
the genuine signals: a checkpoint/authwall URL, or a CAPTCHA iframe. Import
this module before any scraping; it patches on import.
"""

import os
import sys

_PKG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "linkedin_scraper")


def ensure_scraper_importable():
    """The outer <repo>/linkedin_scraper folder (no __init__.py) shadows the
    real package as a namespace package when running from repo root. Pin the
    inner project dir so imports resolve to the installed package."""
    mod = sys.modules.get("linkedin_scraper")
    if mod is not None and getattr(mod, "__file__", None) is None:
        del sys.modules["linkedin_scraper"]
        mod = None
    if mod is None and os.path.isdir(os.path.join(_PKG_DIR, "linkedin_scraper")):
        if _PKG_DIR not in sys.path:
            sys.path.insert(0, _PKG_DIR)


_PATCHED = False


def patch_rate_limit():
    """Replace detect_rate_limit with a version that only trusts URL + CAPTCHA
    signals, dropping the body-text phrase scan that false-positives."""
    global _PATCHED
    if _PATCHED:
        return
    ensure_scraper_importable()

    from linkedin_scraper.core import utils as _utils
    from linkedin_scraper.core.exceptions import RateLimitError

    async def detect_rate_limit(page):
        # Genuine signal 1: LinkedIn bounced us to a security checkpoint/authwall.
        url = page.url
        if "linkedin.com/checkpoint" in url or "authwall" in url:
            raise RateLimitError(
                "LinkedIn security checkpoint detected. Verify your identity or wait.",
                suggested_wait_time=3600,
            )
        # Genuine signal 2: a CAPTCHA challenge iframe is present.
        try:
            captcha = await page.locator(
                'iframe[title*="captcha" i], iframe[src*="captcha" i]'
            ).count()
            if captcha > 0:
                raise RateLimitError(
                    "CAPTCHA challenge detected. Manual intervention required.",
                    suggested_wait_time=3600,
                )
        except RateLimitError:
            raise
        except Exception:
            pass
        # Intentionally NO body-text phrase scan: it false-positives on
        # LinkedIn's own UI copy and blocked every real page.

    # Patch both the source module and the base scraper's imported reference.
    _utils.detect_rate_limit = detect_rate_limit
    try:
        from linkedin_scraper.scrapers import base as _base

        _base.detect_rate_limit = detect_rate_limit
    except Exception:
        pass

    _PATCHED = True


def session_path() -> str:
    return os.environ.get("LINKEDIN_SESSION_PATH", "linkedin_session.json")


def _materialize_from_env() -> None:
    """On hosts with secret-file support (env vars only, e.g. Hugging Face
    Spaces), the whole session JSON is provided in LINKEDIN_SESSION_JSON. Write
    it to session_path() once so the scraper can read it like a normal file."""
    raw = os.environ.get("LINKEDIN_SESSION_JSON")
    if not raw:
        return
    p = session_path()
    if os.path.exists(p):
        return
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write(raw)
    except OSError:
        # Configured path not writable (e.g. read-only mount): use a temp file.
        import tempfile

        alt = os.path.join(tempfile.gettempdir(), "linkedin_session.json")
        with open(alt, "w", encoding="utf-8") as f:
            f.write(raw)
        os.environ["LINKEDIN_SESSION_PATH"] = alt


def has_session() -> bool:
    _materialize_from_env()
    return os.path.exists(session_path())
