"""
Create linkedin_session.json from your existing Chrome login, no password needed.

Steps to get the cookie (in your normal Chrome, logged into LinkedIn):
  1. Open https://www.linkedin.com and press F12 (DevTools)
  2. Application tab -> Storage -> Cookies -> https://www.linkedin.com
  3. Find the cookie named li_at, double-click its Value, copy it (long string)
  4. Run: venv\\Scripts\\python create_session_from_cookie.py
  5. Paste the value when prompted (input is hidden)

The session file is gitignored. Never share it or the cookie.
"""

import asyncio
import getpass
import sys
from pathlib import Path

# The vendored repo folder shadows the installed package; point at the real one
sys.path.insert(0, str(Path(__file__).parent / "linkedin_scraper"))

from linkedin_scraper import BrowserManager, login_with_cookie, is_logged_in


async def main():
    cookie = getpass.getpass("Paste li_at cookie value (hidden): ").strip().strip('"')
    if len(cookie) < 50:
        print("That does not look like a li_at value (too short). Copy the full Value field.")
        return

    async with BrowserManager(headless=True) as browser:
        await login_with_cookie(browser.page, cookie)
        if not await is_logged_in(browser.page):
            print("Login check failed. Cookie may be expired; grab a fresh li_at and retry.")
            return
        await browser.save_session("linkedin_session.json")
        print("Saved linkedin_session.json. LinkedIn page in the app should now show 'Session ready'.")


if __name__ == "__main__":
    asyncio.run(main())
