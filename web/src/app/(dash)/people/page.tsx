"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, pollJob } from "@/lib/api";
import { Button, Card, Chip, Spinner } from "@/components/ui";

/* ------------------------------------------------------------------ *
 * Types
 * ------------------------------------------------------------------ */

interface Person {
  name?: string;
  headline?: string;
  company?: string;
  location?: string;
  profile_url?: string;
}

interface Understood {
  keywords?: string;
  company?: string;
  location?: string;
  role?: string;
}

interface SearchResult {
  query_understood?: Understood;
  people?: Person[];
}

type Turn =
  | { id: number; role: "user"; text: string }
  | {
      id: number;
      role: "assistant";
      status: "thinking" | "done" | "error";
      stage?: string;
      understood?: Understood;
      people?: Person[];
      error?: string;
    };

/* ------------------------------------------------------------------ *
 * Person card (with inline cold-message draft)
 * ------------------------------------------------------------------ */

function PersonCard({ person, resumeId }: { person: Person; resumeId: number | null }) {
  const [drafting, setDrafting] = useState(false);
  const [draft, setDraft] = useState<{ subject: string; body: string } | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  const onDraft = async () => {
    setError("");
    setDrafting(true);
    try {
      const payload: {
        name?: string;
        headline?: string;
        profile_url?: string;
        resume_id?: number;
        tone: string;
      } = {
        name: person.name || "",
        headline: person.headline || "",
        profile_url: person.profile_url || "",
        tone: "warm",
      };
      if (resumeId != null) payload.resume_id = resumeId;
      const d = await api<{ subject?: string; body?: string }>("/people/draft", {
        method: "POST",
        body: payload,
      });
      setDraft({ subject: d.subject || "", body: d.body || "" });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Could not draft a message";
      if (msg !== "unauthorized") setError(msg);
    } finally {
      setDrafting(false);
    }
  };

  // Show company/location only when they add something not already in the headline.
  const hl = (person.headline || "").toLowerCase();
  const meta = [person.company, person.location]
    .map((v) => (v || "").trim())
    .filter((v) => v && !hl.includes(v.toLowerCase()))
    .join(" · ");

  const onCopy = async () => {
    if (!draft) return;
    const text = (draft.subject ? draft.subject + "\n\n" : "") + draft.body;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setError("Could not copy to clipboard.");
    }
  };

  return (
    <div className="rounded-lg border border-line bg-paper p-3.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <b className="text-sm font-semibold text-ink">{person.name || "Unknown"}</b>
        {person.profile_url && (
          <a
            href={person.profile_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs font-medium text-blue hover:underline"
          >
            Open profile
          </a>
        )}
      </div>
      {person.headline && <p className="mt-0.5 text-sm text-ink-soft">{person.headline}</p>}
      {meta && <p className="mt-0.5 text-xs text-ink-faint">{meta}</p>}

      <div className="mt-2.5">
        <Button variant="ghost" size="sm" onClick={onDraft} loading={drafting} disabled={!!draft}>
          {draft ? "Drafted" : "Draft message"}
        </Button>
      </div>

      {error && <p className="mt-2 text-xs text-bad">{error}</p>}

      {draft && (
        <div className="mt-3 space-y-2 rounded-lg border border-line bg-surface p-3">
          {draft.subject && (
            <p className="text-sm font-medium text-ink">{draft.subject}</p>
          )}
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-soft">{draft.body}</p>
          <div className="flex items-center gap-2 pt-1">
            <Button variant="ghost" size="sm" onClick={onCopy}>
              Copy
            </Button>
            {copied && (
              <span className="text-xs text-good" role="status">
                Copied.
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Turn renderers
 * ------------------------------------------------------------------ */

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-blue px-4 py-2.5 text-sm leading-relaxed text-white">
        {text}
      </div>
    </div>
  );
}

function AssistantTurn({
  turn,
  resumeId,
}: {
  turn: Extract<Turn, { role: "assistant" }>;
  resumeId: number | null;
}) {
  if (turn.status === "thinking") {
    return (
      <div className="flex items-center gap-2 text-sm text-ink-soft">
        <Spinner size={14} /> {turn.stage || "Searching LinkedIn..."}
      </div>
    );
  }

  if (turn.status === "error") {
    return <p className="text-sm text-bad">{turn.error || "Something went wrong."}</p>;
  }

  const u = turn.understood || {};
  const chips = [u.role, u.company, u.location].filter(Boolean) as string[];
  const people = turn.people || [];

  return (
    <div className="space-y-3">
      {chips.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-medium uppercase tracking-wide text-ink-faint">
            Understood as
          </span>
          {chips.map((c, i) => (
            <Chip key={i} tone="blue">
              {c}
            </Chip>
          ))}
        </div>
      )}

      {people.length === 0 ? (
        <p className="text-sm text-ink-faint">No one found, try rephrasing.</p>
      ) : (
        <div className="space-y-2">
          {people.map((p, i) => (
            <PersonCard key={i} person={p} resumeId={resumeId} />
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Page
 * ------------------------------------------------------------------ */

export default function PeoplePage() {
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const [resumeId, setResumeId] = useState<number | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  const nextId = useRef(1);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const resumes = await api<{ id: number }[]>("/resumes");
        if (alive.current && resumes.length) setResumeId(resumes[0].id);
      } catch {
        /* resume is optional for drafting */
      }
    })();
  }, []);

  // Keep the newest turn in view.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  const patchAssistant = useCallback(
    (id: number, patch: Partial<Extract<Turn, { role: "assistant" }>>) => {
      if (!alive.current) return;
      setTurns((prev) =>
        prev.map((t) => (t.id === id && t.role === "assistant" ? { ...t, ...patch } : t)),
      );
    },
    [],
  );

  const send = useCallback(async () => {
    const query = input.trim();
    if (!query || busy) return;

    const userId = nextId.current++;
    const asstId = nextId.current++;
    setTurns((prev) => [
      ...prev,
      { id: userId, role: "user", text: query },
      { id: asstId, role: "assistant", status: "thinking", stage: "Searching LinkedIn..." },
    ]);
    setInput("");
    setBusy(true);

    try {
      const { job_id } = await api<{ job_id: string }>("/hr/nl-search", {
        method: "POST",
        body: { query },
      });
      const res = await pollJob<SearchResult>(job_id, (_s, label) => {
        if (label) patchAssistant(asstId, { stage: label });
      });
      patchAssistant(asstId, {
        status: "done",
        understood: res.query_understood || {},
        people: res.people || [],
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Search failed";
      patchAssistant(asstId, {
        status: "error",
        error: msg === "unauthorized" ? "Your session expired. Please sign in again." : msg,
      });
    } finally {
      if (alive.current) setBusy(false);
    }
  }, [input, busy, patchAssistant]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="flex min-h-[calc(100dvh-6rem)] flex-col md:min-h-[calc(100dvh-8rem)]">
      <header className="space-y-2 pb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Find People</h1>
        <p className="max-w-2xl text-sm leading-relaxed text-ink-soft">
          Describe who you want to reach in plain language and get LinkedIn profiles to cold-email.
          One tap drafts a short, truthful message grounded in a real fact from your resume.
        </p>
        <p className="max-w-2xl text-xs text-ink-faint">
          Results are ranked by LinkedIn. Naming a company (e.g. &ldquo;recruiters at OpenAI&rdquo;)
          returns that company&rsquo;s people and is more accurate.
        </p>
      </header>

      {/* Conversation */}
      <div className="flex-1 space-y-6">
        {turns.length === 0 ? (
          <Card className="border-dashed">
            <p className="text-sm font-medium text-ink">Start a search</p>
            <p className="mt-1 text-sm text-ink-soft">Try one of these:</p>
            <ul className="mt-2 space-y-1 text-sm text-ink-soft">
              <li>&ldquo;AI recruiters at OpenAI in Bengaluru&rdquo;</li>
              <li>&ldquo;Who hires backend engineers at Stripe&rdquo;</li>
              <li>&ldquo;Talent acquisition leads at Figma&rdquo;</li>
            </ul>
          </Card>
        ) : (
          turns.map((t) =>
            t.role === "user" ? (
              <UserBubble key={t.id} text={t.text} />
            ) : (
              <AssistantTurn key={t.id} turn={t} resumeId={resumeId} />
            ),
          )
        )}
        <div ref={bottomRef} />
      </div>

      {/* Composer */}
      <div className="sticky bottom-0 -mx-5 -mb-8 border-t border-line bg-paper px-5 pb-5 pt-3 md:-mx-10 md:-mb-12 md:px-10 md:pb-6">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder="Describe who to find, e.g. AI recruiters at OpenAI in Bengaluru"
            aria-label="Describe who to find"
            className="max-h-40 min-h-10 flex-1 resize-none rounded-lg border border-line bg-surface px-3 py-2.5 text-sm leading-relaxed text-ink placeholder:text-ink-faint transition-[border-color,box-shadow] duration-150 [transition-timing-function:var(--ease)] focus:border-blue focus:outline-none focus:ring-[3px] focus:ring-[var(--blue-ring)]"
          />
          <Button onClick={send} loading={busy} disabled={!input.trim()}>
            Send
          </Button>
        </div>
      </div>
    </div>
  );
}
