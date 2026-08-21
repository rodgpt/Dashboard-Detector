/**
 * Session state, resolved once at boot from GET /api/auth/me.
 *
 * The cookie is HttpOnly, so the browser cannot read it and this context is not
 * the credential — it is only what the server told us about the session. That
 * is deliberate: the browser never holds a credential (R-4.2).
 */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { auth, ApiError, type Me } from "@/api/client";

interface AuthState {
  me: Me | null;
  /** Still asking the server. Render nothing decisive until this is false. */
  loading: boolean;
  /** The server was unreachable — different from "not logged in" (R-7.1). */
  offline: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);

  async function refresh() {
    try {
      setMe(await auth.me());
      setOffline(false);
    } catch (err) {
      setMe(null);
      // A 401 means "log in". Anything else means we could not ask, which must
      // not be rendered as a clean logged-out state.
      setOffline(err instanceof ApiError && !err.isAuth);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, []);

  const value: AuthState = {
    me, loading, offline,
    async signIn(email, password) {
      await auth.login(email, password);
      await refresh();
    },
    async signOut() {
      try { await auth.logout(); } catch { /* the server clears it regardless */ }
      setMe(null);
    },
    refresh,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used inside <AuthProvider>");
  return v;
}
