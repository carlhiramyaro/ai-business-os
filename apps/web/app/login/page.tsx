"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";

type Mode = "login" | "register";

export default function LoginPage() {
  const { login, register } = useAuth();
  const router = useRouter();

  const [mode, setMode] = useState<Mode>("login");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "register") {
        await register(fullName, email, password);
      } else {
        await login(email, password);
      }
      router.push("/entry");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center px-4 py-8 sm:px-6 sm:py-16">
      <Card className="w-full max-w-sm">
        <div className="mb-6 flex gap-6 border-b border-border text-sm font-medium">
          <button
            className={`-mb-px border-b-2 px-1 py-3 ${mode === "login" ? "border-brand text-foreground" : "border-transparent text-muted"}`}
            onClick={() => setMode("login")}
          >
            Log in
          </button>
          <button
            className={`-mb-px border-b-2 px-1 py-3 ${mode === "register" ? "border-brand text-foreground" : "border-transparent text-muted"}`}
            onClick={() => setMode("register")}
          >
            Sign up
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          {mode === "register" && (
            <Input
              placeholder="Full name"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              autoComplete="name"
              required
            />
          )}
          <Input
            placeholder="Email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="email"
            inputMode="email"
            autoCapitalize="none"
            spellCheck={false}
            required
          />
          <Input
            placeholder="Password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete={mode === "register" ? "new-password" : "current-password"}
            required
          />
          {error && <p className="text-sm text-danger-fg">{error}</p>}
          <Button type="submit" disabled={submitting} className="mt-2">
            {mode === "register" ? "Create account" : "Log in"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
