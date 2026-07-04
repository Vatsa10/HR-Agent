"use client";

import * as React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { cn, shortDate } from "@/lib/format";
import { Card, Skeleton, EmptyState, ErrorInline, Button } from "@/components/ui";
import { AnalysisResult, type AnalysisResultData } from "@/components/AnalysisResult";

interface HistoryItem {
  id: string;
  resume_id?: string;
  jd_id?: string;
  created_at?: string;
  candidate?: string;
  total_score?: number | null;
}

interface AnalysisRecord extends AnalysisResultData {
  result?: AnalysisResultData;
}

export default function HistoryPage() {
  const router = useRouter();
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AnalysisResultData | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api<HistoryItem[]>("/history")
      .then((data) => {
        if (alive) setItems(data);
      })
      .catch((e) => {
        if (alive && e?.message !== "unauthorized") setListError(e?.message || "Failed to load history");
        else if (alive) setItems([]);
      });
    return () => {
      alive = false;
    };
  }, []);

  const detailToken = useRef(0);
  useEffect(() => () => {
    // Invalidate any in-flight detail fetch on unmount.
    detailToken.current++;
  }, []);

  const open = useCallback(async (id: string) => {
    const token = ++detailToken.current;
    setSelectedId(id);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      const data = await api<AnalysisRecord>(`/analyses/${id}`);
      if (detailToken.current !== token) return;
      setDetail(data.result || data);
    } catch (e) {
      if (detailToken.current !== token) return;
      const msg = e instanceof Error ? e.message : "Failed to load analysis";
      if (msg !== "unauthorized") setDetailError(msg);
    } finally {
      if (detailToken.current === token) setDetailLoading(false);
    }
  }, []);

  return (
    <div className="mx-auto max-w-5xl space-y-8 px-5 py-10 md:px-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">History</h1>
        <p className="text-sm text-ink-soft">Past analyses. Select one to view its full report.</p>
      </header>

      {listError && <ErrorInline>{listError}</ErrorInline>}

      <div className="grid gap-8 md:grid-cols-[minmax(260px,340px)_1fr]">
        {/* List */}
        <div className="space-y-2">
          {items === null ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full rounded-xl" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <EmptyState
              title="No analyses yet"
              hint="Analyze a candidate and the report will show up here."
              action={
                <Button onClick={() => router.push("/analyze")} variant="ghost" size="sm">
                  Go to Analyze
                </Button>
              }
            />
          ) : (
            items.map((a) => (
              <button
                key={a.id}
                onClick={() => open(a.id)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left transition-colors duration-150 [transition-timing-function:var(--ease)] active:scale-[0.99] focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-[var(--blue-ring)]",
                  selectedId === a.id
                    ? "border-blue bg-blue-soft"
                    : "border-line bg-surface hover:bg-surface-2",
                )}
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-ink">
                    {a.candidate || "Unknown candidate"}
                  </p>
                  <p className="text-xs text-ink-faint">{shortDate(a.created_at)}</p>
                </div>
                <span className="font-mono text-sm font-semibold tabular-nums text-ink">
                  {a.total_score != null ? a.total_score : "–"}
                </span>
              </button>
            ))
          )}
        </div>

        {/* Detail */}
        <div>
          {detailLoading ? (
            <Card className="space-y-5" aria-busy="true" aria-label="Loading analysis">
              <div className="flex items-end justify-between gap-4 border-b border-line pb-4">
                <div className="space-y-2">
                  <Skeleton className="h-3 w-20 rounded" />
                  <Skeleton className="h-6 w-44 rounded" />
                </div>
                <Skeleton className="h-8 w-20 rounded" />
              </div>
              <div className="grid gap-5 sm:grid-cols-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full rounded-lg" />
                ))}
              </div>
              <Skeleton className="h-16 w-full rounded-lg" />
            </Card>
          ) : detailError ? (
            <ErrorInline>{detailError}</ErrorInline>
          ) : detail ? (
            <AnalysisResult data={detail} />
          ) : (
            <EmptyState
              title="Select an analysis"
              hint="Pick an entry from the list to see the full report."
            />
          )}
        </div>
      </div>
    </div>
  );
}
