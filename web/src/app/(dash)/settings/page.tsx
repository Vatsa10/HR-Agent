"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import {
  Button,
  Input,
  Textarea,
  Select,
  Field,
  Label,
  Card,
  Chip,
  Skeleton,
  ErrorInline,
} from "@/components/ui";
import { cn } from "@/lib/format";

/* ------------------------------------------------------------------ *
 * Types
 * ------------------------------------------------------------------ */

interface Me {
  email: string;
  github_url?: string | null;
  extras?: Record<string, unknown> | null;
}
interface Block {
  title: string;
  body: string;
}
interface Resume {
  id: number | string;
  filename: string;
  created_at?: string;
}
interface Prefs {
  roles?: string[];
  location?: string;
  seniority?: string;
  work_type?: string;
}

const SENIORITY = [
  { value: "", label: "Any" },
  { value: "internship", label: "Internship" },
  { value: "entry", label: "Entry" },
  { value: "associate", label: "Associate" },
  { value: "mid_senior", label: "Mid-Senior" },
  { value: "director", label: "Director" },
  { value: "executive", label: "Executive" },
];

const WORK_TYPES = [
  { value: "", label: "Any" },
  { value: "remote", label: "Remote" },
  { value: "on_site", label: "On-site" },
  { value: "hybrid", label: "Hybrid" },
];

// Older prefs may store legacy seniority labels (mid/senior/lead...). Map them
// onto the experience tokens above so the Select lands on a valid option.
const SENIORITY_ALIAS: Record<string, string> = {
  mid: "mid_senior",
  senior: "mid_senior",
  junior: "entry",
  lead: "director",
  exec: "executive",
};
function normalizeSeniority(v: string): string {
  const s = (v || "").trim().toLowerCase();
  if (SENIORITY.some((o) => o.value === s)) return s;
  return SENIORITY_ALIAS[s] ?? "";
}

/* ------------------------------------------------------------------ *
 * Shared section shell
 * ------------------------------------------------------------------ */

function Section({
  title,
  desc,
  children,
  footer,
}: {
  title: string;
  desc?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <Card padded={false} className="overflow-hidden">
      <div className="border-b border-line px-5 py-4">
        <h2 className="text-[15px] font-semibold tracking-tight text-ink">{title}</h2>
        {desc && <p className="mt-0.5 text-sm text-ink-soft">{desc}</p>}
      </div>
      <div className="px-5 py-5">{children}</div>
      {footer && (
        <div className="flex items-center justify-end gap-3 border-t border-line bg-surface-2/40 px-5 py-3">
          {footer}
        </div>
      )}
    </Card>
  );
}

function SavedFlash({ show }: { show: boolean }) {
  return (
    <span
      className={cn(
        "flex items-center gap-1.5 text-sm text-good transition-opacity duration-200 [transition-timing-function:var(--ease)]",
        show ? "opacity-100" : "pointer-events-none opacity-0",
      )}
      aria-live="polite"
    >
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M20 6 9 17l-5-5" />
      </svg>
      Saved
    </span>
  );
}

function useFlash(): [boolean, () => void] {
  const [show, setShow] = React.useState(false);
  const t = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const flash = React.useCallback(() => {
    setShow(true);
    if (t.current) clearTimeout(t.current);
    t.current = setTimeout(() => setShow(false), 2400);
  }, []);
  React.useEffect(() => () => { if (t.current) clearTimeout(t.current); }, []);
  return [show, flash];
}

/* skeleton for a labelled control while a section loads */
function FieldSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <Skeleton className="h-3.5 w-24" />
      <Skeleton className="h-10 w-full" />
    </div>
  );
}

/* auto-growing textarea for content blocks */
function AutoTextarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ref = React.useRef<HTMLTextAreaElement>(null);
  const grow = React.useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.max(88, el.scrollHeight) + "px";
  }, []);
  React.useEffect(grow, [grow, props.value]);
  return (
    <Textarea
      ref={ref}
      {...props}
      rows={3}
      className={cn("resize-none overflow-hidden", props.className)}
      onInput={grow}
    />
  );
}

/* ------------------------------------------------------------------ *
 * Page
 * ------------------------------------------------------------------ */

export default function SettingsPage() {
  const router = useRouter();

  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState<string | null>(null);

  // account
  const [email, setEmail] = React.useState("");
  const [loggingOut, setLoggingOut] = React.useState(false);

  // profile context
  const [github, setGithub] = React.useState("");
  const [linkedinUrl, setLinkedinUrl] = React.useState("");
  const [linkedinResumeId, setLinkedinResumeId] = React.useState("");
  const [blocks, setBlocks] = React.useState<Block[]>([]);
  const [resumes, setResumes] = React.useState<Resume[]>([]);
  const [profileSaving, setProfileSaving] = React.useState(false);
  const [profileErr, setProfileErr] = React.useState<string | null>(null);
  const [profileFlash, flashProfile] = useFlash();

  // prefs
  const [roles, setRoles] = React.useState<string[]>([]);
  const [roleInput, setRoleInput] = React.useState("");
  const [location, setLocation] = React.useState("");
  const [seniority, setSeniority] = React.useState("");
  const [workType, setWorkType] = React.useState("");
  const [prefsSaving, setPrefsSaving] = React.useState(false);
  const [prefsErr, setPrefsErr] = React.useState<string | null>(null);
  const [prefsFlash, flashPrefs] = useFlash();

  const handleAuth = React.useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) {
        router.push("/signin");
        return true;
      }
      return false;
    },
    [router],
  );

  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        // One concurrent round-trip instead of three separate requests.
        const boot = await api<{ me: Me; resumes: Resume[]; prefs: Prefs }>("/bootstrap");
        if (!alive) return;
        const me = boot.me || ({} as Me);
        const res = boot.resumes || [];
        const prefs = boot.prefs || ({} as Prefs);
        setEmail(me.email || "");
        setGithub(me.github_url || "");
        const extras = (me.extras || {}) as Record<string, unknown>;
        setLinkedinUrl(typeof extras.linkedin_url === "string" ? extras.linkedin_url : "");
        setLinkedinResumeId(
          extras.linkedin_resume_id != null ? String(extras.linkedin_resume_id) : "",
        );
        if (Array.isArray(extras.blocks)) {
          setBlocks(
            (extras.blocks as Block[]).map((b) => ({
              title: b?.title || "",
              body: b?.body || "",
            })),
          );
        } else {
          // backward compat: flat {key: value} dict -> blocks
          const legacy: Block[] = [];
          for (const [k, v] of Object.entries(extras)) {
            if (k === "blocks" || k === "linkedin_url" || k === "linkedin_resume_id") continue;
            legacy.push({ title: k, body: typeof v === "string" ? v : JSON.stringify(v) });
          }
          setBlocks(legacy);
        }
        setResumes(Array.isArray(res) ? res : []);
        setRoles(Array.isArray(prefs.roles) ? prefs.roles : []);
        setLocation(prefs.location || "");
        setSeniority(normalizeSeniority(prefs.seniority || ""));
        setWorkType(prefs.work_type || "");
      } catch (e) {
        if (!alive) return;
        if (!handleAuth(e)) {
          setLoadError(e instanceof Error ? e.message : "Failed to load settings.");
        }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [handleAuth]);

  const linkedinResumes = React.useMemo(
    () => resumes.filter((r) => (r.filename || "").startsWith("LinkedIn:")),
    [resumes],
  );

  /* ---------- actions ---------- */

  async function logout() {
    setLoggingOut(true);
    try {
      await api("/logout", { method: "POST" });
    } catch {
      /* clear regardless */
    }
    router.push("/signin");
  }

  async function saveProfile() {
    setProfileErr(null);
    setProfileSaving(true);
    const cleaned = blocks
      .map((b) => ({ title: b.title.trim(), body: b.body.trim() }))
      .filter((b) => b.title || b.body);
    try {
      await api("/me", {
        method: "PUT",
        body: {
          github_url: github.trim(),
          extras: {
            blocks: cleaned,
            linkedin_url: linkedinUrl.trim(),
            linkedin_resume_id: linkedinResumeId || null,
          },
        },
      });
      setBlocks(cleaned);
      flashProfile();
    } catch (e) {
      if (!handleAuth(e)) setProfileErr(e instanceof Error ? e.message : "Failed to save.");
    } finally {
      setProfileSaving(false);
    }
  }

  async function savePrefs() {
    setPrefsErr(null);
    setPrefsSaving(true);
    try {
      await api("/prefs", {
        method: "PUT",
        body: { roles, location: location.trim(), seniority, work_type: workType },
      });
      flashPrefs();
    } catch (e) {
      if (!handleAuth(e)) setPrefsErr(e instanceof Error ? e.message : "Failed to save.");
    } finally {
      setPrefsSaving(false);
    }
  }

  function addRole(raw: string) {
    const v = raw.trim().replace(/,$/, "").trim();
    if (!v) return;
    setRoles((cur) => (cur.some((r) => r.toLowerCase() === v.toLowerCase()) ? cur : [...cur, v]));
    setRoleInput("");
  }

  function onRoleKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addRole(roleInput);
    } else if (e.key === "Backspace" && !roleInput && roles.length) {
      setRoles((cur) => cur.slice(0, -1));
    }
  }

  /* ---------- render ---------- */

  return (
    <div className="mx-auto max-w-2xl">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Settings</h1>
        <p className="mt-1 text-sm text-ink-soft">
          Your account, the context Do Apply uses to tailor, and your job preferences.
        </p>
      </header>

      {loadError && (
        <div className="mb-6">
          <ErrorInline>{loadError}</ErrorInline>
        </div>
      )}

      <div className="flex flex-col gap-6">
        {/* Account */}
        <Section title="Account" desc="You are signed in with this email.">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <Field label="Email" className="min-w-[220px] flex-1">
              {loading ? (
                <Skeleton className="h-10 w-full" />
              ) : (
                <Input value={email} readOnly disabled aria-label="Email" />
              )}
            </Field>
            <Button variant="ghost" onClick={logout} loading={loggingOut} disabled={loading}>
              Log out
            </Button>
          </div>
        </Section>

        {/* Profile context */}
        <Section
          title="Profile context"
          desc="Extra signal Do Apply weaves into analysis and tailored resumes. Nothing is invented, this is your material."
          footer={
            <>
              <SavedFlash show={profileFlash} />
              <Button onClick={saveProfile} loading={profileSaving} disabled={loading}>
                Save profile
              </Button>
            </>
          }
        >
          {loading ? (
            <div className="flex flex-col gap-5">
              <FieldSkeleton />
              <div className="grid gap-5 sm:grid-cols-2">
                <FieldSkeleton />
                <FieldSkeleton />
              </div>
              <Skeleton className="h-24 w-full" />
            </div>
          ) : (
          <div className="flex flex-col gap-5">
            {profileErr && <ErrorInline>{profileErr}</ErrorInline>}

            <Field
              label="GitHub URL"
              hint="optional"
              htmlFor="github"
            >
              <Input
                id="github"
                type="url"
                placeholder="https://github.com/you"
                value={github}
                onChange={(e) => setGithub(e.target.value)}
              />
            </Field>

            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="LinkedIn URL" hint="optional" htmlFor="linkedin">
                <Input
                  id="linkedin"
                  type="url"
                  placeholder="https://linkedin.com/in/you"
                  value={linkedinUrl}
                  onChange={(e) => setLinkedinUrl(e.target.value)}
                />
              </Field>
              <Field
                label="Imported LinkedIn resume"
                hint="from LinkedIn import"
                htmlFor="linkedin-resume"
              >
                <Select
                  id="linkedin-resume"
                  value={linkedinResumeId}
                  onChange={(e) => setLinkedinResumeId(e.target.value)}
                >
                  <option value="">None</option>
                  {linkedinResumes.map((r) => (
                    <option key={r.id} value={String(r.id)}>
                      {r.filename.replace(/^LinkedIn:\s*/, "") || `Resume ${r.id}`}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>

            {/* Content blocks */}
            <div className="flex flex-col gap-3">
              <div className="flex items-baseline justify-between">
                <Label className="block">Your content</Label>
                <span className="text-xs text-ink-faint">
                  Certifications, achievements, anything worth surfacing.
                </span>
              </div>

              {blocks.length === 0 && (
                <p className="rounded-lg border border-dashed border-line bg-surface-2/40 px-4 py-6 text-center text-sm text-ink-faint">
                  No blocks yet. Add one to give the tailoring engine more to work with.
                </p>
              )}

              <div className="flex flex-col gap-3">
                {blocks.map((b, i) => (
                  <div
                    key={i}
                    className="rounded-xl border border-line bg-paper p-3"
                  >
                    <div className="mb-2 flex items-center gap-2">
                      <Input
                        aria-label="Block title"
                        placeholder="Title (e.g. Certifications)"
                        className="h-9 border-transparent bg-transparent px-2 text-sm font-medium focus:border-blue"
                        value={b.title}
                        onChange={(e) =>
                          setBlocks((cur) =>
                            cur.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)),
                          )
                        }
                      />
                      <button
                        type="button"
                        aria-label="Remove block"
                        onClick={() => setBlocks((cur) => cur.filter((_, j) => j !== i))}
                        className="grid size-8 shrink-0 place-items-center rounded-md text-ink-faint transition-colors hover:bg-surface-2 hover:text-bad"
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" aria-hidden>
                          <path d="M6 6l12 12M18 6L6 18" />
                        </svg>
                      </button>
                    </div>
                    <AutoTextarea
                      aria-label="Block body"
                      placeholder="Body text. One item per line works well."
                      value={b.body}
                      onChange={(e) =>
                        setBlocks((cur) =>
                          cur.map((x, j) => (j === i ? { ...x, body: e.target.value } : x)),
                        )
                      }
                    />
                  </div>
                ))}
              </div>

              <div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setBlocks((cur) => [...cur, { title: "", body: "" }])}
                >
                  <span aria-hidden className="text-base leading-none">+</span>
                  Add block
                </Button>
              </div>
            </div>
          </div>
          )}
        </Section>

        {/* Job preferences */}
        <Section
          title="Job preferences"
          desc="Used to focus job search and recruiter search on roles that fit."
          footer={
            <>
              <SavedFlash show={prefsFlash} />
              <Button onClick={savePrefs} loading={prefsSaving} disabled={loading}>
                Save preferences
              </Button>
            </>
          }
        >
          {loading ? (
            <div className="flex flex-col gap-5">
              <FieldSkeleton />
              <div className="grid gap-5 sm:grid-cols-3">
                <FieldSkeleton />
                <FieldSkeleton />
                <FieldSkeleton />
              </div>
            </div>
          ) : (
          <div className="flex flex-col gap-5">
            {prefsErr && <ErrorInline>{prefsErr}</ErrorInline>}

            <Field label="Roles" hint="press Enter to add" htmlFor="roles-input">
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-surface px-2.5 py-2 focus-within:border-blue focus-within:ring-[3px] focus-within:ring-[var(--blue-ring)]">
                {roles.map((r) => (
                  <Chip key={r} active className="gap-1.5 pr-1.5">
                    {r}
                    <button
                      type="button"
                      aria-label={`Remove ${r}`}
                      onClick={() => setRoles((cur) => cur.filter((x) => x !== r))}
                      className="grid size-4 place-items-center rounded-full text-blue/70 hover:bg-blue/10 hover:text-blue"
                    >
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" aria-hidden>
                        <path d="M6 6l12 12M18 6L6 18" />
                      </svg>
                    </button>
                  </Chip>
                ))}
                <input
                  id="roles-input"
                  value={roleInput}
                  onChange={(e) => setRoleInput(e.target.value)}
                  onKeyDown={onRoleKey}
                  onBlur={() => addRole(roleInput)}
                  placeholder={roles.length ? "" : "Frontend Engineer, Data Scientist..."}
                  className="h-7 min-w-[140px] flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-faint"
                />
              </div>
            </Field>

            <div className="grid gap-5 sm:grid-cols-3">
              <Field label="Location" htmlFor="location">
                <Input
                  id="location"
                  placeholder="Bengaluru, Remote..."
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                />
              </Field>
              <Field label="Work type" htmlFor="work-type">
                <Select
                  id="work-type"
                  value={workType}
                  onChange={(e) => setWorkType(e.target.value)}
                >
                  {WORK_TYPES.map((w) => (
                    <option key={w.value} value={w.value}>
                      {w.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Seniority" htmlFor="seniority">
                <Select
                  id="seniority"
                  value={seniority}
                  onChange={(e) => setSeniority(e.target.value)}
                >
                  {SENIORITY.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
          </div>
          )}
        </Section>
      </div>
    </div>
  );
}
