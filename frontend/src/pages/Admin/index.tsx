/**
 * Panel de administración: usuarios, dispositivos y su configuración (R-3.3).
 *
 * 403 muestra un mensaje; nunca redirige al acceso. Conflating them logs a user
 * out every time they open something they may not see (API-CONTRACT.md).
 */
import { useCallback, useEffect, useState } from "react";
import AppHeader from "@/components/AppHeader";
import { useAuth } from "@/auth/AuthContext";
import { admin, ApiError, type AdminDevice, type AdminUser, type Site, type SitesSource } from "@/api/client";
import SitesPanel from "@/pages/Admin/SitesPanel";
import UsersPanel from "@/pages/Admin/UsersPanel";
import DevicesPanel from "@/pages/Admin/DevicesPanel";

export default function Admin() {
  const { me } = useAuth();
  const [sites, setSites] = useState<Site[]>([]);
  const [sitesSource, setSitesSource] = useState<SitesSource>("empty");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [devices, setDevices] = useState<AdminDevice[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  const isAdmin = me?.role === "admin";

  const load = useCallback(async () => {
    setLoading(true);
    setErrors([]);
    // Independientes a propósito: si una fuente falla, las otras se muestran (R-7.3)
    const [s, u, d] = await Promise.allSettled([admin.sites(), admin.users(), admin.devices()]);
    const failed: string[] = [];

    if (s.status === "fulfilled") { setSites(s.value.sites); setSitesSource(s.value.source); }
    else failed.push("No se pudo cargar la lista de sitios. Las asignaciones no se pueden editar.");

    if (u.status === "fulfilled") setUsers(u.value);
    else failed.push("No se pudo cargar la lista de usuarios.");

    if (d.status === "fulfilled") setDevices(d.value);
    else failed.push("No se pudo cargar la lista de dispositivos.");

    setErrors(failed);
    setLoading(false);
  }, []);

  useEffect(() => { if (isAdmin) void load(); else setLoading(false); }, [isAdmin, load]);

  if (!isAdmin) {
    return (
      <div className="app-shell">
        <AppHeader title="Administración" subtitle="Usuarios, sitios y dispositivos" />
        <div className="banner error" role="alert">
          Tu cuenta no tiene permiso de administración. Si crees que es un error,
          contacta a la persona administradora.
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <AppHeader title="Administración" subtitle="Usuarios, sitios y dispositivos" />

      {errors.map((e) => (
        <div className="banner error" role="alert" key={e}>
          <span>{e}</span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => void load()}>
            Reintentar
          </button>
        </div>
      ))}

      {loading ? (
        <div className="loading">Cargando…</div>
      ) : (
        <>
          <SitesPanel
            sites={sites} source={sitesSource}
            onChanged={(next, source) => { setSites(next); setSitesSource(source); }}
            onError={(m) => setErrors((p) => [...p, m])}
          />
          <UsersPanel
            sites={sites} users={users} meEmail={me.email}
            onChanged={setUsers} onError={(m) => setErrors((p) => [...p, m])}
          />
          <DevicesPanel
            sites={sites} devices={devices}
            onChanged={setDevices} onError={(m) => setErrors((p) => [...p, m])}
          />
        </>
      )}
    </div>
  );
}

/** Shared by the panels: turn a thrown error into a message worth showing. */
export function messageFor(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}
