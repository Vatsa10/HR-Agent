# Job Hunt + HR Outreach — Design

## Goal
From a candidate's resume + preferences: find relevant LinkedIn jobs, match them fast against the resume, track companies, find each company's recruiter/HR LinkedIn profile, and draft a cold message the user copies into LinkedIn. Priorities: **low latency** and **best curated results per user**.

## Scope (this spec)
1. Fix the LinkedIn rate-limit false positive (blocks all scraping today).
2. Job search over LinkedIn, seeded from resume + user job preferences.
3. Two-stage matching (instant heuristic, then one batched LLM pass) — latency first.
4. Company tracking + HR/recruiter LinkedIn profile finder.
5. Cold message drafter (resume + job + recruiter context) — draft only, user pastes into LinkedIn.
6. Two pages: `/jobs.html`, `/companies.html`.

Out of scope (YAGNI): email discovery/guessing, sending mail, paid enrichment, auto-connect.

## Latency-first matching
- **Stage 0 (instant, no network beyond the search itself):** LinkedIn job search returns ~15-25 postings (title, company, location, snippet, url). Each scored instantly by keyword overlap against the resume's skills + titles. Results render immediately, sorted by heuristic score. This is what the user sees first.
- **Stage 1 (one batched LLM call):** top ~6 heuristic results sent in a SINGLE gpt-4o-mini call that returns, per job, a 0-100 fit score + one-line reason. ~3-4s. UI updates those cards in place. Never N calls.
- **Stage 2 (on demand):** clicking a job runs the existing full `jd_matcher` per-requirement analysis for that one posting only.

Rationale: the user gets sorted results in ~1-2s (search latency), curated reasons a few seconds later, deep analysis only where they ask. No 20-call upfront stall.

## Rate-limit fix
`linkedin_scraper` `detect_rate_limit` treats any page whose body contains "rate limit"/"try again later"/"slow down"/"too many requests" as blocked — false-positives on LinkedIn's own chrome. Fix by monkeypatching from a shared `linkedin_common.py`: keep the checkpoint/authwall URL check and CAPTCHA iframe check (genuine signals), drop the body-text phrase scan. Applied once at import time before any scrape. Also add a small randomized human-like delay between navigations and a single retry on transient failures.

## Modules
- `linkedin_common.py` — `ensure_scraper_importable()` (shared shadow-path guard, moved out of linkedin_importer), `patch_rate_limit()` (applied on import), `run_scrape(coro)` helper (asyncio.run wrapper safe in worker threads), session helpers. linkedin_importer.py refactored to use it.
- `job_search.py` — `search_jobs(query, location, limit)` via `JobSearchScraper`; `heuristic_scores(resume_dict, jobs)` pure function (keyword overlap, 0-100); `batch_llm_scores(resume_text, jobs[:6])` one gpt-4o-mini call -> [{index, score, reason}]. Returns jobs with both scores.
- `hr_finder.py` — `find_recruiters(company, limit=5)` LinkedIn people search for "recruiter OR talent OR hiring at <company>", returns [{name, headline, profile_url}]. Defensive, capped, rate-limit aware. Clearly best-effort.
- `cold_message.py` — `draft_message(resume_text, job, recruiter, tone)` one LLM call -> {subject, body} tuned for LinkedIn (short, specific, references a real resume fact + the job). Truthful, no fabricated claims.
- `prefs`: user job preferences (roles, locations, seniority) stored on `users.extras.job_prefs`, seeded from resume label/skills on first visit.

## Data model (new tables)
- `saved_jobs(id, user_id, title, company, location, url unique-per-user, snippet, heuristic_score, llm_score, llm_reason, status default 'saved', created_at)` — status in saved/applied/dismissed.
- `companies(id, user_id, name, linkedin_url, notes, created_at, unique(user_id, name))`.
- `hr_contacts(id, company_id, user_id, name, headline, profile_url, message_draft, status default 'found', created_at)` — status found/drafted/messaged (user-updated).

DB helpers in `db.py`: save_job/list_jobs/update_job_status, add_company/list_companies/get_company, add_hr_contact/list_hr_contacts/update_hr_contact. All user-scoped.

## API (cookie-auth, JSON)
- `GET/PUT /api/prefs` — job preferences.
- `POST /api/jobs/search {query?, location?}` — background job (stage 'search'); result = jobs with heuristic scores; kicks batched LLM scoring as part of same job, result includes llm scores when ready. `GET /api/jobs/search/{id}` polls.
- `GET /api/jobs/saved`, `POST /api/jobs/save {job}`, `PUT /api/jobs/{id}/status`.
- `POST /api/jobs/{id}/deep-match {resume_id}` — full jd_matcher on that posting.
- `POST /api/companies/track {name, linkedin_url?}`, `GET /api/companies`.
- `POST /api/companies/{id}/find-hr` — background people-search job -> hr_contacts rows.
- `POST /api/hr/{id}/draft {resume_id, tone?}` — cold message draft, stored on the contact.
- `PUT /api/hr/{id}` — status/edited draft.

## Pages
- `/jobs.html` — preferences bar (roles, location, seniority; seeded from resume), Search button, results list: each card shows title/company/location, heuristic score immediately, LLM fit score + reason when they arrive (subtle in-place update), actions: Save, Track company, Deep match (expands per-requirement analysis inline). Empty/loading states that teach.
- `/companies.html` — tracked company cards; each: Find HR button -> lists recruiter profiles (name, headline, "Open profile" link to LinkedIn); per recruiter: Draft message (pick resume, tone) -> editable draft with Copy button + status selector (found/drafted/messaged).
- Both on shared app.css/api.js/nav.js; nav gains Jobs + Companies.

## Agents/workflow note
Scraping runs in background threads (existing JOBS pattern), never on the event loop. LLM batching keeps token cost and latency bounded. HR finder is explicitly best-effort and rate-limit-aware; surfaces partial results.

## Risks
- LinkedIn people search is the most rate-limited surface; cap to 1 company at a time, small result counts, honest partial results, respect the (now-corrected) rate-limit signals.
- Email is intentionally not attempted; outreach is LinkedIn-message-based, user-sent.
