"""
FastAPI web UI for HR-Agent.

POST /api/analyze  -> starts the multi-agent pipeline in a thread, returns job id
GET  /api/jobs/{id} -> current stage + result when finished
"""

import json
import logging
import tempfile
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from agents import build_graph

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="HR-Agent")

STATIC_DIR = Path(__file__).parent / "static"

# Stateful job store: in-memory for live polling, finished jobs persisted to
# cache/jobs/ so results survive server restarts.
# ponytail: JSON files, swap for redis/sqlite if this ever runs multi-worker
JOBS: dict = {}
JOBS_DIR = Path("cache") / "jobs"


def _persist_job(job_id: str, job: dict):
    try:
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        (JOBS_DIR / f"{job_id}.json").write_text(
            json.dumps(job, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as e:
        logger.warning(f"Failed to persist job {job_id}: {e}")


def _load_job(job_id: str):
    f = JOBS_DIR / f"{job_id}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return None

STAGE_LABELS = {
    "parse": "Parser Agent reading the resume",
    "github": "GitHub Agent scouting repositories",
    "jd": "JD Agent matching the job description",
    "evaluate": "Evaluator Agent scoring the candidate",
}


def _run_job(job_id: str, pdf_path: str, jd_url: str, jd_text: str):
    job = JOBS[job_id]
    try:
        graph = build_graph()
        state = {
            "pdf_path": pdf_path,
            "jd_url": jd_url or None,
            "jd_text": jd_text or None,
            "errors": [],
        }
        final = dict(state)
        for step in graph.stream(state):
            for node, node_state in step.items():
                job["stage"] = node
                final.update(node_state)

        evaluation = final.get("evaluation")
        jd_match = final.get("jd_match")
        resume = final.get("resume_data")

        total, max_total = 0.0, 0
        if evaluation:
            for cat in evaluation.scores.model_dump().values():
                total += min(cat["score"], cat["max"])
                max_total += cat["max"]
            total += evaluation.bonus_points.total - evaluation.deductions.total

        job["result"] = {
            "candidate": (resume.basics.name if resume and resume.basics else None)
            or Path(pdf_path).stem,
            "total_score": round(total, 1),
            "max_score": max_total,
            "evaluation": evaluation.model_dump() if evaluation else None,
            "jd_match": jd_match.model_dump() if jd_match else None,
            "errors": final.get("errors", []),
        }
        job["status"] = "done"
        _persist_job(job_id, job)
    except Exception as e:
        logger.exception("Job failed")
        job["status"] = "error"
        job["error"] = str(e)
        _persist_job(job_id, job)
    finally:
        try:
            Path(pdf_path).unlink(missing_ok=True)
        except OSError:
            pass


@app.post("/api/analyze")
async def analyze(
    resume: UploadFile = File(...),
    jd_url: str = Form(""),
    jd_text: str = Form(""),
):
    if not resume.filename or not resume.filename.lower().endswith(".pdf"):
        return JSONResponse({"error": "Upload a PDF resume"}, status_code=400)

    tmp = tempfile.NamedTemporaryFile(
        suffix=".pdf", prefix=Path(resume.filename).stem + "_", delete=False
    )
    tmp.write(await resume.read())
    tmp.close()

    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "running", "stage": "parse"}
    threading.Thread(
        target=_run_job,
        args=(job_id, tmp.name, jd_url.strip(), jd_text.strip()),
        daemon=True,
    ).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    job = JOBS.get(job_id) or _load_job(job_id)
    if not job:
        return JSONResponse({"error": "Unknown job"}, status_code=404)
    payload = {
        "status": job["status"],
        "stage": job.get("stage"),
        "stage_label": STAGE_LABELS.get(job.get("stage"), ""),
    }
    if job["status"] == "done":
        payload["result"] = job["result"]
    if job["status"] == "error":
        payload["error"] = job.get("error")
    return payload


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
