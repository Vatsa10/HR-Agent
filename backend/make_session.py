"""Build linkedin_session.json from a li_at cookie. No browser, no deps.

Usage:
    cd backend && python make_session.py
    (paste the li_at value when prompted — it won't echo)

The file is Playwright storage_state: linkedin_service loads it as the browser
context's cookies. li_at is the only cookie that matters; the rest regenerate.
"""

import json
from getpass import getpass
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "linkedin_session.json"


def main():
    li_at = getpass("Paste li_at cookie value (hidden): ").strip().strip('"')
    if not li_at or not li_at.startswith("AQ"):
        raise SystemExit("That doesn't look like a li_at value (should start with 'AQ').")
    state = {
        "cookies": [
            {
                "name": "li_at",
                "value": li_at,
                "domain": ".linkedin.com",
                "path": "/",
                "expires": -1,
                "httpOnly": True,
                "secure": True,
                "sameSite": "None",
            }
        ],
        "origins": [],
    }
    OUT.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"Wrote {OUT} (li_at only). Test it via the LinkedIn Optimizer page.")


if __name__ == "__main__":
    main()
