/**
 * Pantalla de acceso.
 *
 * 401 aquí significa credenciales inválidas, no sesión expirada; 429 significa
 * espera. Cada fallo se muestra, nunca se ignora (R-7.1).
 */
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { ApiError } from "@/api/client";

export default function Login() {
  const { me, loading, signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /** Sólo rutas internas: un `from` externo sería una redirección abierta. */
  const from = (() => {
    const raw = (location.state as { from?: string } | null)?.from ?? "/";
    return raw.startsWith("/") && !raw.startsWith("//") ? raw : "/";
  })();

  if (loading) return <div className="centered loading">Cargando…</div>;
  if (me) return <Navigate to={from} replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email.trim() || !password) {
      setError("Ingresa tu correo y tu contraseña.");
      return;
    }
    setBusy(true);
    try {
      await signIn(email.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Correo o contraseña incorrectos.");
      } else if (err instanceof ApiError && err.status === 429) {
        setError("Demasiados intentos fallidos. Espera unos minutos y vuelve a intentar.");
      } else if (err instanceof ApiError && err.isOffline) {
        setError("Sin conexión con el servidor. Revisa tu red e intenta de nuevo.");
      } else {
        setError(err instanceof ApiError ? err.message : "Error inesperado al iniciar sesión.");
      }
      setBusy(false);
    }
  }

  return (
    <div className="auth-body">
      <main className="auth-card">
        <div className="auth-head">
          <img src="/assets/logo.png" className="brand-logo" alt="MAR FUTURA" />
          <p>Monitoreo acústico marino — acceso</p>
        </div>

        <form onSubmit={onSubmit} noValidate>
          <div className="field">
            <label htmlFor="email">Correo electrónico</label>
            <input
              id="email" type="email" autoComplete="username" autoFocus required
              value={email} onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="password">Contraseña</label>
            <input
              id="password" type="password" autoComplete="current-password" required
              value={password} onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error && <div className="form-feedback error" role="alert">{error}</div>}
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Ingresando…" : "Ingresar"}
          </button>
        </form>
      </main>
    </div>
  );
}
