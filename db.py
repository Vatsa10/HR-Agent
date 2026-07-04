"""
Postgres persistence layer for HR-Agent.

Sync psycopg3, DATABASE_URL from env (.env via python-dotenv).
Uses psycopg_pool.ConnectionPool when available, else plain connects.
"""

import json
import os
import secrets

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "")

try:
    from psycopg_pool import ConnectionPool

    # Neon (serverless) closes idle connections, so a pooled connection can be
    # dead by the time we use it (SSL closed unexpectedly). We proactively
    # recycle idle connections (max_idle) and cap connection age (max_lifetime)
    # so most are fresh. We deliberately do NOT use check= on checkout: it runs
    # a SELECT 1 every query, an extra ~network round-trip that hurts latency.
    # The rare dead connection is handled by the retry-once wrapper below.
    _pool = ConnectionPool(
        DATABASE_URL,
        min_size=1,
        max_size=5,
        open=True,
        max_idle=60.0,
        max_lifetime=600.0,
    )

    def _connect():
        return _pool.connection()

except ImportError:
    from contextlib import contextmanager

    @contextmanager
    def _connect():
        conn = psycopg.connect(DATABASE_URL)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id serial PRIMARY KEY,
    email text UNIQUE NOT NULL,
    password_hash text NOT NULL,
    github_url text,
    extras jsonb DEFAULT '{}',
    created_at timestamptz DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sessions (
    token text PRIMARY KEY,
    user_id int REFERENCES users(id),
    created_at timestamptz DEFAULT now()
);
CREATE TABLE IF NOT EXISTS resumes (
    id serial PRIMARY KEY,
    user_id int REFERENCES users(id),
    filename text,
    pdf_hash text,
    parsed jsonb,
    created_at timestamptz DEFAULT now()
);
CREATE TABLE IF NOT EXISTS jds (
    id serial PRIMARY KEY,
    user_id int REFERENCES users(id),
    source_url text,
    text text,
    created_at timestamptz DEFAULT now()
);
CREATE TABLE IF NOT EXISTS analyses (
    id serial PRIMARY KEY,
    user_id int REFERENCES users(id),
    resume_id int REFERENCES resumes(id),
    jd_id int REFERENCES jds(id),
    result jsonb,
    created_at timestamptz DEFAULT now()
);
CREATE TABLE IF NOT EXISTS generated_resumes (
    id serial PRIMARY KEY,
    user_id int REFERENCES users(id),
    resume_id int REFERENCES resumes(id),
    jd_id int REFERENCES jds(id),
    content jsonb,
    markdown text,
    created_at timestamptz DEFAULT now()
);
CREATE TABLE IF NOT EXISTS saved_jobs (
    id serial PRIMARY KEY,
    user_id int REFERENCES users(id),
    li_job_id text,
    title text,
    company text,
    location text,
    url text,
    snippet text,
    heuristic_score real,
    llm_score real,
    llm_reason text,
    status text DEFAULT 'saved',
    created_at timestamptz DEFAULT now(),
    UNIQUE (user_id, li_job_id)
);
CREATE TABLE IF NOT EXISTS companies (
    id serial PRIMARY KEY,
    user_id int REFERENCES users(id),
    name text,
    linkedin_url text,
    notes text,
    created_at timestamptz DEFAULT now(),
    UNIQUE (user_id, name)
);
CREATE TABLE IF NOT EXISTS hr_contacts (
    id serial PRIMARY KEY,
    user_id int REFERENCES users(id),
    company_id int REFERENCES companies(id),
    name text,
    headline text,
    profile_url text,
    message_draft text,
    status text DEFAULT 'found',
    created_at timestamptz DEFAULT now()
);
"""


def init_schema():
    with _connect() as conn:
        conn.execute(SCHEMA)


def _retry(op):
    """Run a DB op, retrying once if the pooled connection was closed by Neon
    (idle drop). The failed connection is discarded by the pool on error, so
    the retry gets a fresh one. Happy path pays nothing."""
    try:
        return op()
    except psycopg.OperationalError:
        return op()


def _one(sql, params=()):
    def op():
        with _connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                return cur.fetchone()
    return _retry(op)


def _all(sql, params=()):
    def op():
        with _connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                return cur.fetchall()
    return _retry(op)


def _exec(sql, params=()):
    def op():
        with _connect() as conn:
            conn.execute(sql, params)
    return _retry(op)


# ---------------- users ----------------

def create_user(email, password_hash):
    try:
        row = _one(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id",
            (email, password_hash),
        )
    except psycopg.errors.UniqueViolation:
        raise ValueError("email exists")
    return row["id"]


def get_user_by_email(email):
    return _one(
        "SELECT id, email, password_hash, github_url, extras FROM users WHERE email = %s",
        (email,),
    )


def get_user(user_id):
    return _one(
        "SELECT id, email, password_hash, github_url, extras FROM users WHERE id = %s",
        (user_id,),
    )


def update_user_profile(user_id, github_url, extras):
    _exec(
        "UPDATE users SET github_url = %s, extras = %s WHERE id = %s",
        (github_url, Jsonb(extras or {}), user_id),
    )


# ---------------- sessions ----------------

def create_session(user_id):
    token = secrets.token_hex(32)
    _exec("INSERT INTO sessions (token, user_id) VALUES (%s, %s)", (token, user_id))
    return token


def get_session_user(token):
    return _one(
        """SELECT u.id, u.email, u.password_hash, u.github_url, u.extras
           FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token = %s""",
        (token,),
    )


def delete_session(token):
    _exec("DELETE FROM sessions WHERE token = %s", (token,))


# ---------------- resumes ----------------

def save_resume(user_id, filename, pdf_hash, parsed):
    row = _one(
        "INSERT INTO resumes (user_id, filename, pdf_hash, parsed) VALUES (%s, %s, %s, %s) RETURNING id",
        (user_id, filename, pdf_hash, Jsonb(parsed)),
    )
    return row["id"]


def list_resumes(user_id):
    return _all(
        "SELECT id, filename, created_at FROM resumes WHERE user_id = %s ORDER BY created_at DESC",
        (user_id,),
    )


def get_resume(resume_id, user_id):
    return _one(
        "SELECT id, filename, parsed FROM resumes WHERE id = %s AND user_id = %s",
        (resume_id, user_id),
    )


# ---------------- jds ----------------

def save_jd(user_id, source_url, text):
    row = _one(
        "INSERT INTO jds (user_id, source_url, text) VALUES (%s, %s, %s) RETURNING id",
        (user_id, source_url, text),
    )
    return row["id"]


def list_jds(user_id):
    return _all(
        """SELECT id, source_url, left(text, 200) AS snippet, created_at
           FROM jds WHERE user_id = %s ORDER BY created_at DESC""",
        (user_id,),
    )


def get_jd(jd_id, user_id):
    return _one(
        "SELECT id, source_url, text FROM jds WHERE id = %s AND user_id = %s",
        (jd_id, user_id),
    )


# ---------------- analyses ----------------

def save_analysis(user_id, resume_id, jd_id, result):
    row = _one(
        "INSERT INTO analyses (user_id, resume_id, jd_id, result) VALUES (%s, %s, %s, %s) RETURNING id",
        (user_id, resume_id, jd_id, Jsonb(result)),
    )
    return row["id"]


def list_analyses(user_id):
    return _all(
        """SELECT id, resume_id, jd_id, created_at,
                  result->>'candidate' AS candidate,
                  result->>'total_score' AS total_score
           FROM analyses WHERE user_id = %s ORDER BY created_at DESC""",
        (user_id,),
    )


def get_latest_analysis_for(user_id, resume_id, jd_id):
    """Most recent analysis for this user/resume/jd combo, or None."""
    return _one(
        """SELECT id, user_id, resume_id, jd_id, result, created_at
           FROM analyses
           WHERE user_id = %s AND resume_id = %s AND jd_id IS NOT DISTINCT FROM %s
           ORDER BY created_at DESC LIMIT 1""",
        (user_id, resume_id, jd_id),
    )


def get_analysis(analysis_id, user_id):
    return _one(
        "SELECT id, user_id, resume_id, jd_id, result, created_at FROM analyses WHERE id = %s AND user_id = %s",
        (analysis_id, user_id),
    )


# ---------------- generated resumes ----------------

def save_generated(user_id, resume_id, jd_id, content, markdown):
    row = _one(
        "INSERT INTO generated_resumes (user_id, resume_id, jd_id, content, markdown) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (user_id, resume_id, jd_id, Jsonb(content), markdown),
    )
    return row["id"]


def list_generated(user_id):
    return _all(
        "SELECT id, resume_id, jd_id, created_at FROM generated_resumes WHERE user_id = %s ORDER BY created_at DESC",
        (user_id,),
    )


def get_generated(gen_id, user_id):
    return _one(
        "SELECT id, content, markdown FROM generated_resumes WHERE id = %s AND user_id = %s",
        (gen_id, user_id),
    )


def update_generated(gen_id, user_id, content, markdown):
    _exec(
        "UPDATE generated_resumes SET content = %s, markdown = %s WHERE id = %s AND user_id = %s",
        (Jsonb(content), markdown, gen_id, user_id),
    )


# ---------------- job prefs (users.extras.job_prefs) ----------------

_EMPTY_PREFS = {
    "roles": [],
    "location": "",
    "seniority": "",
    "work_type": "",
    "job_type": "",
}


def get_job_prefs(user_id):
    """Return the user's job preferences, seeding an empty default if absent.

    Always returns every known key (roles/location/seniority/work_type/job_type)
    with a safe default, so rows saved before work_type/job_type existed still
    read back a complete shape.
    """
    row = _one("SELECT extras FROM users WHERE id = %s", (user_id,))
    extras = (row or {}).get("extras") or {}
    prefs = extras.get("job_prefs")
    if not prefs:
        return dict(_EMPTY_PREFS)
    return {
        "roles": prefs.get("roles", []),
        "location": prefs.get("location", ""),
        "seniority": prefs.get("seniority", ""),
        "work_type": prefs.get("work_type", ""),
        "job_type": prefs.get("job_type", ""),
    }


def set_job_prefs(user_id, prefs):
    """Merge prefs into users.extras.job_prefs (user-scoped)."""
    row = _one("SELECT extras FROM users WHERE id = %s", (user_id,))
    extras = (row or {}).get("extras") or {}
    prefs = prefs or {}
    extras["job_prefs"] = {
        "roles": prefs.get("roles", []),
        "location": prefs.get("location", ""),
        "seniority": prefs.get("seniority", ""),
        "work_type": prefs.get("work_type", ""),
        "job_type": prefs.get("job_type", ""),
    }
    _exec("UPDATE users SET extras = %s WHERE id = %s", (Jsonb(extras), user_id))
    return extras["job_prefs"]


# ---------------- saved jobs ----------------

def save_job(user_id, job):
    """Upsert a job for a user, keyed on (user_id, li_job_id)."""
    row = _one(
        """INSERT INTO saved_jobs
             (user_id, li_job_id, title, company, location, url, snippet,
              heuristic_score, llm_score, llm_reason, status)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (user_id, li_job_id) DO UPDATE SET
             title = EXCLUDED.title,
             company = EXCLUDED.company,
             location = EXCLUDED.location,
             url = EXCLUDED.url,
             snippet = EXCLUDED.snippet,
             heuristic_score = EXCLUDED.heuristic_score,
             llm_score = EXCLUDED.llm_score,
             llm_reason = EXCLUDED.llm_reason
           RETURNING id""",
        (
            user_id,
            job.get("li_job_id"),
            job.get("title"),
            job.get("company"),
            job.get("location"),
            job.get("url"),
            job.get("snippet"),
            job.get("heuristic_score"),
            job.get("llm_score"),
            job.get("llm_reason"),
            job.get("status", "saved"),
        ),
    )
    return row["id"]


def list_jobs(user_id):
    return _all(
        """SELECT id, li_job_id, title, company, location, url, snippet,
                  heuristic_score, llm_score, llm_reason, status, created_at
           FROM saved_jobs WHERE user_id = %s ORDER BY created_at DESC""",
        (user_id,),
    )


def get_job(job_id, user_id):
    return _one(
        """SELECT id, li_job_id, title, company, location, url, snippet,
                  heuristic_score, llm_score, llm_reason, status, created_at
           FROM saved_jobs WHERE id = %s AND user_id = %s""",
        (job_id, user_id),
    )


def update_job_status(job_id, user_id, status):
    _exec(
        "UPDATE saved_jobs SET status = %s WHERE id = %s AND user_id = %s",
        (status, job_id, user_id),
    )


def update_job_scores(job_id, user_id, llm_score, llm_reason):
    """Update just the LLM fit score/reason on a saved job (user-scoped)."""
    _exec(
        "UPDATE saved_jobs SET llm_score = %s, llm_reason = %s WHERE id = %s AND user_id = %s",
        (llm_score, llm_reason, job_id, user_id),
    )


def saved_job_ids(user_id):
    """Return the set of li_job_ids the user has already saved or dismissed."""
    rows = _all(
        """SELECT li_job_id FROM saved_jobs
           WHERE user_id = %s AND status IN ('saved', 'dismissed')""",
        (user_id,),
    )
    return {r["li_job_id"] for r in rows if r.get("li_job_id")}


# ---------------- companies ----------------

def add_company(user_id, name, linkedin_url=None, notes=None):
    row = _one(
        """INSERT INTO companies (user_id, name, linkedin_url, notes)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (user_id, name) DO UPDATE SET
             linkedin_url = COALESCE(EXCLUDED.linkedin_url, companies.linkedin_url),
             notes = COALESCE(EXCLUDED.notes, companies.notes)
           RETURNING id""",
        (user_id, name, linkedin_url, notes),
    )
    return row["id"]


def list_companies(user_id):
    return _all(
        """SELECT id, name, linkedin_url, notes, created_at
           FROM companies WHERE user_id = %s ORDER BY created_at DESC""",
        (user_id,),
    )


def get_company(company_id, user_id):
    return _one(
        """SELECT id, name, linkedin_url, notes, created_at
           FROM companies WHERE id = %s AND user_id = %s""",
        (company_id, user_id),
    )


# ---------------- hr contacts ----------------

def add_hr_contact(user_id, company_id, name, headline=None, profile_url=None,
                   message_draft=None, status="found"):
    row = _one(
        """INSERT INTO hr_contacts
             (user_id, company_id, name, headline, profile_url, message_draft, status)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (user_id, company_id, name, headline, profile_url, message_draft, status),
    )
    return row["id"]


def list_hr_contacts(user_id, company_id=None):
    if company_id is not None:
        return _all(
            """SELECT id, company_id, name, headline, profile_url, message_draft,
                      status, created_at
               FROM hr_contacts WHERE user_id = %s AND company_id = %s
               ORDER BY created_at DESC""",
            (user_id, company_id),
        )
    return _all(
        """SELECT id, company_id, name, headline, profile_url, message_draft,
                  status, created_at
           FROM hr_contacts WHERE user_id = %s ORDER BY created_at DESC""",
        (user_id,),
    )


def update_hr_contact(contact_id, user_id, **fields):
    """Update whitelisted fields on an hr_contact (user-scoped)."""
    allowed = {"name", "headline", "profile_url", "message_draft", "status"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    cols = ", ".join(f"{k} = %s" for k in sets)
    params = list(sets.values()) + [contact_id, user_id]
    _exec(
        f"UPDATE hr_contacts SET {cols} WHERE id = %s AND user_id = %s",
        tuple(params),
    )
