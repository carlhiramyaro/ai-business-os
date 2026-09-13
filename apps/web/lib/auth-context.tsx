"use client";

import { useAuth as useClerkAuth, useUser } from "@clerk/nextjs";
import { createContext, useContext, useEffect, useState } from "react";
import { AuthUser, GetToken, getCurrentUser } from "@/lib/api";

interface AuthContextValue {
  getToken: GetToken;
  user: AuthUser | null;
  loading: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { isLoaded, isSignedIn, getToken } = useClerkAuth();
  const { user: clerkUser } = useUser();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  // Reset synchronously during render on sign-out -- same "adjust state
  // during render" pattern NavBar.tsx uses for pathname changes, avoiding
  // a setState-in-effect-body cascading render for this (synchronous,
  // derived-from-other-state) case. The effect below handles only the
  // genuinely async case: fetching our own users row once signed in.
  const [wasSignedIn, setWasSignedIn] = useState(isSignedIn);
  if (isLoaded && isSignedIn !== wasSignedIn) {
    setWasSignedIn(isSignedIn);
    if (!isSignedIn) {
      setUser(null);
      setLoading(false);
    }
  }

  // Fetches our own users row (not Clerk's) so `user.id` stays the ID every
  // business/report/etc. record is keyed by -- see app/dependencies.py's
  // just-in-time provisioning. Re-runs on clerkUser?.id rather than a
  // stable reference so it re-fires across sign-out/sign-in without
  // depending on getToken's identity.
  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;

    let cancelled = false;
    getToken()
      .then((token) => (token ? getCurrentUser(token) : null))
      .then((currentUser) => {
        if (!cancelled) setUser(currentUser);
      })
      .catch(() => {
        if (!cancelled) setUser(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, isSignedIn, clerkUser?.id]);

  return <AuthContext.Provider value={{ getToken, user, loading }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
