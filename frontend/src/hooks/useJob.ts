"use client";

import { useCallback, useRef, useState } from "react";
import { pollJob } from "@/lib/api";

export interface UseJob<T> {
  stage: string;
  label: string;
  running: boolean;
  error: string | null;
  result: T | null;
  /**
   * Kick off a job. `startFn` should hit the endpoint that returns { job_id }.
   * Resolves with the polled result (or rejects with the error already stored
   * in `error`). Returns null on failure so callers can `await` safely.
   */
  run: (startFn: () => Promise<{ job_id: string }>) => Promise<T | null>;
  reset: () => void;
}

export function useJob<T = unknown>(): UseJob<T> {
  const [stage, setStage] = useState("");
  const [label, setLabel] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<T | null>(null);
  const active = useRef(0);

  const reset = useCallback(() => {
    setStage("");
    setLabel("");
    setRunning(false);
    setError(null);
    setResult(null);
  }, []);

  const run = useCallback(async (startFn: () => Promise<{ job_id: string }>) => {
    const token = ++active.current;
    setRunning(true);
    setError(null);
    setResult(null);
    setStage("");
    setLabel("");
    try {
      const { job_id } = await startFn();
      const res = await pollJob<T>(job_id, (s, l) => {
        if (active.current !== token) return;
        setStage(s || "");
        setLabel(l || "");
      });
      if (active.current !== token) return null;
      setResult(res);
      setRunning(false);
      return res;
    } catch (e) {
      if (active.current !== token) return null;
      setError(e instanceof Error ? e.message : "Something went wrong");
      setRunning(false);
      return null;
    }
  }, []);

  return { stage, label, running, error, result, run, reset };
}
