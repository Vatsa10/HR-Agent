"""LinkedIn import: profile -> JSONResume dict, job posting -> JD text.

Backed by linkedin_service (the vendored linkedin-mcp-server extractor), which
returns full profile section text. We structure that text into a JSONResume
with one LLM call, reusing the same provider as the rest of the app.
"""

import json
import logging

import linkedin_service
from linkedin_common import has_session, session_path  # noqa: F401 (re-export)
from llm_utils import initialize_llm_provider, extract_json_from_response
from prompt import DEFAULT_MODEL, MODEL_PARAMETERS
from models import JSONResume

logger = logging.getLogger(__name__)


_STRUCTURE_PROMPT = """Convert the following LinkedIn profile sections into a JSON Resume object.

Rules:
- Use ONLY facts present in the text. Never invent employers, dates, or metrics.
- basics: name, label (headline), summary (from About/main), location.city.
- work: one entry per experience. In the text each role is formatted as: a position-title line, then a company line often like "Company Name · Full-time" (take the company name, drop the " · type" suffix), then a date/duration line, then an optional location line, then bullet lines. Map: position (title line), name (company, suffix stripped), location, startDate, endDate ("Present" if ongoing), highlights (the bullet lines verbatim). Never leave name null when a company line exists.
- education: institution, studyType/area, startDate, endDate.
- skills: group the listed skills under one entry named "Skills" with a keywords list.
- Omit sections with no data.

PROFILE SECTIONS:
__SECTIONS__

Respond ONLY with a valid JSON Resume object."""


def _structure_sections(sections: dict) -> dict:
    """LLM-structure raw section text blobs into a JSONResume-shaped dict."""
    ordered = ["main_profile", "experience", "education", "skills", "projects"]
    blocks = []
    for key in ordered:
        if sections.get(key):
            blocks.append(f"## {key}\n{sections[key]}")
    for key, val in sections.items():
        if key not in ordered and val:
            blocks.append(f"## {key}\n{val}")
    sections_text = "\n\n".join(blocks)

    provider = initialize_llm_provider(DEFAULT_MODEL)
    params = MODEL_PARAMETERS.get(DEFAULT_MODEL, {"temperature": 0.1, "top_p": 0.9})
    response = provider.chat(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": "You convert LinkedIn text into JSON Resume."},
            {"role": "user", "content": _STRUCTURE_PROMPT.replace("__SECTIONS__", sections_text)},
        ],
        options={"stream": False, **params},
        # Enable JSON mode without dumping the huge JSONResume schema into the
        # prompt (that made gpt-4o-mini return {}); the prompt specifies shape.
        format="json_resume",
    )
    raw = extract_json_from_response(response["message"]["content"])
    data = json.loads(raw)
    # gpt-4o-mini sometimes emits a single object where a list is expected.
    for key in ("work", "education", "skills", "projects", "awards"):
        if isinstance(data.get(key), dict):
            data[key] = [data[key]]
    JSONResume(**data)  # validate; raises on bad shape
    return data


def import_profile(profile_url: str) -> dict:
    """Scrape a LinkedIn profile and return a JSONResume-shaped dict."""
    result = linkedin_service.profile_sections(profile_url)
    sections = result.get("sections", {})
    if not any(sections.values()):
        raise RuntimeError("LinkedIn returned no profile content (visibility or session issue)")
    data = _structure_sections(sections)
    # Ensure the LinkedIn URL is recorded as a profile.
    basics = data.setdefault("basics", {})
    profiles = basics.setdefault("profiles", [])
    url = result.get("url") or profile_url
    if not any((p or {}).get("network", "").lower() == "linkedin" for p in profiles):
        profiles.append({"network": "LinkedIn", "url": url})
    return data


def import_job(job_url_or_id: str) -> str:
    """Scrape a LinkedIn job posting and return a plain-text JD."""
    job_id = job_url_or_id.rstrip("/").split("/")[-1].split("?")[0]
    job = linkedin_service.job_details(job_id)
    if isinstance(job, dict):
        parts = []
        for key in ("title", "job_title", "company", "location", "description", "job_description"):
            v = job.get(key)
            if v:
                parts.append(str(v))
        return "\n\n".join(parts)
    return str(job)


if __name__ == "__main__":
    # Offline self-check: structuring logic with a fake section blob (no network).
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    sample = {
        "main_profile": "Jane Doe\nSenior Engineer\nRemote",
        "experience": "Experience\nSenior Engineer\nAcme Corp\n2021 - Present\nLed platform work.",
    }
    blocks = [f"## {k}\n{v}" for k, v in sample.items()]
    assert "Acme Corp" in "\n".join(blocks)
    print("linkedin_importer self-check OK (structuring offline)")
