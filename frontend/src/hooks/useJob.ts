"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { pollJob } from "@/lib/api";

export interface UseJob<T> {
  stage: string;
  label: string;
  running: boolean;
  error: string | null;
  /** Latest error, readable synchronously right after `run` resolves. */
  lastError: React.RefObject<string | null>;
  result: T | null;
  /**
   * Kick off a job. `startFn` should hit the endpoint that returns { job_id }.
   * Resolves with the polled result (or rejects with the error already stored
   * in `error`). Returns null on failure so callers can `await` safely.
   */
  run: (startFn: () => Promise<{ job_id: string }>) => Promise<T | null>;
  reset: () => void;
}

/**
 * Pass a `key` to make in-flight jobs survive refresh/navigation: the job id
 * is stashed in sessionStorage and polling resumes on remount.
 */
export function useJob<T = unknown>(key?: string): UseJob<T> {
  const [stage, setStage] = useState("");
  const [label, setLabel] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<T | null>(null);
  const active = useRef(0);
  const lastError = useRef<string | null>(null);
  const storageKey = key ? `job:${key}` : null;

  const reset = useCallback(() => {
    setStage("");
    setLabel("");
    setRunning(false);
    setError(null);
    lastError.current = null;
    setResult(null);
  }, []);

  const poll = useCallback(
    async (jobId: string, token: number) => {
      try {
        const res = await pollJob<T>(jobId, (s, l) => {
          if (active.current !== token) return;
          setStage(s || "");
          setLabel(l || "");
        });
        if (storageKey) sessionStorage.removeItem(storageKey);
        if (active.current !== token) return null;
        setResult(res);
        lastError.current = null;
        setRunning(false);
        return res;
      } catch (e) {
        if (storageKey) sessionStorage.removeItem(storageKey);
        if (active.current !== token) return null;
        const msg = e instanceof Error ? e.message : "Something went wrong";
        setError(msg);
        lastError.current = msg;
        setRunning(false);
        return null;
      }
    },
    [storageKey],
  );

  const run = useCallback(
    async (startFn: () => Promise<{ job_id: string }>) => {
      const token = ++active.current;
      setRunning(true);
      setError(null);
      lastError.current = null;
      setResult(null);
      setStage("");
      setLabel("");
      try {
        const { job_id } = await startFn();
        if (storageKey) sessionStorage.setItem(storageKey, job_id);
        return await poll(job_id, token);
      } catch (e) {
        if (active.current !== token) return null;
        const msg = e instanceof Error ? e.message : "Something went wrong";
        setError(msg);
        lastError.current = msg;
        setRunning(false);
        return null;
      }
    },
    [poll, storageKey],
  );

  // Resume an in-flight job stashed by a previous mount (refresh / nav away).
  useEffect(() => {
    if (!storageKey) return;
    const jobId = sessionStorage.getItem(storageKey);
    if (!jobId) return;
    const token = ++active.current;
    setRunning(true);
    poll(jobId, token);
  }, [storageKey, poll]);

  return { stage, label, running, error, lastError, result, run, reset };
}
