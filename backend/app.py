"""
FastAPI web UI for HR-Agent.

Cookie-session authenticated JSON API + static frontend.
POST /api/analyze  -> starts the multi-agent pipeline in a thread, returns job id
GET  /api/jobs/{id} -> current stage + result when finished
Plus auth, profile, history, and resume-builder routes backed by db.py.
"""

import asyncio
import hashlib
import json
import logging
import tempfile
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import auth
import cold_message
import db
import hr_finder
import job_search
import jd_matcher
import people_finder
import scoring
from agents import build_graph
from pdf import PDFHandler
from resume_builder import build_resume, json_resume_to_markdown

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        db.init_schema()
    except Exception:
        logger.exception("db.init_schema failed; database features unavailable")
    yield


app = FastAPI(title="HR-Agent", lifespan=lifespan)

STATIC_DIR = Path(__file__).parent / "static"

# Persistent session cookie so users stay signed in across browser restarts.
# secure/samesite flip via env for cross-site prod (Vercel front, Render API).
import os as _os

COOKIE_KW = dict(
    httponly=True,
    samesite=_os.environ.get("COOKIE_SAMESITE", "lax"),
    secure=_os.environ.get("COOKIE_SECURE", "") == "1",
    max_age=60 * 60 * 24 * 30,  # 30 days
)

# Stateful job store: in-memory for live polling, finished jobs persisted to
# cache/jobs/ so results survive server restarts.
# ponytail: JSON files, swap for redis/sqlite if this ever runs multi-worker
JOBS: dict = {}
JOBS_DIR = Path("cache") / "jobs"


@app.get("/api/healthz")
async def healthz():
    """Liveness probe for Render (no DB, always fast)."""
    return {"ok": True}


# Every authenticated request would otherwise re-query the session table (a
# ~network round-trip to a remote DB) just to validate the cookie. Cache the
# token -> user mapping briefly so repeat requests skip that query. The cached
# user carries github_url/extras, so mutations invalidate the entry (see
# _bust_session below) to avoid serving stale profile data.
import time as _time

_SESSION_CACHE: dict = {}  # token -> (user, expires_at)
_SESSION_TTL = 45.0


def _bust_session(request: Request):
    tok = request.cookies.get("session")
    if tok:
        _SESSION_CACHE.pop(tok, None)


def current_user(request: Request):
    token = request.cookies.get("session")
    if not token:
        return None
    now = _time.time()
    hit = _SESSION_CACHE.get(token)
    if hit and hit[1] > now:
        return hit[0]
    try:
        user = db.get_session_user(token)
    except Exception:
        logger.exception("session lookup failed")
        return None
    if user:
        _SESSION_CACHE[token] = (user, now + _SESSION_TTL)
    return user


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
    "linkedin": "LinkedIn Agent importing the profile",
    "audit": "Auditing your LinkedIn profile",
    "search": "Searching LinkedIn jobs and scoring fit",
    "hr": "Finding recruiters at the company",
    "build": "Rewriting your resume",
}


def _resume_text_for(user_id, resume_id=None):
    """Return (row, markdown_text) for a resume; latest if resume_id omitted."""
    row = None
    if resume_id is not None:
        row = db.get_resume(resume_id, user_id)
    else:
        resumes = db.list_resumes(user_id)
        if resumes:
            row = db.get_resume(resumes[0]["id"], user_id)
    if not row:
        return None, ""
    parsed = row.get("parsed") or {}
    try:
        text = json_resume_to_markdown(parsed) if parsed else ""
    except Exception:
        logger.exception("resume markdown render failed")
        text = ""
    return row, text


def _jd_string(details):
    """Build a JD text string from a job_details dict of varying shape."""
    if not isinstance(details, dict):
        return str(details or "")
    parts = []
    for k in ("title", "company", "location", "description", "text"):
        v = details.get(k)
        if v:
            parts.append(str(v))
    if not parts:
        sec = details.get("sections")
        if isinstance(sec, dict):
            parts = [str(v) for v in sec.values() if v]
        elif sec:
            parts = [str(sec)]
    if not parts:
        parts = [json.dumps(details, ensure_ascii=False)]
    return "\n".join(parts)


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
        _SESSION_CACHE.pop(token, None)
        try:
            db.delete_session(token)
        except Exception:
            logger.exception("logout failed")
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("session")
    return resp


@app.get("/api/bootstrap")
async def api_bootstrap(request: Request):
    """One round-trip for common page data (resumes, jds, prefs, profile).

    Pages that would otherwise fire 3-4 separate /api calls (each a DB
    round-trip) can load everything here at once. Sections are best-effort so a
    single failing query never blanks the whole page."""
    user = current_user(request)
    if not user:
        return _unauth()
    uid = user["id"]

    # Run the independent queries CONCURRENTLY (each is a ~network round-trip to
    # a remote DB; sequential would be 4x slower). asyncio.to_thread hands each
    # blocking query to a worker thread; the pool supplies separate connections.
    async def q(fn, default):
        try:
            return await asyncio.to_thread(fn)
        except Exception:
            logger.exception("bootstrap query failed")
            return default

    resumes, jds, prefs, generated = await asyncio.gather(
        q(lambda: db.list_resumes(uid), []),
        q(lambda: db.list_jds(uid), []),
        q(lambda: db.get_job_prefs(uid), {}),
        q(lambda: db.list_generated(uid), []),
    )
    return {
        "me": {
            "email": user["email"],
            "github_url": user.get("github_url"),
            "extras": user.get("extras") or {},
        },
        "resumes": resumes,
        "jds": jds,
        "prefs": prefs,
        "generated": generated,
    }


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
    _bust_session(request)  # cached user carries github_url/extras
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


def _run_linkedin_import(job_id: str, profile_url: str, user_id: int):
    job = JOBS[job_id]
    try:
        import linkedin_importer
        from models import JSONResume

        parsed = linkedin_importer.import_profile(profile_url)
        JSONResume(**parsed)  # validate shape
        name = (parsed.get("basics") or {}).get("name") or "Unknown"
        resume_id = db.save_resume(
            user_id,
            "LinkedIn: " + name,
            hashlib.sha256(profile_url.encode("utf-8")).hexdigest(),
            parsed,
        )
        job["result"] = {
            "resume_id": resume_id,
            "candidate": name,
            "parsed_summary": {
                "work": len(parsed.get("work") or []),
                "education": len(parsed.get("education") or []),
                "skills": len(parsed.get("skills") or []),
                "projects": len(parsed.get("projects") or []),
            },
        }
        job["status"] = "done"
    except Exception as e:
        logger.exception("LinkedIn import failed")
        job["status"] = "error"
        job["error"] = str(e)
    _persist_job(job_id, job)


@app.get("/api/linkedin/status")
async def api_linkedin_status(request: Request):
    if not current_user(request):
        return _unauth()
    import linkedin_importer

    return {"session": linkedin_importer.has_session()}


@app.post("/api/import/linkedin")
async def api_import_linkedin(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    body = await request.json()
    profile_url = (body.get("profile_url") or body.get("url") or "").strip()
    if "linkedin.com/in/" not in profile_url:
        return JSONResponse(
            {"error": "Provide a LinkedIn profile URL (linkedin.com/in/...)"},
            status_code=400,
        )
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "running", "stage": "linkedin"}
    threading.Thread(
        target=_run_linkedin_import,
        args=(job_id, profile_url, user["id"]),
        daemon=True,
    ).start()
    return {"job_id": job_id}


def _run_linkedin_audit(job_id: str, user, pdf_bytes, profile_url: str, resume_id, profile_resume_id=None):
    """Background worker: build profile text (a stored imported profile, a PDF,
    or a URL scrape), pull the stored resume + latest analysis, and run the
    recruiter-lens audit."""
    job = JOBS[job_id]
    try:
        import linkedin_optimizer

        user_id = user["id"]

        # 1. profile_text: prefer an already-imported profile (instant, no
        # scrape/upload), else PDF bytes, else a scraped profile URL.
        profile_text = ""
        if profile_resume_id:
            prow = db.get_resume(int(profile_resume_id), user_id)
            if prow and prow.get("parsed"):
                try:
                    profile_text = json_resume_to_markdown(prow["parsed"]) or ""
                except Exception:
                    logger.exception("audit: rendering saved profile failed")
        if not profile_text.strip() and pdf_bytes:
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", prefix="li_", delete=False)
            tmp.write(pdf_bytes)
            tmp.close()
            try:
                handler = PDFHandler()
                profile_text = handler.extract_text_from_pdf(tmp.name) or ""
                if not profile_text.strip():
                    parsed_pdf = handler.extract_json_from_pdf(tmp.name)
                    if parsed_pdf is not None:
                        from transform import convert_json_resume_to_text

                        profile_text = convert_json_resume_to_text(parsed_pdf) or ""
            finally:
                try:
                    Path(tmp.name).unlink()
                except OSError:
                    pass
        elif profile_url:
            import linkedin_service

            result = linkedin_service.profile_sections(profile_url)
            sections = (result or {}).get("sections") or {}
            profile_text = "\n\n".join(str(v) for v in sections.values() if v)

        if not profile_text.strip():
            job["status"] = "error"
            job["error"] = "Provide a saved profile, a LinkedIn URL, or a PDF"
            _persist_job(job_id, job)
            return

        # 2. stored resume: parsed dict (chosen or latest).
        row, _text = _resume_text_for(user_id, resume_id)
        resume_dict = (row or {}).get("parsed") or {} if row else {}

        # 3. latest analysis result for the user.
        analysis_result = None
        try:
            analyses = db.list_analyses(user_id)
            if analyses:
                latest = db.get_analysis(analyses[0]["id"], user_id)
                if latest:
                    analysis_result = latest.get("result")
        except Exception:
            logger.exception("audit: loading latest analysis failed")

        job["result"] = linkedin_optimizer.audit(profile_text, resume_dict, analysis_result)
        job["status"] = "done"
    except Exception as e:
        logger.exception("LinkedIn audit failed")
        job["status"] = "error"
        job["error"] = str(e)
    _persist_job(job_id, job)


@app.post("/api/linkedin/audit")
async def api_linkedin_audit(
    request: Request,
    pdf: UploadFile = File(None),
    profile_url: str = Form(""),
    resume_id: str = Form(""),
    profile_resume_id: str = Form(""),
):
    user = current_user(request)
    if not user:
        return _unauth()

    pdf_bytes = None
    if pdf is not None and pdf.filename:
        pdf_bytes = await pdf.read()
    profile_url = (profile_url or "").strip()

    def _int(v):
        try:
            return int(v) if v and str(v).strip() else None
        except ValueError:
            return None

    prid = _int(profile_resume_id)
    if not prid and not pdf_bytes and "linkedin.com/in/" not in profile_url:
        return JSONResponse(
            {"error": "Choose a saved profile, a LinkedIn URL, or a PDF export"},
            status_code=400,
        )

    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "running", "stage": "audit"}
    threading.Thread(
        target=_run_linkedin_audit,
        args=(job_id, user, pdf_bytes, profile_url, _int(resume_id), prid),
        daemon=True,
    ).start()
    return {"job_id": job_id}


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

def _run_build(job_id, user, resume_id, jd_id, jd_text, parsed, page_count=1):
    """Background: GitHub + LinkedIn enrichment + LLM rewrite. Both are always
    folded in (when the user has them set) to sharpen the resume, alongside the
    stored jd_match and saved context. Enrichment is truthful: it surfaces
    provable material, never invents."""
    job = JOBS[job_id]
    try:
        github_data = None
        if user.get("github_url"):
            try:
                job["stage"] = "github"
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

        # LinkedIn secondary context: prefer an imported profile (instant),
        # fall back to a live URL fetch only if none selected.
        linkedin_text = None
        extras_cfg = user.get("extras") or {}
        li_resume_id = extras_cfg.get("linkedin_resume_id")
        if li_resume_id:
            li_row = db.get_resume(int(li_resume_id), user["id"])
            if li_row and li_row.get("parsed"):
                try:
                    linkedin_text = json_resume_to_markdown(li_row["parsed"]) or None
                except Exception:
                    logger.exception("linkedin resume render failed")
        if not linkedin_text and extras_cfg.get("linkedin_url"):
            try:
                import linkedin_service

                job["stage"] = "linkedin"
                secs = linkedin_service.profile_sections(extras_cfg["linkedin_url"]).get("sections", {})
                linkedin_text = "\n\n".join(f"## {k}\n{v}" for k, v in secs.items() if v) or None
            except Exception:
                logger.exception("linkedin fetch failed; building without linkedin context")

        job["stage"] = "build"
        built = build_resume(
            parsed, jd_text, github_data, extras_cfg or None,
            jd_match=jd_match, linkedin_text=linkedin_text,
            page_count=page_count,
        )
        content = built["content"]
        tailoring_notes = built.get("tailoring_notes") or []
        if tailoring_notes:
            content["_tailoring_notes"] = tailoring_notes
        critique = built.get("critique") or {}
        gen_id = db.save_generated(
            user["id"], resume_id, jd_id, content, built["markdown"], critique=critique
        )
        job["result"] = {
            "id": gen_id,
            "content": content,
            "markdown": built["markdown"],
            "tailoring_notes": tailoring_notes,
            "critique": critique,
            "ats_coverage": built.get("ats_coverage") or {"covered": [], "missing": []},
            "style_removed": built.get("style_removed") or 0,
        }
        job["status"] = "done"
    except Exception as e:
        logger.exception("build failed")
        job["status"] = "error"
        job["error"] = str(e)
    _persist_job(job_id, job)


@app.post("/api/build")
async def api_build(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    body = await request.json()
    resume_id = body.get("resume_id")
    jd_id = body.get("jd_id")
    page_count = 2 if int(body.get("page_count") or 1) == 2 else 1
    resume_row = db.get_resume(resume_id, user["id"]) if resume_id else None
    if not resume_row:
        return JSONResponse({"error": "resume not found"}, status_code=404)
    jd_text = None
    if jd_id:
        jd_row = db.get_jd(jd_id, user["id"])
        if not jd_row:
            return JSONResponse({"error": "jd not found"}, status_code=404)
        jd_text = jd_row["text"]

    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "running", "stage": "build"}
    threading.Thread(
        target=_run_build,
        args=(job_id, user, resume_id, jd_id, jd_text, resume_row["parsed"] or {}, page_count),
        daemon=True,
    ).start()
    return {"job_id": job_id}


@app.get("/api/generated")
async def api_generated_list(request: Request):
    """List the user's saved (previously built) resumes, newest first."""
    user = current_user(request)
    if not user:
        return _unauth()
    return db.list_generated(user["id"])


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


# ---------------- job preferences ----------------

@app.get("/api/prefs")
async def api_get_prefs(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    return db.get_job_prefs(user["id"])


@app.put("/api/prefs")
async def api_set_prefs(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    body = await request.json()
    roles = body.get("roles") or []
    if not isinstance(roles, list):
        roles = [r.strip() for r in str(roles).split(",") if r.strip()]
    prefs = {
        "roles": [str(r).strip() for r in roles if str(r).strip()],
        "location": (body.get("location") or "").strip(),
        "seniority": (body.get("seniority") or "").strip(),
        "work_type": (body.get("work_type") or "").strip(),
    }
    result = db.set_job_prefs(user["id"], prefs)
    _bust_session(request)  # prefs live in users.extras -> cached user is stale
    return result


# ---------------- job search ----------------

_EXPERIENCE_TOKENS = {
    "internship", "entry", "associate", "mid_senior", "director", "executive",
}

# Best-effort mapping of common seniority labels onto experience_level tokens.
# A value that is already a token passes through unchanged; an unrecognised
# value is passed through as-is (the extractor simply ignores what it can't use).
_SENIORITY_TO_EXPERIENCE = {
    "intern": "internship",
    "internship": "internship",
    "entry": "entry",
    "entry-level": "entry",
    "entry level": "entry",
    "junior": "entry",
    "associate": "associate",
    "mid": "mid_senior",
    "mid-senior": "mid_senior",
    "mid_senior": "mid_senior",
    "mid-senior level": "mid_senior",
    "senior": "mid_senior",
    "director": "director",
    "lead": "director",
    "executive": "executive",
    "exec": "executive",
}


def _resolve_experience(body_value, seniority):
    """experience_level from the request body, else derived from stored seniority.

    If seniority is already an experience token it is used directly; otherwise a
    known label is mapped to a token, and anything else is passed through. Empty
    on both sides yields None (no filter)."""
    v = (body_value or "").strip()
    if v:
        return v
    s = (seniority or "").strip()
    if not s:
        return None
    key = s.lower()
    if key in _EXPERIENCE_TOKENS:
        return key
    return _SENIORITY_TO_EXPERIENCE.get(key, s)


def _run_job_search(job_id: str, keywords: str, location: str, user_id: int,
                    work_type: str = None, experience_level: str = None,
                    job_type: str = None, date_posted: str = None):
    job = JOBS[job_id]
    try:
        jobs = job_search.search(
            keywords,
            location=location or None,
            work_type=work_type or None,
            experience_level=experience_level or None,
            job_type=job_type or None,
            date_posted=date_posted or None,
        )
        try:
            seen_ids = db.saved_job_ids(user_id)
        except Exception:
            logger.exception("saved_job_ids lookup failed")
            seen_ids = set()
        for j in jobs:
            j["seen"] = j.get("li_job_id") in seen_ids
        row, resume_text = _resume_text_for(user_id)
        # Heuristic score first for an instant sort/paint baseline.
        if row and (row.get("parsed") or {}):
            jobs = job_search.heuristic_scores(row["parsed"], jobs)
        else:
            for j in jobs:
                j["heuristic_score"] = 0.0
        jobs.sort(key=lambda j: j.get("heuristic_score", 0) or 0, reverse=True)
        # Single displayed "score": defaults to the heuristic.
        for j in jobs:
            j["score"] = j.get("heuristic_score", 0.0)
            j.setdefault("reason", "")
        # Refine ALL jobs with parallel LLM scoring (chunked concurrently).
        if resume_text and jobs:
            for s in job_search.score_all(resume_text, jobs):
                idx = s.get("index")
                if not (isinstance(idx, int) and 0 <= idx < len(jobs)):
                    continue
                if s.get("score") is not None:
                    jobs[idx]["llm_score"] = s.get("score")
                    jobs[idx]["score"] = s.get("score")
                if s.get("reason"):
                    jobs[idx]["llm_reason"] = s.get("reason")
                    jobs[idx]["reason"] = s.get("reason")
        # Verdict band + deterministic deal-breaker vetoes. A vetoed job is
        # forced to the "excluded" band regardless of its score.
        deal_breakers = db.get_deal_breakers(user_id)
        for j in jobs:
            veto = scoring.apply_vetoes(j, deal_breakers)
            j["vetoed"] = veto == "FAIL"
            j["band"] = "excluded" if j["vetoed"] else scoring.verdict_band(j.get("score", 0))
        jobs.sort(key=lambda j: (not j["vetoed"], j.get("score", 0) or 0), reverse=True)
        job["result"] = {"jobs": jobs}
        job["status"] = "done"
    except Exception as e:
        logger.exception("job search failed")
        job["status"] = "error"
        job["error"] = str(e)
    _persist_job(job_id, job)


@app.post("/api/jobs/search")
async def api_jobs_search(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    body = await request.json()
    prefs = db.get_job_prefs(user["id"])
    # Resolve each filter from the request body, falling back to stored prefs.
    # Empty/absent values collapse to None so the extractor applies no filter.
    keywords = (body.get("keywords") or " ".join(prefs.get("roles") or [])).strip()
    location = (body.get("location") or prefs.get("location") or "").strip() or None
    work_type = (body.get("work_type") or prefs.get("work_type") or "").strip() or None
    job_type = (body.get("job_type") or prefs.get("job_type") or "").strip() or None
    experience_level = _resolve_experience(
        body.get("experience_level"), prefs.get("seniority")
    )
    if not keywords:
        return JSONResponse({"error": "Provide keywords or set roles in preferences"}, status_code=400)
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "running", "stage": "search"}
    threading.Thread(
        target=_run_job_search,
        args=(job_id, keywords, location, user["id"]),
        kwargs={
            "work_type": work_type,
            "experience_level": experience_level,
            "job_type": job_type,
        },
        daemon=True,
    ).start()
    return {"job_id": job_id}


@app.get("/api/jobs/search/{job_id}")
async def api_jobs_search_status(request: Request, job_id: str):
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


@app.get("/api/jobs/deal-breakers")
async def api_deal_breakers_get(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    return {"deal_breakers": db.get_deal_breakers(user["id"]) or {"locations": [], "work_types": []}}


@app.put("/api/jobs/deal-breakers")
async def api_deal_breakers_put(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    body = await request.json()
    data = {
        "locations": [s for s in (body.get("locations") or []) if str(s).strip()],
        "work_types": [s for s in (body.get("work_types") or []) if str(s).strip()],
    }
    db.set_deal_breakers(user["id"], data)
    return {"deal_breakers": data}


# ---------------- saved jobs ----------------

@app.get("/api/jobs/saved")
async def api_jobs_saved(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    return db.list_jobs(user["id"])


@app.post("/api/jobs/save")
async def api_jobs_save(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    body = await request.json()
    job = body.get("job") or {}
    if not job.get("li_job_id"):
        return JSONResponse({"error": "job.li_job_id required"}, status_code=400)
    new_id = db.save_job(user["id"], job)
    return {"id": new_id}


@app.put("/api/jobs/{job_id}/status")
async def api_jobs_status(request: Request, job_id: int):
    user = current_user(request)
    if not user:
        return _unauth()
    body = await request.json()
    db.update_job_status(job_id, user["id"], (body.get("status") or "saved").strip())
    return {"ok": True}


@app.post("/api/jobs/batch-match")
async def api_jobs_batch_match(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    body = await request.json()
    row, resume_text = _resume_text_for(user["id"], body.get("resume_id"))
    if not row or not resume_text:
        return JSONResponse({"error": "resume not found"}, status_code=404)
    saved = db.list_jobs(user["id"])[:10]
    if not saved:
        return {"jobs": []}
    for start in range(0, len(saved), 6):
        batch = saved[start:start + 6]
        try:
            scores = job_search.batch_llm_scores(resume_text, batch)
        except Exception:
            logger.exception("batch_llm_scores failed")
            continue
        for s in scores:
            idx = s.get("index")
            if isinstance(idx, int) and 0 <= idx < len(batch):
                job = batch[idx]
                job["llm_score"] = s.get("score")
                job["llm_reason"] = s.get("reason")
                try:
                    db.update_job_scores(
                        job["id"], user["id"], s.get("score"), s.get("reason")
                    )
                except Exception:
                    logger.exception("update_job_scores failed")
    return {"jobs": saved}


@app.post("/api/jobs/{job_id}/tailor")
async def api_jobs_tailor(request: Request, job_id: int):
    user = current_user(request)
    if not user:
        return _unauth()
    saved = db.get_job(job_id, user["id"])
    if not saved:
        return JSONResponse({"error": "job not found"}, status_code=404)
    jd_text = ""
    try:
        import linkedin_service
        details = linkedin_service.job_details(saved["li_job_id"])
        jd_text = _jd_string(details).strip()
    except Exception:
        logger.exception("job_details failed; falling back to stored fields")
    if not jd_text:
        jd_text = "\n".join(
            str(saved.get(k) or "")
            for k in ("title", "company", "snippet")
            if saved.get(k)
        ).strip()
    jd_id = db.save_jd(user["id"], saved.get("url") or None, jd_text)
    resumes = db.list_resumes(user["id"])
    resume_hint = resumes[0]["id"] if resumes else None
    return {"jd_id": jd_id, "resume_hint": resume_hint}


@app.post("/api/jobs/{job_id}/deep-match")
async def api_jobs_deep_match(request: Request, job_id: int):
    user = current_user(request)
    if not user:
        return _unauth()
    body = await request.json()
    saved = db.get_job(job_id, user["id"])
    if not saved:
        return JSONResponse({"error": "job not found"}, status_code=404)
    row, resume_text = _resume_text_for(user["id"], body.get("resume_id"))
    if not row or not resume_text:
        return JSONResponse({"error": "resume not found"}, status_code=404)
    try:
        import linkedin_service
        details = linkedin_service.job_details(saved["li_job_id"])
    except Exception as e:
        logger.exception("job_details failed")
        return JSONResponse({"error": f"could not fetch job: {e}"}, status_code=502)
    jd_text = _jd_string(details)
    if not jd_text.strip():
        return JSONResponse({"error": "empty job description"}, status_code=502)
    try:
        analysis = jd_matcher.match_resume_to_jd(resume_text, jd_text=jd_text)
    except Exception as e:
        logger.exception("deep match failed")
        return JSONResponse({"error": str(e)}, status_code=500)
    return analysis.model_dump()


# ---------------- companies ----------------

@app.get("/api/companies")
async def api_companies(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    companies = db.list_companies(user["id"])
    for c in companies:
        c["contacts"] = db.list_hr_contacts(user["id"], c["id"])
    return companies


@app.post("/api/companies/track")
async def api_companies_track(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    new_id = db.add_company(user["id"], name, (body.get("linkedin_url") or "").strip() or None)
    return {"id": new_id}


def _run_find_hr(job_id: str, company_id: int, company_name: str, user_id: int):
    job = JOBS[job_id]
    try:
        prefs = db.get_job_prefs(user_id) or {}
        location = (prefs.get("location") or "").strip() or None
        roles = prefs.get("roles") or []
        role = roles[0] if roles else None
        recruiters = hr_finder.find_recruiters(company_name, location=location, role=role)
        contacts = []
        for r in recruiters:
            cid = db.add_hr_contact(
                user_id, company_id, r.get("name"),
                headline=r.get("headline"), profile_url=r.get("profile_url"),
            )
            contacts.append({"id": cid, **r})
        job["result"] = {"contacts": contacts}
        job["status"] = "done"
    except Exception as e:
        logger.exception("find hr failed")
        job["status"] = "error"
        job["error"] = str(e)
    _persist_job(job_id, job)


@app.post("/api/companies/{company_id}/find-hr")
async def api_companies_find_hr(request: Request, company_id: int):
    user = current_user(request)
    if not user:
        return _unauth()
    company = db.get_company(company_id, user["id"])
    if not company:
        return JSONResponse({"error": "company not found"}, status_code=404)
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "running", "stage": "hr"}
    threading.Thread(
        target=_run_find_hr,
        args=(job_id, company_id, company["name"], user["id"]),
        daemon=True,
    ).start()
    return {"job_id": job_id}


# ---------------- nl people finder (chatbot) ----------------

def _run_nl_search(job_id: str, query: str, user_id: int, company_id):
    job = JOBS[job_id]
    try:
        result = people_finder.search(query)
        if company_id:
            for p in result.get("people") or []:
                try:
                    cid = db.add_hr_contact(
                        user_id, company_id, p.get("name"),
                        headline=p.get("headline"), profile_url=p.get("profile_url"),
                    )
                    p["contact_id"] = cid
                except Exception:
                    logger.exception("add_hr_contact failed")
        job["result"] = result
        job["status"] = "done"
    except Exception as e:
        logger.exception("nl search failed")
        job["status"] = "error"
        job["error"] = str(e)
    _persist_job(job_id, job)


@app.post("/api/hr/nl-search")
async def api_hr_nl_search(request: Request):
    user = current_user(request)
    if not user:
        return _unauth()
    body = await request.json()
    query = (body.get("query") or "").strip()
    if not query:
        return JSONResponse({"error": "query required"}, status_code=400)
    company_id = body.get("company_id")
    if company_id is not None:
        company = db.get_company(company_id, user["id"])
        if not company:
            return JSONResponse({"error": "company not found"}, status_code=404)
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "running", "stage": "hr"}
    threading.Thread(
        target=_run_nl_search,
        args=(job_id, query, user["id"], company_id),
        daemon=True,
    ).start()
    return {"job_id": job_id}


@app.post("/api/people/draft")
async def api_people_draft(request: Request):
    """Stateless cold-message draft for a found person. No DB writes."""
    user = current_user(request)
    if not user:
        return _unauth()
    body = await request.json()
    name = (body.get("name") or "").strip()
    headline = (body.get("headline") or "").strip()
    profile_url = (body.get("profile_url") or "").strip()
    _row, resume_text = _resume_text_for(user["id"], body.get("resume_id"))
    drafted = cold_message.draft_message(
        resume_text,
        {"company": headline or ""},
        {"name": name, "headline": headline, "profile_url": profile_url},
        body.get("tone") or "warm",
    )
    return {"subject": drafted.get("subject", ""), "body": drafted.get("body", "")}


# ---------------- hr contacts ----------------

@app.post("/api/hr/{contact_id}/draft")
async def api_hr_draft(request: Request, contact_id: int):
    user = current_user(request)
    if not user:
        return _unauth()
    body = await request.json()
    contacts = db.list_hr_contacts(user["id"])
    contact = next((c for c in contacts if c["id"] == contact_id), None)
    if not contact:
        return JSONResponse({"error": "contact not found"}, status_code=404)
    row, resume_text = _resume_text_for(user["id"], body.get("resume_id"))
    if not row or not resume_text:
        return JSONResponse({"error": "resume not found"}, status_code=404)
    company = db.get_company(contact["company_id"], user["id"]) if contact.get("company_id") else None
    target = {"company": (company or {}).get("name", "")}
    recruiter = {"name": contact.get("name"), "headline": contact.get("headline")}
    drafted = cold_message.draft_message(resume_text, target, recruiter, tone=(body.get("tone") or "warm"))
    combined = drafted.get("subject", "")
    if drafted.get("body"):
        combined = (combined + "\n\n" + drafted["body"]).strip()
    db.update_hr_contact(contact_id, user["id"], message_draft=combined, status="drafted")
    return drafted


@app.put("/api/hr/{contact_id}")
async def api_hr_update(request: Request, contact_id: int):
    user = current_user(request)
    if not user:
        return _unauth()
    body = await request.json()
    fields = {}
    if "status" in body:
        fields["status"] = body["status"]
    if "message_draft" in body:
        fields["message_draft"] = body["message_draft"]
    db.update_hr_contact(contact_id, user["id"], **fields)
    return {"ok": True}


# ---------------- generic job polling (analyze / linkedin) ----------------
# Defined after the specific /api/jobs/* routes so those win path matching.

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


@app.get("/linkedin.html")
async def linkedin_page(request: Request):
    if not current_user(request):
        return RedirectResponse("/login.html", status_code=302)
    return FileResponse(STATIC_DIR / "linkedin.html")


@app.get("/jobs.html")
async def jobs_page(request: Request):
    if not current_user(request):
        return RedirectResponse("/login.html", status_code=302)
    return FileResponse(STATIC_DIR / "jobs.html")


@app.get("/companies.html")
async def companies_page(request: Request):
    if not current_user(request):
        return RedirectResponse("/login.html", status_code=302)
    return FileResponse(STATIC_DIR / "companies.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import os
    import uvicorn

    # Pass the app as an import string so reload/workers can work.
    # RELOAD=1 for hot-reload in dev; PORT/HOST override for deploy.
    uvicorn.run(
        "app:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=os.environ.get("RELOAD", "") == "1",
    )
