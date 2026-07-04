// Small pure helpers shared across the app.

export type ClassValue = string | false | null | undefined;

/** Join truthy class names. */
export function cn(...parts: ClassValue[]): string {
  return parts.filter(Boolean).join(" ");
}

export type Tone = "good" | "warn" | "bad" | "neutral" | "blue";

/**
 * Map a JD-match verdict string to a tone. Backend verdicts vary in wording
 * (strong fit / good / partial / weak / no), so match loosely.
 */
export function verdictColor(verdict?: string | null): Tone {
  const v = (verdict || "").toLowerCase();
  if (!v) return "neutral";
  if (/strong|excellent|great|high/.test(v)) return "good";
  if (/good|fit\b|solid|match/.test(v)) return "good";
  if (/partial|moderate|maybe|medium|mixed/.test(v)) return "warn";
  if (/weak|low|poor|no fit|not|mismatch/.test(v)) return "bad";
  return "neutral";
}

export type Status = "met" | "partial" | "missing" | string;

/** Requirement / skill status -> a mark + tone for rendering. */
export function statusMark(status?: Status): { mark: string; tone: Tone; label: string } {
  const s = (status || "").toLowerCase();
  if (/met|yes|present|pass|have|full/.test(s)) return { mark: "✓", tone: "good", label: "Met" };
  if (/partial|some|weak|maybe/.test(s)) return { mark: "–", tone: "warn", label: "Partial" };
  if (/missing|no|absent|fail|gap/.test(s)) return { mark: "✗", tone: "bad", label: "Missing" };
  return { mark: "•", tone: "neutral", label: status || "Unknown" };
}

/** Clamp a numeric score into 0..100 for meters. */
export function pct(score: number, max = 100): number {
  if (!isFinite(score) || !isFinite(max) || max <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((score / max) * 100)));
}

/** Format an ISO date to a short readable string. */
export function shortDate(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
