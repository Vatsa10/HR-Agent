"""
Multi-agent orchestration with LangGraph.

Four specialized agents, each with its own unique tool:

- ParserAgent    -> tool: PDF extraction (PyMuPDF + section LLM parsing)
- GitHubAgent    -> tool: GitHub REST API enrichment
- JDAgent        -> tool: URL fetcher + JD/resume matching
- EvaluatorAgent -> tool: strict rubric-scored resume evaluation

The graph:  parse -> github -> (jd if provided) -> evaluate -> END
GitHub and JD steps are skipped gracefully when their inputs are absent.
"""

import logging
from typing import Optional, TypedDict

from langgraph.graph import StateGraph, END

from models import JSONResume, EvaluationData
from jd_matcher import JDMatchResult, match_resume_to_jd

logger = logging.getLogger(__name__)


class PipelineState(TypedDict, total=False):
    pdf_path: str
    jd_url: Optional[str]
    jd_text: Optional[str]
    resume_data: Optional[JSONResume]
    resume_text: str
    github_data: dict
    jd_match: Optional[JDMatchResult]
    evaluation: Optional[EvaluationData]
    errors: list[str]


def _append_error(state: PipelineState, msg: str):
    state.setdefault("errors", []).append(msg)
    logger.warning(msg)


# --- Agent nodes -------------------------------------------------------------


def parser_agent(state: PipelineState) -> PipelineState:
    """ParserAgent — unique tool: PDF-to-JSONResume extraction.

    Stateful: results cached by PDF content hash, so re-analyzing the same
    resume skips all LLM extraction calls.
    """
    import hashlib
    import json
    from pathlib import Path

    from pdf import PDFHandler
    from transform import convert_json_resume_to_text

    pdf_bytes = Path(state["pdf_path"]).read_bytes()
    digest = hashlib.sha256(pdf_bytes).hexdigest()[:16]
    cache_file = Path("cache") / f"resume_{digest}.json"

    resume_data = None
    if cache_file.exists():
        try:
            resume_data = JSONResume(
                **json.loads(cache_file.read_text(encoding="utf-8"))
            )
            logger.info(f"🤖 ParserAgent: cache hit ({cache_file.name})")
        except Exception:
            resume_data = None

    if resume_data is None:
        logger.info("🤖 ParserAgent: extracting resume from PDF")
        resume_data = PDFHandler().extract_json_from_pdf(state["pdf_path"])
        if resume_data is None:
            raise ValueError("Failed to extract resume data from PDF")
        cache_file.parent.mkdir(exist_ok=True)
        cache_file.write_text(
            json.dumps(resume_data.model_dump(), ensure_ascii=False), encoding="utf-8"
        )

    state["resume_data"] = resume_data
    state["resume_text"] = convert_json_resume_to_text(resume_data)
    return state


def github_agent(state: PipelineState) -> PipelineState:
    """GitHubAgent — unique tool: GitHub REST API profile/repo enrichment."""
    from github import fetch_and_display_github_info
    from transform import convert_github_data_to_text

    resume = state.get("resume_data")
    profiles = (resume.basics.profiles or []) if resume and resume.basics else []
    gh = next(
        (p for p in profiles if p.network and p.network.lower() == "github"), None
    )
    if not gh:
        logger.info("🤖 GitHubAgent: no GitHub profile found, skipping")
        state["github_data"] = {}
        return state

    logger.info(f"🤖 GitHubAgent: enriching from {gh.url}")
    try:
        data = fetch_and_display_github_info(gh.url) or {}
        state["github_data"] = data
        if data:
            state["resume_text"] += convert_github_data_to_text(data)
    except Exception as e:
        _append_error(state, f"GitHubAgent failed: {e}")
        state["github_data"] = {}
    return state


def jd_agent(state: PipelineState) -> PipelineState:
    """JDAgent — unique tool: URL fetch + JD/resume fit scoring."""
    logger.info("🤖 JDAgent: matching resume against job description")
    try:
        if not state.get("jd_text") and state.get("jd_url"):
            from jd_matcher import fetch_jd_from_url

            jd_url = state["jd_url"]
            jd_text = None
            if "linkedin.com/jobs" in jd_url:
                try:
                    import linkedin_importer

                    if linkedin_importer.has_session():
                        jd_text = linkedin_importer.import_job(jd_url)
                except Exception as e:
                    logger.warning(f"LinkedIn JD scrape failed, falling back: {e}")
            state["jd_text"] = jd_text or fetch_jd_from_url(jd_url)
        state["jd_match"] = match_resume_to_jd(
            resume_text=state["resume_text"],
            jd_text=state.get("jd_text"),
        )
    except Exception as e:
        _append_error(state, f"JDAgent failed: {e}")
        state["jd_match"] = None
    return state


def evaluator_agent(state: PipelineState) -> PipelineState:
    """EvaluatorAgent — unique tool: rubric-based scoring engine."""
    from evaluator import ResumeEvaluator
    from prompt import DEFAULT_MODEL, MODEL_PARAMETERS

    logger.info("🤖 EvaluatorAgent: scoring resume")
    evaluator = ResumeEvaluator(
        model_name=DEFAULT_MODEL, model_params=MODEL_PARAMETERS.get(DEFAULT_MODEL)
    )
    state["evaluation"] = evaluator.evaluate_resume(state["resume_text"])
    return state


# --- Graph -------------------------------------------------------------------


def _has_jd(state: PipelineState) -> str:
    return "jd" if (state.get("jd_url") or state.get("jd_text")) else "evaluate"


def build_graph():
    g = StateGraph(PipelineState)
    g.add_node("parse", parser_agent)
    g.add_node("github", github_agent)
    g.add_node("jd", jd_agent)
    g.add_node("evaluate", evaluator_agent)

    g.set_entry_point("parse")
    g.add_edge("parse", "github")
    g.add_conditional_edges("github", _has_jd, {"jd": "jd", "evaluate": "evaluate"})
    g.add_edge("jd", "evaluate")
    g.add_edge("evaluate", END)
    return g.compile()


def run_pipeline(
    pdf_path: str, jd_url: Optional[str] = None, jd_text: Optional[str] = None
) -> PipelineState:
    """Run the full multi-agent pipeline for one resume."""
    graph = build_graph()
    return graph.invoke(
        {"pdf_path": pdf_path, "jd_url": jd_url, "jd_text": jd_text, "errors": []}
    )


if __name__ == "__main__":
    # smoke check: graph wires up and routing works
    graph = build_graph()
    assert _has_jd({"jd_url": "http://x"}) == "jd"
    assert _has_jd({}) == "evaluate"
    print("agents graph self-check OK")
