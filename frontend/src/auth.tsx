import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { API_BASE_URL, apiFetch } from "./http";

export interface SessionUser {
  uid: string;
  email?: string | null;
  name: string;
  picture?: string | null;
  email_verified: boolean;
  provider?: string | null;
}

interface AuthContextValue {
  user: SessionUser | null;
  loading: boolean;
  error: string | null;
  establishSession: (idToken: string) => Promise<SessionUser>;
  refreshSession: () => Promise<SessionUser | null>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

async function parseMessage(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // fall back below
  }
  return fallback;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshSession = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/auth/me`, { credentials: "include" });
      if (response.status === 401) {
        setUser(null);
        setError(null);
        return null;
      }
      if (!response.ok) throw new Error(await parseMessage(response, "Unable to verify your ReviveAI session."));
      const next = await response.json() as SessionUser;
      setUser(next);
      setError(null);
      return next;
    } catch (err) {
      setUser(null);
      setError(err instanceof Error ? err.message : "Unable to verify your ReviveAI session.");
      return null;
    }
  }, []);

  useEffect(() => {
    let active = true;
    refreshSession().finally(() => { if (active) setLoading(false); });
    const onExpired = () => { setUser(null); setError("Your session ended. Sign in again to continue."); };
    window.addEventListener("reviveai:session-expired", onExpired);
    return () => { active = false; window.removeEventListener("reviveai:session-expired", onExpired); };
  }, [refreshSession]);

  const establishSession = useCallback(async (idToken: string) => {
    const response = await fetch(`${API_BASE_URL}/api/v1/auth/session`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id_token: idToken }),
    });
    if (!response.ok) throw new Error(await parseMessage(response, "Unable to start a secure ReviveAI session."));
    const next = await response.json() as SessionUser;
    setUser(next);
    setError(null);
    return next;
  }, []);

  const signOut = useCallback(async () => {
    try {
      await apiFetch(`${API_BASE_URL}/api/v1/auth/logout`, { method: "POST" });
    } finally {
      setUser(null);
      setError(null);
    }
  }, []);

  const value = useMemo<AuthContextValue>(() => ({ user, loading, error, establishSession, refreshSession, signOut }), [user, loading, error, establishSession, refreshSession, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider.");
  return value;
}
