# Unified Job Score + Person-Finder Chatbot — Design

## Goals
1. Fix the confusing two-number job score (match/fit) into ONE "Match" score, and drop garbage empty rows.
2. Speed up job search and people search (warm browser already landed; also score all jobs in parallel).
3. Replace the Companies page with a pure person-finder chatbot: chat, get LinkedIn profiles to cold-email, one-tap draft.

## 1. Unified job score (job_search.py + app.py + jobs page)
- `search()`: drop any parsed row whose title is empty (LinkedIn returns more job_ids than have real data; those became "Untitled role / match 0"). Only keep jobs with a real title.
- Score ALL valid jobs, not just 6: chunk into groups of ~6 and run `batch_llm_scores` per chunk concurrently (ThreadPoolExecutor). Merge back by index. Every job gets an AI fit score + one-line reason.
- ONE displayed score: the job's `score` = AI fit when available, else the heuristic. The heuristic is computed first for an instant sort/paint; the AI score refines the same number. Backend result: each job has `score` (0-100), `reason` (string), plus internal `heuristic_score`/`llm_score` kept but the UI shows only `score` + `reason` under a single label "Match".
- app.py `_run_job_search`: filter empties, heuristic sort, parallel LLM score all, set `score`/`reason` per job, sort by `score` desc.
- Jobs page: render one "Match NN" chip + reason line. Remove the separate match/fit chips. Dedup/seen and actions unchanged.

## 2. Person-finder chatbot (replaces Companies)
- New route `/people` (dashboard). Nav label "Find People" (replaces "Companies"). Remove the Companies page and its nav entry; `/companies` redirects to `/people` (proxy) for safety.
- Pure chat: a conversation column. User types a natural-language request ("AI recruiters at OpenAI in Bengaluru", "who hires backend engineers at Stripe"). Each query posts to `/api/hr/nl-search {query}` (people_finder.search, background job, poll). The assistant turn shows a small "Understood as" line (role/company/location chips) and a list of person cards.
- Person card: name, headline, "Open profile" (LinkedIn URL, new tab), and "Draft message" → posts to a new stateless endpoint `POST /api/people/draft {name, headline, profile_url, resume_id?, tone?}` → `{subject, body}` via `cold_message.draft_message`, shown inline with a Copy button. No company tracking, no DB writes required (stateless finder).
- Conversation history lives in page state (stacked turns); nothing persisted server-side beyond the transient job.
- Empty/error/loading states: chat shows a thinking indicator while the job polls; "No one found, try rephrasing" on empty.

### Backend for draft
- `POST /api/people/draft` (auth): body `{name, headline, profile_url, resume_id?, tone?}`. Resolve resume text via `_resume_text_for(user_id, resume_id)`; call `cold_message.draft_message(resume_text, {"company": headline or ""}, {"name","headline","profile_url"}, tone)`; return `{subject, body}`. Truthful, grounded in one real resume fact (existing prompt). No persistence.
- Keep existing `/api/companies*` and `/api/hr/*` routes as-is (harmless, unused by the new page) OR leave them; do not remove backend to avoid churn.

## 3. Speed (done + this spec)
- Warm browser (landed): persistent Patchright context on a background loop, page pool, cold-start removed.
- Parallel job scoring (this spec): all jobs scored via concurrent LLM chunks.
- People search benefits from the warm browser automatically.

## Nav / routing
- Sidebar: replace "Companies" (`/companies`) with "Find People" (`/people`).
- proxy.ts: guard `/people`; redirect `/companies` -> `/people`.
- Remove `web/src/app/(dash)/companies/page.tsx`; add `web/src/app/(dash)/people/page.tsx`.

## Testing
- job_search self-check: empty-title rows dropped; chunked scoring merges by index; one `score` per job.
- people draft endpoint: returns {subject, body} for a fake person (stub provider).
- Frontend: tsc + next build; jobs shows one Match chip; /people chat posts + renders cards + draft; /companies redirects.

## Out of scope
- Persisting found people / outreach history (pure finder per user request).
- Removing backend company/hr tables and routes (left in place, unused).
