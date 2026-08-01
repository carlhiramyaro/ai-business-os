"use client";

import Link from "next/link";
import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { BusinessFact, deleteBusinessFact, listBusinessFacts } from "@/lib/api";
import { BusinessPicker } from "@/components/BusinessPicker";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

export default function MemoryPage() {
  const { accessToken, loading } = useAuth();
  const [error, setError] = useState<string | null>(null);

  const [businessId, setBusinessId] = useState<string | null>(null);
  const [facts, setFacts] = useState<BusinessFact[] | null>(null);

  async function handleSelectBusiness(id: string) {
    if (!accessToken) return;
    setError(null);
    setBusinessId(id);
    setFacts(null);
    try {
      setFacts(await listBusinessFacts(accessToken, id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load memory");
    }
  }

  async function handleDelete(factId: string) {
    if (!accessToken || !businessId) return;
    setError(null);
    try {
      await deleteBusinessFact(accessToken, businessId, factId);
      setFacts((prev) => prev?.filter((fact) => fact.id !== factId) ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete fact");
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
          to view memory.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-8 sm:px-6 sm:py-16">
      <div>
        <h1 className="text-2xl font-semibold text-foreground">Memory</h1>
        <p className="text-sm text-muted">
          What the AI has learned about your business from chat — durable facts it uses to answer
          questions and explain insights.
        </p>
      </div>
      {error && <p className="text-sm text-danger-fg">{error}</p>}

      <Card>
        <label className="mb-2 block text-sm font-medium text-foreground">Business</label>
        <BusinessPicker accessToken={accessToken} selectedBusinessId={businessId} onSelect={handleSelectBusiness} />
      </Card>

      {facts && (
        <div className="flex flex-col gap-3">
          {facts.length === 0 && (
            <Card>
              <p className="text-sm text-muted">
                Nothing remembered yet. Mention something durable in{" "}
                <Link href="/chat" className="text-brand underline">
                  chat
                </Link>{" "}
                (e.g. &ldquo;December is our peak season&rdquo;) and it&apos;ll show up here.
              </p>
            </Card>
          )}
          {facts.map((fact) => (
            <Card key={fact.id} className="flex items-center justify-between gap-4">
              <div className="flex flex-col gap-1">
                <p className="text-sm text-foreground">{fact.content}</p>
                <div className="flex items-center gap-2">
                  <Badge tone="neutral">{fact.source}</Badge>
                  <span className="text-xs text-muted">{new Date(fact.createdAt).toLocaleString()}</span>
                </div>
              </div>
              <Button variant="danger" onClick={() => handleDelete(fact.id)}>
                Delete
              </Button>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
