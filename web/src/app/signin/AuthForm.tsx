"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { Button, Input, Field, ErrorInline } from "@/components/ui";
import { Logo } from "@/components/Logo";

type Mode = "signin" | "signup";

const COPY: Record<Mode, { title: string; sub: string; cta: string; endpoint: string; alt: string; altHref: string; altLabel: string }> = {
  signin: {
    title: "Welcome back",
    sub: "Sign in to keep the loop tight.",
    cta: "Sign in",
    endpoint: "/login",
    alt: "New here?",
    altHref: "/signup",
    altLabel: "Create an account",
  },
  signup: {
    title: "Create your account",
    sub: "Start analyzing, tailoring, and reaching out.",
    cta: "Get started",
    endpoint: "/register",
    alt: "Already have an account?",
    altHref: "/signin",
    altLabel: "Sign in",
  },
};

export function AuthForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const c = COPY[mode];
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api(c.endpoint, { method: "POST", body: { email: email.trim(), password } });
      router.push("/analyze");
    } catch (err) {
      const msg =
        err instanceof ApiError && err.message === "unauthorized"
          ? "Incorrect email or password."
          : err instanceof Error
            ? err.message
            : "Something went wrong.";
      setError(msg);
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-paper">
      <header className="px-5 py-5 md:px-8">
        <Link href="/" className="inline-flex items-center gap-2 font-semibold tracking-tight text-ink">
          <Logo size={28} />
          <span className="text-[15px]">Do Apply</span>
        </Link>
      </header>

      <main className="flex flex-1 items-center justify-center px-5 pb-24">
        <div className="w-full max-w-[400px]">
          <div className="mb-7 text-center">
            <h1 className="text-2xl font-semibold tracking-tight text-ink">{c.title}</h1>
            <p className="mt-1.5 text-sm text-ink-soft">{c.sub}</p>
          </div>

          <div className="rounded-2xl border border-line bg-surface p-6 shadow-sm shadow-black/[0.03]">
            <form onSubmit={onSubmit} className="flex flex-col gap-4">
              {error && <ErrorInline>{error}</ErrorInline>}

              <Field label="Email" htmlFor="email">
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  required
                  autoFocus
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </Field>

              <Field label="Password" htmlFor="password">
                <Input
                  id="password"
                  type="password"
                  autoComplete={mode === "signin" ? "current-password" : "new-password"}
                  required
                  minLength={mode === "signup" ? 6 : undefined}
                  placeholder={mode === "signup" ? "At least 6 characters" : "Your password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </Field>

              <Button type="submit" size="lg" loading={loading} className="mt-1 w-full">
                {c.cta}
              </Button>
            </form>
          </div>

          <p className="mt-6 text-center text-sm text-ink-soft">
            {c.alt}{" "}
            <Link href={c.altHref} className="font-medium text-blue hover:text-blue-strong">
              {c.altLabel}
            </Link>
          </p>
          <p className="mt-3 text-center text-xs text-ink-faint">
            <Link href="/" className="hover:text-ink-soft">
              &larr; Back to home
            </Link>
          </p>
        </div>
      </main>
    </div>
  );
}
