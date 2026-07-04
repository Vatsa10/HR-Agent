"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { pollJob } from "@/lib/api";
import { cn, statusMark, verdictColor } from "@/lib/format";
import {
  Button,
  Card,
  Chip,
  Badge,
  Input,
  Select,
  Field,
  Spinner,
  Skeleton,
  EmptyState,
  ErrorInline,
  StatusDot,
} from "@/components/ui";

/* ------------------------------------------------------------------ *
 * Types
 * ------------------------------------------------------------------ */

interface Prefs {
  roles: string[];
  location: string;
  seniority: string;
}

interface Job {
  li_job_id: string;
  title?: string;
  company?: string;
  location?: string;
  url?: string;
  heuristic_score?: number | null;
  llm_score?: number | null;
  llm_reason?: string | null;
  seen?: boolean;
}

interface SavedJob extends Job {
  id: number;
  status?: string;
}

interface Requirement {
  requirement: string;
  kind: string;
  status: string;
  evidence?: string;
  suggestion?: string;
}

interface JdMatch {
  fit_score: number;
  verdict?: string;
  summary?: string;
  requirements?: Requirement[];
  missing_skills?: string[];
}

const SENIORITY = ["", "internship", "entry", "mid", "senior", "lead"];
const STATUSES = ["saved", "applied", "interviewing", "offer", "rejected", "archived"];

const MARK_COLOR: Record<string, string> = {
  good: "text-good",
  warn: "text-warn",
  bad: "text-bad",
  blue: "text-blue",
  neutral: "text-ink-soft",
};

/* ------------------------------------------------------------------ *
 * Deep match view (compact matcher, reused per card)
 * ------------------------------------------------------------------ */

function DeepMatch({ m }: { m: JdMatch }) {
  const vtone = verdictColor(m.verdict);
  const reqs = m.requirements || [];
  return (
    <div className="mt-4 rounded-lg border border-line bg-paper p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h4 className="text-sm font-semibold text-ink">Deep match</h4>
        <span className="font-mono text-lg tabular-nums text-ink">
          {Math.round(m.fit_score)}
          <span className="text-xs text-ink-faint">/100</span>
        </span>
        {m.verdict && <Badge tone={vtone}>{m.verdict.replace(/_/g, " ")}</Badge>}
      </div>
      {m.summary && <p className="mt-2 text-sm leading-relaxed text-ink-soft">{m.summary}</p>}

      {reqs.length > 0 && (
        <div className="mt-4 space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-ink-faint">
            Requirement breakdown
          </p>
          <div className="space-y-1.5">
            {reqs.map((r, i) => {
              const s = statusMark(r.status);
              return (
                <div key={i} className="flex gap-2.5 rounded-md border border-line bg-surface px-3 py-2">
                  <span className={cn("mt-0.5 shrink-0 font-mono text-sm", MARK_COLOR[s.tone])}>
                    {s.mark}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="text-sm text-ink">{r.requirement}</span>
                      <span className="text-[11px] uppercase tracking-wide text-ink-faint">
                        {r.kind === "must_have" ? "must have" : "nice to have"}
                      </span>
                    </div>
                    {r.evidence && <p className="mt-1 text-xs text-ink-soft">{r.evidence}</p>}
                    {r.suggestion && <p className="mt-1 text-xs text-blue">{r.suggestion}</p>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {(m.missing_skills || []).length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-medium uppercase tracking-wide text-ink-faint">Missing must-haves</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {m.missing_skills!.map((s, i) => (
              <Chip key={i} tone="bad">
                {s}
              </Chip>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Result card
 * ------------------------------------------------------------------ */

function ResultCard({
  job,
  resumeId,
  onSaved,
  onError,
}: {
  job: Job;
  resumeId: number | null;
  onSaved: () => void;
  onError: (m: string) => void;
}) {
  const router = useRouter();
  const [saving, setSaving] = useState(false);
  const [savedLabel, setSavedLabel] = useState<string | null>(null);
  const [tracking, setTracking] = useState(false);
  const [trackedLabel, setTrackedLabel] = useState<string | null>(null);
  const [tailoring, setTailoring] = useState(false);
  const [deepLoading, setDeepLoading] = useState(false);
  const [deep, setDeep] = useState<JdMatch | null>(null);

  const seen = job.seen === true;

  const guard = (fn: () => Promise<void>) => async () => {
    try {
      await fn();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Something went wrong";
      if (msg !== "unauthorized") onError(msg);
    }
  };

  const saveJob = () => api<SavedJob>("/jobs/save", { method: "POST", body: { job } });

  const onSave = guard(async () => {
    setSaving(true);
    try {
      await saveJob();
      setSavedLabel("Saved");
      onSaved();
    } finally {
      setSaving(false);
    }
  });

  const onTrack = guard(async () => {
    if (!job.company) {
      onError("No company on this job");
      return;
    }
    setTracking(true);
    try {
      await api("/companies/track", { method: "POST", body: { name: job.company } });
      setTrackedLabel("Tracked");
    } finally {
      setTracking(false);
    }
  });

  const onTailor = guard(async () => {
    setTailoring(true);
    try {
      const saved = await saveJob();
      const t = await api<{ jd_id?: number | null; resume_hint?: number | null }>(
        `/jobs/${saved.id}/tailor`,
        { method: "POST", body: {} },
      );
      const params = new URLSearchParams();
      if (t.jd_id != null) params.set("jd", String(t.jd_id));
      const resume = t.resume_hint != null ? t.resume_hint : resumeId;
      if (resume != null) params.set("resume", String(resume));
      router.push(`/builder?${params.toString()}`);
    } finally {
      setTailoring(false);
    }
  });

  const onDeep = guard(async () => {
    setDeepLoading(true);
    try {
      const saved = await saveJob();
      const m = await api<JdMatch>(`/jobs/${saved.id}/deep-match`, {
        method: "POST",
        body: { resume_id: resumeId },
      });
      setDeep(m);
      onSaved();
    } finally {
      setDeepLoading(false);
    }
  });

  return (
    <Card className={cn("flex flex-col gap-3", seen && "opacity-60")}>
      <div>
        <h3 className="flex items-center gap-2 text-base font-semibold text-ink">
          <span>{job.title || "Untitled role"}</span>
          {seen && (
            <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[11px] font-normal text-ink-faint">
              saved
            </span>
          )}
        </h3>
        <p className="mt-0.5 text-sm text-ink-soft">
          <span className="font-medium text-ink">{job.company || ""}</span>
          {job.location ? ` · ${job.location}` : ""}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {job.heuristic_score != null && (
          <Badge tone="neutral" mono title="Instant heuristic score">
            match {Math.round(job.heuristic_score)}
          </Badge>
        )}
        {job.llm_score != null && (
          <Badge tone="blue" mono title="LLM fit score against your resume">
            <StatusDot tone="blue" /> fit {Math.round(job.llm_score)}
          </Badge>
        )}
      </div>

      {job.llm_reason && <p className="text-sm leading-relaxed text-ink-soft">{job.llm_reason}</p>}

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onSave} loading={saving} disabled={!!savedLabel}>
          {savedLabel || "Save"}
        </Button>
        <Button variant="ghost" size="sm" onClick={onTailor} loading={tailoring}>
          Tailor resume
        </Button>
        <Button variant="ghost" size="sm" onClick={onTrack} loading={tracking} disabled={!!trackedLabel}>
          {trackedLabel || "Track company"}
        </Button>
        <Button variant="ghost" size="sm" onClick={onDeep} loading={deepLoading}>
          Deep match
        </Button>
        {job.url && (
          <a
            href={job.url}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto text-sm font-medium text-blue hover:underline"
          >
            Open
          </a>
        )}
      </div>

      {deep && <DeepMatch m={deep} />}
    </Card>
  );
}

/* ------------------------------------------------------------------ *
 * Skeletons
 * ------------------------------------------------------------------ */

function ResultCardSkeleton() {
  return (
    <Card className="flex flex-col gap-3">
      <div className="space-y-2">
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-4 w-1/3" />
      </div>
      <div className="flex gap-1.5">
        <Skeleton className="h-5 w-20" />
        <Skeleton className="h-5 w-16" />
      </div>
      <Skeleton className="h-4 w-full" />
      <div className="flex gap-2">
        <Skeleton className="h-8 w-16" />
        <Skeleton className="h-8 w-28" />
        <Skeleton className="h-8 w-32" />
      </div>
    </Card>
  );
}

function SavedRowSkeleton() {
  return (
    <Card className="flex items-center gap-3">
      <div className="min-w-0 flex-1 space-y-2">
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-3.5 w-1/3" />
      </div>
      <Skeleton className="h-5 w-16" />
      <Skeleton className="h-8 w-36" />
    </Card>
  );
}

/* ------------------------------------------------------------------ *
 * Page
 * ------------------------------------------------------------------ */

export default function JobsPage() {
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const [error, setError] = useState("");
  const flash = useCallback((m: string) => {
    if (!alive.current) return;
    setError(m);
    window.setTimeout(() => {
      if (alive.current) setError("");
    }, 6000);
  }, []);

  const [resumeId, setResumeId] = useState<number | null>(null);

  // prefs
  const [roles, setRoles] = useState<string[]>([]);
  const [roleInput, setRoleInput] = useState("");
  const [location, setLocation] = useState("");
  const [seniority, setSeniority] = useState("");
  const [prefsSaved, setPrefsSaved] = useState(false);
  const saveTimer = useRef<number | null>(null);

  // search
  const [searching, setSearching] = useState(false);
  const [searchStage, setSearchStage] = useState("");
  const [results, setResults] = useState<Job[] | null>(null);

  // saved
  const [saved, setSaved] = useState<SavedJob[] | null>(null);
  const [matchingAll, setMatchingAll] = useState(false);

  const savePrefs = useCallback(
    (next: Partial<Prefs>) => {
      const payload: Prefs = {
        roles: next.roles ?? roles,
        location: next.location ?? location,
        seniority: next.seniority ?? seniority,
      };
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(async () => {
        try {
          await api("/prefs", { method: "PUT", body: payload });
          setPrefsSaved(true);
          window.setTimeout(() => setPrefsSaved(false), 1800);
        } catch (e) {
          const msg = e instanceof Error ? e.message : "";
          if (msg && msg !== "unauthorized") flash(msg);
        }
      }, 500);
    },
    [roles, location, seniority, flash],
  );

  const addRole = (raw: string) => {
    const v = raw.trim();
    if (v && !roles.includes(v)) {
      const next = [...roles, v];
      setRoles(next);
      savePrefs({ roles: next });
    }
    setRoleInput("");
  };

  const removeRole = (i: number) => {
    const next = roles.filter((_, idx) => idx !== i);
    setRoles(next);
    savePrefs({ roles: next });
  };

  const loadSaved = useCallback(async () => {
    try {
      const items = await api<SavedJob[]>("/jobs/saved");
      if (alive.current) setSaved(items);
    } catch {
      /* 401 handled elsewhere */
    }
  }, []);

  useEffect(() => {
    // Fire each fetch independently so one slow call never blocks the others.
    (async () => {
      try {
        const resumes = await api<{ id: number }[]>("/resumes");
        if (alive.current && resumes.length) setResumeId(resumes[0].id);
      } catch {
        /* ignore */
      }
    })();
    (async () => {
      try {
        const p = await api<Prefs>("/prefs");
        if (!alive.current) return;
        setRoles(Array.isArray(p.roles) ? p.roles : []);
        setLocation(p.location || "");
        setSeniority(p.seniority || "");
      } catch {
        /* ignore */
      }
    })();
    loadSaved();
  }, [loadSaved]);

  const runSearch = async () => {
    setSearching(true);
    setResults(null);
    setSearchStage("Starting search...");
    try {
      const { job_id } = await api<{ job_id: string }>("/jobs/search", {
        method: "POST",
        body: { keywords: roles.join(" "), location: location.trim() },
      });
      const res = await pollJob<{ jobs?: Job[] }>(job_id, (_s, l) => {
        if (alive.current) setSearchStage(l || "Searching...");
      });
      if (alive.current) setResults(res.jobs || []);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Search failed";
      if (msg !== "unauthorized") flash(msg);
      if (alive.current) setResults([]);
    } finally {
      if (alive.current) {
        setSearching(false);
        setSearchStage("");
      }
    }
  };

  const sortedResults = useMemo(() => {
    if (!results) return null;
    return results.slice().sort((a, b) => Number(a.seen === true) - Number(b.seen === true));
  }, [results]);

  const setSavedStatus = async (id: number, status: string) => {
    try {
      await api(`/jobs/${id}/status`, { method: "PUT", body: { status } });
      setSaved((prev) => prev?.map((j) => (j.id === id ? { ...j, status } : j)) ?? prev);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "";
      if (msg && msg !== "unauthorized") flash(msg);
    }
  };

  const matchAll = async () => {
    setMatchingAll(true);
    try {
      await api("/jobs/batch-match", { method: "POST", body: { resume_id: resumeId } });
      await loadSaved();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "";
      if (msg && msg !== "unauthorized") flash(msg);
    } finally {
      if (alive.current) setMatchingAll(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-8 px-5 py-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Jobs</h1>
        <p className="max-w-2xl text-sm leading-relaxed text-ink-soft">
          Search LinkedIn for roles that match your preferences. Each result gets an instant
          heuristic score, and the top picks get a deeper LLM fit score against your latest resume.
        </p>
      </header>

      {/* Prefs bar */}
      <Card className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-[2fr_1.4fr_1fr]">
          <Field label="Roles" hint="Enter to add">
            <div className="flex min-h-10 flex-wrap items-center gap-1.5 rounded-lg border border-line bg-surface px-2 py-1.5">
              {roles.map((r, i) => (
                <span
                  key={r}
                  className="inline-flex items-center gap-1 rounded-full border border-line bg-paper px-2 py-0.5 text-xs text-ink"
                >
                  {r}
                  <button
                    type="button"
                    aria-label={`Remove ${r}`}
                    onClick={() => removeRole(i)}
                    className="text-ink-faint hover:text-ink"
                  >
                    ×
                  </button>
                </span>
              ))}
              <input
                value={roleInput}
                onChange={(e) => setRoleInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === ",") {
                    e.preventDefault();
                    addRole(roleInput);
                  } else if (e.key === "Backspace" && !roleInput && roles.length) {
                    removeRole(roles.length - 1);
                  }
                }}
                onBlur={() => roleInput.trim() && addRole(roleInput)}
                placeholder="Type a role"
                aria-label="Add role"
                className="min-w-[8ch] flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-faint"
              />
            </div>
          </Field>

          <Field label="Location">
            <Input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              onBlur={() => savePrefs({ location })}
              placeholder="Bengaluru, Remote..."
            />
          </Field>

          <Field label="Seniority">
            <Select
              value={seniority}
              onChange={(e) => {
                setSeniority(e.target.value);
                savePrefs({ seniority: e.target.value });
              }}
            >
              {SENIORITY.map((s) => (
                <option key={s} value={s}>
                  {s ? s[0].toUpperCase() + s.slice(1) : "Any"}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <div className="flex items-center gap-3">
          <Button onClick={runSearch} loading={searching}>
            Search jobs
          </Button>
          {prefsSaved && (
            <span className="flex items-center gap-1.5 text-xs text-good">
              <StatusDot tone="good" /> Preferences saved
            </span>
          )}
          <span className="ml-auto text-xs text-ink-faint">
            Manage defaults in{" "}
            <a href="/settings" className="text-blue hover:underline">
              Settings
            </a>
          </span>
        </div>
      </Card>

      {error && <ErrorInline>{error}</ErrorInline>}

      {/* Search status / results */}
      {searching && (
        <section className="space-y-4">
          <div className="flex items-center gap-2 text-sm text-ink-soft">
            <Spinner size={14} /> {searchStage || "Searching..."}
          </div>
          <div className="grid gap-4" aria-hidden="true">
            <ResultCardSkeleton />
            <ResultCardSkeleton />
            <ResultCardSkeleton />
          </div>
        </section>
      )}

      {sortedResults && !searching && (
        <section className="space-y-4">
          {sortedResults.length === 0 ? (
            <EmptyState
              title="No jobs found"
              hint="Try different roles or a broader location."
            />
          ) : (
            <div className="grid gap-4">
              {sortedResults.map((j) => (
                <ResultCard
                  key={j.li_job_id}
                  job={j}
                  resumeId={resumeId}
                  onSaved={loadSaved}
                  onError={flash}
                />
              ))}
            </div>
          )}
        </section>
      )}

      {/* Saved jobs */}
      <section className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-ink">Saved jobs</h2>
          <Button
            variant="ghost"
            size="sm"
            onClick={matchAll}
            loading={matchingAll}
            disabled={!saved || saved.length === 0}
          >
            Match all saved
          </Button>
        </div>

        {saved === null ? (
          <div className="space-y-2" aria-hidden="true">
            <SavedRowSkeleton />
            <SavedRowSkeleton />
            <SavedRowSkeleton />
          </div>
        ) : saved.length === 0 ? (
          <EmptyState
            title="No saved jobs yet"
            hint="Search above and hit Save on any card."
          />
        ) : (
          <div className="space-y-2">
            {saved.map((j) => (
              <Card key={j.id} className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium text-ink">{j.title || "Untitled"}</p>
                  <p className="truncate text-sm text-ink-soft">
                    {j.company || ""}
                    {j.location ? ` · ${j.location}` : ""}
                  </p>
                  {j.llm_reason && <p className="mt-1 text-xs text-ink-faint">{j.llm_reason}</p>}
                </div>
                {j.llm_score != null ? (
                  <Badge tone="blue" mono>
                    fit {Math.round(j.llm_score)}
                  </Badge>
                ) : j.heuristic_score != null ? (
                  <Badge tone="neutral" mono>
                    match {Math.round(j.heuristic_score)}
                  </Badge>
                ) : null}
                <Select
                  value={j.status || "saved"}
                  onChange={(e) => setSavedStatus(j.id, e.target.value)}
                  className="h-8 w-auto text-[13px] sm:w-36"
                >
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </Select>
                {j.url && (
                  <a
                    href={j.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm font-medium text-blue hover:underline"
                  >
                    Open
                  </a>
                )}
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
