"use client";

import * as React from "react";
import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { Button, Card, Field, Select, Spinner, ErrorInline } from "@/components/ui";
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

  const [resumes, setResumes] = useState<ResumeRow[]>([]);
  const [jds, setJds] = useState<JdRow[]>([]);
  const [resumeId, setResumeId] = useState("");
  const [jdId, setJdId] = useState("");

  const [content, setContent] = useState<ResumeContent | null>(null);
  const [genId, setGenId] = useState<number | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [notes, setNotes] = useState<string[]>([]);

  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [saveLabel, setSaveLabel] = useState("Save");
  const [error, setError] = useState<string | null>(null);

  // Load resumes + JDs, then apply ?jd= / ?resume= deep-link preselect.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [r, j] = await Promise.all([
          api<ResumeRow[]>("/resumes"),
          api<JdRow[]>("/jds"),
        ]);
        if (!alive) return;
        setResumes(r);
        setJds(j);
        const qResume = searchParams.get("resume");
        const qJd = searchParams.get("jd");
        if (qResume && r.some((x) => String(x.id) === qResume)) setResumeId(qResume);
        else if (r.length) setResumeId(String(r[0].id));
        if (qJd && j.some((x) => String(x.id) === qJd)) setJdId(qJd);
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
    setError(null);
    try {
      const data = await api<BuildResult>("/build", {
        method: "POST",
        body: { resume_id: Number(resumeId), jd_id: jdId ? Number(jdId) : null },
      });
      setGenId(data.id);
      setContent(data.content);
      setMarkdown(data.markdown || "");
      setNotes(data.tailoring_notes || data.content?._tailoring_notes || []);
    } catch (e) {
      if (e instanceof Error && e.message !== "unauthorized") setError(e.message);
    } finally {
      setGenerating(false);
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
      if (data.markdown) setMarkdown(data.markdown);
      setSaveLabel("Saved");
      setTimeout(() => setSaveLabel("Save"), 2000);
    } catch (e) {
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

  const hasResume = resumes.length > 0;

  return (
    <div className="print:block">
      {/* Print rules: show only the sheet, A4-ish. */}
      <style>{`
        @media print {
          body { background: #fff; }
          body * { visibility: hidden; }
          #resume-sheet, #resume-sheet * { visibility: visible; }
          #resume-sheet {
            position: absolute; left: 0; top: 0; width: 100%;
            border: none; border-radius: 0; box-shadow: none; padding: 0;
          }
          #resume-sheet [contenteditable] { background: none !important; box-shadow: none !important; }
        }
      `}</style>

      <header className="mb-6 print:hidden">
        <h1 className="text-xl font-semibold tracking-tight text-ink">Resume Builder</h1>
        <p className="mt-1 max-w-[60ch] text-sm text-ink-soft">
          Pick a resume and (optionally) a job description, then generate an impact-first,
          tailored rewrite. Click any line to edit it in place.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        {/* ---------------- Left rail: generate controls ---------------- */}
        <aside className="space-y-5 print:hidden lg:sticky lg:top-6 lg:self-start">
          <Card className="space-y-4">
            <div>
              <h2 className="text-sm font-semibold text-ink">Generate</h2>
              <p className="mt-1 text-xs text-ink-faint">
                Profile context (GitHub, LinkedIn, extra material) now lives in{" "}
                <Link href="/settings" className="text-blue hover:underline">
                  Settings
                </Link>
                . The builder folds it in automatically.
              </p>
            </div>

            <Field
              label="Resume"
              htmlFor="resume-sel"
              hint={!hasResume && !loading ? "none yet" : undefined}
            >
              <Select
                id="resume-sel"
                value={resumeId}
                onChange={(e) => setResumeId(e.target.value)}
                disabled={loading || !hasResume}
              >
                {hasResume ? (
                  resumes.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.filename}
                    </option>
                  ))
                ) : (
                  <option value="">No resumes yet</option>
                )}
              </Select>
              {!hasResume && !loading && (
                <p className="text-xs text-ink-faint">
                  No resumes yet.{" "}
                  <Link href="/analyze" className="text-blue hover:underline">
                    Run an analysis first
                  </Link>
                  .
                </p>
              )}
            </Field>

            <Field label="Job description" htmlFor="jd-sel" hint="optional">
              <Select
                id="jd-sel"
                value={jdId}
                onChange={(e) => setJdId(e.target.value)}
                disabled={loading}
              >
                <option value="">None (general polish)</option>
                {jds.map((j) => (
                  <option key={j.id} value={j.id}>
                    {j.source_url || j.snippet || `JD #${j.id}`}
                  </option>
                ))}
              </Select>
            </Field>

            <Button onClick={generate} loading={generating} disabled={!hasResume} className="w-full">
              {generating ? "Generating..." : content ? "Regenerate" : "Generate resume"}
            </Button>
            <p className="text-xs text-ink-faint">
              The builder rewrites your parsed resume with impact-first bullets, tuned to the JD if
              one is selected.
            </p>

            {error && <ErrorInline>{error}</ErrorInline>}
          </Card>

          {notes.length > 0 && (
            <Card className="space-y-2">
              <h3 className="text-sm font-semibold text-ink">What changed</h3>
              <ul className="space-y-1.5">
                {notes.map((n, i) => (
                  <li key={i} className="flex gap-2 text-xs text-ink-soft">
                    <span aria-hidden className="mt-0.5 text-blue">
                      +
                    </span>
                    <span>{n}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </aside>

        {/* ---------------- Main: editable resume sheet ---------------- */}
        <section className="space-y-4">
          {content && (
            <div className="flex flex-wrap items-center gap-2 print:hidden">
              <Button variant="ghost" size="sm" onClick={addSection}>
                Add custom section
              </Button>
              <Button variant="ghost" size="sm" onClick={save}>
                {saveLabel}
              </Button>
              <Button variant="ghost" size="sm" onClick={downloadMd}>
                Download Markdown
              </Button>
              <Button variant="ghost" size="sm" onClick={() => window.print()}>
                Print / Save as PDF
              </Button>
            </div>
          )}

          {loading ? (
            <Card className="flex items-center gap-3 text-sm text-ink-soft">
              <Spinner size={16} /> Loading your resumes...
            </Card>
          ) : !content ? (
            <Card
              padded={false}
              className="flex min-h-[340px] flex-col items-center justify-center gap-2 border-dashed p-10 text-center"
            >
              <p className="text-sm font-medium text-ink">Nothing built yet</p>
              <p className="max-w-sm text-sm text-ink-faint">
                Pick a resume on the left and hit Generate to build a polished version here. Then
                click any text to edit it.
              </p>
            </Card>
          ) : (
            <Sheet content={content} sheetRef={sheetRef} onRemoveSection={removeSection} />
          )}
        </section>
      </div>
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
}: {
  content: ResumeContent;
  sheetRef: React.RefObject<HTMLDivElement | null>;
  onRemoveSection: (i: number) => void;
}) {
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
      className="mx-auto w-full max-w-[820px] rounded-xl border border-line bg-paper p-8 shadow-sm md:p-12"
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
