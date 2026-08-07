"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import {
  ChannelIdentitySummary,
  LinkCodeResponse,
  NotificationFrequency,
  createWhatsAppLinkCode,
  listChannels,
  unlinkChannel,
  updateChannelFrequency,
} from "@/lib/api";
import { BusinessPicker } from "@/components/BusinessPicker";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Select } from "@/components/ui/Select";

const FREQUENCY_LABELS: Record<NotificationFrequency, string> = {
  off: "Off -- ask-only, no proactive messages",
  immediate: "Immediate -- as soon as a new insight is found",
  daily_digest: "Daily digest -- one bundled message per day",
};

function remainingSeconds(expiresAt: string | null): number | null {
  return expiresAt ? Math.max(0, Math.round((new Date(expiresAt).getTime() - Date.now()) / 1000)) : null;
}

function useCountdown(expiresAt: string | null) {
  const [secondsLeft, setSecondsLeft] = useState<number | null>(() => remainingSeconds(expiresAt));
  // Reset synchronously during render when expiresAt changes (a new code
  // generated) -- same "adjust state during render" pattern NavBar.tsx uses
  // for resetting on pathname change, avoiding a setState-in-effect-body
  // cascading render. See docs/decisions.md [mobile-first polish].
  const [prevExpiresAt, setPrevExpiresAt] = useState(expiresAt);
  if (expiresAt !== prevExpiresAt) {
    setPrevExpiresAt(expiresAt);
    setSecondsLeft(remainingSeconds(expiresAt));
  }

  useEffect(() => {
    if (!expiresAt) return;
    const interval = setInterval(() => setSecondsLeft(remainingSeconds(expiresAt)), 1000);
    return () => clearInterval(interval);
  }, [expiresAt]);

  return secondsLeft;
}

export default function SettingsPage() {
  const { accessToken, loading } = useAuth();
  const [error, setError] = useState<string | null>(null);

  const [businessId, setBusinessId] = useState<string | null>(null);
  const [channels, setChannels] = useState<ChannelIdentitySummary[] | null>(null);
  const [linkCode, setLinkCode] = useState<LinkCodeResponse | null>(null);
  const [generating, setGenerating] = useState(false);

  const secondsLeft = useCountdown(linkCode?.expiresAt ?? null);
  const expired = secondsLeft === 0;

  async function loadChannels(id: string) {
    if (!accessToken) return;
    try {
      setChannels(await listChannels(accessToken, id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load linked numbers");
    }
  }

  async function handleSelectBusiness(id: string) {
    if (!accessToken) return;
    setError(null);
    setBusinessId(id);
    setChannels(null);
    setLinkCode(null);
    await loadChannels(id);
  }

  async function handleGenerateCode() {
    if (!accessToken || !businessId) return;
    setError(null);
    setGenerating(true);
    try {
      setLinkCode(await createWhatsAppLinkCode(accessToken, businessId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not generate a link code");
    } finally {
      setGenerating(false);
    }
  }

  async function handleUnlink(channelIdentityId: string) {
    if (!accessToken || !businessId) return;
    setError(null);
    try {
      await unlinkChannel(accessToken, businessId, channelIdentityId);
      setChannels((prev) => prev?.filter((c) => c.id !== channelIdentityId) ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not unlink number");
    }
  }

  async function handleFrequencyChange(channelIdentityId: string, frequency: NotificationFrequency) {
    if (!accessToken || !businessId) return;
    setError(null);
    // Update immediately, roll back on failure -- picking a value from a
    // <select> should feel instant, not wait on a round trip.
    const previous = channels;
    setChannels(
      (prev) => prev?.map((c) => (c.id === channelIdentityId ? { ...c, notificationFrequency: frequency } : c)) ?? null
    );
    try {
      await updateChannelFrequency(accessToken, businessId, channelIdentityId, frequency);
    } catch (err) {
      setChannels(previous ?? null);
      setError(err instanceof Error ? err.message : "Could not update notification setting");
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
          to view settings.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-8 sm:px-6 sm:py-16">
      <div>
        <h1 className="text-2xl font-semibold text-foreground">Settings</h1>
        <p className="text-sm text-muted">Link a WhatsApp number to chat with the assistant from your phone.</p>
      </div>
      {error && <p className="text-sm text-danger-fg">{error}</p>}

      <Card>
        <label className="mb-2 block text-sm font-medium text-foreground">Business</label>
        <BusinessPicker accessToken={accessToken} selectedBusinessId={businessId} onSelect={handleSelectBusiness} />
      </Card>

      {businessId && (
        <Card className="flex flex-col gap-4">
          <div>
            <h2 className="text-base font-semibold text-foreground">Link WhatsApp</h2>
            <p className="text-sm text-muted">
              Generate a code, then text it from WhatsApp to link this number to this business.
            </p>
          </div>

          {linkCode && !expired ? (
            <div className="flex flex-col items-start gap-2 rounded-md border border-border bg-background p-4">
              <span className="text-3xl font-semibold tracking-widest text-foreground">{linkCode.code}</span>
              <p className="text-sm text-muted">
                {linkCode.whatsappNumber ? (
                  <>
                    Text this code to <span className="font-medium text-foreground">{linkCode.whatsappNumber}</span>{" "}
                    on WhatsApp.
                  </>
                ) : (
                  "Text this code to the business's WhatsApp number."
                )}
              </p>
              {secondsLeft !== null && (
                <p className="text-xs text-muted">
                  Expires in {Math.floor(secondsLeft / 60)}m {secondsLeft % 60}s
                </p>
              )}
            </div>
          ) : (
            linkCode &&
            expired && <p className="text-sm text-danger-fg">That code has expired -- generate a new one.</p>
          )}

          <Button
            type="button"
            variant={linkCode && !expired ? "secondary" : "primary"}
            onClick={handleGenerateCode}
            disabled={generating}
            className="self-start"
          >
            {generating ? "Generating…" : linkCode ? "Generate new code" : "Generate link code"}
          </Button>
        </Card>
      )}

      {businessId && channels && (
        <Card className="flex flex-col gap-3">
          <h2 className="text-base font-semibold text-foreground">Linked numbers</h2>
          {channels.length === 0 ? (
            <p className="text-sm text-muted">No WhatsApp numbers linked yet.</p>
          ) : (
            <div className="flex flex-col gap-3">
              {channels.map((identity) => (
                <div key={identity.id} className="flex flex-col gap-3 rounded-md border border-border p-3">
                  <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex flex-col gap-1">
                      <p className="text-sm font-medium text-foreground">
                        {identity.displayName ?? "WhatsApp"} · {identity.maskedExternalId}
                      </p>
                      <span className="text-xs text-muted">
                        Linked {new Date(identity.verifiedAt).toLocaleString()}
                      </span>
                    </div>
                    <Button variant="danger" onClick={() => handleUnlink(identity.id)} className="sm:shrink-0">
                      Unlink
                    </Button>
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-muted">Proactive insights</label>
                    <Select
                      value={identity.notificationFrequency}
                      onChange={(event) =>
                        handleFrequencyChange(identity.id, event.target.value as NotificationFrequency)
                      }
                    >
                      {(Object.keys(FREQUENCY_LABELS) as NotificationFrequency[]).map((value) => (
                        <option key={value} value={value}>
                          {FREQUENCY_LABELS[value]}
                        </option>
                      ))}
                    </Select>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
