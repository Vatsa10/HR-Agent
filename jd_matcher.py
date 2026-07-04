"""
Job Description matching: fetch a JD from a URL (or raw text) and score a
resume against it using the configured LLM provider.
"""

import json
import logging
import re
from html.parser import HTMLParser
from typing import Optional

import requests
from pydantic import BaseModel, Field

from llm_utils import initialize_llm_provider, extract_json_from_response
from prompt import DEFAULT_MODEL, MODEL_PARAMETERS

logger = logging.getLogger(__name__)


class JDMatchResult(BaseModel):
    """Result of matching a resume against a job description."""

    fit_score: float = Field(ge=0, le=100, description="Overall fit score 0-100")
    matching_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(
        default_factory=list, description="Missing MUST-HAVE requirements only"
    )
    bonus_matched: list[str] = Field(
        default_factory=list, description="Nice-to-have/bonus JD items the candidate has"
    )
    experience_match: str = Field(description="How experience aligns with the JD")
    verdict: str = Field(description="One of: strong_fit, moderate_fit, weak_fit")
    summary: str = Field(description="2-3 sentence recruiter-facing summary")


class _TextExtractor(HTMLParser):
    """Extract visible text from HTML, skipping script/style."""

    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0 and data.strip():
            self.parts.append(data.strip())


def fetch_jd_from_url(url: str, timeout: int = 15) -> str:
    """Fetch a job posting URL and return its visible text content."""
    resp = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (HR-Agent JD fetcher)"},
    )
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type and not resp.text.lstrip().startswith("<"):
        return resp.text[:20000]
    parser = _TextExtractor()
    parser.feed(resp.text)
    text = "\n".join(parser.parts)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # ponytail: 20k char cap keeps prompts sane; chunking if JDs ever exceed it
    return text[:20000]


JD_MATCH_PROMPT = """You are an expert technical recruiter. Compare the candidate's resume against the job description and produce a rigorous, evidence-based fit assessment.

First, understand the JD's own priorities. Classify every requirement:
- MUST-HAVE: listed as required, essential, or clearly core to the role.
- NICE-TO-HAVE: phrased as "bonus points", "nice to have", "preferred", "a plus", "good to know", or similar optional language.

Scoring rules:
- fit_score is driven by MUST-HAVE coverage and relevant experience depth (up to ~90 points).
- Matched NICE-TO-HAVE items add a small boost (up to ~10 points total).
- A missing NICE-TO-HAVE must NEVER reduce the score or appear in missing_skills.
- missing_skills lists ONLY unmet MUST-HAVE requirements.

JOB DESCRIPTION:
{jd_text}

CANDIDATE RESUME:
{resume_text}

Respond ONLY with valid JSON:
{{
  "fit_score": <0-100 number>,
  "matching_skills": ["matched must-have skill", ...],
  "missing_skills": ["unmet must-have requirement", ...],
  "bonus_matched": ["matched nice-to-have/bonus item", ...],
  "experience_match": "<how the candidate's experience aligns>",
  "verdict": "<strong_fit | moderate_fit | weak_fit>",
  "summary": "<2-3 sentence recruiter-facing summary>"
}}"""


def match_resume_to_jd(
    resume_text: str, jd_text: Optional[str] = None, jd_url: Optional[str] = None
) -> JDMatchResult:
    """Score a resume against a JD given as raw text or a URL."""
    if not jd_text and jd_url:
        jd_text = fetch_jd_from_url(jd_url)
    if not jd_text:
        raise ValueError("Provide jd_text or jd_url")

    provider = initialize_llm_provider(DEFAULT_MODEL)
    params = MODEL_PARAMETERS.get(DEFAULT_MODEL, {"temperature": 0.1, "top_p": 0.9})
    response = provider.chat(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": "You are a precise technical recruiter."},
            {
                "role": "user",
                "content": JD_MATCH_PROMPT.format(
                    jd_text=jd_text, resume_text=resume_text
                ),
            },
        ],
        options={"stream": False, **params},
        format=JDMatchResult.model_json_schema(),
    )
    raw = extract_json_from_response(response["message"]["content"])
    return JDMatchResult(**json.loads(raw))


if __name__ == "__main__":
    # smoke check: HTML text extraction
    parser = _TextExtractor()
    parser.feed("<html><head><style>x{}</style></head><body><h1>Engineer</h1><script>bad()</script><p>Python required</p></body></html>")
    text = "\n".join(parser.parts)
    assert "Engineer" in text and "Python required" in text
    assert "bad()" not in text and "x{}" not in text
    print("jd_matcher self-check OK")
