---
title: Do Apply Backend
emoji: 🚀
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# HR-Agent

**AI hiring copilot.** A multi-agent pipeline that parses resume PDFs, enriches with GitHub signals, matches candidates against job postings (by URL or pasted text), and produces fair, explainable evaluations — with a clean web UI.

## Features

- **Multi-agent system (LangGraph)** — four specialized agents, each with its own tool:
  | Agent | Unique tool |
  |---|---|
  | Parser Agent | PDF extraction (PyMuPDF + section-wise LLM parsing) |
  | GitHub Scout | GitHub REST API profile/repo enrichment |
  | JD Analyst | URL fetcher + JD/resume fit scoring |
  | Evaluator | Strict rubric-based scoring engine |
- **JD matching from a URL** — paste a job posting link, the JD Analyst fetches it, extracts the text, and scores fit (0–100, matching/missing skills, verdict).
- **Three LLM backends** — OpenAI (`gpt-4o-mini` default), Google Gemini, or local Ollama.
- **Web UI** — upload resume, optional JD, watch agents work live, read evidence-backed scores.
- **Explainable output** — every category score ships with its evidence.
- **Accounts and history** — email/password auth (scrypt-hashed, cookie sessions), every analysis, resume, and JD saved to Postgres per user.
- **Resume Builder** — pick a saved resume and JD, one LLM pass rewrites it impact-first (JD must-haves front-loaded, GitHub projects folded in), then edit inline, save, download Markdown, or print to PDF.

## Quick start

```bash
git clone https://github.com/Vatsa10/HR-Agent
cd HR-Agent

python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # set OPENAI_API_KEY (or Gemini/Ollama config)
```

### Database (required for auth, history, builder)

Set `DATABASE_URL` in `.env` to a Postgres connection string. A free [Neon](https://neon.tech) database works:

```
DATABASE_URL=postgresql://user:password@ep-xxx.region.aws.neon.tech/neondb?sslmode=require
```

Tables are created automatically on server startup. Register at `/login.html`, then Analyze (history saved per account) and build tailored resumes at `/builder.html`.

### Web UI

```bash
cd backend
python app.py
# open http://127.0.0.1:8000
```

### CLI

```bash
# Score a resume (from backend/)
cd backend && python score.py path/to/resume.pdf

# Full multi-agent pipeline with JD matching
python -c "from agents import run_pipeline; import json; s = run_pipeline('resume.pdf', jd_url='https://company.com/jobs/123'); print(s['jd_match'])"
```

## Configuration

| Variable | Values | Description |
|---|---|---|
| `LLM_PROVIDER` | `openai`, `gemini`, `ollama` | Provider (default: ollama) |
| `DEFAULT_MODEL` | e.g. `gpt-4o-mini` | Model passed to the provider |
| `OPENAI_API_KEY` | string | Required for OpenAI |
| `GEMINI_API_KEY` | string | Required for Gemini |
| `GITHUB_TOKEN` | optional | Better GitHub rate limits |

## Architecture

```
            ┌───────────────┐
resume.pdf ─▶  Parser Agent │  PyMuPDF → Markdown → section LLM parsing → JSONResume
            └──────┬────────┘
                   ▼
            ┌───────────────┐
            │ GitHub Scout  │  profile + repos via GitHub API, top-project selection
            └──────┬────────┘
                   ▼ (if JD given)
            ┌───────────────┐
jd url/text ▶  JD Analyst   │  fetch URL → extract text → LLM fit scoring
            └──────┬────────┘
                   ▼
            ┌───────────────┐
            │  Evaluator    │  rubric scoring: open source, self projects,
            └──────┬────────┘  production, technical skills + bonus/deductions
                   ▼
             scores + evidence + JD fit
```

Key modules: [agents.py](agents.py) (LangGraph orchestration), [jd_matcher.py](jd_matcher.py) (JD fetch + match), [app.py](app.py) (FastAPI + UI), [models.py](models.py) (schemas + providers), [evaluator.py](evaluator.py) (scoring), [pdf.py](pdf.py) / [github.py](github.py) (extraction tools).

## License

MIT
