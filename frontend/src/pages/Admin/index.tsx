/**
 * Panel de administración: usuarios, sitios, dispositivos, índice (R-3.3).
 *
 * 403 muestra un mensaje; nunca redirige al acceso. Conflating them logs a user
 * out every time they open something they may not see (API-CONTRACT.md).
 *
 * Las tres fuentes se cargan con `useResource`, igual que el resto del panel:
 * cada una falla sola, dice POR QUÉ (código y mensaje del servidor, no un texto
 * fijo) y se puede reintentar sola. Antes un 403, un 500 y una red caída se
 * leían idénticos (review FE-05c, 2026-10-24).
 */
import { useEffect, useState } from "react";
import AppHeader from "@/components/AppHeader";
import { useAuth } from "@/auth/AuthContext";
import { useResource, type Resource } from "@/hooks/useResource";
import { admin, ApiError, type AdminDevice, type AdminSites, type AdminUser, type Site, type SitesSource } from "@/api/client";
import SitesPanel from "@/pages/Admin/SitesPanel";
import UsersPanel from "@/pages/Admin/UsersPanel";
import DevicesPanel from "@/pages/Admin/DevicesPanel";
import IndexPanel from "@/pages/Admin/IndexPanel";

export default function Admin() {
  const { me } = useAuth();
  const isAdmin = me?.role === "admin";

  const sitesRes = useResource<AdminSites>(() => admin.sites(), [], { enabled: isAdmin });
  const usersRes = useResource<AdminUser[]>(() => admin.users(), [], { enabled: isAdmin });
  const devicesRes = useResource<AdminDevice[]>(() => admin.devices(), [], { enabled: isAdmin });

  // Copias editables: los paneles hijos actualizan la lista tras crear/borrar
  // sin volver a pedirla; una recarga del recurso las vuelve a sembrar.
  const [sites, setSites] = useState<Site[]>([]);
  const [sitesSource, setSitesSource] = useState<SitesSource>("empty");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [devices, setDevices] = useState<AdminDevice[]>([]);
  useEffect(() => { if (sitesRes.data) { setSites(sitesRes.data.sites); setSitesSource(sitesRes.data.source); } }, [sitesRes.data]);
  useEffect(() => { if (usersRes.data) setUsers(usersRes.data); }, [usersRes.data]);
  useEffect(() => { if (devicesRes.data) setDevices(devicesRes.data); }, [devicesRes.data]);

  // Errores de acciones (crear, borrar…): con clave propia, no por texto, para
  // que dos mensajes iguales no colisionen.
  const [actionErrors, setActionErrors] = useState<{ id: number; text: string }[]>([]);
  const pushError = (text: string) => setActionErrors((p) => [...p, { id: Date.now() + Math.random(), text }]);

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

  const loading = sitesRes.loading || usersRes.loading || devicesRes.loading;

  return (
    <div className="app-shell">
      <AppHeader title="Administración" subtitle="Usuarios, sitios y dispositivos" />

      <SourceError label="la lista de sitios" res={sitesRes}
                   consequence="Las asignaciones no se pueden editar." />
      <SourceError label="la lista de usuarios" res={usersRes} />
      <SourceError label="la lista de dispositivos" res={devicesRes} />

      {actionErrors.map((e) => (
        <div className="banner error" role="alert" key={e.id}>
          <span>{e.text}</span>
          <button type="button" className="btn btn-ghost btn-sm"
                  onClick={() => setActionErrors((p) => p.filter((x) => x.id !== e.id))}>
            Cerrar
          </button>
        </div>
      ))}

      {loading ? (
        <div className="loading">Cargando…</div>
      ) : (
        <>
          {sitesRes.data && (
            <SitesPanel
              sites={sites} source={sitesSource}
              onChanged={(next, source) => { setSites(next); setSitesSource(source); }}
              onError={pushError}
            />
          )}
          {usersRes.data && (
            <UsersPanel
              sites={sites} users={users} meEmail={me.email}
              onChanged={setUsers} onError={pushError}
            />
          )}
          {devicesRes.data && (
            <DevicesPanel
              sites={sites} devices={devices}
              onChanged={setDevices} onError={pushError}
            />
          )}
          <IndexPanel />
        </>
      )}
    </div>
  );
}

/** Un recurso que falló: el motivo real del servidor, y reintento propio. */
function SourceError<T>({ label, res, consequence }: {
  label: string; res: Resource<T>; consequence?: string;
}) {
  if (!res.failed) return null;
  const why = res.error?.isForbidden
    ? "sin permiso (403)"
    : res.error?.isOffline
      ? "sin conexión con el servidor"
      : `${res.error?.status ?? "?"} ${res.error?.message ?? ""}`.trim();
  return (
    <div className="banner error" role="alert">
      <span>No se pudo cargar {label}: {why}.{consequence ? ` ${consequence}` : ""}</span>
      {!res.terminal && (
        <button type="button" className="btn btn-ghost btn-sm" onClick={res.reload}>
          Reintentar
        </button>
      )}
    </div>
  );
}

/** Shared by the panels: turn a thrown error into a message worth showing. */
export function messageFor(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}
