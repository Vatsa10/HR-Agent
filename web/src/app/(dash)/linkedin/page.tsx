"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useJob } from "@/hooks/useJob";
import { Button, Card, Field, Input, Spinner, StatusDot, ErrorInline } from "@/components/ui";

interface ImportResult {
  resume_id: number;
  candidate?: string;
  parsed_summary?: {
    work?: number;
    education?: number;
    skills?: number;
    [k: string]: number | undefined;
  };
}

function validUrl(v: string) {
  return /linkedin\.com\/in\//.test(v.trim());
}

export default function LinkedInPage() {
  const [sessionOk, setSessionOk] = useState<boolean | null>(null);
  const [url, setUrl] = useState("");
  const job = useJob<ImportResult>();

  async function checkStatus() {
    try {
      const s = await api<{ session: boolean }>("/linkedin/status");
      setSessionOk(!!s.session);
    } catch {
      setSessionOk(false);
    }
  }

  useEffect(() => {
    checkStatus();
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!sessionOk || !validUrl(url) || job.running) return;
    const res = await job.run(() =>
      api<{ job_id: string }>("/import/linkedin", {
        method: "POST",
        body: { url: url.trim() },
      }),
    );
    // If the session went stale mid-import, reflect it in status.
    if (!res && job.error && /session not found/i.test(job.error)) setSessionOk(false);
  }

  const canImport = !!sessionOk && validUrl(url) && !job.running;
  const result = job.result;
  const summary = result?.parsed_summary || {};

  return (
    <div className="mx-auto max-w-[720px]">
      <header className="mb-8">
        <h1 className="text-xl font-semibold tracking-tight text-ink">LinkedIn Import</h1>
        <p className="mt-1.5 max-w-[58ch] text-sm text-ink-soft">
          Import your LinkedIn profile as a resume source. Scraping runs locally with your own
          logged-in session. Nothing is shared.
        </p>
      </header>

      {/* Session status */}
      <Card className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-ink">Session</h2>
          <div className="flex items-center gap-2 text-sm font-medium">
            {sessionOk === null ? (
              <>
                <Spinner size={14} className="text-ink-faint" />
                <span className="text-ink-soft">Checking session...</span>
              </>
            ) : sessionOk ? (
              <>
                <StatusDot tone="good" />
                <span className="text-ink">Session ready</span>
              </>
            ) : (
              <>
                <StatusDot tone="neutral" />
                <span className="text-ink-soft">No session found</span>
              </>
            )}
          </div>
        </div>

        {sessionOk === false && (
          <div className="space-y-3 border-t border-line pt-3">
            <p className="text-xs text-ink-faint">
              No LinkedIn session found. Set one up once:
            </p>
            <ol className="space-y-3 pl-5 text-sm text-ink-soft [list-style:decimal]">
              <li>
                Everything is already installed. In the project folder, run:
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
                in the project root. Keep this file private. It is your login.
              </li>
            </ol>
            <Button variant="ghost" size="sm" onClick={checkStatus}>
              Refresh status
            </Button>
          </div>
        )}
      </Card>

      {/* Import form */}
      <form onSubmit={submit} className="mt-6">
        <Field
          label="Profile URL"
          htmlFor="li-url"
          hint="linkedin.com/in/your-handle"
        >
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
        <Button type="submit" disabled={!canImport} loading={job.running} className="mt-4">
          {job.running ? "Scraping profile..." : "Import profile"}
        </Button>
      </form>

      {/* Live pipeline */}
      {job.running && (
        <Card className="mt-6 flex items-center gap-3 text-sm text-ink-soft">
          <StatusDot tone="blue" pulse />
          {job.label || "Scraping profile via your session"}
        </Card>
      )}

      {/* Error */}
      {job.error && !job.running && (
        <ErrorInline className="mt-6">Import failed: {job.error}</ErrorInline>
      )}

      {/* Result */}
      {result && !job.running && (
        <Card className="mt-6 space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-ink">Imported</h2>
            <p className="mt-1 text-base font-semibold tracking-tight text-ink">
              {result.candidate || "Unnamed profile"}
            </p>
          </div>
          <div className="flex flex-wrap gap-8">
            {[
              { n: summary.work || 0, label: "work entries" },
              { n: summary.education || 0, label: "education" },
              { n: summary.skills || 0, label: "skills" },
            ].map((c) => (
              <div key={c.label}>
                <div className="font-mono text-xl font-semibold tabular-nums text-ink">{c.n}</div>
                <div className="text-xs text-ink-faint">{c.label}</div>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
            <Link href="/builder">
              <Button variant="ghost" size="sm">
                Open Builder
              </Button>
            </Link>
            <span className="text-xs text-ink-faint">
              Or analyze it. The profile now appears in your saved resumes.
            </span>
          </div>
        </Card>
      )}
    </div>
  );
}
