"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { AuthUser, getCurrentUser, loginUser, registerUser } from "@/lib/api";

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
