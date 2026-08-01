"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import {
  ReportDetail,
  ReportSummary,
  deleteReport,
  generateReport,
  getReport,
  listReports,
} from "@/lib/api";
import { BusinessPicker } from "@/components/BusinessPicker";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";

const POLL_INTERVAL_MS = 2000;

const HEALTH_TONE: Record<string, "success" | "warning" | "danger"> = {
  Good: "success",
  Fair: "warning",
  "Needs Attention": "danger",
};

const STATUS_TONE: Record<"PENDING" | "FAILED", "warning" | "danger"> = {
  PENDING: "warning",
  FAILED: "danger",
};

export default function ReportsPage() {
  const { accessToken, loading } = useAuth();
  const [error, setError] = useState<string | null>(null);

  const [businessId, setBusinessId] = useState<string | null>(null);
  const [reports, setReports] = useState<ReportSummary[] | null>(null);
  const [selectedReport, setSelectedReport] = useState<ReportDetail | null>(null);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);

  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [generatingReportId, setGeneratingReportId] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

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

  async function refreshGeneratingReport(reportId: string, currentBusinessId: string) {
    if (!accessToken) return;
    try {
      const latest = await getReport(accessToken, currentBusinessId, reportId);
      if (latest.status !== "PENDING") {
        stopPolling();
        setGeneratingReportId(null);
        setReports(await listReports(accessToken, currentBusinessId));
      }
    } catch (err) {
      stopPolling();
      setGeneratingReportId(null);
      setError(err instanceof Error ? err.message : "Failed to check report status");
    }
  }

  function startPolling(reportId: string, currentBusinessId: string) {
    pollRef.current = setInterval(() => refreshGeneratingReport(reportId, currentBusinessId), POLL_INTERVAL_MS);
  }

  async function handleSelectBusiness(id: string) {
    if (!accessToken) return;
    stopPolling();
    setError(null);
    setBusinessId(id);
    setSelectedReport(null);
    setSelectedReportId(null);
    setGeneratingReportId(null);
    try {
      setReports(await listReports(accessToken, id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load reports");
    }
  }

  async function handleGenerateReport(event: React.FormEvent) {
    event.preventDefault();
    if (!accessToken || !businessId || !periodStart || !periodEnd) return;
    setError(null);
    try {
      const created = await generateReport(accessToken, businessId, periodStart, periodEnd);
      setGeneratingReportId(created.reportId);
      startPolling(created.reportId, businessId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not generate report");
    }
  }

  async function handleOpenReport(reportId: string) {
    if (!accessToken || !businessId) return;
    setError(null);
    try {
      setSelectedReport(await getReport(accessToken, businessId, reportId));
      setSelectedReportId(reportId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load report");
    }
  }

  async function handleDeleteReport(reportId: string) {
    if (!accessToken || !businessId) return;
    setError(null);
    try {
      await deleteReport(accessToken, businessId, reportId);
      setReports((prev) => prev?.filter((report) => report.id !== reportId) ?? null);
      if (selectedReportId === reportId) {
        setSelectedReport(null);
        setSelectedReportId(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete report");
    }
  }

  if (loading) return null;

  if (!accessToken) {
    return (
      <div className="flex flex-1 items-center justify-center px-6 py-16">
        <p className="text-sm text-muted">
          Please{" "}
          <Link href="/login" className="text-brand underline">
            log in
          </Link>{" "}
          to view reports.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-6 py-16">
      <div>
        <h1 className="text-2xl font-semibold text-foreground">Business Health Reports</h1>
        <p className="text-sm text-muted">
          Generated automatically after an upload, or on demand for a custom date range.
        </p>
      </div>
      {error && <p className="text-sm text-danger-fg">{error}</p>}

      <Card>
        <label className="mb-2 block text-sm font-medium text-foreground">Business</label>
        <BusinessPicker accessToken={accessToken} selectedBusinessId={businessId} onSelect={handleSelectBusiness} />
      </Card>

      {businessId && !selectedReport && (
        <Card>
          <form onSubmit={handleGenerateReport} className="flex flex-col gap-4">
            <label className="mb-2 block text-sm font-medium text-foreground">Generate a report for a date range</label>
            <div className="flex items-end gap-3">
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted">From</span>
                <Input
                  type="date"
                  value={periodStart}
                  max={periodEnd || undefined}
                  onChange={(event) => setPeriodStart(event.target.value)}
                  className="py-1.5"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted">To</span>
                <Input
                  type="date"
                  value={periodEnd}
                  min={periodStart || undefined}
                  onChange={(event) => setPeriodEnd(event.target.value)}
                  className="py-1.5"
                />
              </label>
              <Button type="submit" disabled={!periodStart || !periodEnd || generatingReportId !== null}>
                {generatingReportId ? "Generating…" : "Generate report"}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {reports && !selectedReport && (
        <div className="flex flex-col gap-3">
          {reports.length === 0 && (
            <Card>
              <p className="text-sm text-muted">
                No reports yet.{" "}
                <Link href="/upload" className="text-brand underline">
                  Upload data
                </Link>{" "}
                to generate one.
              </p>
            </Card>
          )}
          {reports.map((report) => (
            <Card key={report.id} className="flex items-center justify-between">
              <div className="flex flex-col gap-1">
                <span className="text-sm font-medium text-foreground">
                  {report.periodStart} – {report.periodEnd}
                </span>
                <span className="text-xs text-muted">{new Date(report.createdAt).toLocaleString()}</span>
                {report.status === "COMPLETED" ? (
                  <Badge tone={HEALTH_TONE[report.businessHealth] ?? "neutral"}>{report.businessHealth}</Badge>
                ) : (
                  <Badge tone={STATUS_TONE[report.status]}>
                    {report.status === "PENDING" ? "Generating…" : "Failed"}
                  </Badge>
                )}
              </div>
              <div className="flex items-center gap-4">
                <button
                  className="text-sm font-medium text-brand hover:underline disabled:cursor-not-allowed disabled:text-muted"
                  onClick={() => handleOpenReport(report.id)}
                  disabled={report.status !== "COMPLETED"}
                >
                  View
                </button>
                <Button variant="danger" onClick={() => handleDeleteReport(report.id)}>
                  Delete
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {selectedReport && (
        <Card className="flex flex-col gap-5">
          <button className="self-start text-sm text-brand hover:underline" onClick={() => setSelectedReport(null)}>
            ← Back to list
          </button>

          <Section title="Summary" text={selectedReport.summary} />
          <ListSection title="Risks" items={selectedReport.risks} />
          <ListSection title="Opportunities" items={selectedReport.opportunities} />
          <ListSection title="Action Plan" items={selectedReport.actionPlan} />
          <Section title="Forecast" text={selectedReport.forecast} />
        </Card>
      )}
    </div>
  );
}

function Section({ title, text }: { title: string; text: string | null }) {
  return (
    <div>
      <h2 className="text-sm font-semibold text-foreground">{title}</h2>
      <p className="mt-1 text-sm text-muted">{text}</p>
    </div>
  );
}

function ListSection({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <h2 className="text-sm font-semibold text-foreground">{title}</h2>
      <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-muted">
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
