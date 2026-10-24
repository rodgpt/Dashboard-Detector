/**
 * El armazón del monitor: selector de sitio, pestañas y estado del equipo.
 *
 * La salud del sitio vive aquí, arriba de las pestañas, porque un equipo
 * degradado tiene que verse sin abrir nada (R-7.4). Cada pestaña carga su
 * propia fuente y falla sola (R-7.3).
 *
 * Las vistas se montan con `key={siteId}`: cambiar de sitio reinicia filtros,
 * paginación y ventanas. Antes el `offset` de Detecciones sobrevivía al cambio
 * y pedía la página N del sitio nuevo, que podía estar vacía — un "sin
 * detecciones" falso (review FE-05d, 2026-10-24).
 */
import { Suspense, lazy, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import AppHeader from "@/components/AppHeader";
import SitePicker from "@/components/SitePicker";
import HealthBadge, { readHealth, type HealthState } from "@/components/HealthBadge";
import { useResource } from "@/hooks/useResource";
import { data, ops, type DeviceAlert, type Health, type Site } from "@/api/client";
import { formatDateTime, timeAgo } from "@/lib/time";
import Detections from "@/pages/views/Detections";
import SensorStatus from "@/pages/views/SensorStatus";
import Acoustic from "@/pages/views/Acoustic";
import Ocean from "@/pages/views/Ocean";
import Analysis from "@/pages/views/Analysis";
import ClipDetail from "@/pages/views/ClipDetail";

// Leaflet sólo se descarga cuando hay un mapa que dibujar (review FE-05k).
const SiteMap = lazy(() => import("@/components/SiteMap"));

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

  // Polled so a unit going quiet becomes visible without a reload. Shared with
  // the sensor tab (prop), so the badge and the tab cannot disagree.
  const status = useResource<Record<string, unknown>>(
    () => data.status(siteId!), [siteId], { enabled: !!siteId, pollMs: 60_000 });

  const health = readHealth(status.data);

  // Outages the backend recorded while nobody was looking (R-7.5). Until
  // 2026-10-24 these rows existed and no screen read them. A failed fetch here
  // hides nothing else: it is its own source (R-7.3).
  const alerts = useResource<{ alerts: DeviceAlert[] }>(
    () => data.alerts(siteId!), [siteId], { enabled: !!siteId, pollMs: 300_000 });
  const openAlerts = alerts.data?.alerts.filter((a) => a.open) ?? [];
  // Whether anything this backend alerts about reaches a human (Rpi-Detector
  // D-020: the backend is the only sender). Not per site, not per unit.
  const server = useResource<Health>(() => ops.health(), [], { pollMs: 300_000 });
  const alertsReachNobody = server.data != null && server.data.alerts !== "twilio";

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

      {/* Silencio registrado por el backend: distinto del badge de arriba, que
          sólo sabe lo que dice el último status. Esto dice desde cuándo, y si
          alguien fue avisado fuera del panel. */}
      {openAlerts.map((a) => (
        <div className="banner error" role="alert" key={a.id}>
          <span>
            <strong>Alerta de silencio abierta.</strong>{" "}
            El equipo no reporta desde {a.last_seen_utc ? formatDateTime(a.last_seen_utc) : "una fecha desconocida"}{" "}
            (detectado {timeAgo(a.opened_utc)}).{" "}
            {a.notify_count > 0
              ? `Aviso enviado ${a.notify_count} ${a.notify_count === 1 ? "vez" : "veces"}.`
              : a.notify_error
                ? `El aviso externo falló: ${a.notify_error}.`
                : "Nadie ha sido avisado fuera de este panel (el servidor no tiene Twilio configurado)."}
          </span>
        </div>
      ))}

      {/* Del servidor, no del equipo (D-020): desde 2026-10-24 el único que
          avisa por WhatsApp/voz es el backend. Si no tiene Twilio, NINGUNA
          detección, caída ni degradación de NINGÚN sitio llega a nadie —
          solo a este panel. Informativo en banco; en producción es un fallo
          de despliegue, por eso el aviso es visible y no se puede ocultar. */}
      {alertsReachNobody && (
        <div className="banner warn" role="status">
          <span>
            <strong>Las alertas no llegan a nadie</strong> ({server.data?.alerts}):
            el servidor no tiene Twilio configurado. Las detecciones y caídas se
            registran y se muestran aquí con normalidad, pero nadie recibe
            WhatsApp ni llamada hasta que se configure.
          </span>
        </div>
      )}

      {/* El mapa vive arriba de las pestañas: es el "de un vistazo" del que
          habla R-7.4 cuando hay más de un sitio. SiteMap decide por sí mismo
          si dibuja el mapa o el aviso de "sin coordenadas" — el panel no debe
          desaparecer entero solo porque ningún sitio tiene lat/lon. Sólo el
          sitio seleccionado tiene estado consultado; los demás se dibujan como
          "sin consultar", no como "desconocido" (review FE-05i). */}
      <section className="panel">
        <div className="panel-head"><h2>Sitios</h2></div>
        <Suspense fallback={<div className="loading">Cargando mapa…</div>}>
          <SiteMap sites={list}
                   health={{ [siteId ?? ""]: health.state } as Record<string, HealthState>}
                   selected={siteId} onSelect={setSelected} />
        </Suspense>
      </section>

      <nav className="tab-nav">
        {TABS.map((t) => (
          <NavLink key={t.path} to={`/${t.path}`}
                   className={({ isActive }) => isActive ? "tab-btn active" : "tab-btn"}>
            {t.label}
          </NavLink>
        ))}
      </nav>

      {/* ?play= es un enlace compartido: se atiende sea cual sea la pestaña (R-8.5). */}
      {siteId && <ClipDetail key={siteId} siteId={siteId} />}

      {siteId && (
        <Routes>
          <Route index element={<Navigate to="detecciones" replace />} />
          <Route path="detecciones" element={<Detections key={siteId} siteId={siteId} />} />
          <Route path="acustica" element={<Acoustic key={siteId} siteId={siteId} />} />
          <Route path="mar" element={<Ocean key={siteId} siteId={siteId} />} />
          <Route path="analisis" element={<Analysis key={siteId} siteId={siteId} />} />
          <Route path="sensor" element={<SensorStatus key={siteId} siteId={siteId} status={status} />} />
          {/* Una ruta desconocida vuelve a la primera pestaña en vez de dejar el
              armazón con el cuerpo vacío (review FE-08). */}
          <Route path="*" element={<Navigate to="/detecciones" replace />} />
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
