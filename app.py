"""
FastAPI web UI for HR-Agent.

Cookie-session authenticated JSON API + static frontend.
POST /api/analyze  -> starts the multi-agent pipeline in a thread, returns job id
GET  /api/jobs/{id} -> current stage + result when finished
Plus auth, profile, history, and resume-builder routes backed by db.py.
"""

import hashlib
import json
import logging
import tempfile
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import auth
import db
from agents import build_graph
from resume_builder import build_resume, json_resume_to_markdown

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="HR-Agent")

STATIC_DIR = Path(__file__).parent / "static"

COOKIE_KW = dict(httponly=True, samesite="lax", secure=False)

# Stateful job store: in-memory for live polling, finished jobs persisted to
# cache/jobs/ so results survive server restarts.
# ponytail: JSON files, swap for redis/sqlite if this ever runs multi-worker
JOBS: dict = {}
JOBS_DIR = Path("cache") / "jobs"


@app.on_event("startup")
def _startup():
    try:
        db.init_schema()
    except Exception:
        logger.exception("db.init_schema failed; database features unavailable")


def current_user(request: Request):
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        return db.get_session_user(token)
    except Exception:
        logger.exception("session lookup failed")
        return None


def _unauth():
    return JSONResponse({"error": "unauthorized"}, status_code=401)


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


# ---------------- auth routes ----------------

@app.post("/api/register")
async def api_register(request: Request):
    body = await request.json()
    try:
        token = auth.register((body.get("email") or "").strip().lower(), body.get("password") or "")
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    resp = JSONResponse({"ok": True})
    resp.set_cookie("session", token, **COOKIE_KW)
    return resp


@app.post("/api/login")
async def api_login(request: Request):
    body = await request.json()
    try:
        token = auth.login((body.get("email") or "").strip().lower(), body.get("password") or "")
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=401)
    resp = JSONResponse({"ok": True})
    resp.set_cookie("session", token, **COOKIE_KW)
    return resp


@app.post("/api/logout")
async def api_logout(request: Request):
    token = request.cookies.get("session")
    if token:
        try:
            db.delete_session(token)
        except Exception:
            logger.exception("logout failed")
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("session")
    return resp


@app.get("/api/me")
async def api_me(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    return {"email": user["email"], "github_url": user.get("github_url"), "extras": user.get("extras") or {}}


@app.put("/api/me")
async def api_me_update(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    body = await request.json()
    db.update_user_profile(user["id"], body.get("github_url") or None, body.get("extras") or {})
    return {"ok": True}


# ---------------- pipeline ----------------

def _run_job(job_id: str, pdf_path: str, jd_url: str, jd_text: str, user_id: int, filename: str, pdf_hash: str):
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

        result = {
            "candidate": (resume.basics.name if resume and resume.basics else None)
            or Path(pdf_path).stem,
            "total_score": round(total, 1),
            "max_score": max_total,
            "evaluation": evaluation.model_dump() if evaluation else None,
            "jd_match": jd_match.model_dump() if jd_match else None,
            "errors": final.get("errors", []),
        }

        # Persist to database under the launching user.
        try:
            resume_id = db.save_resume(
                user_id, filename, pdf_hash,
                resume.model_dump() if resume else {},
            )
            jd_id = None
            effective_jd_text = final.get("jd_text") or jd_text or ""
            if effective_jd_text or jd_url:
                jd_id = db.save_jd(user_id, jd_url or None, effective_jd_text)
            analysis_id = db.save_analysis(user_id, resume_id, jd_id, result)
            result["resume_id"] = resume_id
            result["jd_id"] = jd_id
            result["analysis_id"] = analysis_id
        except Exception:
            logger.exception("failed to persist analysis to db")

        job["result"] = result
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
    request: Request,
    resume: UploadFile = File(...),
    jd_url: str = Form(""),
    jd_text: str = Form(""),
):
    user = current_user(request)
    if not user:
        return _unauth()
    if not resume.filename or not resume.filename.lower().endswith(".pdf"):
        return JSONResponse({"error": "Upload a PDF resume"}, status_code=400)

    pdf_bytes = await resume.read()
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    tmp = tempfile.NamedTemporaryFile(
        suffix=".pdf", prefix=Path(resume.filename).stem + "_", delete=False
    )
    tmp.write(pdf_bytes)
    tmp.close()

    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "running", "stage": "parse"}
    threading.Thread(
        target=_run_job,
        args=(job_id, tmp.name, jd_url.strip(), jd_text.strip(), user["id"], resume.filename, pdf_hash),
        daemon=True,
    ).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def job_status(request: Request, job_id: str):
    if not current_user(request):
        return _unauth()
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


# ---------------- history / data routes ----------------

@app.get("/api/history")
async def api_history(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    return db.list_analyses(user["id"])


@app.get("/api/analyses/{analysis_id}")
async def api_analysis(request: Request, analysis_id: int):
    user = current_user(request)
    if not user:
        return _unauth()
    row = db.get_analysis(analysis_id, user["id"])
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    return row["result"]


@app.get("/api/resumes")
async def api_resumes(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    return db.list_resumes(user["id"])


@app.get("/api/jds")
async def api_jds(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    return db.list_jds(user["id"])


# ---------------- resume builder ----------------

@app.post("/api/build")
async def api_build(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    body = await request.json()
    resume_id = body.get("resume_id")
    jd_id = body.get("jd_id")
    resume_row = db.get_resume(resume_id, user["id"]) if resume_id else None
    if not resume_row:
        return JSONResponse({"error": "resume not found"}, status_code=404)
    jd_text = None
    if jd_id:
        jd_row = db.get_jd(jd_id, user["id"])
        if not jd_row:
            return JSONResponse({"error": "jd not found"}, status_code=404)
        jd_text = jd_row["text"]

    parsed = resume_row["parsed"] or {}
    github_data = None
    if user.get("github_url"):
        try:
            from github import fetch_and_display_github_info

            github_data = fetch_and_display_github_info(user["github_url"]) or None
        except Exception:
            logger.exception("github fetch failed; building without github data")

    jd_match = None
    try:
        analysis = db.get_latest_analysis_for(user["id"], resume_id, jd_id)
        if analysis and isinstance(analysis.get("result"), dict):
            jd_match = analysis["result"].get("jd_match")
    except Exception:
        logger.exception("analysis lookup failed; building without jd match")

    built = build_resume(parsed, jd_text, github_data, user.get("extras") or None, jd_match=jd_match)
    content = built["content"]
    tailoring_notes = built.get("tailoring_notes") or []
    if tailoring_notes:
        content["_tailoring_notes"] = tailoring_notes
    gen_id = db.save_generated(user["id"], resume_id, jd_id, content, built["markdown"])
    return {
        "id": gen_id,
        "content": content,
        "markdown": built["markdown"],
        "tailoring_notes": tailoring_notes,
    }


@app.get("/api/generated/{gen_id}")
async def api_generated(request: Request, gen_id: int):
    user = current_user(request)
    if not user:
        return _unauth()
    row = db.get_generated(gen_id, user["id"])
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    return row


@app.put("/api/generated/{gen_id}")
async def api_generated_update(request: Request, gen_id: int):
    user = current_user(request)
    if not user:
        return _unauth()
    row = db.get_generated(gen_id, user["id"])
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    body = await request.json()
    content = body.get("content") or {}
    markdown = json_resume_to_markdown(content)
    db.update_generated(gen_id, user["id"], content, markdown)
    return {"id": gen_id, "content": content, "markdown": markdown}


# ---------------- pages ----------------

@app.get("/")
async def index(request: Request):
    if not current_user(request):
        return RedirectResponse("/login.html", status_code=302)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/login.html")
async def login_page():
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/builder.html")
async def builder_page(request: Request):
    if not current_user(request):
        return RedirectResponse("/login.html", status_code=302)
    return FileResponse(STATIC_DIR / "builder.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
