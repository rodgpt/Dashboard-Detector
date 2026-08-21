import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { AuthProvider, useAuth } from "@/auth/AuthContext";
import Login from "@/pages/Login";
import Admin from "@/pages/Admin";
import Dashboard from "@/pages/Dashboard";

/** Gate for anything that needs a session. 401 sends you to login; a server we
 *  cannot reach says so instead of pretending you are logged out (R-7.1). */
function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading, offline } = useAuth();
  const location = useLocation();

  if (loading) return <div className="centered loading">Cargando…</div>;
  if (offline) {
    return (
      <div className="centered">
        <div className="banner error" role="alert">
          Sin conexión con el servidor. No se puede verificar la sesión.
          Recarga la página para reintentar.
        </div>
      </div>
    );
  }
  if (!me) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/admin/*" element={<RequireAuth><Admin /></RequireAuth>} />
          <Route path="/" element={<RequireAuth><Dashboard /></RequireAuth>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
