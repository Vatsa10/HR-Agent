# Fast Builder + Page-Count Templates — Design

## Goal
Make the resume Builder fast by reusing data already computed and stored at Analyze time (parsed resume, JD match with requirements/gaps, evaluation) plus the user's saved context, instead of re-fetching GitHub live on every build. Add a page-length choice (1 vs 2 pages) with one strong, ATS-friendly template each.

## Problem today
`/api/build` re-runs GitHub enrichment on every Generate: a full repo walk (up to 200 repos) plus an LLM top-project selection, then the synthesis LLM call. Two LLM calls plus API fan-out = slow, even though the Analyze step already stored `jd_match` and the parsed resume per user.

## Decisions (approved)
- GitHub becomes an opt-in toggle in the Builder, default OFF. Default build does no GitHub walk.
- Builder reuses the stored analysis (`jd_match`) and the user's context (LinkedIn secondary + content blocks). Default build = one synthesis LLM call over already-stored data.
- Page length: 1 or 2 pages, one clean template each. Prompt tunes content density; rendering + print CSS adapt.
- Default page length: 1 page (recruiters favor concise; user can switch to 2).

## Backend

### `build_resume(...)` (resume_builder.py)
Add two params:
- `page_count: int = 1`
- (github stays via existing `github_data`; caller passes None when the toggle is off)

Prompt changes:
- Inject a LENGTH DIRECTIVE.
  - 1 page: keep only the most impactful content. Top ~3-4 most recent/relevant roles, terse metric-first bullets (max ~3 per role), a compact skills line, top ~2-3 projects. Drop older/weak items. Must fit one A4 page.
  - 2 pages: fuller detail, more roles/bullets/projects allowed, still tight and impact-first.
- Everything else (truthfulness, JD front-loading via stored `jd_match`, LinkedIn/GitHub as secondary context, tailoring_notes) unchanged.
- Store `page_count` in the returned content under `content["_page_count"]` (underscore key, ignored by the renderer's data walk, used by the UI).

### `/api/build` (app.py, background job — already converted)
Request body: `{resume_id, jd_id?, page_count?: 1|2, include_github?: bool}`.
- `page_count` defaults to 1; clamp to {1,2}.
- `include_github` defaults to False. Only when True does `_run_build` call `fetch_and_display_github_info`; otherwise `github_data = None` and the GitHub stage is skipped entirely.
- `jd_match` reuse is unchanged (already via `db.get_latest_analysis_for`).
- Pass `page_count` to `build_resume`; persist it in the saved content.
- Result unchanged shape: `{id, content, markdown, tailoring_notes}`.

No new GitHub fetch on the default path is the core speed win.

## Frontend (Builder page)

Controls (left rail, in the Generate card):
- Segmented control "Page length": `1 page` (default) / `2 pages`.
- Toggle "Include GitHub projects" (default off) with hint: "Slower, walks your repositories. Off uses your resume, JD match, and saved context only."
- Generate posts `{resume_id, jd_id, page_count, include_github}` and polls (already background + staged). When GitHub is off, the github/build stages collapse to just "Rewriting your resume".

Rendering — two templates keyed by `page_count`:
- Shared editable sheet (contentEditable, data-path save) stays.
- `1 page`: compact template. Tighter vertical rhythm, slightly smaller type, denser section spacing, single column, aimed to fit one A4. A subtle "1 page" affordance.
- `2 pages`: current roomy template.
- Print CSS per length: A4 page size; 1-page tuned to a single sheet, 2-page allows flow. Reopening a generated resume respects `content._page_count`.

Keep: Save (PUT /api/generated/{id}), Download Markdown, Print/PDF, Add custom section, the context editor (GitHub URL/LinkedIn dropdown/content blocks) already restored.

## Data flow
Analyze (stores parsed + jd_match + evaluation per user)  ->  Builder reads stored resume + latest jd_match + context (+ GitHub only if toggled)  ->  one synthesis LLM call with the length directive  ->  editable sheet in the chosen template  ->  save/export.

## Error handling
- Missing resume/JD: 404 as today.
- GitHub toggle on but fetch fails: build proceeds without it (already try/except), a note in errors.
- No stored analysis for the pair: build still runs (jd_match just absent), unchanged.

## Testing
- resume_builder self-check: assert the prompt includes the 1-page directive for page_count=1 and 2-page for page_count=2; `json_resume_to_markdown` still renders; `_page_count` present in content and ignored by markdown/renderer.
- app import check.
- Frontend: tsc + next build; page-length control + toggle wired; posts correct body; renderer switches template by `_page_count`.

## Out of scope (YAGNI)
Multiple template styles per length, server-side PDF, GitHub caching with TTL (toggle makes it unnecessary for the fast path).
