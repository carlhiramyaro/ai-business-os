"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import {
  Insight,
  InsightSeverity,
  getUnreadInsightCount,
  listInsights,
  markInsightRead,
  runInsightsAnalysis,
} from "@/lib/api";
import { BusinessPicker } from "@/components/BusinessPicker";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

const POLL_INTERVAL_MS = 3000;
const MAX_POLLS = 10;

const SEVERITY_TONE: Record<InsightSeverity, "danger" | "warning" | "neutral"> = {
  critical: "danger",
  warning: "warning",
  info: "neutral",
};

export default function InsightsPage() {
  const { accessToken, loading } = useAuth();
  const [error, setError] = useState<string | null>(null);

  const [businessId, setBusinessId] = useState<string | null>(null);
  const [insights, setInsights] = useState<Insight[] | null>(null);
  const [unreadCount, setUnreadCount] = useState(0);
  const [running, setRunning] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollCountRef = useRef(0);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  async function refresh(currentBusinessId: string) {
    if (!accessToken) return;
    const [insightList, unread] = await Promise.all([
      listInsights(accessToken, currentBusinessId),
      getUnreadInsightCount(accessToken, currentBusinessId),
    ]);
    setInsights(insightList);
    setUnreadCount(unread.unreadCount);
  }

  async function handleSelectBusiness(id: string) {
    if (!accessToken) return;
    stopPolling();
    setError(null);
    setBusinessId(id);
    setInsights(null);
    setRunning(false);
    try {
      await refresh(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load insights");
    }
  }

  async function handleRunAnalysis() {
    if (!accessToken || !businessId) return;
    setError(null);
    setRunning(true);
    const baselineCount = insights?.length ?? 0;
    try {
      await runInsightsAnalysis(accessToken, businessId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start analysis");
      setRunning(false);
      return;
    }

    pollCountRef.current = 0;
    pollRef.current = setInterval(async () => {
      pollCountRef.current += 1;
      try {
        const insightList = await listInsights(accessToken, businessId);
        if (insightList.length !== baselineCount || pollCountRef.current >= MAX_POLLS) {
          stopPolling();
          setRunning(false);
          await refresh(businessId);
        }
      } catch (err) {
        stopPolling();
        setRunning(false);
        setError(err instanceof Error ? err.message : "Could not check analysis status");
      }
    }, POLL_INTERVAL_MS);
  }

  async function handleOpenInsight(insight: Insight) {
    if (!accessToken || !businessId || insight.isRead) return;
    try {
      await markInsightRead(accessToken, businessId, insight.id);
      setInsights((prev) => prev?.map((i) => (i.id === insight.id ? { ...i, isRead: true } : i)) ?? null);
      setUnreadCount((prev) => Math.max(0, prev - 1));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not mark insight as read");
    }
  }

  if (loading) return null;

  if (!accessToken) {
    return (
      <div className="flex flex-1 items-center justify-center px-4 py-8 sm:px-6 sm:py-16">
        <p className="text-sm text-muted">
          Please{" "}
          <Link href="/login" className="text-brand underline">
            log in
          </Link>{" "}
          to view insights.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-8 sm:px-6 sm:py-16">
      <div className="flex items-center gap-2">
        <h1 className="text-2xl font-semibold text-foreground">Insights</h1>
        {unreadCount > 0 && <Badge tone="danger">{unreadCount} unread</Badge>}
      </div>
      <p className="text-sm text-muted">
        Trends and risks detected automatically from your data — no need to ask.
      </p>
      {error && <p className="text-sm text-danger-fg">{error}</p>}

      <Card>
        <label className="mb-2 block text-sm font-medium text-foreground">Business</label>
        <BusinessPicker accessToken={accessToken} selectedBusinessId={businessId} onSelect={handleSelectBusiness} />
      </Card>

      {businessId && (
        <div className="flex justify-end">
          <Button onClick={handleRunAnalysis} disabled={running}>
            {running ? "Analyzing…" : "Run analysis now"}
          </Button>
        </div>
      )}

      {insights && (
        <div className="flex flex-col gap-3">
          {insights.length === 0 && (
            <Card>
              <p className="text-sm text-muted">
                No insights yet. Upload data, then run analysis to detect trends and risks.
              </p>
            </Card>
          )}
          {insights.map((insight) => (
            <Card
              key={insight.id}
              className={`flex cursor-pointer flex-col gap-2 ${insight.isRead ? "" : "border-brand/40"}`}
              onClick={() => handleOpenInsight(insight)}
            >
              <div className="flex items-center justify-between gap-3">
                <span className={`text-sm ${insight.isRead ? "font-normal" : "font-semibold"} text-foreground`}>
                  {insight.title}
                </span>
                <Badge tone={SEVERITY_TONE[insight.severity]}>{insight.severity}</Badge>
              </div>
              <p className="text-sm text-muted">{insight.body}</p>
              <span className="text-xs text-muted">{new Date(insight.createdAt).toLocaleString()}</span>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
