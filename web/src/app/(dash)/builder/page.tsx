"use client";

import * as React from "react";
import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, pollJob } from "@/lib/api";
import { Button, Card, Field, Input, Select, Textarea, Skeleton, ErrorInline, Segmented, Toggle } from "@/components/ui";
import { cn } from "@/lib/format";

/* ------------------------------------------------------------------ *
 * Types (JSON Resume-ish, loosely typed — backend shape varies)
 * ------------------------------------------------------------------ */

interface ResumeRow {
  id: number;
  filename: string;
  created_at?: string;
}
interface JdRow {
  id: number;
  source_url?: string | null;
  snippet?: string | null;
  created_at?: string;
}
interface GeneratedRow {
  id: number;
  created_at?: string;
  candidate?: string | null;
}

type Loc = { city?: string | null } | null | undefined;

interface Basics {
  name?: string;
  label?: string;
  email?: string;
  phone?: string;
  url?: string;
  summary?: string;
  location?: Loc;
}
interface Work {
  name?: string;
  company?: string;
  position?: string;
  location?: string;
  startDate?: string;
  endDate?: string;
  summary?: string;
  highlights?: string[];
}
interface Project {
  name?: string;
  url?: string;
  description?: string;
  highlights?: string[];
}
interface SkillGroup {
  name?: string;
  keywords?: string[];
}
interface Education {
  institution?: string;
  studyType?: string;
  area?: string;
  startDate?: string;
  endDate?: string;
}
interface Award {
  title?: string;
  awarder?: string;
  date?: string;
  summary?: string;
}
interface ExtraBlock {
  title?: string;
  body?: string;
}
interface CustomSection {
  title?: string;
  body?: string;
}

interface ResumeContent {
  basics?: Basics;
  work?: Work[];
  projects?: Project[];
  skills?: SkillGroup[];
  education?: Education[];
  awards?: Award[];
  extras?: ExtraBlock[];
  custom_sections?: CustomSection[];
  _tailoring_notes?: string[];
  [key: string]: unknown;
}

interface BuildResult {
  id: number;
  content: ResumeContent;
  markdown: string;
  tailoring_notes?: string[];
}

/* ------------------------------------------------------------------ *
 * DOM <-> JSON path helpers (ported from static/builder.html)
 * ------------------------------------------------------------------ */

function setPath(obj: Record<string, unknown>, path: string, value: string) {
  const parts = path.split(".");
  let cur: Record<string, unknown> | unknown[] = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    const key = /^\d+$/.test(parts[i]) ? Number(parts[i]) : parts[i];
    const nextIsIndex = /^\d+$/.test(parts[i + 1]);
    const container = cur as Record<string | number, unknown>;
    if (container[key] == null) container[key] = nextIsIndex ? [] : {};
    cur = container[key] as Record<string, unknown> | unknown[];
  }
  const last = parts[parts.length - 1];
  (cur as Record<string | number, unknown>)[/^\d+$/.test(last) ? Number(last) : last] = value;
}

/* ------------------------------------------------------------------ *
 * Editable node
 * ------------------------------------------------------------------ */

function Ed({
  path,
  value,
  as: Tag = "span",
  className,
}: {
  path: string;
  value: string;
  as?: React.ElementType;
  className?: string;
}) {
  return (
    <Tag
      contentEditable
      suppressContentEditableWarning
      data-path={path}
      spellCheck={false}
      className={cn(
        "outline-none rounded-[3px] px-0.5 -mx-0.5 focus:bg-blue-soft focus:ring-1 focus:ring-blue/40 transition-colors",
        className,
      )}
    >
      {value}
    </Tag>
  );
}

/* ------------------------------------------------------------------ *
 * Page
 * ------------------------------------------------------------------ */

export default function BuilderPage() {
  return (
    <Suspense fallback={null}>
      <BuilderInner />
    </Suspense>
  );
}

function BuilderInner() {
  const searchParams = useSearchParams();
  const sheetRef = useRef<HTMLDivElement>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const [resumes, setResumes] = useState<ResumeRow[]>([]);
  const [jds, setJds] = useState<JdRow[]>([]);
  const [resumeId, setResumeId] = useState("");
  const [jdId, setJdId] = useState("");
  const [pageCount, setPageCount] = useState<1 | 2>(1);
  const [includeGithub, setIncludeGithub] = useState(false);

  const [content, setContent] = useState<ResumeContent | null>(null);
  const [genId, setGenId] = useState<number | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [notes, setNotes] = useState<string[]>([]);

  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [genStage, setGenStage] = useState("");
  const [saveLabel, setSaveLabel] = useState("Save");
  const [error, setError] = useState<string | null>(null);

  // Profile context (GitHub, LinkedIn, extra material) — secondary context the
  // builder folds in. Lives here so tailoring can be tuned without leaving.
  const [github, setGithub] = useState("");
  const [linkedinUrl, setLinkedinUrl] = useState("");
  const [linkedinResumeId, setLinkedinResumeId] = useState("");
  const [blocks, setBlocks] = useState<ExtraBlock[]>([]);
  const [ctxSave, setCtxSave] = useState("Save context");
  const [ctxOpen, setCtxOpen] = useState(false);
  const [generated, setGenerated] = useState<GeneratedRow[]>([]);

  const linkedinResumes = resumes.filter((r) => (r.filename || "").startsWith("LinkedIn:"));
  // The main resume picker is for actual resumes only; imported LinkedIn
  // profiles belong to the secondary-context dropdown, not here.
  const pickResumes = resumes.filter((r) => !(r.filename || "").startsWith("LinkedIn:"));

  // Load resumes + JDs + profile, then apply ?jd= / ?resume= deep-link preselect.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        // One round-trip instead of three (resumes + jds + me).
        const boot = await api<{
          resumes: ResumeRow[];
          jds: JdRow[];
          generated: GeneratedRow[];
          me: { github_url?: string; extras?: Record<string, unknown> };
        }>("/bootstrap");
        if (!alive) return;
        const r = boot.resumes || [];
        const j = boot.jds || [];
        const me = boot.me || {};
        setResumes(r);
        setJds(j);
        setGenerated(boot.generated || []);
        const qResume = searchParams.get("resume");
        const qJd = searchParams.get("jd");
        const pick = r.filter((x) => !(x.filename || "").startsWith("LinkedIn:"));
        if (qResume && r.some((x) => String(x.id) === qResume)) setResumeId(qResume);
        else if (pick.length) setResumeId(String(pick[0].id));
        if (qJd && j.some((x) => String(x.id) === qJd)) setJdId(qJd);
        // profile context
        setGithub(me.github_url || "");
        const ex = (me.extras || {}) as Record<string, unknown>;
        setLinkedinUrl(typeof ex.linkedin_url === "string" ? ex.linkedin_url : "");
        setLinkedinResumeId(ex.linkedin_resume_id ? String(ex.linkedin_resume_id) : "");
        if (Array.isArray(ex.blocks)) {
          setBlocks(ex.blocks as ExtraBlock[]);
        } else {
          // legacy flat extras -> blocks
          const legacy = Object.entries(ex)
            .filter(([k]) => !["blocks", "linkedin_url", "linkedin_resume_id"].includes(k))
            .map(([k, v]) => ({ title: k, body: typeof v === "string" ? v : JSON.stringify(v) }));
          setBlocks(legacy);
        }
      } catch (e) {
        if (alive && e instanceof Error && e.message !== "unauthorized") setError(e.message);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [searchParams]);

  async function saveContext() {
    setCtxSave("Saving...");
    try {
      await api("/me", {
        method: "PUT",
        body: {
          github_url: github.trim(),
          extras: {
            blocks: blocks.filter((b) => (b.title || "").trim() || (b.body || "").trim()),
            linkedin_url: linkedinUrl.trim(),
            linkedin_resume_id: linkedinResumeId || null,
          },
        },
      });
      if (!mounted.current) return;
      setCtxSave("Saved");
      setTimeout(() => mounted.current && setCtxSave("Save context"), 2000);
    } catch (e) {
      if (!mounted.current) return;
      setCtxSave("Save context");
      if (e instanceof Error && e.message !== "unauthorized") setError(e.message);
    }
  }

  /** Read every editable node back into a fresh content object. */
  function syncFromDom(): ResumeContent | null {
    if (!content || !sheetRef.current) return content;
    const clone: ResumeContent = JSON.parse(JSON.stringify(content));
    sheetRef.current.querySelectorAll<HTMLElement>("[data-path]").forEach((el) => {
      setPath(clone as Record<string, unknown>, el.dataset.path!, el.textContent ?? "");
    });
    setContent(clone);
    return clone;
  }

  async function generate() {
    if (!resumeId) {
      setError("No resume selected. Run an analysis first to add one.");
      return;
    }
    setGenerating(true);
    setGenStage("");
    setError(null);
    try {
      // Build runs as a background job (GitHub + LinkedIn enrichment + rewrite
      // is slow); start it and poll so the request never hangs.
      const { job_id } = await api<{ job_id: string }>("/build", {
        method: "POST",
        body: {
          resume_id: Number(resumeId),
          jd_id: jdId ? Number(jdId) : null,
          page_count: pageCount,
          include_github: includeGithub,
        },
      });
      const data = await pollJob<BuildResult>(job_id, (s, l) => {
        if (mounted.current) setGenStage(l || s || "");
      });
      if (!mounted.current) return;
      setGenId(data.id);
      const pc = data.content?._page_count;
      if (pc === 1 || pc === 2) setPageCount(pc);
      setContent(data.content);
      setMarkdown(data.markdown || "");
      setNotes(data.tailoring_notes || data.content?._tailoring_notes || []);
    } catch (e) {
      if (mounted.current && e instanceof Error && e.message !== "unauthorized") setError(e.message);
    } finally {
      if (mounted.current) {
        setGenerating(false);
        setGenStage("");
      }
    }
  }

  function addSection() {
    const cur = syncFromDom();
    if (!cur) return;
    const next: ResumeContent = JSON.parse(JSON.stringify(cur));
    next.custom_sections = next.custom_sections || [];
    next.custom_sections.push({ title: "New section", body: "Click to edit this text." });
    setContent(next);
  }

  function removeSection(i: number) {
    const cur = syncFromDom();
    if (!cur || !cur.custom_sections) return;
    const next: ResumeContent = JSON.parse(JSON.stringify(cur));
    next.custom_sections!.splice(i, 1);
    setContent(next);
  }

  async function save() {
    if (genId == null) return;
    const cur = syncFromDom();
    if (!cur) return;
    setSaveLabel("Saving...");
    try {
      const data = await api<{ id: number; content: ResumeContent; markdown: string }>(
        `/generated/${genId}`,
        { method: "PUT", body: { content: cur } },
      );
      if (!mounted.current) return;
      if (data.markdown) setMarkdown(data.markdown);
      setSaveLabel("Saved");
      setTimeout(() => mounted.current && setSaveLabel("Save"), 2000);
    } catch (e) {
      if (!mounted.current) return;
      setSaveLabel("Save");
      if (e instanceof Error && e.message !== "unauthorized") setError(e.message);
    }
  }

  function downloadMd() {
    const blob = new Blob([markdown || ""], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "resume.md";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // Browser-native PDF: print-to-PDF against the print stylesheet, which shows
  // only the resume sheet at A4. No server dependency.
  function downloadPdf() {
    window.print();
  }

  async function openSaved(id: string) {
    if (!id) return;
    setError(null);
    try {
      const data = await api<{ id: number; content: ResumeContent; markdown: string }>(
        `/generated/${id}`,
      );
      if (!mounted.current) return;
      setGenId(data.id);
      const pc = data.content?._page_count;
      if (pc === 1 || pc === 2) setPageCount(pc);
      setContent(data.content);
      setMarkdown(data.markdown || "");
      setNotes(data.content?._tailoring_notes || []);
    } catch (e) {
      if (mounted.current && e instanceof Error && e.message !== "unauthorized") setError(e.message);
    }
  }

  const hasResume = pickResumes.length > 0;

  return (
    <div className="print:block">
      {/* Print rules: show only the sheet, A4-ish. */}
      <style>{`
        /* Compact (1-page) variant: tighter rhythm, smaller type, denser gaps.
           Applied by class switch on the sheet, not a fork of the component. */
        #resume-sheet.is-compact { font-size: 0.94em; line-height: 1.32; }
        #resume-sheet.is-compact h2 { margin-top: 0.85rem; margin-bottom: 0.3rem; }
        #resume-sheet.is-compact .mb-4 { margin-bottom: 0.6rem; }
        #resume-sheet.is-compact .mb-3 { margin-bottom: 0.45rem; }
        #resume-sheet.is-compact ul { margin-top: 0.25rem; }
        #resume-sheet.is-compact ul li { line-height: 1.3; }
        #resume-sheet.is-compact header p { margin-top: 0.5rem; }

        @media print {
          @page { size: A4; margin: 14mm; }
          body { background: #fff; }
          body * { visibility: hidden; }
          #resume-sheet, #resume-sheet * { visibility: visible; }
          #resume-sheet {
            position: absolute; left: 0; top: 0; width: 100%;
            border: none; border-radius: 0; box-shadow: none; padding: 0;
            max-width: none;
          }
          #resume-sheet [contenteditable] { background: none !important; box-shadow: none !important; }
          /* 1-page tuned to a single sheet: tighter still, avoid overflow. */
          #resume-sheet.is-compact { font-size: 10pt; line-height: 1.28; }
          #resume-sheet.is-compact h2 { margin-top: 0.6rem; }
          /* 2-page allows natural flow across sheets. */
        }
      `}</style>

      <header className="mb-6 print:hidden">
        <h1 className="text-xl font-semibold tracking-tight text-ink">Resume Builder</h1>
        <p className="mt-1 max-w-[60ch] text-sm text-ink-soft">
          Pick a resume and (optionally) a job description, then generate an impact-first,
          tailored rewrite. Click any line to edit it in place.
        </p>
      </header>

      {/* ---------------- Control bar: pick + generate, all inline ---------------- */}
      <Card className="mb-5 print:hidden">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[180px] flex-1">
            <Field label="Resume" htmlFor="resume-sel" hint={loading ? "loading" : !hasResume ? "none yet" : undefined}>
              {loading ? (
                <Skeleton className="h-10 w-full" />
              ) : (
                <Select id="resume-sel" value={resumeId} onChange={(e) => setResumeId(e.target.value)} disabled={!hasResume}>
                  {hasResume ? (
                    pickResumes.map((r) => (
                      <option key={r.id} value={r.id}>{r.filename}</option>
                    ))
                  ) : (
                    <option value="">No resumes yet</option>
                  )}
                </Select>
              )}
            </Field>
          </div>

          <div className="min-w-[180px] flex-1">
            <Field label="Job description" htmlFor="jd-sel" hint="optional">
              {loading ? (
                <Skeleton className="h-10 w-full" />
              ) : (
                <Select id="jd-sel" value={jdId} onChange={(e) => setJdId(e.target.value)}>
                  <option value="">None (general polish)</option>
                  {jds.map((j) => (
                    <option key={j.id} value={j.id}>{j.source_url || j.snippet || `JD #${j.id}`}</option>
                  ))}
                </Select>
              )}
            </Field>
          </div>

          <Field label="Length">
            <Segmented<1 | 2>
              aria-label="Page length"
              value={pageCount}
              onChange={setPageCount}
              options={[{ value: 1, label: "1 page" }, { value: 2, label: "2 pages" }]}
            />
          </Field>

          <div className="flex items-center gap-2 pb-2.5">
            <Toggle id="gh-toggle" aria-label="Include GitHub projects" checked={includeGithub} onChange={setIncludeGithub} />
            <label htmlFor="gh-toggle" className="text-[13px] text-ink-soft">GitHub</label>
          </div>

          <Button onClick={generate} loading={generating} disabled={loading || !hasResume}>
            {generating ? "Generating..." : content ? "Regenerate" : "Generate"}
          </Button>
        </div>

        {/* second row: reopen a saved build, edit context, live stage */}
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line pt-3">
          {generated.length > 0 && (
            <label className="flex items-center gap-2 text-[13px] text-ink-soft">
              Open saved
              <Select
                className="h-8 w-auto min-w-[160px] text-[13px]"
                value=""
                onChange={(e) => openSaved(e.target.value)}
              >
                <option value="">Choose a build...</option>
                {generated.map((g) => (
                  <option key={g.id} value={g.id}>
                    {(g.candidate || "Resume")}{g.created_at ? ` · ${new Date(g.created_at).toLocaleDateString()}` : ""}
                  </option>
                ))}
              </Select>
            </label>
          )}
          <button
            type="button"
            onClick={() => setCtxOpen((v) => !v)}
            aria-expanded={ctxOpen}
            className="text-[13px] font-medium text-blue hover:underline"
          >
            {ctxOpen ? "Hide context" : "Edit context (GitHub, LinkedIn, extras)"}
          </button>
          {!hasResume && !loading && (
            <span className="text-[13px] text-ink-faint">
              No resumes yet.{" "}
              <Link href="/analyze" className="text-blue hover:underline">Run an analysis first</Link>.
            </span>
          )}
          {generating && genStage && (
            <span className="flex items-center gap-1.5 text-[13px] text-ink-soft" aria-live="polite">
              <span aria-hidden className="inline-block size-1.5 animate-pulse rounded-full bg-blue" />
              {genStage}
            </span>
          )}
          <span className="ml-auto text-xs text-ink-faint">
            Resume is the source of truth. GitHub and LinkedIn only enrich.
          </span>
        </div>

        {/* collapsible context (grid-rows transition, not height) */}
        <div
          className="grid transition-[grid-template-rows] duration-300 [transition-timing-function:var(--ease)]"
          style={{ gridTemplateRows: ctxOpen ? "1fr" : "0fr" }}
        >
          <div className="overflow-hidden">
            <div className="mt-3 grid gap-4 border-t border-line pt-4 sm:grid-cols-2">
              <Field label="GitHub URL" hint="secondary" htmlFor="gh">
                <Input id="gh" type="url" placeholder="https://github.com/you" value={github} onChange={(e) => setGithub(e.target.value)} />
              </Field>
              <Field label="LinkedIn profile" hint="secondary" htmlFor="li-sel">
                <Select id="li-sel" value={linkedinResumeId} onChange={(e) => setLinkedinResumeId(e.target.value)}>
                  <option value="">None</option>
                  {linkedinResumes.map((r) => (
                    <option key={r.id} value={r.id}>{r.filename}</option>
                  ))}
                </Select>
                <Input type="url" className="mt-1.5" placeholder="or https://www.linkedin.com/in/you" value={linkedinUrl} onChange={(e) => setLinkedinUrl(e.target.value)} />
              </Field>
              <div className="sm:col-span-2 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-ink-soft">Your content (certifications, publications, anything extra)</span>
                  <button type="button" onClick={() => setBlocks((b) => [...b, { title: "", body: "" }])} className="text-xs font-medium text-blue hover:underline">
                    Add block
                  </button>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {blocks.map((blk, i) => (
                    <div key={i} className="space-y-1.5 rounded-lg border border-line bg-surface p-2.5">
                      <div className="flex items-center gap-2">
                        <Input className="h-8 text-[13px]" placeholder="Title" value={blk.title || ""} onChange={(e) => setBlocks((bs) => bs.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))} />
                        <button type="button" aria-label="Remove block" onClick={() => setBlocks((bs) => bs.filter((_, j) => j !== i))} className="text-ink-faint hover:text-bad">×</button>
                      </div>
                      <Textarea rows={2} className="text-[13px]" placeholder="Body. One item per line." value={blk.body || ""} onChange={(e) => setBlocks((bs) => bs.map((x, j) => (j === i ? { ...x, body: e.target.value } : x)))} />
                    </div>
                  ))}
                </div>
                <Button variant="ghost" size="sm" onClick={saveContext}>{ctxSave}</Button>
              </div>
            </div>
          </div>
        </div>

        {error && <div className="mt-3"><ErrorInline>{error}</ErrorInline></div>}
      </Card>

      {/* ---------------- What changed (tailoring notes) ---------------- */}
      {notes.length > 0 && (
        <div className="mb-5 rounded-xl border border-line bg-blue-soft/40 p-4 print:hidden">
          <h3 className="text-sm font-semibold text-ink">What changed</h3>
          <ul className="mt-1.5 grid gap-1.5 sm:grid-cols-2">
            {notes.map((n, i) => (
              <li key={i} className="flex gap-2 text-xs text-ink-soft">
                <span aria-hidden className="mt-0.5 text-blue">+</span>
                <span>{n}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ---------------- The resume sheet (hero) with sticky toolbar ---------------- */}
      <section className="space-y-3">
        {content && (
          <div className="sticky top-3 z-10 mx-auto flex w-full max-w-[820px] flex-wrap items-center gap-2 rounded-xl border border-line bg-paper/85 px-2 py-2 shadow-sm backdrop-blur print:hidden">
            <Button size="sm" onClick={save}>{saveLabel}</Button>
            <Button variant="ghost" size="sm" onClick={downloadPdf}>Download PDF</Button>
            <Button variant="ghost" size="sm" onClick={downloadMd}>Markdown</Button>
            <Button variant="ghost" size="sm" onClick={addSection}>Add section</Button>
            <span className="ml-auto pr-1 text-xs text-ink-faint">Click any line to edit</span>
          </div>
        )}

        {loading ? (
            <div
              className="mx-auto w-full max-w-[820px] space-y-4 rounded-xl border border-line bg-paper p-8 shadow-sm md:p-12"
              aria-busy="true"
              aria-label="Loading your resumes"
            >
              <div className="flex flex-col items-center gap-2">
                <Skeleton className="h-7 w-56" />
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-3 w-72" />
              </div>
              <div className="space-y-3 pt-4">
                <Skeleton className="h-3 w-32" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-11/12" />
                <Skeleton className="h-3 w-4/5" />
              </div>
              <div className="space-y-3 pt-2">
                <Skeleton className="h-3 w-28" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-10/12" />
              </div>
            </div>
          ) : !content ? (
            <Card
              padded={false}
              className="flex min-h-[340px] flex-col items-center justify-center gap-2 border-dashed p-10 text-center"
            >
              <p className="text-sm font-medium text-ink">Nothing built yet</p>
              <p className="max-w-sm text-sm text-ink-faint">
                Pick a resume above and hit Generate to build a polished version here, or open a
                saved build. Then click any line to edit it.
              </p>
            </Card>
          ) : (
            <Sheet
              content={content}
              sheetRef={sheetRef}
              onRemoveSection={removeSection}
              pageCount={
                content._page_count === 1 || content._page_count === 2
                  ? (content._page_count as 1 | 2)
                  : pageCount
              }
            />
          )}
        </section>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * The rendered, contentEditable resume sheet
 * ------------------------------------------------------------------ */

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mt-6 mb-2 border-b border-line pb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-soft">
      {children}
    </h2>
  );
}

function ItemHead({
  base,
  title,
  titleKey,
  sub,
  subKey,
  start,
  end,
}: {
  base: string;
  title: string;
  titleKey: string;
  sub?: string | null;
  subKey?: string;
  start?: string | null;
  end?: string | null;
}) {
  const showDates = start != null || end != null;
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-3">
      <span className="text-sm">
        <Ed path={`${base}.${titleKey}`} value={title} className="font-semibold text-ink" />
        {sub != null && subKey && (
          <>
            {" "}
            <Ed path={`${base}.${subKey}`} value={sub} className="text-ink-soft" />
          </>
        )}
      </span>
      {showDates && (
        <span className="font-mono text-xs tabular-nums text-ink-faint">
          {start != null && <Ed path={`${base}.startDate`} value={start} />}
          {(start != null || end != null) && " – "}
          {end != null ? <Ed path={`${base}.endDate`} value={end} /> : <span>Present</span>}
        </span>
      )}
    </div>
  );
}

function Highlights({ base, arr }: { base: string; arr?: string[] }) {
  if (!arr || !arr.length) return null;
  return (
    <ul className="mt-1.5 space-y-1 pl-4">
      {arr.map((h, i) => (
        <li key={i} className="list-disc text-[13px] leading-relaxed text-ink-soft marker:text-ink-faint">
          <Ed path={`${base}.highlights.${i}`} value={h} />
        </li>
      ))}
    </ul>
  );
}

function Sheet({
  content,
  sheetRef,
  onRemoveSection,
  pageCount,
}: {
  content: ResumeContent;
  sheetRef: React.RefObject<HTMLDivElement | null>;
  onRemoveSection: (i: number) => void;
  pageCount: 1 | 2;
}) {
  const compact = pageCount === 1;
  const b = content.basics || {};
  const contact: React.ReactNode[] = [];
  if (b.email != null) contact.push(<Ed key="email" path="basics.email" value={b.email} />);
  if (b.phone != null) contact.push(<Ed key="phone" path="basics.phone" value={b.phone} />);
  if (b.url != null) contact.push(<Ed key="url" path="basics.url" value={b.url} />);
  if (b.location && b.location.city != null)
    contact.push(<Ed key="city" path="basics.location.city" value={b.location.city} />);

  return (
    <div
      id="resume-sheet"
      ref={sheetRef}
      data-page-count={pageCount}
      className={cn(
        "resume-sheet mx-auto w-full max-w-[820px] rounded-xl border border-line bg-paper shadow-sm",
        compact ? "is-compact p-6 md:p-10" : "p-8 md:p-12",
      )}
    >
      {/* Header */}
      <header className="text-center">
        <Ed
          path="basics.name"
          value={b.name || "Your Name"}
          as="h1"
          className="block text-2xl font-bold tracking-tight text-ink"
        />
        {b.label != null && (
          <Ed
            path="basics.label"
            value={b.label}
            as="div"
            className="mt-0.5 text-sm font-medium text-blue"
          />
        )}
        {contact.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-xs text-ink-soft">
            {contact.map((c, i) => (
              <React.Fragment key={i}>
                {i > 0 && <span className="text-ink-faint">·</span>}
                {c}
              </React.Fragment>
            ))}
          </div>
        )}
        {b.summary != null && (
          <Ed
            path="basics.summary"
            value={b.summary}
            as="p"
            className="mx-auto mt-3 max-w-[68ch] text-[13px] leading-relaxed text-ink-soft"
          />
        )}
      </header>

      {/* Experience */}
      {(content.work || []).length > 0 && (
        <>
          <SectionHeading>Experience</SectionHeading>
          {content.work!.map((w, i) => {
            const base = `work.${i}`;
            return (
              <div key={i} className="mb-4">
                <ItemHead
                  base={base}
                  title={w.position || ""}
                  titleKey="position"
                  sub={w.name ?? w.company ?? null}
                  subKey="name"
                  start={w.startDate ?? null}
                  end={w.endDate ?? null}
                />
                {w.location != null && w.location !== "" && (
                  <Ed path={`${base}.location`} value={w.location} as="div" className="text-xs text-ink-faint" />
                )}
                {w.summary != null && (
                  <Ed path={`${base}.summary`} value={w.summary} as="div" className="mt-1 text-[13px] text-ink-soft" />
                )}
                <Highlights base={base} arr={w.highlights} />
              </div>
            );
          })}
        </>
      )}

      {/* Projects */}
      {(content.projects || []).length > 0 && (
        <>
          <SectionHeading>Projects</SectionHeading>
          {content.projects!.map((p, i) => {
            const base = `projects.${i}`;
            return (
              <div key={i} className="mb-4">
                <ItemHead
                  base={base}
                  title={p.name || ""}
                  titleKey="name"
                  sub={p.url ?? null}
                  subKey="url"
                />
                {p.description != null && (
                  <Ed
                    path={`${base}.description`}
                    value={p.description}
                    as="div"
                    className="mt-1 text-[13px] text-ink-soft"
                  />
                )}
                <Highlights base={base} arr={p.highlights} />
              </div>
            );
          })}
        </>
      )}

      {/* Skills */}
      {(content.skills || []).length > 0 && (
        <>
          <SectionHeading>Skills</SectionHeading>
          <div className="space-y-1">
            {content.skills!.map((s, i) => {
              const base = `skills.${i}`;
              return (
                <div key={i} className="text-[13px] text-ink-soft">
                  <Ed path={`${base}.name`} value={s.name || ""} className="font-semibold text-ink" />
                  {(s.keywords || []).length > 0 && (
                    <>
                      {": "}
                      {s.keywords!.map((k, j) => (
                        <React.Fragment key={j}>
                          {j > 0 && ", "}
                          <Ed path={`${base}.keywords.${j}`} value={k} />
                        </React.Fragment>
                      ))}
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* Education */}
      {(content.education || []).length > 0 && (
        <>
          <SectionHeading>Education</SectionHeading>
          {content.education!.map((e, i) => {
            const base = `education.${i}`;
            const degree = [e.studyType, e.area].filter(Boolean).join(", ");
            return (
              <div key={i} className="mb-3">
                <ItemHead
                  base={base}
                  title={e.institution || ""}
                  titleKey="institution"
                  sub={degree || e.studyType || null}
                  subKey="studyType"
                  start={e.startDate ?? null}
                  end={e.endDate ?? null}
                />
              </div>
            );
          })}
        </>
      )}

      {/* Awards */}
      {(content.awards || []).length > 0 && (
        <>
          <SectionHeading>Awards</SectionHeading>
          {content.awards!.map((a, i) => {
            const base = `awards.${i}`;
            return (
              <div key={i} className="mb-3">
                <ItemHead
                  base={base}
                  title={a.title || ""}
                  titleKey="title"
                  sub={a.awarder ?? null}
                  subKey="awarder"
                  start={a.date ?? null}
                  end={null}
                />
                {a.summary != null && (
                  <Ed path={`${base}.summary`} value={a.summary} as="div" className="mt-1 text-[13px] text-ink-soft" />
                )}
              </div>
            );
          })}
        </>
      )}

      {/* Extras (user-supplied blocks) */}
      {Array.isArray(content.extras) && content.extras.length > 0 && (
        <>
          {content.extras.map((x, i) => {
            const base = `extras.${i}`;
            return (
              <div key={i} className="mb-3">
                <SectionHeading>
                  <Ed path={`${base}.title`} value={x.title || "Extra"} />
                </SectionHeading>
                {x.body != null && (
                  <Ed
                    path={`${base}.body`}
                    value={x.body}
                    as="div"
                    className="whitespace-pre-line text-[13px] leading-relaxed text-ink-soft"
                  />
                )}
              </div>
            );
          })}
        </>
      )}

      {/* Custom sections (added in-app, removable) */}
      {(content.custom_sections || []).map((s, i) => {
        const base = `custom_sections.${i}`;
        return (
          <div key={i} className="group mb-3">
            <h2 className="mt-6 mb-2 flex items-center gap-2 border-b border-line pb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-soft">
              <button
                type="button"
                onClick={() => onRemoveSection(i)}
                aria-label="Remove section"
                className="text-ink-faint opacity-0 transition-opacity hover:text-bad group-hover:opacity-100 print:hidden"
              >
                ×
              </button>
              <Ed path={`${base}.title`} value={s.title || "Custom section"} />
            </h2>
            <Ed
              path={`${base}.body`}
              value={s.body || ""}
              as="div"
              className="whitespace-pre-line text-[13px] leading-relaxed text-ink-soft"
            />
          </div>
        );
      })}
    </div>
  );
}
