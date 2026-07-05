"use client";

import * as React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useJob } from "@/hooks/useJob";
import { cn, type Tone } from "@/lib/format";
import {
  Button,
  Card,
  Field,
  Input,
  Select,
  Meter,
  Badge,
  Chip,
  Spinner,
  Skeleton,
  StatusDot,
  ErrorInline,
  Segmented,
} from "@/components/ui";

/* ------------------------------------------------------------------ *
 * Types
 * ------------------------------------------------------------------ */

type SectionKey =
  | "headline"
  | "about"
  | "experience"
  | "skills"
  | "featured_projects"
  | "keywords"
  | "completeness";
type Verdict = "good" | "improve" | "missing";
type Priority = "high" | "medium" | "low";

interface AuditSection {
  key: SectionKey;
  title: string;
  verdict: Verdict;
  current: string;
  suggested: string;
  priority: Priority;
  why: string;
}

interface ChecklistItem {
  text: string;
  priority: Priority;
}

interface AuditResult {
  readiness_score: number;
  summary: string;
  sections: AuditSection[];
  checklist: ChecklistItem[];
}

interface ImportResult {
  resume_id: number;
  candidate?: string;
}

/* ------------------------------------------------------------------ *
 * Helpers
 * ------------------------------------------------------------------ */

function validUrl(v: string) {
  return /linkedin\.com\/in\//.test(v.trim());
}

const verdictTone: Record<Verdict, Tone> = {
  good: "good",
  improve: "warn",
  missing: "bad",
};

const verdictLabel: Record<Verdict, string> = {
  good: "Solid",
  improve: "Improve",
  missing: "Missing",
};

const priorityTone: Record<Priority, Tone> = {
  high: "bad",
  medium: "warn",
  low: "neutral",
};

function scoreTone(n: number): Tone {
  if (n >= 75) return "good";
  if (n >= 45) return "warn";
  return "bad";
}

/* ------------------------------------------------------------------ *
 * Copy button
 * ------------------------------------------------------------------ */

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const onCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard blocked; ignore */
    }
  }, [text]);

  return (
    <Button variant="ghost" size="sm" onClick={onCopy} type="button">
      {copied ? "Copied" : "Copy"}
    </Button>
  );
}

/* ------------------------------------------------------------------ *
 * Drop zone (LinkedIn PDF)
 * ------------------------------------------------------------------ */

function DropZone({ file, onFile }: { file: File | null; onFile: (f: File | null) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);

  const pick = useCallback(
    (f?: File | null) => {
      if (!f) return;
      if (!f.name.toLowerCase().endsWith(".pdf")) {
        setFileError(`"${f.name}" is not a PDF. Upload a .pdf export.`);
        return;
      }
      setFileError(null);
      onFile(f);
    },
    [onFile],
  );

  return (
    <div className="space-y-1.5">
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload LinkedIn PDF"
        aria-invalid={fileError ? true : undefined}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragEnter={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          setOver(false);
        }}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          pick(e.dataTransfer.files?.[0]);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl border border-dashed px-6 py-10 text-center outline-none transition-colors duration-150 [transition-timing-function:var(--ease)]",
          "focus-visible:ring-[3px] focus-visible:ring-[var(--blue-ring)]",
          fileError
            ? "border-bad bg-surface"
            : over
              ? "border-blue bg-blue-soft"
              : file
                ? "border-blue/50 bg-surface"
                : "border-line bg-surface hover:bg-surface-2",
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          hidden
          onChange={(e) => {
            pick(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        {file ? (
          <>
            <span className="font-mono text-sm font-medium text-ink">{file.name}</span>
            <span className="text-xs text-ink-faint">Click to choose a different file</span>
          </>
        ) : (
          <>
            <strong className="text-sm font-medium text-ink">Drop your LinkedIn PDF here</strong>
            <span className="text-xs text-ink-faint">or click to browse</span>
          </>
        )}
      </div>
      <p className="text-xs text-ink-faint">
        Export it from LinkedIn: More &gt; Save to PDF.
      </p>
      {fileError && <ErrorInline>{fileError}</ErrorInline>}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Section card
 * ------------------------------------------------------------------ */

function SectionCard({ s }: { s: AuditSection }) {
  return (
    <Card className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-ink">{s.title}</h3>
          <Badge tone={verdictTone[s.verdict]}>{verdictLabel[s.verdict]}</Badge>
        </div>
        <Chip tone={priorityTone[s.priority]}>{s.priority} priority</Chip>
      </div>

      {s.current && (
        <p className="text-xs leading-relaxed text-ink-faint">
          <span className="font-medium text-ink-soft">Now: </span>
          {s.current}
        </p>
      )}

      {s.suggested && (
        <div className="space-y-2 rounded-lg bg-surface-2 p-3">
          <div className="flex items-start justify-between gap-3">
            <p className="flex-1 text-sm leading-relaxed text-ink">{s.suggested}</p>
            <CopyButton text={s.suggested} />
          </div>
        </div>
      )}

      {s.why && <p className="text-xs leading-relaxed text-ink-soft">{s.why}</p>}
    </Card>
  );
}

/* ------------------------------------------------------------------ *
 * Page
 * ------------------------------------------------------------------ */

type Mode = "saved" | "url" | "pdf";

export default function LinkedInOptimizerPage() {
  const [mode, setMode] = useState<Mode>("url");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);

  // Already-imported LinkedIn profiles (stored as "LinkedIn:" resumes).
  const [savedProfiles, setSavedProfiles] = useState<{ id: number; filename: string }[]>([]);
  const [savedProfileId, setSavedProfileId] = useState("");

  const [sessionOk, setSessionOk] = useState<boolean | null>(null);
  const [checking, setChecking] = useState(true);

  const job = useJob<AuditResult>();
  const mounted = useRef(true);

  // Secondary "save as resume" action state
  const [savedResume, setSavedResume] = useState<ImportResult | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const checkStatus = useCallback(async () => {
    setChecking(true);
    try {
      const s = await api<{ session: boolean }>("/linkedin/status");
      if (mounted.current) setSessionOk(!!s.session);
    } catch {
      if (mounted.current) setSessionOk(false);
    } finally {
      if (mounted.current) setChecking(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    checkStatus();
    // Load already-imported LinkedIn profiles so they can be audited instantly.
    (async () => {
      try {
        const resumes = await api<{ id: number; filename: string }[]>("/resumes");
        if (!mounted.current) return;
        const li = (resumes || []).filter((r) => (r.filename || "").startsWith("LinkedIn:"));
        setSavedProfiles(li);
        if (li.length) {
          setMode("saved");
          setSavedProfileId(String(li[0].id));
        }
      } catch {
        /* non-fatal */
      }
    })();
    return () => {
      mounted.current = false;
    };
  }, [checkStatus]);

  const submit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (job.running) return;

      setSavedResume(null);
      setSaveError(null);

      const fd = new FormData();
      if (mode === "saved") {
        if (!savedProfileId) return;
        fd.append("profile_resume_id", savedProfileId);
      } else if (mode === "url") {
        if (!sessionOk || !validUrl(url)) return;
        fd.append("profile_url", url.trim());
      } else {
        if (!file) return;
        fd.append("pdf", file);
        fd.append("profile_url", "");
      }

      const res = await job.run(() =>
        api<{ job_id: string }>("/linkedin/audit", { method: "POST", body: fd }),
      );

      if (!res && job.error && /session not found/i.test(job.error) && mounted.current) {
        setSessionOk(false);
      }
    },
    [mode, url, file, sessionOk, savedProfileId, job],
  );

  const saveAsResume = useCallback(async () => {
    if (saving || !validUrl(url)) return;
    setSaving(true);
    setSaveError(null);
    try {
      // /import/linkedin is a background job returning { job_id }
      const start = await api<{ job_id: string }>("/import/linkedin", {
        method: "POST",
        body: { url: url.trim() },
      });
      const { pollJob } = await import("@/lib/api");
      const result = await pollJob<ImportResult>(start.job_id);
      if (mounted.current) setSavedResume(result);
    } catch (err) {
      if (mounted.current) {
        setSaveError(err instanceof Error ? err.message : "Could not save profile");
      }
    } finally {
      if (mounted.current) setSaving(false);
    }
  }, [saving, url]);

  const canRun =
    !job.running &&
    (mode === "saved"
      ? !!savedProfileId
      : mode === "url"
        ? !!sessionOk && validUrl(url)
        : !!file);

  const result = job.result;
  const highItems = result?.checklist.filter((c) => c.priority === "high") ?? [];

  return (
    <div className="mx-auto max-w-[760px] px-5 py-10 md:px-8">
      <header className="mb-8 space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">LinkedIn Optimizer</h1>
        <p className="max-w-[62ch] text-sm leading-relaxed text-ink-soft">
          Improve your profile for recruiters, grounded in your resume and GitHub.
        </p>
      </header>

      <form onSubmit={submit} className="space-y-5">
        <Segmented<Mode>
          aria-label="Input mode"
          options={[
            ...(savedProfiles.length ? [{ value: "saved" as Mode, label: "Saved profile" }] : []),
            { value: "url", label: "Profile URL" },
            { value: "pdf", label: "Upload PDF" },
          ]}
          value={mode}
          onChange={setMode}
        />

        {mode === "saved" ? (
          <Field label="Imported profile" htmlFor="saved-sel">
            <Select
              id="saved-sel"
              value={savedProfileId}
              onChange={(e) => setSavedProfileId(e.target.value)}
            >
              {savedProfiles.map((p) => (
                <option key={p.id} value={p.id}>{p.filename}</option>
              ))}
            </Select>
            <p className="text-xs text-ink-faint">
              Audit an already-imported profile instantly, no re-scrape. Import a new one via Profile URL.
            </p>
          </Field>
        ) : mode === "url" ? (
          <div className="space-y-4">
            {/* Session gate: only for URL mode */}
            {checking ? (
              <Skeleton className="h-5 w-40" />
            ) : sessionOk === false ? (
              <Card className="space-y-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <StatusDot tone="neutral" />
                  <span className="text-ink-soft">No LinkedIn session found</span>
                </div>
                <div className="space-y-3 border-t border-line pt-3">
                  <p className="text-xs text-ink-faint">
                    URL mode reads your profile through your own logged-in session. Set one up once,
                    or switch to Upload PDF above.
                  </p>
                  <ol className="space-y-3 pl-5 text-sm text-ink-soft [list-style:decimal]">
                    <li>
                      In the project folder, run:
                      <code className="mt-1.5 block select-all overflow-x-auto rounded-lg border border-line bg-surface-2 px-3 py-2 font-mono text-xs text-ink">
                        python create_session_from_cookie.py
                      </code>
                    </li>
                    <li>Log in to LinkedIn inside the browser window that opens.</li>
                    <li>
                      The session saves to{" "}
                      <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-ink">
                        linkedin_session.json
                      </code>{" "}
                      in the project root. Keep this file private.
                    </li>
                  </ol>
                  <Button variant="ghost" size="sm" type="button" onClick={checkStatus}>
                    Refresh status
                  </Button>
                </div>
              </Card>
            ) : (
              <div className="flex items-center gap-2 text-sm font-medium">
                <StatusDot tone="good" />
                <span className="text-ink">Session ready</span>
              </div>
            )}

            <Field label="Profile URL" htmlFor="li-url" hint="linkedin.com/in/your-handle">
              <Input
                id="li-url"
                type="url"
                autoComplete="off"
                placeholder="https://www.linkedin.com/in/your-handle/"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                disabled={job.running}
              />
            </Field>
          </div>
        ) : (
          <DropZone file={file} onFile={setFile} />
        )}

        <Button type="submit" size="lg" disabled={!canRun} loading={job.running} className="w-full">
          {job.running ? "Auditing" : "Audit my profile"}
        </Button>
      </form>

      {/* Progress */}
      {job.running && (
        <Card className="mt-6 flex items-center gap-3 text-sm text-ink-soft">
          <Spinner size={14} className="text-blue" />
          {job.label || "Auditing your LinkedIn profile"}
        </Card>
      )}

      {/* Error */}
      {job.error && !job.running && (
        <ErrorInline className="mt-6">Audit failed: {job.error}</ErrorInline>
      )}

      {/* Result */}
      {result && !job.running && (
        <div className="mt-8 space-y-6">
          {/* Score + summary */}
          <Card className="space-y-4">
            <div className="flex items-end gap-4">
              <div className="leading-none">
                <div
                  className={cn(
                    "font-mono text-5xl font-semibold tabular-nums",
                    toneTextClass(scoreTone(result.readiness_score)),
                  )}
                >
                  {result.readiness_score}
                </div>
                <div className="mt-1 text-xs text-ink-faint">recruiter readiness / 100</div>
              </div>
              <div className="flex-1 pb-1">
                <Meter value={result.readiness_score} tone={scoreTone(result.readiness_score)} />
              </div>
            </div>
            {result.summary && (
              <p className="text-sm leading-relaxed text-ink-soft">{result.summary}</p>
            )}
          </Card>

          {/* Do these first */}
          {highItems.length > 0 && (
            <Card className="space-y-3">
              <h2 className="text-sm font-semibold text-ink">Do these first</h2>
              <ul className="space-y-2">
                {highItems.map((c, i) => (
                  <li key={i} className="flex items-start gap-2.5 text-sm text-ink">
                    <StatusDot tone="bad" className="mt-1.5" />
                    <span className="leading-relaxed">{c.text}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {/* Section cards */}
          {result.sections.length > 0 && (
            <div className="space-y-4">
              <h2 className="text-sm font-semibold text-ink">Section by section</h2>
              {result.sections.map((s, i) => (
                <SectionCard key={`${s.key}-${i}`} s={s} />
              ))}
            </div>
          )}

          {/* Full checklist */}
          {result.checklist.length > 0 && (
            <Card className="space-y-3">
              <h2 className="text-sm font-semibold text-ink">Full checklist</h2>
              <ul className="space-y-2.5">
                {result.checklist.map((c, i) => (
                  <li key={i} className="flex items-start justify-between gap-3 text-sm text-ink">
                    <span className="leading-relaxed">{c.text}</span>
                    <Chip tone={priorityTone[c.priority]} className="shrink-0">
                      {c.priority}
                    </Chip>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {/* Secondary: save URL profile as a resume for the Builder */}
          {mode === "url" && validUrl(url) && (
            <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
              {savedResume ? (
                <span className="text-xs text-ink-faint">
                  Saved as a resume. It now appears in your saved resumes and Builder.
                </span>
              ) : (
                <>
                  <Button
                    variant="quiet"
                    size="sm"
                    type="button"
                    loading={saving}
                    onClick={saveAsResume}
                  >
                    {saving ? "Saving" : "Save this profile as a resume"}
                  </Button>
                  <span className="text-xs text-ink-faint">Optional, feeds the Builder.</span>
                </>
              )}
            </div>
          )}
          {saveError && <ErrorInline>{saveError}</ErrorInline>}
        </div>
      )}
    </div>
  );
}

/* Score number color, reusing tone tokens. */
function toneTextClass(tone: Tone): string {
  switch (tone) {
    case "good":
      return "text-good";
    case "warn":
      return "text-warn";
    case "bad":
      return "text-bad";
    default:
      return "text-ink";
  }
}
