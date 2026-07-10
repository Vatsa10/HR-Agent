"use client";

import * as React from "react";
import { Card, Badge, Chip, Meter } from "@/components/ui";
import { cn, pct, verdictColor, type Tone } from "@/lib/format";

/* ------------------------------------------------------------------ *
 * Types (mirror the backend analyze / analyses result shape)
 * ------------------------------------------------------------------ */

export interface CategoryScore {
  score: number;
  max: number;
  evidence?: string;
}

export interface Evaluation {
  scores: Record<string, CategoryScore>;
  bonus_points: { total: number; breakdown?: string };
  deductions: { total: number; reasons?: string };
  key_strengths: string[];
  areas_for_improvement: string[];
}

export type ReqStatus = "met" | "partial" | "missing" | string;

export interface Requirement {
  requirement: string;
  kind?: string;
  status?: ReqStatus;
  evidence?: string;
  suggestion?: string;
}

export interface FitDimension {
  name: string;
  score: number;
  note?: string;
}

export interface JdMatch {
  fit_score: number;
  band?: string;
  dimensions?: FitDimension[];
  strengths?: string[];
  gaps?: string[];
  verdict?: string;
  summary?: string;
  experience_match?: string;
  matching_skills?: string[];
  missing_skills?: string[];
  bonus_matched?: string[];
  requirements?: Requirement[];
  ats_keywords?: { present?: string[]; absent?: string[]; have_add?: string[]; real_gap?: string[] };
}

export interface AnalysisResultData {
  candidate?: string;
  total_score?: number;
  max_score?: number;
  evaluation?: Evaluation | null;
  jd_match?: JdMatch | null;
  errors?: string[];
}

const CAT_LABELS: Record<string, string> = {
  open_source: "Open source",
  self_projects: "Self projects",
  production: "Production experience",
  technical_skills: "Technical skills",
};

const REQ_MARK: Record<string, { mark: string; tone: Tone; label: string }> = {
  met: { mark: "✓", tone: "good", label: "met" },
  partial: { mark: "◑", tone: "warn", label: "partial" },
  missing: { mark: "✕", tone: "bad", label: "missing" },
};

function meterTone(p: number): Tone {
  if (p >= 70) return "good";
  if (p >= 40) return "warn";
  return "bad";
}

/* ------------------------------------------------------------------ *
 * Sub-sections
 * ------------------------------------------------------------------ */

function SkillChips({ label, items, tone }: { label: string; items?: string[]; tone: Tone }) {
  if (!items || !items.length) return null;
  return (
    <div>
      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-faint">{label}</p>
      <div className="flex flex-wrap gap-1.5">
        {items.map((s, i) => (
          <Chip key={i} tone={tone}>
            {s}
          </Chip>
        ))}
      </div>
    </div>
  );
}

function Requirements({ reqs }: { reqs?: Requirement[] }) {
  if (!reqs || !reqs.length) return null;
  return (
    <div>
      <p className="mb-2.5 text-xs font-medium uppercase tracking-wide text-ink-faint">
        Requirement breakdown
      </p>
      <div className="flex flex-col divide-y divide-line rounded-lg border border-line">
        {reqs.map((r, i) => {
          const key = ["met", "partial", "missing"].includes(String(r.status)) ? String(r.status) : "partial";
          const m = REQ_MARK[key];
          return (
            <div key={i} className="flex gap-3 p-3.5">
              <span
                aria-label={m.label}
                className={cn(
                  "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold",
                  m.tone === "good" && "bg-blue-soft text-good",
                  m.tone === "warn" && "bg-surface-2 text-warn",
                  m.tone === "bad" && "bg-surface-2 text-bad",
                )}
              >
                {m.mark}
              </span>
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="text-sm font-medium text-ink">{r.requirement}</span>
                  <span className="text-[11px] uppercase tracking-wide text-ink-faint">
                    {r.kind === "must_have" ? "must have" : "nice to have"}
                  </span>
                </div>
                {r.evidence && <p className="text-sm text-ink-soft">{r.evidence}</p>}
                {r.suggestion && <p className="text-sm text-blue">{r.suggestion}</p>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DimensionBars({ dims, band }: { dims?: FitDimension[]; band?: string }) {
  if (!dims?.length) return null;
  const bandTone: Tone =
    band === "shortlist" ? "good" : band === "excluded" ? "bad" : "blue";
  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-ink-faint">Fit by dimension</p>
        {band && <Badge tone={bandTone}>{band}</Badge>}
      </div>
      {dims.map((d, i) => {
        const s = Math.max(0, Math.min(100, d.score));
        const tone = s >= 70 ? "var(--good)" : s >= 45 ? "var(--blue)" : "var(--bad)";
        return (
          <div key={i} className="space-y-1">
            <div className="flex items-baseline justify-between text-sm">
              <span className="font-medium capitalize text-ink">{d.name}</span>
              <span className="font-mono text-xs tabular-nums text-ink-soft">{s}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
              <div className="h-full rounded-full" style={{ width: `${s}%`, background: tone }} />
            </div>
            {d.note && <p className="text-xs text-ink-faint">{d.note}</p>}
          </div>
        );
      })}
    </div>
  );
}

function AtsKeywords({ ats }: { ats?: JdMatch["ats_keywords"] }) {
  const present = ats?.present || [];
  // 4-state taxonomy: prefer have_add / real_gap when present, else fall back to absent.
  const haveAdd = ats?.have_add || [];
  const realGap = ats?.real_gap || [];
  const absent = ats?.absent || [];
  const showSplit = haveAdd.length > 0 || realGap.length > 0;
  if (!present.length && !absent.length && !showSplit) return null;
  return (
    <div className="space-y-3">
      <SkillChips label="ATS keywords present" items={present} tone="good" />
      {showSplit ? (
        <>
          {haveAdd.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-faint">
                You have this — surface it truthfully
              </p>
              <div className="flex flex-wrap gap-1.5">
                {haveAdd.map((s, i) => (
                  <Chip key={i} tone="blue">{s}</Chip>
                ))}
              </div>
            </div>
          )}
          {realGap.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-faint">
                Genuine gaps
              </p>
              <div className="flex flex-wrap gap-1.5">
                {realGap.map((s, i) => (
                  <Chip key={i} tone="bad">{s}</Chip>
                ))}
              </div>
            </div>
          )}
        </>
      ) : (
        absent.length > 0 && (
          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-faint">
              Not found in the resume
            </p>
            <div className="flex flex-wrap gap-1.5">
              {absent.map((s, i) => (
                <Chip key={i} tone="bad">{s}</Chip>
              ))}
            </div>
          </div>
        )
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Main renderer
 * ------------------------------------------------------------------ */

export interface AnalysisResultProps {
  data: AnalysisResultData;
  className?: string;
}

export function AnalysisResult({ data, className }: AnalysisResultProps) {
  const ev = data.evaluation;
  const m = data.jd_match;

  return (
    <div className={cn("space-y-6", className)}>
      {/* Score card */}
      {ev && (
        <Card className="space-y-5">
          <div className="flex items-end justify-between gap-4 border-b border-line pb-4">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-ink-faint">Candidate</p>
              <h2 className="mt-1 text-xl font-semibold tracking-tight text-ink">
                {data.candidate || "Unknown candidate"}
              </h2>
            </div>
            <div className="text-right">
              <span className="font-mono text-3xl font-semibold tabular-nums text-ink">
                {data.total_score ?? "–"}
              </span>
              <span className="font-mono text-sm text-ink-faint"> / {data.max_score ?? 100}</span>
            </div>
          </div>

          <div className="grid gap-5 sm:grid-cols-2">
            {Object.entries(ev.scores).map(([key, c]) => {
              const p = pct(Math.min(c.score, c.max), c.max);
              return (
                <div key={key} className="space-y-1.5">
                  <Meter
                    value={Math.min(c.score, c.max)}
                    max={c.max}
                    tone={meterTone(p)}
                    showValue
                    label={CAT_LABELS[key] || key}
                  />
                  {c.evidence && <p className="text-sm text-ink-soft">{c.evidence}</p>}
                </div>
              );
            })}
          </div>

          <div className="flex flex-wrap gap-3 border-t border-line pt-4">
            <div className="flex-1 min-w-[200px] space-y-1">
              <Badge tone="good">Bonus +{ev.bonus_points.total}</Badge>
              {ev.bonus_points.breakdown && (
                <p className="text-sm text-ink-soft">{ev.bonus_points.breakdown}</p>
              )}
            </div>
            {ev.deductions.total > 0 && (
              <div className="flex-1 min-w-[200px] space-y-1">
                <Badge tone="bad">Deductions −{ev.deductions.total}</Badge>
                {ev.deductions.reasons && (
                  <p className="text-sm text-ink-soft">{ev.deductions.reasons}</p>
                )}
              </div>
            )}
          </div>
        </Card>
      )}

      {/* JD fit card */}
      {m && (
        <Card className="space-y-5">
          <div className="flex flex-wrap items-center gap-3 border-b border-line pb-4">
            <h2 className="text-lg font-semibold tracking-tight text-ink">Job description fit</h2>
            <span className="font-mono text-lg font-semibold tabular-nums text-ink">
              {m.fit_score}
              <span className="text-sm text-ink-faint">/100</span>
            </span>
            {m.verdict && (
              <Badge tone={verdictColor(m.verdict)}>{m.verdict.replace(/_/g, " ")}</Badge>
            )}
          </div>

          {m.summary && <p className="text-sm leading-relaxed text-ink-soft">{m.summary}</p>}
          {m.experience_match && (
            <p className="text-sm leading-relaxed text-ink-soft">{m.experience_match}</p>
          )}

          <DimensionBars dims={m.dimensions} band={m.band} />
          {(m.strengths?.length || m.gaps?.length) ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <SkillChips label="Strengths" items={m.strengths} tone="good" />
              <SkillChips label="Honest gaps" items={m.gaps} tone="bad" />
            </div>
          ) : null}

          <Requirements reqs={m.requirements} />
          <SkillChips label="Matching skills" items={m.matching_skills} tone="good" />
          <SkillChips label="Bonus (nice-to-have) matched" items={m.bonus_matched} tone="blue" />
          <SkillChips label="Missing skills" items={m.missing_skills} tone="bad" />
          <AtsKeywords ats={m.ats_keywords} />
        </Card>
      )}

      {/* Strengths / improvements */}
      {ev && (ev.key_strengths?.length || ev.areas_for_improvement?.length) ? (
        <div className="grid gap-6 sm:grid-cols-2">
          <Card>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-faint">
              Key strengths
            </h2>
            <ol className="space-y-2">
              {ev.key_strengths.map((s, i) => (
                <li key={i} className="flex gap-2.5 text-sm text-ink-soft">
                  <span className="font-mono text-xs text-good">{String(i + 1).padStart(2, "0")}</span>
                  <span>{s}</span>
                </li>
              ))}
            </ol>
          </Card>
          <Card>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-faint">
              Areas for improvement
            </h2>
            <ol className="space-y-2">
              {ev.areas_for_improvement.map((s, i) => (
                <li key={i} className="flex gap-2.5 text-sm text-ink-soft">
                  <span className="font-mono text-xs text-warn">{String(i + 1).padStart(2, "0")}</span>
                  <span>{s}</span>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      ) : null}

      {data.errors && data.errors.length > 0 && (
        <p className="text-sm text-ink-faint">Notes: {data.errors.join(" · ")}</p>
      )}
    </div>
  );
}

export default AnalysisResult;
