"use client";

import * as React from "react";
import { useCallback, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useJob } from "@/hooks/useJob";
import { cn } from "@/lib/format";
import { Button, Card, Spinner, ErrorInline } from "@/components/ui";
import { AnalysisResult, type AnalysisResultData } from "@/components/AnalysisResult";

/* ------------------------------------------------------------------ *
 * Agent stepper
 * ------------------------------------------------------------------ */

const STEPS: { stage: string; agent: string; task: string }[] = [
  { stage: "parse", agent: "Parser", task: "reading the resume" },
  { stage: "github", agent: "GitHub Scout", task: "checking repositories" },
  { stage: "jd", agent: "JD Analyst", task: "matching the posting" },
  { stage: "evaluate", agent: "Evaluator", task: "scoring the candidate" },
];
const ORDER = STEPS.map((s) => s.stage);

function Stepper({ stage, running, hasJd }: { stage: string; running: boolean; hasJd: boolean }) {
  const idx = ORDER.indexOf(stage);
  return (
    <Card className="space-y-1">
      {STEPS.map((s) => {
        const i = ORDER.indexOf(s.stage);
        const skipped = s.stage === "jd" && !hasJd;
        const done = !skipped && (!running || i < idx);
        const active = !skipped && running && i === idx;
        return (
          <div
            key={s.stage}
            className={cn(
              "flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors duration-200 [transition-timing-function:var(--ease)]",
              active && "bg-blue-soft",
              skipped && "opacity-40",
            )}
          >
            <span className="flex size-5 shrink-0 items-center justify-center">
              {active ? (
                <Spinner size={14} className="text-blue" />
              ) : done ? (
                <span className="flex size-5 items-center justify-center rounded-full bg-blue-soft text-[11px] font-semibold text-good">
                  ✓
                </span>
              ) : (
                <span
                  className={cn(
                    "size-2 rounded-full",
                    skipped ? "bg-[var(--ink-faint)]" : "bg-surface-2 ring-1 ring-line",
                  )}
                />
              )}
            </span>
            <span className={cn("font-medium", active ? "text-ink" : done ? "text-ink" : "text-ink-soft")}>
              {s.agent}
            </span>
            <span className="text-ink-faint">{skipped ? "skipped, no job description" : s.task}</span>
          </div>
        );
      })}
    </Card>
  );
}

/* ------------------------------------------------------------------ *
 * Drop zone
 * ------------------------------------------------------------------ */

function DropZone({ file, onFile }: { file: File | null; onFile: (f: File | null) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);

  const pick = useCallback((f?: File | null) => {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".pdf")) {
      setFileError(`"${f.name}" is not a PDF. Upload a .pdf resume.`);
      return;
    }
    setFileError(null);
    onFile(f);
  }, [onFile]);

  return (
    <div className="space-y-1.5">
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload resume PDF"
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
            <strong className="text-sm font-medium text-ink">Drop the resume PDF here</strong>
            <span className="text-xs text-ink-faint">or click to browse</span>
          </>
        )}
      </div>
      {fileError && <ErrorInline>{fileError}</ErrorInline>}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Page
 * ------------------------------------------------------------------ */

type JdTab = "url" | "text";

export default function AnalyzePage() {
  const [file, setFile] = useState<File | null>(null);
  const [tab, setTab] = useState<JdTab>("url");
  const [jdUrl, setJdUrl] = useState("");
  const [jdText, setJdText] = useState("");
  const [hasJd, setHasJd] = useState(false);

  const job = useJob<AnalysisResultData>("analyze");

  const submit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!file || job.running) return;

      const url = tab === "url" ? jdUrl.trim() : "";
      const text = tab === "text" ? jdText.trim() : "";
      setHasJd(!!(url || text));

      const fd = new FormData();
      fd.append("resume", file);
      fd.append("jd_url", url);
      fd.append("jd_text", text);

      await job.run(() => api<{ job_id: string }>("/analyze", { method: "POST", body: fd }));
    },
    [file, tab, jdUrl, jdText, job],
  );

  const seg =
    "flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors duration-150 [transition-timing-function:var(--ease)] cursor-pointer";

  return (
    <div className="mx-auto max-w-3xl space-y-8 px-5 py-10 md:px-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Analyze a candidate</h1>
        <p className="max-w-xl text-sm leading-relaxed text-ink-soft">
          Upload a resume and, optionally, a job posting. Four agents parse, enrich, match and score
          the candidate with evidence behind every number.
        </p>
      </header>

      <form onSubmit={submit} className="space-y-5">
        <DropZone file={file} onFile={setFile} />

        <Card className="space-y-4">
          <div className="flex items-baseline justify-between">
            <span className="text-sm font-medium text-ink">Job description</span>
            <span className="text-xs text-ink-faint">optional</span>
          </div>

          <div className="flex gap-1 rounded-lg bg-surface-2 p-1">
            <button
              type="button"
              aria-pressed={tab === "url"}
              onClick={() => setTab("url")}
              className={cn(seg, tab === "url" ? "bg-paper text-ink shadow-sm" : "text-ink-soft hover:text-ink")}
            >
              Posting URL
            </button>
            <button
              type="button"
              aria-pressed={tab === "text"}
              onClick={() => setTab("text")}
              className={cn(seg, tab === "text" ? "bg-paper text-ink shadow-sm" : "text-ink-soft hover:text-ink")}
            >
              Paste text
            </button>
          </div>

          {tab === "url" ? (
            <div className="space-y-1.5">
              <input
                type="url"
                value={jdUrl}
                onChange={(e) => setJdUrl(e.target.value)}
                placeholder="https://company.com/careers/senior-engineer"
                className="h-10 w-full rounded-lg border border-line bg-surface px-3 text-sm text-ink placeholder:text-ink-faint transition-[border-color,box-shadow] duration-150 [transition-timing-function:var(--ease)] focus:border-blue focus:outline-none focus:ring-[3px] focus:ring-[var(--blue-ring)]"
              />
              <p className="text-xs text-ink-faint">
                The JD Analyst fetches the page and scores fit against the resume.
              </p>
            </div>
          ) : (
            <textarea
              value={jdText}
              onChange={(e) => setJdText(e.target.value)}
              rows={6}
              placeholder="Paste the job description text"
              className="w-full resize-y rounded-lg border border-line bg-surface px-3 py-2 text-sm leading-relaxed text-ink placeholder:text-ink-faint transition-[border-color,box-shadow] duration-150 [transition-timing-function:var(--ease)] focus:border-blue focus:outline-none focus:ring-[3px] focus:ring-[var(--blue-ring)]"
            />
          )}
        </Card>

        <Button type="submit" size="lg" disabled={!file} loading={job.running} className="w-full">
          {job.running ? "Analyzing" : "Analyze candidate"}
        </Button>
      </form>

      {job.running && <Stepper stage={job.stage} running={job.running} hasJd={hasJd} />}

      {job.error && <ErrorInline>Analysis failed: {job.error}</ErrorInline>}

      {job.result && !job.running && <AnalysisResult data={job.result} />}
    </div>
  );
}
