"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import {
  CANONICAL_FIELDS,
  ColumnMapping,
  IGNORE_FIELD,
  MAPPING_CONFIDENCE_THRESHOLD,
  UploadStatus,
  confirmColumnMappings,
  createUpload,
  getColumnMappings,
  getUploadStatus,
  listUploads,
  updateColumnMapping,
} from "@/lib/api";
import { BusinessPicker } from "@/components/BusinessPicker";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

const POLL_INTERVAL_MS = 2000;

export default function UploadPage() {
  const { accessToken, loading } = useAuth();
  const [error, setError] = useState<string | null>(null);

  const [businessId, setBusinessId] = useState<string | null>(null);

  const [salesFile, setSalesFile] = useState<File | null>(null);
  const [inventoryFile, setInventoryFile] = useState<File | null>(null);
  const [expensesFile, setExpensesFile] = useState<File | null>(null);

  const [uploadSessionId, setUploadSessionId] = useState<string | null>(null);
  const [status, setStatus] = useState<UploadStatus | null>(null);
  const [mappings, setMappings] = useState<ColumnMapping[]>([]);
  const [editedTargets, setEditedTargets] = useState<Record<string, string>>({});

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

  async function refreshStatus(sessionId: string, currentBusinessId: string) {
    if (!accessToken) return null;
    try {
      const latest = await getUploadStatus(accessToken, currentBusinessId, sessionId);
      setStatus(latest);

      if (latest.status === "NEEDS_REVIEW") {
        stopPolling();
        const rows = await getColumnMappings(accessToken, currentBusinessId, sessionId);
        setMappings(rows);
      } else if (latest.status === "COMPLETED" || latest.status === "FAILED") {
        stopPolling();
      }
      return latest;
    } catch (err) {
      stopPolling();
      setError(err instanceof Error ? err.message : "Failed to fetch upload status");
      return null;
    }
  }

  function startPolling(sessionId: string, currentBusinessId: string) {
    pollRef.current = setInterval(() => refreshStatus(sessionId, currentBusinessId), POLL_INTERVAL_MS);
  }

  async function hydrateSession(sessionId: string, currentBusinessId: string) {
    setUploadSessionId(sessionId);
    const latest = await refreshStatus(sessionId, currentBusinessId);
    if (latest?.status === "PROCESSING") {
      startPolling(sessionId, currentBusinessId);
    }
  }

  async function handleSelectBusiness(id: string) {
    if (!accessToken) return;
    stopPolling();
    setError(null);
    setBusinessId(id);
    setUploadSessionId(null);
    setStatus(null);
    setMappings([]);
    setEditedTargets({});

    try {
      const sessions = await listUploads(accessToken, id);
      const latest = sessions[0];
      if (latest) {
        await hydrateSession(latest.id, id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load existing uploads");
    }
  }

  async function handleUpload(event: React.FormEvent) {
    event.preventDefault();
    if (!accessToken || !businessId || !salesFile || !inventoryFile || !expensesFile) return;
    setError(null);
    try {
      const created = await createUpload(accessToken, businessId, {
        sales: salesFile,
        inventory: inventoryFile,
        expenses: expensesFile,
      });
      setUploadSessionId(created.uploadSessionId);
      setStatus({ status: "PROCESSING", progress: 50, pendingReview: null });
      startPolling(created.uploadSessionId, businessId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    }
  }

  async function handleConfirmMappings() {
    if (!accessToken || !businessId || !uploadSessionId) return;
    setError(null);
    try {
      const lowConfidenceMappings = mappings.filter((m) => m.confidenceScore < MAPPING_CONFIDENCE_THRESHOLD);
      for (const mapping of lowConfidenceMappings) {
        const chosenField = editedTargets[mapping.id] ?? mapping.targetField;
        if (chosenField !== mapping.targetField) {
          await updateColumnMapping(accessToken, businessId, uploadSessionId, mapping.id, chosenField);
        }
      }
      await confirmColumnMappings(accessToken, businessId, uploadSessionId);
      setStatus({ status: "PROCESSING", progress: 50, pendingReview: null });
      startPolling(uploadSessionId, businessId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not confirm mappings");
    }
  }

  function resetUpload() {
    stopPolling();
    setUploadSessionId(null);
    setStatus(null);
    setMappings([]);
    setEditedTargets({});
    setSalesFile(null);
    setInventoryFile(null);
    setExpensesFile(null);
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
          to upload data.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-6 py-16">
      <div>
        <h1 className="text-2xl font-semibold text-foreground">Upload business data</h1>
        <p className="text-sm text-muted">Sales, inventory, and expense CSVs for one business.</p>
      </div>
      {error && <p className="text-sm text-danger-fg">{error}</p>}

      <Card>
        <label className="mb-2 block text-sm font-medium text-foreground">Business</label>
        <BusinessPicker accessToken={accessToken} selectedBusinessId={businessId} onSelect={handleSelectBusiness} />
      </Card>

      {businessId && !status && (
        <Card>
          <form onSubmit={handleUpload} className="flex flex-col gap-4">
            <FileField label="sales.csv" onChange={setSalesFile} />
            <FileField label="inventory.csv" onChange={setInventoryFile} />
            <FileField label="expenses.csv" onChange={setExpensesFile} />
            <Button type="submit" disabled={!salesFile || !inventoryFile || !expensesFile}>
              Upload
            </Button>
          </form>
        </Card>
      )}

      {status && (
        <Card className="flex flex-col gap-4">
          <div>
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium text-foreground">{status.status.replace("_", " ")}</span>
              <span className="text-muted">{status.progress}%</span>
            </div>
            <div className="mt-2 h-2 w-full rounded bg-background">
              <div className="h-2 rounded bg-brand transition-all" style={{ width: `${status.progress}%` }} />
            </div>
          </div>

          {status.status === "PROCESSING" && <p className="text-sm text-muted">Processing…</p>}

          {status.status === "NEEDS_REVIEW" && (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-muted">
                Some columns need review before continuing — pending: {status.pendingReview?.join(", ")}
              </p>
              {mappings
                .filter((mapping) => mapping.confidenceScore < MAPPING_CONFIDENCE_THRESHOLD)
                .map((mapping) => (
                  <div key={mapping.id} className="rounded-md border border-border p-3 text-sm">
                    <p className="text-foreground">
                      <span className="font-medium">{mapping.datasetType}</span> — &quot;{mapping.sourceColumnName}
                      &quot; (confidence {mapping.confidenceScore}, {mapping.mappingMethod})
                    </p>
                    <p className="mt-1 text-muted">Sample values: {mapping.sampleValues?.join(", ")}</p>
                    <select
                      className="mt-2 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-sm"
                      value={editedTargets[mapping.id] ?? mapping.targetField}
                      onChange={(event) =>
                        setEditedTargets((prev) => ({ ...prev, [mapping.id]: event.target.value }))
                      }
                    >
                      {CANONICAL_FIELDS[mapping.datasetType]?.map((field) => (
                        <option key={field} value={field}>
                          {field}
                        </option>
                      ))}
                      <option value={IGNORE_FIELD}>Not needed — ignore this column</option>
                    </select>
                  </div>
                ))}
              <Button onClick={handleConfirmMappings}>Confirm mappings and continue</Button>
            </div>
          )}

          {status.status === "COMPLETED" && (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-success-fg">Upload complete — the report is ready.</p>
              <div className="flex gap-3">
                <Link href="/reports">
                  <Button>View report</Button>
                </Link>
                <Button variant="secondary" onClick={resetUpload}>
                  Upload another
                </Button>
              </div>
            </div>
          )}

          {status.status === "FAILED" && (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-danger-fg">Upload processing failed.</p>
              <Button variant="secondary" onClick={resetUpload}>
                Try again
              </Button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

function FileField({ label, onChange }: { label: string; onChange: (file: File | null) => void }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-foreground">{label}</span>
      <input
        type="file"
        accept=".csv"
        onChange={(event) => onChange(event.target.files?.[0] ?? null)}
        className="text-sm text-muted file:mr-3 file:rounded-md file:border-0 file:bg-background file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-foreground hover:file:bg-border"
      />
    </label>
  );
}
