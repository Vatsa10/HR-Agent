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

    _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=5, open=True)

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
"""


def init_schema():
    with _connect() as conn:
        conn.execute(SCHEMA)


def _one(sql, params=()):
    with _connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def _all(sql, params=()):
    with _connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def _exec(sql, params=()):
    with _connect() as conn:
        conn.execute(sql, params)


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
