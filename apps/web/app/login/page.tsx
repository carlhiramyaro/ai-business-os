"use client";

import { useSignIn, useSignUp } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";

type Mode = "login" | "register";

// Clerk's future-hooks API (useSignIn/useSignUp) returns { error } from
// each call instead of throwing -- error.message is dev-facing per Clerk's
// own docs, so longMessage is what's safe to show a user.
function errorMessage(error: { message: string; longMessage?: string } | null): string | null {
  if (!error) return null;
  return error.longMessage ?? error.message;
}

// Clerk's SignUp wants firstName/lastName, but the rest of this app (and
// the backend's users.full_name) only ever collects one field -- same
// split as scripts/import_users_to_clerk.py, kept in sync manually.
function splitName(fullName: string): { firstName: string; lastName: string } {
  const [firstName, ...rest] = fullName.trim().split(" ");
  return { firstName, lastName: rest.join(" ") };
}

export default function LoginPage() {
  const router = useRouter();
  const { signIn } = useSignIn();
  const { signUp } = useSignUp();

  const [mode, setMode] = useState<Mode>("login");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [pendingVerification, setPendingVerification] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleLogin(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { error: signInError } = await signIn.password({ emailAddress: email, password });
      if (signInError) {
        setError(errorMessage(signInError));
        return;
      }
      if (signIn.status === "complete") {
        await signIn.finalize();
        router.push("/entry");
      } else {
        // Multi-factor/other Clerk-side challenges aren't wired up in this
        // custom UI yet -- surface it rather than silently doing nothing.
        setError("Additional verification is required for this account.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRegister(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { firstName, lastName } = splitName(fullName);
      const { error: createError } = await signUp.password({ emailAddress: email, password, firstName, lastName });
      if (createError) {
        setError(errorMessage(createError));
        return;
      }
      const { error: sendError } = await signUp.verifications.sendEmailCode();
      if (sendError) {
        setError(errorMessage(sendError));
        return;
      }
      setPendingVerification(true);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleVerify(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { error: verifyError } = await signUp.verifications.verifyEmailCode({ code });
      if (verifyError) {
        setError(errorMessage(verifyError));
        return;
      }
      if (signUp.status === "complete") {
        await signUp.finalize();
        router.push("/entry");
      } else {
        setError("Could not verify that code.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleGoogle() {
    setError(null);
    const resource = mode === "login" ? signIn : signUp;
    const { error: ssoError } = await resource.sso({
      strategy: "oauth_google",
      redirectCallbackUrl: "/sso-callback",
      redirectUrl: "/entry",
    });
    if (ssoError) setError(errorMessage(ssoError));
  }

  if (pendingVerification) {
    return (
      <div className="flex flex-1 items-center justify-center px-4 py-8 sm:px-6 sm:py-16">
        <Card className="w-full max-w-sm">
          <h1 className="mb-1 text-lg font-semibold text-foreground">Check your email</h1>
          <p className="mb-6 text-sm text-muted">Enter the code we sent to {email}.</p>
          <form onSubmit={handleVerify} className="flex flex-col gap-3">
            <Input
              placeholder="Verification code"
              value={code}
              onChange={(event) => setCode(event.target.value)}
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus
              required
            />
            {error && <p className="text-sm text-danger-fg">{error}</p>}
            <Button type="submit" disabled={submitting} className="mt-2">
              Verify
            </Button>
          </form>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex flex-1 items-center justify-center px-4 py-8 sm:px-6 sm:py-16">
      <Card className="w-full max-w-sm">
        <div className="mb-6 flex gap-6 border-b border-border text-sm font-medium">
          <button
            className={`-mb-px border-b-2 px-1 py-3 ${mode === "login" ? "border-brand text-foreground" : "border-transparent text-muted"}`}
            onClick={() => {
              setMode("login");
              setError(null);
            }}
          >
            Log in
          </button>
          <button
            className={`-mb-px border-b-2 px-1 py-3 ${mode === "register" ? "border-brand text-foreground" : "border-transparent text-muted"}`}
            onClick={() => {
              setMode("register");
              setError(null);
            }}
          >
            Sign up
          </button>
        </div>

        <form onSubmit={mode === "register" ? handleRegister : handleLogin} className="flex flex-col gap-3">
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
          {/* Mount point for Clerk's bot-protection challenge, required
              when using custom UI instead of <SignUp />/<SignIn />. Invisible
              unless Clerk decides a challenge is needed. */}
          <div id="clerk-captcha" />
          {error && <p className="text-sm text-danger-fg">{error}</p>}
          <Button type="submit" disabled={submitting} className="mt-2">
            {mode === "register" ? "Create account" : "Log in"}
          </Button>
        </form>

        <div className="my-4 flex items-center gap-3 text-xs text-muted">
          <div className="h-px flex-1 bg-border" />
          or
          <div className="h-px flex-1 bg-border" />
        </div>

        <Button type="button" variant="secondary" onClick={handleGoogle} className="w-full">
          Continue with Google
        </Button>
      </Card>
    </div>
  );
}
