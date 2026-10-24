import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { AuthProvider, useAuth } from "@/auth/AuthContext";
import Login from "@/pages/Login";
import Admin from "@/pages/Admin";
import Dashboard from "@/pages/Dashboard";

/** Gate for anything that needs a session. 401 sends you to login; a server we
 *  cannot reach says so instead of pretending you are logged out (R-7.1). */
function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading, offline, serverError } = useAuth();
  const location = useLocation();

  if (loading) return <div className="centered loading">Cargando…</div>;
  if (offline || serverError) {
    return (
      <div className="centered">
        <div className="banner error" role="alert">
          {offline
            ? "Sin conexión con el servidor. No se puede verificar la sesión."
            : `El servidor respondió con un error al verificar la sesión: ${serverError}.`}
          {" "}Recarga la página para reintentar.
        </div>
      </div>
    );
  }
  // `search` incluido: un enlace ?play= compartido por WhatsApp tiene que
  // sobrevivir al paso por el acceso (R-8.5). Durante un mes sólo viajaba el
  // pathname y el enlace llegaba a la portada sin su clip (review FE-02).
  if (!me) return <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/admin/*" element={<RequireAuth><Admin /></RequireAuth>} />
          <Route path="/*" element={<RequireAuth><Dashboard /></RequireAuth>} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
