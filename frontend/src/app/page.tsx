"use client";

import * as React from "react";
import Link from "next/link";
import { cn } from "@/lib/format";
import { Logo } from "@/components/Logo";

/* ================================================================== *
 * Scroll-reveal primitive (transform/opacity, --ease)
 * ================================================================== */

function Reveal({
  children,
  delay = 0,
  className,
  as: Tag = "div",
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
  as?: React.ElementType;
}) {
  const ref = React.useRef<HTMLDivElement | null>(null);
  const [shown, setShown] = React.useState(false);

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced || typeof IntersectionObserver === "undefined") {
      setShown(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            setShown(true);
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.15, rootMargin: "0px 0px -8% 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <Tag
      ref={ref}
      className={cn(
        "transition-[opacity,transform] duration-700 [transition-timing-function:var(--ease)] will-change-transform",
        shown ? "opacity-100 translate-y-0" : "opacity-0 translate-y-6",
        className,
      )}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {children}
    </Tag>
  );
}

/* ================================================================== *
 * Browser chrome frame
 * ================================================================== */

function BrowserFrame({
  url = "doapply.online",
  children,
  className,
}: {
  url?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border border-line bg-paper shadow-[0_24px_60px_-24px_rgba(20,30,60,0.35)]",
        className,
      )}
    >
      <div className="flex items-center gap-2 border-b border-line bg-surface px-3.5 py-2.5">
        <span className="size-2.5 rounded-full bg-[var(--line)]" />
        <span className="size-2.5 rounded-full bg-[var(--line)]" />
        <span className="size-2.5 rounded-full bg-[var(--line)]" />
        <div className="ml-2 flex h-6 flex-1 items-center rounded-md bg-surface-2 px-2.5 text-[11px] text-ink-faint">
          {url}
        </div>
      </div>
      <div className="bg-paper p-4 sm:p-5">{children}</div>
    </div>
  );
}

/* ================================================================== *
 * Mockups — real-looking product UI, not placeholders
 * ================================================================== */

function Bar({ w = "100%", h = 8, tone = "line" }: { w?: string; h?: number; tone?: "line" | "soft" | "blue" }) {
  const bg = tone === "blue" ? "bg-blue" : tone === "soft" ? "bg-surface-2" : "bg-line";
  return <span className={cn("block rounded-full", bg)} style={{ width: w, height: h }} />;
}

function Meter({ pct, tone = "blue" }: { pct: number; tone?: "blue" | "good" | "warn" | "bad" }) {
  const bg = tone === "good" ? "bg-good" : tone === "warn" ? "bg-warn" : tone === "bad" ? "bg-bad" : "bg-blue";
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-surface-2">
      <div className={cn("h-full rounded-full", bg)} style={{ width: `${pct}%` }} />
    </div>
  );
}

// 1. Match / score card
function MatchCardMock() {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[13px] font-medium text-ink">Senior Backend Engineer</p>
          <p className="text-[11px] text-ink-faint">Resume vs. job description</p>
        </div>
        <div className="rounded-md bg-blue-soft px-2 py-1 text-right">
          <span className="font-mono text-lg font-semibold leading-none text-blue">86</span>
          <span className="font-mono text-[10px] text-blue">/100</span>
        </div>
      </div>
      <div className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-[color-mix(in_oklch,var(--good)_14%,var(--paper))] px-2 py-0.5">
        <span className="size-1.5 rounded-full bg-good" />
        <span className="text-[11px] font-medium text-good">Strong fit</span>
      </div>
      <div className="mt-4 space-y-3">
        {[
          { label: "Production systems", pct: 90, tone: "good" as const },
          { label: "Open source", pct: 62, tone: "warn" as const },
          { label: "Technical skills", pct: 84, tone: "good" as const },
        ].map((r) => (
          <div key={r.label} className="space-y-1">
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-ink-soft">{r.label}</span>
              <span className="font-mono tabular-nums text-ink-faint">{r.pct}</span>
            </div>
            <Meter pct={r.pct} tone={r.tone} />
          </div>
        ))}
      </div>
    </div>
  );
}

// 2. Requirements table
function RequirementsMock() {
  const rows = [
    { req: "5+ years backend", mark: "✓", tone: "good" as const, note: "6 yrs at Stripe, Acme" },
    { req: "Go or Rust", mark: "✓", tone: "good" as const, note: "Go across 3 roles" },
    { req: "Kubernetes", mark: "–", tone: "warn" as const, note: "Docker only, no k8s" },
    { req: "Kafka streaming", mark: "✗", tone: "bad" as const, note: "Not found" },
  ];
  const toneText = { good: "text-good", warn: "text-warn", bad: "text-bad" };
  const toneBg = {
    good: "bg-[color-mix(in_oklch,var(--good)_14%,var(--paper))]",
    warn: "bg-[color-mix(in_oklch,var(--warn)_16%,var(--paper))]",
    bad: "bg-[color-mix(in_oklch,var(--bad)_12%,var(--paper))]",
  };
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-surface">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <span className="text-[12px] font-medium text-ink">Requirements</span>
        <span className="font-mono text-[11px] text-ink-faint">2 met / 1 partial / 1 gap</span>
      </div>
      <div className="divide-y divide-line">
        {rows.map((r) => (
          <div key={r.req} className="flex items-center gap-3 px-4 py-2.5">
            <span className={cn("grid size-5 shrink-0 place-items-center rounded-md text-[11px] font-bold", toneBg[r.tone], toneText[r.tone])}>
              {r.mark}
            </span>
            <span className="w-32 shrink-0 text-[12px] text-ink">{r.req}</span>
            <span className="truncate text-[11px] text-ink-faint">{r.note}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// 3. Job list with two-stage fit chips
function JobListMock() {
  const jobs = [
    { title: "Platform Engineer", co: "Vercel", loc: "Remote", inst: 74, ai: 91 },
    { title: "Backend Engineer", co: "Linear", loc: "SF · Hybrid", inst: 68, ai: 80 },
    { title: "Infra Engineer", co: "Fly.io", loc: "Remote", inst: 55, ai: null },
  ];
  return (
    <div className="space-y-2.5">
      {jobs.map((j) => (
        <div key={j.title} className="flex items-center gap-3 rounded-xl border border-line bg-surface p-3.5">
          <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-surface-2 font-mono text-[13px] font-semibold text-ink-soft">
            {j.co[0]}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[12px] font-medium text-ink">{j.title}</p>
            <p className="truncate text-[11px] text-ink-faint">
              {j.co} · {j.loc}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <span className="rounded-full border border-line bg-paper px-2 py-0.5 font-mono text-[10px] text-ink-soft">
              {j.inst}
            </span>
            {j.ai != null ? (
              <span className="rounded-full bg-blue-soft px-2 py-0.5 font-mono text-[10px] font-medium text-blue">
                AI {j.ai}
              </span>
            ) : (
              <span className="flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-[10px] text-ink-faint">
                <span className="size-1.5 animate-pulse rounded-full bg-blue" />
                scoring
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// 4. Recruiter row (NL search result)
function RecruiterMock() {
  const people = [
    { name: "Dana Ruiz", role: "Eng Recruiter · Vercel", init: "DR" },
    { name: "Marcus Lee", role: "Talent Lead · Linear", init: "ML" },
  ];
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="rounded-lg border border-line bg-paper px-3 py-2 text-[12px] text-ink-soft">
        <span className="text-ink-faint">Find </span>
        <span className="text-ink">recruiters hiring backend roles at Vercel</span>
        <span className="ml-0.5 inline-block h-3.5 w-px translate-y-0.5 animate-pulse bg-blue" />
      </div>
      <div className="mt-3 space-y-2">
        {people.map((p) => (
          <div key={p.name} className="flex items-center gap-3 rounded-lg px-1 py-1.5">
            <div className="grid size-8 shrink-0 place-items-center rounded-full bg-blue-soft font-mono text-[11px] font-semibold text-blue">
              {p.init}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[12px] font-medium text-ink">{p.name}</p>
              <p className="truncate text-[11px] text-ink-faint">{p.role}</p>
            </div>
            <span className="shrink-0 rounded-md border border-line px-2 py-1 text-[10px] font-medium text-ink-soft">
              Draft note
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// 5. Builder / tailored resume mock
function BuilderMock() {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="flex items-center gap-2">
        <span className="text-[12px] font-medium text-ink">Tailored resume</span>
        <span className="rounded-md bg-blue-soft px-1.5 py-0.5 font-mono text-[10px] text-blue">JSON Resume</span>
      </div>
      <div className="mt-3 rounded-lg border border-line bg-paper p-3">
        <Bar w="52%" h={9} tone="soft" />
        <div className="mt-1.5"><Bar w="34%" h={6} /></div>
        <div className="mt-3 space-y-1.5">
          <Bar w="100%" h={6} />
          <Bar w="92%" h={6} />
          <span className="block h-1.5" />
          <div className="flex items-center gap-2">
            <span className="mt-px size-1.5 shrink-0 rounded-full bg-blue" />
            <Bar w="80%" h={6} tone="blue" />
          </div>
          <Bar w="88%" h={6} />
        </div>
      </div>
      <div className="mt-3 flex items-start gap-2 rounded-lg bg-blue-soft px-3 py-2">
        <span className="mt-px text-[11px] text-blue">✎</span>
        <p className="text-[11px] leading-snug text-blue">
          Surfaced your Go and payments work to match the top requirements. Nothing invented.
        </p>
      </div>
    </div>
  );
}

/* ================================================================== *
 * Section scaffolding
 * ================================================================== */

function FeatureSection({
  index,
  kicker,
  title,
  body,
  media,
  flip = false,
}: {
  index: string;
  kicker: string;
  title: React.ReactNode;
  body: React.ReactNode;
  media: React.ReactNode;
  flip?: boolean;
}) {
  return (
    <section className="mx-auto grid max-w-6xl items-center gap-10 px-6 py-16 md:grid-cols-2 md:gap-16 md:py-24">
      <Reveal className={cn(flip ? "md:order-2" : "")}>
        <div className="flex items-center gap-3">
          <span className="font-mono text-xs text-blue">{index}</span>
          <span className="h-px w-8 bg-line" />
          <span className="font-mono text-[11px] uppercase tracking-wider text-ink-faint">{kicker}</span>
        </div>
        <h2 className="mt-4 text-2xl font-semibold tracking-tight text-ink sm:text-3xl">{title}</h2>
        <p className="mt-4 max-w-md text-[15px] leading-relaxed text-ink-soft">{body}</p>
      </Reveal>
      <Reveal delay={120} className={cn(flip ? "md:order-1" : "")}>
        {media}
      </Reveal>
    </section>
  );
}

/* ================================================================== *
 * Page
 * ================================================================== */

export default function Home() {
  return (
    <div className="min-h-screen bg-paper text-ink">
      {/* Top nav */}
      <header className="sticky top-0 z-40 border-b border-line/70 bg-paper/85 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3.5">
          <div className="flex items-center gap-2 font-semibold tracking-tight">
            <Logo size={28} />
            <span>Do Apply</span>
          </div>
          <nav className="flex items-center gap-1.5">
            <Link
              href="/signin"
              className="rounded-lg px-3.5 py-2 text-sm font-medium text-ink-soft transition-colors hover:text-ink"
            >
              Sign in
            </Link>
            <Link
              href="/signup"
              className="rounded-lg bg-blue px-3.5 py-2 text-sm font-medium text-white transition-[transform,background-color] duration-150 [transition-timing-function:var(--ease)] hover:bg-blue-strong active:scale-[0.97]"
            >
              Get started
            </Link>
          </nav>
        </div>
      </header>

      {/* Hero — asymmetric, one blue accent */}
      <section className="relative overflow-hidden">
        <div className="mx-auto grid max-w-6xl gap-12 px-6 pb-8 pt-16 md:grid-cols-[1.05fr_0.95fr] md:items-center md:pb-16 md:pt-24">
          <div>
            <Reveal>
              <span className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-xs text-ink-soft">
                <span className="size-1.5 rounded-full bg-blue" />
                Your whole job hunt, one copilot
              </span>
            </Reveal>
            <Reveal delay={80}>
              <h1 className="mt-6 text-[clamp(2.4rem,6vw,4.2rem)] font-semibold leading-[1.02] tracking-[-0.02em]">
                Run your job hunt
                <br />
                like you mean it.
                <br />
                <span className="text-blue">Find, tailor, reach out.</span>
              </h1>
            </Reveal>
            <Reveal delay={160}>
              <p className="mt-6 max-w-lg text-[17px] leading-relaxed text-ink-soft">
                Do Apply scores your resume against real jobs, tailors it without inventing anything,
                finds the recruiters, and drafts outreach you can actually send. Every number carries
                its reasoning.
              </p>
            </Reveal>
            <Reveal delay={240}>
              <div className="mt-8 flex flex-wrap items-center gap-3">
                <Link
                  href="/signup"
                  className="inline-flex h-12 items-center rounded-lg bg-blue px-6 text-[15px] font-medium text-white transition-[transform,background-color] duration-150 [transition-timing-function:var(--ease)] hover:bg-blue-strong active:scale-[0.97]"
                >
                  Get started free
                </Link>
                <Link
                  href="/signin"
                  className="inline-flex h-12 items-center rounded-lg border border-line bg-paper px-6 text-[15px] font-medium text-ink transition-colors hover:bg-surface-2"
                >
                  Sign in
                </Link>
              </div>
            </Reveal>
          </div>

          {/* Hero media: layered real-UI mockups */}
          <Reveal delay={200} className="relative">
            <BrowserFrame url="doapply.online/analyze">
              <MatchCardMock />
            </BrowserFrame>
            <div className="absolute -bottom-8 -left-6 hidden w-56 sm:block">
              <div className="rounded-xl border border-line bg-paper p-1 shadow-[0_20px_50px_-20px_rgba(20,30,60,0.4)]">
                <JobListMock />
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* Feature sections */}
      <FeatureSection
        index="01"
        kicker="Resume analysis"
        title="Scores that show their reasoning"
        body="Upload a resume and a job. Do Apply grades open source, self-projects, production experience, and technical skills, each backed by the exact evidence it found. No black-box number."
        media={
          <BrowserFrame url="doapply.online/analyze">
            <MatchCardMock />
          </BrowserFrame>
        }
      />

      <FeatureSection
        index="02"
        kicker="Requirement matching"
        title="Every requirement, met or missing"
        body="See each line of the job description mapped to your resume: met, partial, or a gap, with a suggestion for what to add. ATS keywords surfaced so nothing quietly filters you out."
        media={
          <BrowserFrame url="doapply.online/analyze">
            <RequirementsMock />
          </BrowserFrame>
        }
        flip
      />

      <FeatureSection
        index="03"
        kicker="Resume builder"
        title="Tailored to the job, true to you"
        body="Generate a JD-tailored resume that reorders and reframes your real experience to match what the role wants. It surfaces what fits and never fabricates a thing."
        media={
          <BrowserFrame url="doapply.online/builder">
            <BuilderMock />
          </BrowserFrame>
        }
      />

      <FeatureSection
        index="04"
        kicker="Job search"
        title="Instant results, then AI refinement"
        body="Search roles and get a fast heuristic score immediately, then a deeper AI fit score with its reasoning moments later. Latency is a feature: signal first, precision second."
        media={
          <BrowserFrame url="doapply.online/jobs">
            <JobListMock />
          </BrowserFrame>
        }
        flip
      />

      <FeatureSection
        index="05"
        kicker="Recruiter finder"
        title="Ask for the right people in plain words"
        body="Type what you want, like recruiters hiring backend roles at a company, and Do Apply reads the intent and returns the people to reach. LinkedIn import fills your profile in one paste."
        media={
          <BrowserFrame url="doapply.online/people">
            <RecruiterMock />
          </BrowserFrame>
        }
      />

      {/* CTA band */}
      <section className="mx-auto max-w-6xl px-6 py-20">
        <Reveal>
          <div className="relative overflow-hidden rounded-2xl border border-line bg-surface px-8 py-14 text-center sm:px-16">
            <div
              aria-hidden
              className="pointer-events-none absolute inset-x-0 top-0 h-px bg-blue"
              style={{ maskImage: "linear-gradient(90deg,transparent,black,transparent)" }}
            />
            <h2 className="mx-auto max-w-xl text-3xl font-semibold tracking-tight sm:text-4xl">
              Stop admiring dashboards. <span className="text-blue">Do apply.</span>
            </h2>
            <p className="mx-auto mt-4 max-w-md text-[15px] leading-relaxed text-ink-soft">
              Tighten the loop from open role to sent message. Start free, bring your resume, and
              let the copilot do the busywork.
            </p>
            <Link
              href="/signup"
              className="mt-8 inline-flex h-12 items-center rounded-lg bg-blue px-7 text-[15px] font-medium text-white transition-[transform,background-color] duration-150 [transition-timing-function:var(--ease)] hover:bg-blue-strong active:scale-[0.97]"
            >
              Get started free
            </Link>
          </div>
        </Reveal>
      </section>

      {/* Footer */}
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-6 py-10 sm:flex-row">
          <div className="flex items-center gap-2 text-sm font-medium text-ink">
            <Logo size={24} />
            Do Apply
          </div>
          <p className="text-sm text-ink-faint">doapply.online</p>
          <div className="flex items-center gap-4 text-sm text-ink-soft">
            <Link href="/signin" className="hover:text-ink">
              Sign in
            </Link>
            <Link href="/signup" className="hover:text-ink">
              Get started
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
