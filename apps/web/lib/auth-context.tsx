"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { AuthUser, getCurrentUser, loginUser, refreshAccessToken, registerUser } from "@/lib/api";

// Access tokens expire after ACCESS_TOKEN_EXPIRE_MINUTES (apps/api/app/
// security.py, default 15) -- refreshing every 5 minutes gives 3x
// headroom. This is a frontend-side guess at a backend env var it can't
// query directly; if that default is ever changed via SSM without
// updating this constant, sessions go back to silently breaking mid-use.
// See docs/decisions.md [mobile-first polish] for why this exists: a
// phone-paced walk through register -> business -> data in -> chat ->
// insights can easily exceed 15 minutes, and every API call fails with a
// generic per-page error instead of a re-login prompt once it does.
const REFRESH_INTERVAL_MS = 5 * 60 * 1000;

interface AuthContextValue {
  accessToken: string | null;
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (fullName: string, email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const stored = localStorage.getItem("accessToken");
    const restore = stored
      ? getCurrentUser(stored)
          .then((currentUser) => {
            setAccessToken(stored);
            setUser(currentUser);
          })
          .catch(() => localStorage.removeItem("accessToken"))
      : Promise.resolve();

    restore.finally(() => setLoading(false));
  }, []);

  // Proactive refresh, not a reactive 401-retry: lib/api.ts has ~30
  // independent fetch()-calling functions with no shared client to
  // intercept a failed request through, so replacing the token before it
  // expires (rather than recovering after a request already failed) is
  // the change with the smallest footprint. Runs whenever accessToken
  // transitions from null to a value -- covers both a fresh login and a
  // session restored from localStorage on page load -- and each
  // successful refresh re-triggers this effect (accessToken changes),
  // which harmlessly resets the interval for another REFRESH_INTERVAL_MS.
  useEffect(() => {
    if (!accessToken) return;

    async function refresh() {
      const storedRefreshToken = localStorage.getItem("refreshToken");
      if (!storedRefreshToken) return;
      try {
        const tokens = await refreshAccessToken(storedRefreshToken);
        localStorage.setItem("accessToken", tokens.accessToken);
        localStorage.setItem("refreshToken", tokens.refreshToken);
        setAccessToken(tokens.accessToken);
      } catch {
        // Refresh token also expired/invalid, or already consumed by a
        // concurrent refresh -- nothing recoverable client-side. Sign out
        // cleanly rather than leaving every subsequent API call failing
        // silently against a dead access token.
        localStorage.removeItem("accessToken");
        localStorage.removeItem("refreshToken");
        setAccessToken(null);
        setUser(null);
      }
    }

    const interval = setInterval(refresh, REFRESH_INTERVAL_MS);

    // Mobile browsers throttle/suspend JS timers on backgrounded tabs --
    // a phone backgrounded mid-session past the access token's expiry and
    // then resumed later needs this to catch what the interval alone
    // would miss.
    function handleVisibilityChange() {
      if (document.visibilityState === "visible") refresh();
    }
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [accessToken]);

  async function login(email: string, password: string) {
    const tokens = await loginUser(email, password);
    localStorage.setItem("accessToken", tokens.accessToken);
    localStorage.setItem("refreshToken", tokens.refreshToken);
    setAccessToken(tokens.accessToken);
    setUser(await getCurrentUser(tokens.accessToken));
  }

  async function register(fullName: string, email: string, password: string) {
    await registerUser(fullName, email, password);
    await login(email, password);
  }

  function logout() {
    localStorage.removeItem("accessToken");
    localStorage.removeItem("refreshToken");
    setAccessToken(null);
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ accessToken, user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
