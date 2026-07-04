"use client";

import { useCallback, useEffect, useState } from "react";
import { api, pollJob } from "@/lib/api";
import { Button, Card, Chip, Input, Field, Select, Textarea, Spinner, EmptyState, ErrorInline } from "@/components/ui";

/* ------------------------------------------------------------------ *
 * Types
 * ------------------------------------------------------------------ */

interface Resume {
  id: number;
  filename: string;
}

interface Contact {
  id: number;
  name?: string;
  headline?: string;
  profile_url?: string;
  status?: string;
  message_draft?: string;
}

interface Company {
  id: number;
  name: string;
  linkedin_url?: string;
  contacts?: Contact[];
}

interface Person {
  name?: string;
  headline?: string;
  profile_url?: string;
  contact_id?: number | null;
}

interface AskResult {
  query_understood?: { keywords?: string; company?: string; location?: string; role?: string };
  people?: Person[];
}

const TONES = ["warm", "direct", "formal", "enthusiastic"];
const HR_STATUSES = ["found", "drafted", "messaged"];

/* ------------------------------------------------------------------ *
 * Recruiter row (inside a tracked company)
 * ------------------------------------------------------------------ */

function Recruiter({
  contact,
  resumes,
  onError,
}: {
  contact: Contact;
  resumes: Resume[];
  onError: (m: string) => void;
}) {
  const [resumeId, setResumeId] = useState<string>(resumes[0] ? String(resumes[0].id) : "");
  const [tone, setTone] = useState("warm");
  const [status, setStatus] = useState(contact.status || "found");
  const [drafting, setDrafting] = useState(false);
  const [open, setOpen] = useState(!!contact.message_draft);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState(contact.message_draft || "");
  const [flash, setFlash] = useState("");

  const showFlash = (m: string) => {
    setFlash(m);
    window.setTimeout(() => setFlash(""), 1500);
  };

  const guardMsg = (e: unknown) => {
    const msg = e instanceof Error ? e.message : "Something went wrong";
    if (msg !== "unauthorized") onError(msg);
  };

  const draft = async () => {
    if (!resumeId || !resumes.length) {
      onError("No resume available. Add one on the Analyze page first.");
      return;
    }
    setDrafting(true);
    try {
      const d = await api<{ subject?: string; body?: string }>(`/hr/${contact.id}/draft`, {
        method: "POST",
        body: { resume_id: Number(resumeId), tone },
      });
      setSubject(d.subject || "");
      setBody(d.body || "");
      setOpen(true);
      setStatus("drafted");
    } catch (e) {
      guardMsg(e);
    } finally {
      setDrafting(false);
    }
  };

  const changeStatus = async (s: string) => {
    setStatus(s);
    try {
      await api(`/hr/${contact.id}`, { method: "PUT", body: { status: s } });
    } catch (e) {
      guardMsg(e);
    }
  };

  const copy = async () => {
    const text = (subject ? subject + "\n\n" : "") + body;
    try {
      await navigator.clipboard.writeText(text);
      showFlash("Copied.");
    } catch {
      /* ignore */
    }
  };

  const saveDraft = async () => {
    const combined = (subject ? subject + "\n\n" : "") + body;
    try {
      await api(`/hr/${contact.id}`, { method: "PUT", body: { message_draft: combined } });
      showFlash("Saved.");
    } catch (e) {
      guardMsg(e);
    }
  };

  return (
    <div className="rounded-lg border border-line bg-paper p-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <b className="text-sm text-ink">{contact.name || "Unknown"}</b>
        {contact.headline && <span className="text-xs text-ink-soft">{contact.headline}</span>}
        {contact.profile_url && (
          <a
            href={contact.profile_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs font-medium text-blue hover:underline"
          >
            Open profile
          </a>
        )}
        <span className="ml-auto rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-ink-soft">
          {status}
        </span>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <Select
          value={resumeId}
          onChange={(e) => setResumeId(e.target.value)}
          disabled={!resumes.length}
          className="h-8 w-auto text-[13px]"
        >
          {resumes.length ? (
            resumes.map((r) => (
              <option key={r.id} value={r.id}>
                {r.filename}
              </option>
            ))
          ) : (
            <option>No resume</option>
          )}
        </Select>
        <Select value={tone} onChange={(e) => setTone(e.target.value)} className="h-8 w-auto text-[13px]">
          {TONES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </Select>
        <Button variant="ghost" size="sm" onClick={draft} loading={drafting}>
          Draft message
        </Button>
        <Select
          value={status}
          onChange={(e) => changeStatus(e.target.value)}
          className="h-8 w-auto text-[13px]"
        >
          {HR_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </Select>
      </div>

      {open && (
        <div className="mt-3 space-y-2">
          <Input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Subject" />
          <Textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Message body"
            rows={6}
          />
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={copy}>
              Copy
            </Button>
            <Button variant="ghost" size="sm" onClick={saveDraft}>
              Save draft
            </Button>
            {flash && <span className="text-xs text-good">{flash}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Tracked company card
 * ------------------------------------------------------------------ */

function CompanyCard({
  company,
  resumes,
  onError,
}: {
  company: Company;
  resumes: Resume[];
  onError: (m: string) => void;
}) {
  const [contacts, setContacts] = useState<Contact[]>(company.contacts || []);
  const [finding, setFinding] = useState(false);
  const [statusLine, setStatusLine] = useState("");
  const [note, setNote] = useState("");

  const findHr = async () => {
    setFinding(true);
    setNote("");
    setStatusLine("Starting...");
    try {
      const { job_id } = await api<{ job_id: string }>(`/companies/${company.id}/find-hr`, {
        method: "POST",
        body: {},
      });
      const res = await pollJob<{ contacts?: Contact[] }>(job_id, (_s, l) =>
        setStatusLine(l || "Finding recruiters..."),
      );
      const found = res.contacts || [];
      if (!found.length) {
        setNote("No recruiters found. LinkedIn may need a session, or try again later.");
      } else {
        setContacts(found);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Search failed";
      if (msg !== "unauthorized") onError(msg);
    } finally {
      setFinding(false);
      setStatusLine("");
    }
  };

  return (
    <Card className="space-y-3">
      <div>
        <h3 className="text-base font-semibold text-ink">{company.name}</h3>
        {company.linkedin_url && (
          <a
            href={company.linkedin_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm font-medium text-blue hover:underline"
          >
            Company page
          </a>
        )}
      </div>

      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={findHr} loading={finding}>
          Find HR
        </Button>
        {statusLine && (
          <span className="flex items-center gap-1.5 text-xs text-ink-soft">
            <Spinner size={12} /> {statusLine}
          </span>
        )}
      </div>

      {note && <p className="text-sm text-ink-faint">{note}</p>}

      {contacts.length > 0 && (
        <div className="space-y-2">
          {contacts.map((c) => (
            <Recruiter key={c.id} contact={c} resumes={resumes} onError={onError} />
          ))}
        </div>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------------ *
 * Page
 * ------------------------------------------------------------------ */

export default function CompaniesPage() {
  const [error, setError] = useState("");
  const flash = useCallback((m: string) => {
    setError(m);
    window.setTimeout(() => setError(""), 6000);
  }, []);

  const [resumes, setResumes] = useState<Resume[]>([]);
  const [companies, setCompanies] = useState<Company[] | null>(null);

  // track form
  const [cname, setCname] = useState("");
  const [curl, setCurl] = useState("");
  const [tracking, setTracking] = useState(false);

  // ask panel
  const [askQuery, setAskQuery] = useState("");
  const [askCompany, setAskCompany] = useState("");
  const [asking, setAsking] = useState(false);
  const [askStatus, setAskStatus] = useState("");
  const [askResult, setAskResult] = useState<AskResult | null>(null);

  const loadCompanies = useCallback(async () => {
    try {
      const items = await api<Company[]>("/companies");
      setCompanies(items);
    } catch {
      /* 401 handled elsewhere */
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        setResumes(await api<Resume[]>("/resumes"));
      } catch {
        setResumes([]);
      }
      loadCompanies();
    })();
  }, [loadCompanies]);

  const track = async () => {
    const name = cname.trim();
    if (!name) {
      flash("Enter a company name");
      return;
    }
    setTracking(true);
    try {
      await api("/companies/track", { method: "POST", body: { name, linkedin_url: curl.trim() } });
      setCname("");
      setCurl("");
      loadCompanies();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "";
      if (msg && msg !== "unauthorized") flash(msg);
    } finally {
      setTracking(false);
    }
  };

  const runAsk = async (companyId?: number) => {
    const query = askQuery.trim();
    if (!query) {
      flash("Describe who to find first");
      return;
    }
    setAsking(true);
    setAskStatus("Starting...");
    try {
      const payload: { query: string; company_id?: number } = { query };
      if (companyId) payload.company_id = companyId;
      const { job_id } = await api<{ job_id: string }>("/hr/nl-search", {
        method: "POST",
        body: payload,
      });
      const res = await pollJob<AskResult>(job_id, (_s, l) =>
        setAskStatus(l || "Searching LinkedIn..."),
      );
      setAskResult(res);
      if (companyId) loadCompanies();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Search failed";
      if (msg !== "unauthorized") flash(msg);
    } finally {
      setAsking(false);
      setAskStatus("");
    }
  };

  const understood = askResult?.query_understood || {};
  const understoodChips = [understood.role, understood.company, understood.location].filter(
    Boolean,
  ) as string[];

  return (
    <div className="mx-auto max-w-4xl space-y-8 px-5 py-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Companies</h1>
        <p className="max-w-2xl text-sm leading-relaxed text-ink-soft">
          Track companies you care about, find recruiters and talent-acquisition contacts, and draft
          a short, truthful outreach message grounded in one real fact from your resume.
        </p>
        <p className="text-sm text-ink-faint">
          Recruiter search is filtered by your job preferences (role and location).{" "}
          <a href="/jobs" className="text-blue hover:underline">
            Set them on the Jobs page.
          </a>
        </p>
      </header>

      {/* Track form */}
      <Card>
        <div className="grid gap-4 sm:grid-cols-[2fr_2fr_auto] sm:items-end">
          <Field label="Company name">
            <Input value={cname} onChange={(e) => setCname(e.target.value)} placeholder="Acme Inc" />
          </Field>
          <Field label="LinkedIn URL" hint="optional">
            <Input
              type="url"
              value={curl}
              onChange={(e) => setCurl(e.target.value)}
              placeholder="https://linkedin.com/company/acme"
            />
          </Field>
          <Button onClick={track} loading={tracking}>
            Track
          </Button>
        </div>
      </Card>

      {error && <ErrorInline>{error}</ErrorInline>}

      {/* Ask panel */}
      <Card className="space-y-3">
        <div>
          <h2 className="text-lg font-semibold text-ink">Ask</h2>
          <p className="mt-1 text-sm text-ink-soft">
            Describe who you are looking for in plain language. Pick a company to auto-save the
            results, or add people individually afterwards.
          </p>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            value={askQuery}
            onChange={(e) => setAskQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                runAsk(askCompany ? Number(askCompany) : undefined);
              }
            }}
            placeholder='Describe who to find, e.g. "AI recruiters at OpenAI in SF"'
            aria-label="People search query"
            className="flex-1"
          />
          <Select
            value={askCompany}
            onChange={(e) => setAskCompany(e.target.value)}
            aria-label="Save results to company"
            className="sm:w-52"
          >
            <option value="">Save to... (optional)</option>
            {(companies || []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          <Button onClick={() => runAsk(askCompany ? Number(askCompany) : undefined)} loading={asking}>
            Ask
          </Button>
        </div>

        {askStatus && (
          <span className="flex items-center gap-1.5 text-xs text-ink-soft">
            <Spinner size={12} /> {askStatus}
          </span>
        )}

        {understoodChips.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium uppercase tracking-wide text-ink-faint">
              Understood as
            </span>
            {understoodChips.map((c, i) => (
              <Chip key={i} tone="blue">
                {c}
              </Chip>
            ))}
          </div>
        )}

        {askResult && (
          <div className="space-y-2">
            {(askResult.people || []).length === 0 ? (
              <p className="text-sm text-ink-faint">No one found, try rephrasing.</p>
            ) : (
              (askResult.people || []).map((p, i) => {
                const saved = p.contact_id != null;
                return (
                  <div key={i} className="rounded-lg border border-line bg-paper p-3">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      <b className="text-sm text-ink">{p.name || "Unknown"}</b>
                      {p.headline && <span className="text-xs text-ink-soft">{p.headline}</span>}
                      {p.profile_url && (
                        <a
                          href={p.profile_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs font-medium text-blue hover:underline"
                        >
                          Open profile
                        </a>
                      )}
                      {saved && (
                        <span className="ml-auto rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-ink-soft">
                          saved
                        </span>
                      )}
                    </div>
                    {!saved && (
                      <div className="mt-2.5 flex flex-wrap items-center gap-2">
                        <Select
                          value={askCompany}
                          onChange={(e) => setAskCompany(e.target.value)}
                          disabled={!(companies || []).length}
                          className="h-8 w-auto text-[13px]"
                        >
                          {(companies || []).length ? (
                            (companies || []).map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.name}
                              </option>
                            ))
                          ) : (
                            <option>No companies tracked</option>
                          )}
                        </Select>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={!(companies || []).length}
                          onClick={() => {
                            if (!askCompany) {
                              flash("Pick a company first");
                              return;
                            }
                            runAsk(Number(askCompany));
                          }}
                        >
                          Add to a company
                        </Button>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        )}
      </Card>

      {/* Tracked companies */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold text-ink">Tracked companies</h2>
        {companies === null ? (
          <p className="text-sm text-ink-faint">Loading companies...</p>
        ) : companies.length === 0 ? (
          <EmptyState
            title="No tracked companies yet"
            hint="Add one above, or track a company from the Jobs page."
          />
        ) : (
          <div className="grid gap-4">
            {companies.map((c) => (
              <CompanyCard key={c.id} company={c} resumes={resumes} onError={flash} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
