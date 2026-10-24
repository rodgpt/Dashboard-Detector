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
  /** The server answered, but not with a session or a 401: a 5xx, a proxy
   *  page, a 503. Also not "logged out" — and not "offline" either, which is
   *  what it used to be called (review FE-08). */
  serverError: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  async function refresh() {
    try {
      setMe(await auth.me());
      setOffline(false);
      setServerError(null);
    } catch (err) {
      setMe(null);
      // A 401 means "log in". Unreachable means offline. Anything else means
      // the server is there and broken, which must not be rendered as a clean
      // logged-out state nor as a dead network.
      const api = err instanceof ApiError ? err : null;
      setOffline(api?.isOffline ?? true);
      setServerError(api && !api.isAuth && !api.isOffline ? `${api.status} ${api.message}` : null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, []);

  const value: AuthState = {
    me, loading, offline, serverError,
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
