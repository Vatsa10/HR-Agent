# LinkedIn Optimizer — Design

## Goal
Turn the LinkedIn page from a profile importer into a **LinkedIn optimizer**:
the user gives their profile (a URL to scrape, or a LinkedIn PDF export), and we
return recruiter-perspective improvements, section by section, with
ready-to-paste rewrites and a prioritized checklist. It reuses what we already
store (the user's parsed resume and their latest analysis, which is
GitHub-informed) so it is fast and grounded in what the person can actually
prove.

## Inputs
- **Profile URL** -> `linkedin_service.profile_sections(url)` -> concatenated
  section text (headline/about/experience/education/skills).
- **PDF export** (LinkedIn -> More -> Save to PDF) -> existing `PDFHandler` /
  pymupdf text extraction -> profile text.
- **Stored resume** (latest, or a chosen one) -> parsed JSON.
- **Stored analysis** (latest for the user) -> its `evaluation` (open_source,
  self_projects, production, technical_skills, strengths) which reflects the
  GitHub enrichment run at Analyze time. No live GitHub walk.

Everything is best-effort: audit still runs if analysis or resume is absent.

## Backend: linkedin_optimizer.py
`audit(profile_text, resume_dict, analysis_result) -> dict` in one gpt-4o-mini
call (format="json"), recruiter/hiring lens. Returns:
```
{
  "readiness_score": 0-100,          // recruiter-readiness of the profile
  "summary": "<2-3 sentence recruiter take>",
  "sections": [
    {
      "key": "headline|about|experience|skills|featured_projects|keywords|completeness",
      "title": "Headline",
      "verdict": "good|improve|missing",
      "current": "<short quote/paraphrase of what's there, empty if missing>",
      "suggested": "<ready-to-paste rewrite the user can copy>",
      "priority": "high|medium|low",
      "why": "<why a recruiter cares / what gap this closes>"
    }, ...
  ],
  "checklist": [ {"text": "<one concrete change>", "priority": "high|medium|low"} ]
}
```
Prompt rules: compare the profile against what the resume + evaluation prove;
surface strong, provable material the profile is hiding (metrics, projects,
production impact); fix a weak/empty headline and About with concrete rewrites;
recommend keywords recruiters search that the person truthfully matches; flag
missing skills the resume proves; suggest Featured/Projects from resume/GitHub
projects; never invent experience. Ready-to-paste text must be truthful to the
source material.

## Endpoint: POST /api/linkedin/audit (auth, background job, stage "audit")
- Accepts multipart: optional `pdf` file, form `profile_url`, optional `resume_id`.
- Worker `_run_linkedin_audit`:
  1. profile_text: if pdf given -> extract text; elif profile_url -> `linkedin_service.profile_sections` joined; else error.
  2. resume: `db.get_resume(resume_id)` or latest via `_resume_text_for`.
  3. analysis: latest for the user (`db.list_analyses` newest -> `db.get_analysis(id)` result).
  4. `linkedin_optimizer.audit(profile_text, parsed, analysis_result)`.
  5. result = the audit dict.
- Poll via existing `/api/jobs/{id}`.
- Keep the existing `/api/import/linkedin` (import as resume) for the secondary action.

## Frontend: /linkedin -> "LinkedIn Optimizer"
- Header: "LinkedIn Optimizer" + one line: improve your profile for recruiters,
  grounded in your resume and GitHub.
- Two input tabs:
  - **Profile URL**: url input; needs a session (show status; if missing, the
    setup steps as today). Run -> POST /api/linkedin/audit {profile_url}.
  - **Upload PDF**: file drop for the LinkedIn PDF export (no session needed).
    Run -> POST multipart with the pdf.
- Poll (single "Auditing your profile" stage). Render the audit:
  - **Recruiter-readiness score** (big number 0-100) + summary.
  - **Do these first**: the high-priority checklist items.
  - **Section cards**: verdict badge (good/improve/missing tone), title, current
    (muted), suggested rewrite in a copyable block with a Copy button, why line.
  - Full checklist below.
- Secondary: a quiet "Save this profile as a resume" action (reuses
  /api/import/linkedin) so the scraped/PDF profile can still feed the Builder.
- Nav label stays "LinkedIn".

## Reuse / no-refetch
Resume and the GitHub-informed evaluation come from storage; only the profile
(URL scrape or PDF) is fetched fresh. This keeps the audit to one scrape (or
zero for PDF) + one LLM call.

## Testing
- linkedin_optimizer self-check: audit prompt formats; parsing a stubbed LLM
  response yields readiness_score + sections + checklist; graceful defaults on
  bad output.
- app import; endpoint registered; poll shape.
- Frontend tsc + next build; URL and PDF paths post correctly; audit renders;
  Copy works.

## Out of scope (YAGNI)
Scraping posts/activity; live GitHub re-walk (stored evaluation is the GitHub
signal); persisting audits (transient, like the person finder).
