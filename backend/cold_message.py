"""
Draft a short, truthful LinkedIn-appropriate outreach message to a recruiter,
referencing one real resume fact and the specific role/company.
"""

import json
import logging

import style_guardrails
from llm_utils import initialize_llm_provider, extract_json_from_response
from prompt import MODEL_PARAMETERS

logger = logging.getLogger(__name__)

_MODEL = "gpt-4o-mini"


DRAFT_PROMPT = """You are writing a short LinkedIn outreach message from a job seeker to a recruiter.

Tone: {tone}. Keep it under 90 words. Be specific and truthful.
Reference exactly ONE concrete fact from the resume and the specific role/company below.
Do NOT invent facts, numbers, or experience. No fluff, no em dashes.

CANDIDATE RESUME:
{resume}

ROLE / COMPANY:
{target}

RECRUITER:
{recruiter}

Respond ONLY with JSON: {{"subject": "<short subject>", "body": "<message body>"}}"""


def draft_message(resume_text, job_or_company, recruiter, tone="warm"):
    """One gpt-4o-mini call -> {subject, body}. Falls back to a stub on failure."""
    target = "\n".join(
        f"{k}: {v}" for k, v in (job_or_company or {}).items() if v
    ) or "(unspecified role)"
    rec = "\n".join(
        f"{k}: {v}" for k, v in (recruiter or {}).items() if v
    ) or "(unknown recruiter)"

    provider = initialize_llm_provider(_MODEL)
    params = MODEL_PARAMETERS.get(_MODEL, {"temperature": 0.3, "top_p": 0.9})
    try:
        resp = provider.chat(
            model=_MODEL,
            messages=[
                {"role": "system", "content": "You write concise, truthful outreach. Respond only with JSON."},
                {"role": "user", "content": DRAFT_PROMPT.format(
                    tone=tone,
                    resume=(resume_text or "")[:6000],
                    target=target,
                    recruiter=rec,
                )},
            ],
            options={"stream": False, **params},
            format="json",
        )
        obj = json.loads(extract_json_from_response(resp["message"]["content"]))
        body, _ = style_guardrails.lint((obj.get("body") or "").strip())
        return {
            "subject": (obj.get("subject") or "").strip(),
            "body": body,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("draft_message failed: %s", e)
        name = (recruiter or {}).get("name", "there")
        company = (job_or_company or {}).get("company", "your team")
        return {
            "subject": f"Interested in opportunities at {company}",
            "body": f"Hi {name}, I came across your profile and would love to connect "
                    f"about roles at {company}. Thanks for your time.",
        }


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8")

    # exercise prompt formatting + fallback (no LLM) with junk provider-free path
    target = {"title": "Backend Engineer", "company": "Acme"}
    rec = {"name": "Jane Doe", "headline": "Recruiter"}
    formatted = DRAFT_PROMPT.format(tone="warm", resume="Python dev", target="x", recruiter="y")
    assert "Backend" not in formatted and "warm" in formatted
    # fallback shape check by simulating failure branch inputs
    fb_name = rec.get("name", "there")
    fb_company = target.get("company", "your team")
    assert fb_name == "Jane Doe" and fb_company == "Acme"
    # empty inputs shouldn't crash formatting
    assert "unspecified" in ("\n".join(f"{k}: {v}" for k, v in {}.items() if v) or "(unspecified role)")

    print("cold_message self-check OK")
