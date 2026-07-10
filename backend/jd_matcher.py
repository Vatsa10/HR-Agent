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

import scoring
from llm_utils import initialize_llm_provider, extract_json_from_response
from prompt import DEFAULT_MODEL, MODEL_PARAMETERS

logger = logging.getLogger(__name__)


class FitDimension(BaseModel):
    """One scored dimension of candidate-job fit."""

    name: str = Field(description="One of: technical, experience, behavioral, career")
    score: float = Field(ge=0, le=100)
    note: str = Field(default="", description="One-line justification")


class RequirementCheck(BaseModel):
    """One JD requirement checked against the resume."""

    requirement: str
    kind: str = Field(description="One of: must_have, nice_to_have")
    status: str = Field(description="One of: met, partial, missing")
    evidence: str = Field(
        default="", description="Quote/paraphrase from resume; empty if missing"
    )
    suggestion: str = Field(
        default="", description="How the candidate could close the gap; empty if met"
    )


class ATSKeywords(BaseModel):
    """Keywords an ATS would scan for from the JD, in a 4-state taxonomy.

    present   -> already in the resume.
    absent    -> not in the resume (kept for backward compat = have_add + real_gap).
    have_add  -> the candidate's real experience supports it, but it's not surfaced;
                 truthfully add it.
    real_gap  -> the candidate genuinely lacks it; a real skill gap.
    """

    present: list[str] = Field(default_factory=list)
    absent: list[str] = Field(default_factory=list)
    have_add: list[str] = Field(default_factory=list)
    real_gap: list[str] = Field(default_factory=list)


class JDMatchResult(BaseModel):
    """Result of matching a resume against a job description."""

    fit_score: float = Field(ge=0, le=100, description="Overall fit score 0-100")
    dimensions: list[FitDimension] = Field(
        default_factory=list,
        description="Per-dimension fit scores (technical/experience/behavioral/career)",
    )
    band: str = Field(default="", description="shortlist | below | excluded (derived)")
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
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
    requirements: list[RequirementCheck] = Field(
        default_factory=list,
        description="Per-requirement breakdown of JD coverage",
    )
    ats_keywords: ATSKeywords = Field(
        default_factory=ATSKeywords,
        description="ATS-scannable JD keywords present/absent in the resume",
    )


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

Score four fit dimensions, each 0-100, with a one-line note:
- technical: coverage of the JD's required skills/tools/tech.
- experience: depth and relevance of experience vs the role's seniority.
- behavioral: soft skills / working-style signals the JD asks for.
- career: how well the role aligns with the candidate's trajectory.
Do NOT compute the overall yourself — an external system weights the dimensions.
Still return fit_score as your best estimate; it will be recomputed.

Scoring rules:
- A missing NICE-TO-HAVE must NEVER reduce a dimension or appear in missing_skills.
- missing_skills lists ONLY unmet MUST-HAVE requirements.

JOB DESCRIPTION:
{jd_text}

CANDIDATE RESUME:
{resume_text}

Respond ONLY with valid JSON:
{{
  "fit_score": <0-100 number>,
  "dimensions": [
    {{"name": "technical",  "score": <0-100>, "note": "<one line>"}},
    {{"name": "experience", "score": <0-100>, "note": "<one line>"}},
    {{"name": "behavioral", "score": <0-100>, "note": "<one line>"}},
    {{"name": "career",     "score": <0-100>, "note": "<one line>"}}
  ],
  "strengths": ["<top reason this candidate fits>", ...],
  "gaps": ["<top honest concern>", ...],
  "matching_skills": ["matched must-have skill", ...],
  "missing_skills": ["unmet must-have requirement", ...],
  "bonus_matched": ["matched nice-to-have/bonus item", ...],
  "experience_match": "<how the candidate's experience aligns>",
  "verdict": "<strong_fit | moderate_fit | weak_fit>",
  "summary": "<2-3 sentence recruiter-facing summary>",
  "requirements": [
    {{
      "requirement": "<the JD requirement, concise>",
      "kind": "<must_have | nice_to_have>",
      "status": "<met | partial | missing>",
      "evidence": "<short quote or paraphrase from the resume backing this up; empty string if missing>",
      "suggestion": "<concrete way the candidate could close the gap; empty string if met>"
    }}
  ],
  "ats_keywords": {{
    "present": ["<JD keyword an ATS would scan for that appears in the resume>", ...],
    "absent": ["<every JD keyword NOT literally in the resume>", ...],
    "have_add": ["<absent keyword the candidate's REAL experience truthfully supports but did not surface>", ...],
    "real_gap": ["<absent keyword the candidate genuinely lacks>", ...]
  }}
}}

Requirements list rules:
- Include EVERY distinct requirement from the JD, both must-have and nice-to-have, each classified with kind.
- status is "met" only when resume evidence clearly covers it; "partial" when adjacent/incomplete evidence exists; "missing" when there is no evidence.
- evidence must be a short quote or close paraphrase from the resume (empty string when status is "missing").
- suggestion must be a practical way to close the gap (empty string when status is "met").

ATS keyword rules:
- ats_keywords are the concrete technologies, tools, certifications, and role terms an applicant tracking system would scan the JD for.
- "present" means the exact or near-exact term appears in the resume; otherwise it goes in "absent".
- Every "absent" keyword must also appear in exactly ONE of have_add or real_gap.
  have_add = truthfully supported by the candidate's real work but not spelled out;
  real_gap = the candidate genuinely does not have it. NEVER put a keyword in
  have_add unless the resume gives honest grounds for it."""


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
    result = JDMatchResult(**json.loads(raw))

    # Recompute the overall from the dimensions in pure Python so the fit number
    # is auditable and deterministic (the LLM's fit_score is only a hint). Fall
    # back to the LLM's fit_score when it returned no dimensions.
    if result.dimensions:
        dims = [{"name": d.name, "score": d.score} for d in result.dimensions]
        result.fit_score = scoring.weighted_overall(dims)
    result.band = scoring.verdict_band(result.fit_score)
    return result


if __name__ == "__main__":
    # smoke check: HTML text extraction
    parser = _TextExtractor()
    parser.feed("<html><head><style>x{}</style></head><body><h1>Engineer</h1><script>bad()</script><p>Python required</p></body></html>")
    text = "\n".join(parser.parts)
    assert "Engineer" in text and "Python required" in text
    assert "bad()" not in text and "x{}" not in text

    # model round-trips new fields; band/overall recompute logic (pure).
    r = JDMatchResult(
        fit_score=50,
        dimensions=[
            FitDimension(name="technical", score=90),
            FitDimension(name="experience", score=80),
            FitDimension(name="behavioral", score=60),
            FitDimension(name="career", score=100),
        ],
        experience_match="x", verdict="strong_fit", summary="y",
    )
    dims = [{"name": d.name, "score": d.score} for d in r.dimensions]
    assert scoring.weighted_overall(dims) == 86
    assert scoring.verdict_band(86) == "shortlist"
    k = ATSKeywords(absent=["k8s"], have_add=["k8s"])
    assert k.have_add == ["k8s"] and k.real_gap == []
    print("jd_matcher self-check OK")
