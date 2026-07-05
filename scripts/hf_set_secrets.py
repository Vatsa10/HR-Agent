"""Push .env values (and the LinkedIn session) as Hugging Face Space secrets.

Usage:
    # token from env (recommended):
    set HF_TOKEN=hf_xxx                       # PowerShell: $env:HF_TOKEN="hf_xxx"
    venv\\Scripts\\python scripts\\hf_set_secrets.py

    # or pass the space id explicitly:
    venv\\Scripts\\python scripts\\hf_set_secrets.py Vatsajoshi/do-appy-backend

Reads .env, uploads each key as a Space secret (skipping placeholders and keys
that are baked into the Dockerfile), then adds LINKEDIN_SESSION_JSON from
linkedin_session.json. Get a write-scoped token at
https://huggingface.co/settings/tokens
"""

import os
import sys
from getpass import getpass
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SPACE = "Vatsajoshi/do-appy-backend"

# Baked into the Dockerfile already, so no need to push (and PATH would be wrong).
SKIP_KEYS = {"LINKEDIN_SESSION_PATH", "COOKIE_SECURE", "COOKIE_SAMESITE",
             "PORT", "HOME", "TEMP", "HF_TOKEN"}


def _looks_placeholder(v: str) -> bool:
    v = (v or "").strip()
    return (not v) or ("your_" in v) or v.lower() in {"changeme", "xxx"}


def main():
    space = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SPACE
    try:
        from huggingface_hub import HfApi
    except ImportError:
        sys.exit("huggingface_hub not installed. Run: pip install huggingface_hub")

    token = os.environ.get("HF_TOKEN") or getpass("HF write token (hidden): ").strip()
    if not token:
        sys.exit("No HF token provided.")

    api = HfApi(token=token)

    env = dotenv_values(ROOT / ".env")
    pushed = []
    for key, val in env.items():
        if key in SKIP_KEYS or _looks_placeholder(val):
            continue
        api.add_space_secret(repo_id=space, key=key, value=val)
        pushed.append(key)

    # LinkedIn session: whole JSON as one secret.
    sess = ROOT / (env.get("LINKEDIN_SESSION_PATH") or "linkedin_session.json")
    if sess.exists():
        api.add_space_secret(
            repo_id=space, key="LINKEDIN_SESSION_JSON",
            value=sess.read_text(encoding="utf-8"),
        )
        pushed.append("LINKEDIN_SESSION_JSON")
    else:
        print(f"(no {sess.name} found; skipping LINKEDIN_SESSION_JSON)")

    print(f"Set {len(pushed)} secrets on {space}: {', '.join(pushed)}")
    print("The Space will restart and pick them up.")


if __name__ == "__main__":
    main()
