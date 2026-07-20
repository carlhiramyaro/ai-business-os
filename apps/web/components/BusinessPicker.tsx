"use client";

import { useEffect, useState } from "react";
import { Business, createBusiness, listBusinesses } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

export function BusinessPicker({
  accessToken,
  selectedBusinessId,
  onSelect,
}: {
  accessToken: string;
  selectedBusinessId: string | null;
  onSelect: (businessId: string) => void;
}) {
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newBusinessName, setNewBusinessName] = useState("");

  useEffect(() => {
    listBusinesses(accessToken)
      .then(setBusinesses)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load businesses"))
      .finally(() => setLoading(false));
  }, [accessToken]);

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    if (!newBusinessName.trim()) return;
    setError(null);
    try {
      const business = await createBusiness(accessToken, newBusinessName);
      setBusinesses((prev) => [...prev, business]);
      setNewBusinessName("");
      setCreating(false);
      onSelect(business.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create business");
    }
  }

  if (loading) return <p className="text-sm text-muted">Loading businesses…</p>;

  return (
    <div className="flex flex-col gap-3">
      {error && <p className="text-sm text-danger-fg">{error}</p>}

      {businesses.length > 0 && (
        <select
          className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-brand/40"
          value={selectedBusinessId ?? ""}
          onChange={(event) => onSelect(event.target.value)}
        >
          <option value="" disabled>
            Select a business
          </option>
          {businesses.map((business) => (
            <option key={business.id} value={business.id}>
              {business.businessName}
            </option>
          ))}
        </select>
      )}

      {businesses.length === 0 && !creating && (
        <p className="text-sm text-muted">You don&apos;t have any businesses yet.</p>
      )}

      {creating ? (
        <form onSubmit={handleCreate} className="flex gap-2">
          <Input
            placeholder="Business name"
            value={newBusinessName}
            onChange={(event) => setNewBusinessName(event.target.value)}
            autoFocus
          />
          <Button type="submit">Create</Button>
          <Button type="button" variant="secondary" onClick={() => setCreating(false)}>
            Cancel
          </Button>
        </form>
      ) : (
        <Button type="button" variant="secondary" className="self-start" onClick={() => setCreating(true)}>
          + New business
        </Button>
      )}
    </div>
  );
}
