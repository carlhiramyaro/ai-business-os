"use client";

import Link from "next/link";
import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { createConversation, sendChatMessage } from "@/lib/api";
import { BusinessPicker } from "@/components/BusinessPicker";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export default function ChatPage() {
  const { accessToken, loading } = useAuth();
  const [error, setError] = useState<string | null>(null);

  const [businessId, setBusinessId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [startingConversation, setStartingConversation] = useState(false);

  async function handleSelectBusiness(id: string) {
    if (!accessToken) return;
    setError(null);
    setBusinessId(id);
    setConversationId(null);
    setMessages([]);
    setStartingConversation(true);
    try {
      const conversation = await createConversation(accessToken, id);
      setConversationId(conversation.conversationId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start conversation");
    } finally {
      setStartingConversation(false);
    }
  }

  async function handleSend(event: React.FormEvent) {
    event.preventDefault();
    if (!accessToken || !businessId || !conversationId || !draft.trim()) return;
    setError(null);
    setSending(true);

    const question = draft;
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setDraft("");

    try {
      const response = await sendChatMessage(accessToken, businessId, conversationId, question);
      setMessages((prev) => [...prev, { role: "assistant", content: response.answer }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Message failed");
    } finally {
      setSending(false);
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
          to chat with your data.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-6 py-16">
      <div>
        <h1 className="text-2xl font-semibold text-foreground">Chat</h1>
        <p className="text-sm text-muted">Ask questions grounded in your business&apos;s report and data.</p>
      </div>
      {error && <p className="text-sm text-danger-fg">{error}</p>}

      <Card>
        <label className="mb-2 block text-sm font-medium text-foreground">Business</label>
        <BusinessPicker accessToken={accessToken} selectedBusinessId={businessId} onSelect={handleSelectBusiness} />
      </Card>

      {startingConversation && <p className="text-sm text-muted">Starting conversation…</p>}

      {conversationId && (
        <Card className="flex flex-col gap-4">
          <div className="flex h-96 flex-col gap-3 overflow-y-auto">
            {messages.length === 0 && (
              <p className="text-sm text-muted">
                Ask something like &quot;Why is profit decreasing?&quot; or &quot;What should I focus on?&quot;
              </p>
            )}
            {messages.map((message, index) => (
              <div
                key={index}
                className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                  message.role === "user"
                    ? "self-end bg-brand text-brand-foreground"
                    : "self-start bg-background text-foreground"
                }`}
              >
                {message.content}
              </div>
            ))}
            {sending && <p className="self-start text-sm text-muted">Thinking…</p>}
          </div>

          <form onSubmit={handleSend} className="flex gap-2">
            <Input
              className="flex-1"
              placeholder="Ask a question about this business..."
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              disabled={sending}
            />
            <Button type="submit" disabled={sending}>
              Send
            </Button>
          </form>
        </Card>
      )}
    </div>
  );
}
