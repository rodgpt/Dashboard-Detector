/**
 * El armazón del monitor: selector de sitio, pestañas y estado del equipo.
 *
 * La salud del sitio vive aquí, arriba de las pestañas, porque un equipo
 * degradado tiene que verse sin abrir nada (R-7.4). Cada pestaña carga su
 * propia fuente y falla sola (R-7.3).
 */
import { useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import AppHeader from "@/components/AppHeader";
import SitePicker from "@/components/SitePicker";
import HealthBadge, { readHealth, type HealthState } from "@/components/HealthBadge";
import SiteMap from "@/components/SiteMap";
import { useResource } from "@/hooks/useResource";
import { data, type Site } from "@/api/client";
import { timeAgo } from "@/lib/time";
import Detections from "@/pages/views/Detections";
import SensorStatus from "@/pages/views/SensorStatus";
import Acoustic from "@/pages/views/Acoustic";
import Ocean from "@/pages/views/Ocean";
import Analysis from "@/pages/views/Analysis";
import ClipDetail from "@/pages/views/ClipDetail";

const TABS = [
  { path: "detecciones", label: "Detecciones" },
  { path: "acustica",    label: "Monitoreo acústico" },
  { path: "mar",         label: "Condiciones del mar" },
  { path: "analisis",    label: "Análisis" },
  { path: "sensor",      label: "Estado del sensor" },
];

export default function Dashboard() {
  const sites = useResource<{ sites: Site[] }>(() => data.sites(), []);
  const [selected, setSelected] = useState<string | null>(null);

  const list = sites.data?.sites ?? [];
  const siteId = selected ?? list[0]?.id ?? null;

  // Polled so a unit going quiet becomes visible without a reload.
  const status = useResource<Record<string, unknown>>(
    () => data.status(siteId!), [siteId], { enabled: !!siteId, pollMs: 60_000 });

  const health = readHealth(status.data);

  if (sites.loading) return <Shell><div className="loading">Cargando sitios…</div></Shell>;

  if (sites.failed) {
    return (
      <Shell>
        <div className="banner error" role="alert">
          <span>No se pudo cargar la lista de sitios: {sites.error?.message}</span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={sites.reload}>
            Reintentar
          </button>
        </div>
      </Shell>
    );
  }

  if (list.length === 0) {
    return (
      <Shell>
        <div className="banner error" role="alert">
          Tu cuenta no tiene ningún sitio asignado, así que no hay nada que mostrar.
          Pide a la administración que te asigne uno.
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="monitor-bar">
        <SitePicker sites={list} value={siteId} onChange={setSelected} />
        <div className="monitor-status">
          <HealthBadge status={status.data} />
          {status.stale && (
            <span className="panel-age stale">
              estado sin actualizar desde {timeAgo(status.lastLoadedAt)}
            </span>
          )}
          {status.failed && (
            <span className="panel-age stale">
              {status.error?.status === 404
                ? "el equipo no ha publicado estado"
                : `estado no disponible: ${status.error?.message}`}
            </span>
          )}
        </div>
      </div>

      {/* El aviso que importa: degradado o sin contacto, arriba de todo. */}
      {(health.state === "degraded" || health.state === "offline") && (
        <div className="banner error" role="alert">
          <span>
            <strong>{health.state === "offline" ? "Sin contacto con el equipo." : "Equipo degradado."}</strong>
            {health.reason ? ` ${health.reason}.` : ""} Las detecciones que se
            muestran pueden estar incompletas.
          </span>
        </div>
      )}

      {/* El mapa vive arriba de las pestañas: es el "de un vistazo" del que
          habla R-7.4 cuando hay más de un sitio. */}
      {list.filter((s) => s.lat != null && s.lon != null).length > 0 && (
        <section className="panel">
          <div className="panel-head"><h2>Sitios</h2></div>
          <SiteMap sites={list}
                   health={{ [siteId ?? ""]: health.state } as Record<string, HealthState>}
                   selected={siteId} onSelect={setSelected} />
        </section>
      )}

      <nav className="tab-nav">
        {TABS.map((t) => (
          <NavLink key={t.path} to={t.path}
                   className={({ isActive }) => isActive ? "tab-btn active" : "tab-btn"}>
            {t.label}
          </NavLink>
        ))}
      </nav>

      {/* ?play= es un enlace compartido: se atiende sea cual sea la pestaña (R-8.5). */}
      {siteId && <ClipDetail siteId={siteId} />}

      {siteId && (
        <Routes>
          <Route index element={<Navigate to="detecciones" replace />} />
          <Route path="detecciones" element={<Detections siteId={siteId} />} />
          <Route path="acustica" element={<Acoustic siteId={siteId} />} />
          <Route path="mar" element={<Ocean siteId={siteId} />} />
          <Route path="analisis" element={<Analysis siteId={siteId} />} />
          <Route path="sensor" element={<SensorStatus siteId={siteId} />} />
        </Routes>
      )}
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-shell">
      <AppHeader title="Monitor acústico" subtitle="Mar Futura" />
      {children}
    </div>
  );
}
