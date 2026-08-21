import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";

export default function AppHeader({ title, subtitle }: { title: string; subtitle: string }) {
  const { me, signOut } = useAuth();
  const navigate = useNavigate();

  return (
    <header className="app-header">
      <div className="header-left">
        <img src="/assets/logo.png" className="brand-logo" alt="MAR FUTURA" />
        <div>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
      </div>
      <div className="header-right">
        {me && <span className="who">{me.email}</span>}
        <Link to="/">Panel</Link>
        {me?.role === "admin" && <Link to="/admin">Administración</Link>}
        <button
          type="button" className="btn btn-ghost btn-sm"
          onClick={async () => { await signOut(); navigate("/login", { replace: true }); }}
        >
          Cerrar sesión
        </button>
      </div>
    </header>
  );
}
