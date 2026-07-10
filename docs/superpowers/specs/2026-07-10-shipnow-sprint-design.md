# Ship-now Sprint — Design Spec

Date: 2026-07-10
Branch: `feat/shipnow-sprint`

## Goal

Port the valuable, browser-free features mined from `ai-job-search/` into Do Apply,
making job matching and resume output materially more accurate and honest, and
**retiring the Patchright dependency from the job-search path** (which HF banned).
Then restructure the scattered root codebase into a clean `backend/` + `frontend/`
layout.

Guiding bias (ponytail): ship the smallest set that most improves accuracy and
truthfulness. Port value, skip noise.

## Explicitly out of scope / skipped

Deliberately NOT ported (low value or hostile to our stack):
- Danish job portals (Jobindex/Jobnet/Jobbank/Jobdanmark) — market-specific.
- LaTeX CV/cover-letter toolchain + compile-and-inspect PDF loop — we render HTML
  and print; fold `break-inside: avoid` CSS into the renderer instead.
- Salary benchmark — ships only with a placeholder dataset; no portable global
  data source. Defer until a real salary API exists.
- Google Scholar enrichment — CAPTCHA-blocks plain HTTP (would need a stealth
  browser). Substitute Semantic Scholar API only if demanded later.
- Deadline/expiry flags — need per-posting body fetch; do opportunistically only
  when a user pastes a JD.

Deferred to a later sprint (real new surfaces, gated behind an application
tracker so calibration has data): application tracker, calibration-from-outcomes,
cover-letter generator, interview prep, competency enrichment, learning plan.

## Features (8, "ship now")

### A. Browser-free job sources
- New `job_sources.py`:
  - `async search_linkedin_guest(keywords, location, work_type, date_posted, start)`
    → `httpx.AsyncClient` GET
    `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search`
    with params `keywords`, `location`, `f_TPR` (r604800=7d, r2592000=30d),
    `f_WT` (1 onsite / 2 remote / 3 hybrid), `start` (offset). Parse the returned
    HTML job cards (`data-entity-urn`, title, company, location, posted date, link).
  - `async search_freehire(keywords, region, remote)` → GET freehire.dev
    `/api/v1/jobs/search` (JSON; structured skills/seniority/category).
    `FREEHIRE_API_URL` env override for self-host.
- `job_search.py` `search()` becomes a multi-source merge + dedup (by normalized
  title+company) + graceful degradation: one source 429/erroring never breaks
  `/jobs`. Existing return shape preserved so `score_all()` and the concurrent
  pool are untouched.
- Patchright removed from the job-search path. Profile/people scraping keeps it
  (separate host, per the HF plan).
- 429 backoff, low request volume. Honesty note in code: LinkedIn guest access is
  unauthenticated/public but automated access touches LinkedIn ToS — personal-use
  framing, low volume.

### B. Scoring — `jd_matcher.py` + `job_search.py`
- **Multi-dimension weighted fit**: scoring prompt emits
  `dimensions: [{name, score, note}]` over technical / experience / behavioral /
  career, plus `strengths[]` and `gaps[]`. Overall computed in **pure Python** as
  a weighted sum (`WEIGHTS = {technical:30, experience:25, behavioral:15,
  career:30}`, a module constant). `verdict_band(overall)` → `shortlist` /
  `below` / `excluded`. Keeps scoring auditable and cheap.
- **Deal-breaker vetoes**: pure `apply_vetoes(job, deal_breakers) -> "PASS" |
  "FAIL" | "FLAG"` on the `location` / `work_type` fields `search()` already
  returns. FAIL forces the excluded band regardless of score. Shared by
  `jd_matcher` and `job_search`.
- **4-state keyword taxonomy**: cross-reference the existing
  `ats_keywords.absent` list against the parsed profile: absent-but-in-profile →
  `have_add` ("surface it"), absent-not-in-profile → `real_gap`. One extra
  `synthesize_gaps()` LLM call classifies domain/soft gaps + priority. Rendered as
  a heatmap table under the fit score.

### C. Resume — `resume_builder.py`
- **Style guardrails**: one `STYLE_RULES` constant (no em-dashes, banned-cliché
  list, active voice, show-don't-tell) imported into every drafting prompt
  (`resume_builder`, `people_finder`, future cover letter) + a cheap post-gen
  regex linter that strips em-dashes/clichés and returns an "N clichés removed"
  note. No data-model change.
- **Drafter–Reviewer loop**: `review_resume(draft_json, jd, profile)` → second LLM
  call returning `{edits: [{json_path, old, new, reason}], per_bullet: [{path,
  tag: "safe" | "stretch" | "fabrication"}]}`. Edits applied deterministically to
  json_resume field values. Fabrication-tagged bullets surfaced to the user with
  Keep / Soften / Drop controls. Critique persisted on the build. Always-on (one
  extra LLM call; biggest single quality lever).
- **ATS text-layer check**: join rendered resume text (summary + bullets +
  skills), run keyword coverage vs the JD. No `pdftotext` — our print flow is
  single-column-clean by construction.
- **Relevance-weighted cutting**: on page overflow, cut the lowest
  (relevance × uniqueness) line rather than the oldest, reusing the jd_matcher
  keyword list.

### D. Data model — `db.py` (all additive, `ADD COLUMN IF NOT EXISTS`)
```sql
ALTER TABLE resumes            ADD COLUMN IF NOT EXISTS deal_breakers jsonb;
ALTER TABLE generated_resumes  ADD COLUMN IF NOT EXISTS critique      jsonb;
ALTER TABLE saved_jobs         ADD COLUMN IF NOT EXISTS scores        jsonb;
-- analyses.result is already jsonb: dimensions + taxonomy nest inside, no migration.
```

### E. Frontend
- **jobs page**: dimension bars + verdict-band grouping + per-card strengths/gaps;
  deal-breaker settings control.
- **analyze page**: keyword heatmap table under the fit score.
- **builder**: reviewer diff + per-bullet safe/stretch/fabrication chips
  (Keep/Soften/Drop); style-lint note.

### F. Checks (one runnable each, no frameworks)
- `job_sources.py` `__main__`: parse a saved LinkedIn HTML fixture → assert N
  cards + fields present (no live network in the test).
- `verdict_band()` / `apply_vetoes()` / weighted-overall: pure-function asserts.
- keyword taxonomy classifier: assert `have_add` vs `real_gap` on a fixture.
- style linter: assert em-dash / cliché stripped.

## Restructure (separate final phase)

After the 8 features land and verify, move the scattered root into:
```
backend/    all Python (app.py, db.py, agents, matchers, builders, sources, prompts, ...)
frontend/   the existing web/ Next.js app (renamed)
```
Fix imports, `Dockerfile`, `render.yaml`, `.dockerignore`, `next.config.ts`
(`API_ORIGIN`), HF `README.md`/paths, and any hardcoded paths. Verify the backend
imports and starts, and the frontend builds, before committing. Done as its own
commit so it can be reverted independently.

## Sequencing

1. Phase A — browser-free job sources (unblocks HF).
2. Phase B — scoring (multi-dim fit, vetoes, keyword taxonomy).
3. Phase C — resume (style, reviewer, ATS check, relevance cutting).
4. Phase D/E — DB + frontend surfaces (interleaved with B/C where they pair).
5. Phase R — restructure to backend/frontend.

Each phase is independently committable and, where it has runtime surface,
verified before moving on.

## Decisions locked

- Persist per-job `scores` on `saved_jobs` (vs recompute per view).
- Reviewer loop always-on (not an opt-in toggle).
- New backend files created at root for now; the restructure phase moves
  everything together and fixes imports in one isolated commit.
