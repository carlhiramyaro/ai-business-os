"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import {
  CANONICAL_FIELDS,
  DocumentStatus,
  confirmDocument,
  createExpenseEntry,
  createInventoryEntry,
  createSaleEntry,
  getDocumentStatus,
  updateDocumentRows,
  uploadDocument,
} from "@/lib/api";
import { BusinessPicker } from "@/components/BusinessPicker";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";

type EntryType = "sale" | "expense" | "inventory" | "photo";

const ENTRY_TYPES: { value: EntryType; label: string }[] = [
  { value: "sale", label: "Sale" },
  { value: "expense", label: "Expense" },
  { value: "inventory", label: "Inventory" },
  { value: "photo", label: "Photo" },
];

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

export default function EntryPage() {
  const { accessToken, loading } = useAuth();
  const [businessId, setBusinessId] = useState<string | null>(null);
  const [entryType, setEntryType] = useState<EntryType>("sale");

  if (loading) return null;

  if (!accessToken) {
    return (
      <div className="flex flex-1 items-center justify-center px-4 py-8 sm:px-6 sm:py-16">
        <p className="text-sm text-muted">
          Please{" "}
          <Link href="/login" className="text-brand underline">
            log in
          </Link>{" "}
          to add an entry.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-6 px-4 py-8 sm:px-6 sm:py-16">
      <div>
        <h1 className="text-2xl font-semibold text-foreground">Add entry</h1>
        <p className="text-sm text-muted">Record a sale, expense, or inventory item in a few taps.</p>
      </div>

      <Card>
        <label className="mb-2 block text-sm font-medium text-foreground">Business</label>
        <BusinessPicker accessToken={accessToken} selectedBusinessId={businessId} onSelect={setBusinessId} />
      </Card>

      {businessId && (
        <>
          <div className="flex gap-1 rounded-lg border border-border bg-surface p-1">
            {ENTRY_TYPES.map((type) => (
              <button
                key={type.value}
                type="button"
                onClick={() => setEntryType(type.value)}
                className={`min-h-11 flex-1 rounded-md py-2.5 text-sm font-medium transition-colors ${
                  entryType === type.value
                    ? "bg-brand text-brand-foreground"
                    : "text-muted hover:text-foreground"
                }`}
              >
                {type.label}
              </button>
            ))}
          </div>

          {entryType === "sale" && <SaleForm accessToken={accessToken} businessId={businessId} />}
          {entryType === "expense" && <ExpenseForm accessToken={accessToken} businessId={businessId} />}
          {entryType === "inventory" && <InventoryForm accessToken={accessToken} businessId={businessId} />}
          {entryType === "photo" && <PhotoForm accessToken={accessToken} businessId={businessId} />}
        </>
      )}
    </div>
  );
}

function SuccessBanner({ duplicateWarning, onAddAnother }: { duplicateWarning: boolean; onAddAnother: () => void }) {
  return (
    <Card className="flex flex-col gap-3">
      <p className="text-sm text-success-fg">Saved.</p>
      {duplicateWarning && (
        <div className="flex items-start gap-2">
          <Badge tone="warning" className="shrink-0">
            Possible duplicate
          </Badge>
          <p className="text-sm text-muted">
            This looks like something you&apos;ve already entered — it was still saved, but double-check.
          </p>
        </div>
      )}
      <Button variant="secondary" onClick={onAddAnother}>
        Add another
      </Button>
    </Card>
  );
}

function SaleForm({ accessToken, businessId }: { accessToken: string; businessId: string }) {
  const [saleDate, setSaleDate] = useState(todayIso());
  const [productName, setProductName] = useState("");
  const [quantity, setQuantity] = useState("");
  const [unitPrice, setUnitPrice] = useState("");
  const [customerName, setCustomerName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ duplicateWarning: boolean } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function reset() {
    setProductName("");
    setQuantity("");
    setUnitPrice("");
    setCustomerName("");
    setResult(null);
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!productName || !quantity) return;
    setError(null);
    setSubmitting(true);
    try {
      const created = await createSaleEntry(accessToken, businessId, {
        saleDate,
        productName,
        quantity: Number(quantity),
        unitPrice: unitPrice || undefined,
        customerName: customerName || undefined,
      });
      setResult({ duplicateWarning: created.duplicateWarning });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save sale");
    } finally {
      setSubmitting(false);
    }
  }

  if (result) return <SuccessBanner duplicateWarning={result.duplicateWarning} onAddAnother={reset} />;

  return (
    <Card>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {error && <p className="text-sm text-danger-fg">{error}</p>}
        <Field label="Date">
          <Input type="date" value={saleDate} onChange={(e) => setSaleDate(e.target.value)} required />
        </Field>
        <Field label="Product">
          <Input
            placeholder="e.g. Rice"
            value={productName}
            onChange={(e) => setProductName(e.target.value)}
            autoFocus
            required
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Quantity">
            <Input
              type="number"
              inputMode="numeric"
              min="1"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              required
            />
          </Field>
          <Field label="Unit price">
            <Input
              type="number"
              inputMode="decimal"
              step="0.01"
              min="0"
              value={unitPrice}
              onChange={(e) => setUnitPrice(e.target.value)}
            />
          </Field>
        </div>
        <Field label="Customer (optional)">
          <Input placeholder="e.g. Ama Mensah" value={customerName} onChange={(e) => setCustomerName(e.target.value)} />
        </Field>
        <Button type="submit" disabled={submitting || !productName || !quantity}>
          {submitting ? "Saving…" : "Save sale"}
        </Button>
      </form>
    </Card>
  );
}

function ExpenseForm({ accessToken, businessId }: { accessToken: string; businessId: string }) {
  const [expenseDate, setExpenseDate] = useState(todayIso());
  const [category, setCategory] = useState("");
  const [vendor, setVendor] = useState("");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ duplicateWarning: boolean } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function reset() {
    setCategory("");
    setVendor("");
    setAmount("");
    setResult(null);
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!category || !amount) return;
    setError(null);
    setSubmitting(true);
    try {
      const created = await createExpenseEntry(accessToken, businessId, {
        expenseDate,
        category,
        vendor: vendor || undefined,
        amount,
      });
      setResult({ duplicateWarning: created.duplicateWarning });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save expense");
    } finally {
      setSubmitting(false);
    }
  }

  if (result) return <SuccessBanner duplicateWarning={result.duplicateWarning} onAddAnother={reset} />;

  return (
    <Card>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {error && <p className="text-sm text-danger-fg">{error}</p>}
        <Field label="Date">
          <Input type="date" value={expenseDate} onChange={(e) => setExpenseDate(e.target.value)} required />
        </Field>
        <Field label="Category">
          <Input
            placeholder="e.g. Utilities"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            autoFocus
            required
          />
        </Field>
        <Field label="Vendor (optional)">
          <Input placeholder="e.g. Power Co" value={vendor} onChange={(e) => setVendor(e.target.value)} />
        </Field>
        <Field label="Amount">
          <Input
            type="number"
            inputMode="decimal"
            step="0.01"
            min="0"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            required
          />
        </Field>
        <Button type="submit" disabled={submitting || !category || !amount}>
          {submitting ? "Saving…" : "Save expense"}
        </Button>
      </form>
    </Card>
  );
}

function InventoryForm({ accessToken, businessId }: { accessToken: string; businessId: string }) {
  const [productName, setProductName] = useState("");
  const [quantity, setQuantity] = useState("");
  const [supplier, setSupplier] = useState("");
  const [costPrice, setCostPrice] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ duplicateWarning: boolean } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function reset() {
    setProductName("");
    setQuantity("");
    setSupplier("");
    setCostPrice("");
    setResult(null);
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!productName || !quantity) return;
    setError(null);
    setSubmitting(true);
    try {
      const created = await createInventoryEntry(accessToken, businessId, {
        productName,
        quantity: Number(quantity),
        supplier: supplier || undefined,
        costPrice: costPrice || undefined,
      });
      setResult({ duplicateWarning: created.duplicateWarning });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save inventory item");
    } finally {
      setSubmitting(false);
    }
  }

  if (result) return <SuccessBanner duplicateWarning={result.duplicateWarning} onAddAnother={reset} />;

  return (
    <Card>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {error && <p className="text-sm text-danger-fg">{error}</p>}
        <Field label="Product">
          <Input
            placeholder="e.g. Rice"
            value={productName}
            onChange={(e) => setProductName(e.target.value)}
            autoFocus
            required
          />
        </Field>
        <Field label="Quantity">
          <Input
            type="number"
            inputMode="numeric"
            min="0"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            required
          />
        </Field>
        <Field label="Supplier (optional)">
          <Input placeholder="e.g. Acme Supplies" value={supplier} onChange={(e) => setSupplier(e.target.value)} />
        </Field>
        <Field label="Cost price (optional)">
          <Input
            type="number"
            inputMode="decimal"
            step="0.01"
            min="0"
            value={costPrice}
            onChange={(e) => setCostPrice(e.target.value)}
          />
        </Field>
        <Button type="submit" disabled={submitting || !productName || !quantity}>
          {submitting ? "Saving…" : "Save inventory item"}
        </Button>
      </form>
    </Card>
  );
}

const PHOTO_POLL_INTERVAL_MS = 2000;

const DATASET_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "expenses", label: "Expense (receipt/invoice)" },
  { value: "sales", label: "Sale (receipt)" },
  { value: "inventory", label: "Inventory (supplier invoice)" },
];

function PhotoForm({ accessToken, businessId }: { accessToken: string; businessId: string }) {
  const [datasetType, setDatasetType] = useState("expenses");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [status, setStatus] = useState<DocumentStatus | null>(null);
  const [rows, setRows] = useState<Record<string, string>[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [confirmResult, setConfirmResult] = useState<{ duplicateWarning: boolean } | null>(null);
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

  async function refreshStatus(id: string) {
    try {
      const latest = await getDocumentStatus(accessToken, businessId, id);
      setStatus(latest);
      if (latest.status === "NEEDS_REVIEW" && latest.extractedRows) {
        stopPolling();
        const fields = CANONICAL_FIELDS[latest.datasetType ?? datasetType] ?? [];
        setRows(
          latest.extractedRows.map((row) => {
            const normalized: Record<string, string> = {};
            for (const field of fields) normalized[field] = row[field] ?? "";
            return normalized;
          })
        );
      } else if (latest.status === "COMPLETED" || latest.status === "FAILED") {
        stopPolling();
      }
    } catch (err) {
      stopPolling();
      setError(err instanceof Error ? err.message : "Failed to check extraction status");
    }
  }

  function startPolling(id: string) {
    pollRef.current = setInterval(() => refreshStatus(id), PHOTO_POLL_INTERVAL_MS);
  }

  async function handleFileSelected(file: File | null) {
    if (!file) return;
    setError(null);
    setUploading(true);
    try {
      const created = await uploadDocument(accessToken, businessId, datasetType, file);
      setSessionId(created.uploadSessionId);
      setStatus({ status: "PROCESSING", progress: 50, datasetType, extractedRows: null, overallConfidence: null });
      startPolling(created.uploadSessionId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  function updateRowField(index: number, field: string, value: string) {
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, [field]: value } : row)));
  }

  async function handleConfirm() {
    if (!sessionId) return;
    setError(null);
    setConfirming(true);
    try {
      await updateDocumentRows(accessToken, businessId, sessionId, rows);
      const result = await confirmDocument(accessToken, businessId, sessionId);
      setConfirmResult({ duplicateWarning: result.duplicateWarning });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not confirm extracted rows");
    } finally {
      setConfirming(false);
    }
  }

  function reset() {
    stopPolling();
    setSessionId(null);
    setStatus(null);
    setRows([]);
    setConfirmResult(null);
    setError(null);
  }

  if (confirmResult) return <SuccessBanner duplicateWarning={confirmResult.duplicateWarning} onAddAnother={reset} />;

  return (
    <Card className="flex flex-col gap-4">
      {error && <p className="text-sm text-danger-fg">{error}</p>}

      {!sessionId && (
        <>
          <Field label="What does this photo show?">
            <Select value={datasetType} onChange={(e) => setDatasetType(e.target.value)}>
              {DATASET_TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Photo">
            {/* capture="environment" hands off to the OS camera app on
                mobile (with a normal file-picker fallback on desktop) --
                expected to be unaffected by next.config.ts's
                Permissions-Policy camera=() header since this never
                calls getUserMedia(), but that needs a real-device check
                (Commit 10) before treating it as confirmed -- see
                docs/decisions.md [mobile-first polish]. w-full: native
                file inputs size to their content, so a long filename on
                a narrow phone screen can force horizontal page scroll
                without this. */}
            <input
              type="file"
              accept="image/*"
              capture="environment"
              disabled={uploading}
              onChange={(e) => handleFileSelected(e.target.files?.[0] ?? null)}
              className="w-full text-sm text-muted file:mr-3 file:rounded-md file:border-0 file:bg-background file:px-3 file:py-3 file:text-sm file:font-medium file:text-foreground hover:file:bg-border"
            />
          </Field>
          {uploading && <p className="text-sm text-muted">Uploading…</p>}
        </>
      )}

      {sessionId && status && status.status === "PROCESSING" && (
        <div>
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium text-foreground">Reading photo…</span>
            <span className="text-muted">{status.progress}%</span>
          </div>
          <div className="mt-2 h-2 w-full rounded bg-background">
            <div className="h-2 rounded bg-brand transition-all" style={{ width: `${status.progress}%` }} />
          </div>
        </div>
      )}

      {sessionId && status?.status === "NEEDS_REVIEW" && (
        <div className="flex flex-col gap-4">
          <p className="text-sm text-muted">
            Review what we read from the photo before saving
            {status.overallConfidence !== null && ` (confidence ${Math.round(status.overallConfidence * 100)}%)`}.
          </p>
          {rows.length === 0 && <p className="text-sm text-danger-fg">Nothing legible was found in this photo.</p>}
          {rows.map((row, index) => (
            <div key={index} className="flex flex-col gap-2 rounded-md border border-border p-3">
              {(CANONICAL_FIELDS[status.datasetType ?? datasetType] ?? []).map((field) => (
                <Field key={field} label={field}>
                  <Input value={row[field] ?? ""} onChange={(e) => updateRowField(index, field, e.target.value)} />
                </Field>
              ))}
            </div>
          ))}
          <div className="flex gap-3">
            <Button onClick={handleConfirm} disabled={confirming || rows.length === 0}>
              {confirming ? "Saving…" : "Confirm and save"}
            </Button>
            <Button variant="secondary" onClick={reset}>
              Start over
            </Button>
          </div>
        </div>
      )}

      {sessionId && status?.status === "FAILED" && (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-danger-fg">Couldn&apos;t process this photo.</p>
          <Button variant="secondary" onClick={reset}>
            Try again
          </Button>
        </div>
      )}
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-foreground">{label}</span>
      {children}
    </label>
  );
}
