/**
 * Mapa de sitios, con el color de salud de cada uno.
 *
 * **Las coordenadas son sensibles.** Localizan hardware sin vigilancia en un
 * lugar remoto, y el modelo de amenaza incluye a quienes el sistema detecta.
 * Por eso el mapa no hace zoom cerrado ni muestra decimales completos: sitúa el
 * sitio en la costa, no en la caja. Quien va a repararlo tiene la coordenada por
 * otro camino; quien mira el panel no la necesita.
 */
import { useEffect } from "react";
import { MapContainer, TileLayer, CircleMarker, Tooltip, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import type { Site } from "@/api/client";
import type { HealthState } from "@/components/HealthBadge";

const COLOR: Record<HealthState, string> = {
  ok: "#22c55e", degraded: "#f59e0b", offline: "#ef4444", unknown: "#9fbcc8",
};
const LABEL: Record<HealthState, string> = {
  ok: "operativo", degraded: "degradado", offline: "sin contacto", unknown: "estado desconocido",
};

/** Precisión reducida a propósito: ~11 m, suficiente para un mapa. */
const coarse = (n: number) => +n.toFixed(4);

/** Zoom máximo deliberado. Acercarse más no aporta y sí expone. */
const MAX_ZOOM = 12;

function FitSites({ sites }: { sites: Site[] }) {
  const map = useMap();
  useEffect(() => {
    const pts = sites.filter((s) => s.lat != null && s.lon != null)
                     .map((s) => [coarse(s.lat), coarse(s.lon)] as [number, number]);
    if (pts.length === 1) map.setView(pts[0]!, 9);
    else if (pts.length > 1) map.fitBounds(pts, { padding: [40, 40], maxZoom: MAX_ZOOM });
  }, [sites, map]);
  return null;
}

export default function SiteMap({ sites, health, selected, onSelect }: {
  sites: Site[];
  /** Estado por site_id. Los sitios sin entrada salen como "desconocido". */
  health: Record<string, HealthState>;
  selected: string | null;
  onSelect: (siteId: string) => void;
}) {
  const located = sites.filter((s) => s.lat != null && s.lon != null);

  if (located.length === 0) {
    return (
      <p className="loading">
        Ningún sitio tiene coordenadas registradas, así que no hay nada que
        situar. Se añaden en el panel de administración.
      </p>
    );
  }

  return (
    <>
      <div className="site-map">
        <MapContainer center={[coarse(located[0]!.lat), coarse(located[0]!.lon)]}
                      zoom={8} maxZoom={MAX_ZOOM} scrollWheelZoom={false}
                      style={{ height: "100%", width: "100%" }}>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            maxZoom={MAX_ZOOM}
          />
          <FitSites sites={located} />
          {located.map((s) => {
            const state = health[s.id] ?? "unknown";
            return (
              <CircleMarker
                key={s.id}
                center={[coarse(s.lat), coarse(s.lon)]}
                radius={s.id === selected ? 12 : 8}
                pathOptions={{
                  color: COLOR[state], fillColor: COLOR[state],
                  fillOpacity: s.id === selected ? 0.9 : 0.6,
                  weight: s.id === selected ? 3 : 2,
                }}
                eventHandlers={{ click: () => onSelect(s.id) }}
              >
                <Tooltip>
                  <strong>{s.name || s.id}</strong><br />
                  {LABEL[state]}
                  {s.active === false && <><br />sitio inactivo</>}
                </Tooltip>
              </CircleMarker>
            );
          })}
        </MapContainer>
      </div>
      <p className="chart-note">
        Coordenadas mostradas con precisión reducida y zoom limitado a propósito:
        sitúan el sitio, no el equipo.
      </p>
    </>
  );
}
