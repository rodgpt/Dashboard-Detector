/**
 * Estado del sensor: la pestaña donde un equipo enfermo tiene que verse enfermo.
 *
 * Reglas que esta vista respeta:
 *  - `health` primero, arriba, con la razón en palabras (R-7.4).
 *  - `null` es ausencia, nunca cero (`StatGrid`).
 *  - El contrato dice que `health` puede traer más campos de los que conocemos,
 *    y que hay que tolerarlos. Los desconocidos se muestran en crudo en vez de
 *    descartarse: un campo nuevo del equipo que el panel se come es un dato
 *    perdido, y perder datos del equipo es lo que no puede pasar.
 *  - Los umbrales que se muestran son los que están **en vigor** en el equipo,
 *    que es la mitad honesta de F-09.
 */
import Panel from "@/components/Panel";
import StatGrid, { type Stat } from "@/components/StatGrid";
import HealthBadge from "@/components/HealthBadge";
import PowerChart from "@/components/PowerChart";
import UptimeGrid from "@/components/UptimeGrid";
import { useResource } from "@/hooks/useResource";
import { data, type DetectionEvent, type Page } from "@/api/client";
import { formatDateTime, timeAgo } from "@/lib/time";

type Doc = Record<string, any>;

/** Campos de `health` que esta versión entiende. El resto se muestra igual. */
const KNOWN_HEALTH = new Set([
  "detector_ok", "audio_ok", "duty_cycle_pct", "clips_dropped",
  "upload_backlog", "degraded_reason",
]);

const bool = (v: unknown) =>
  v == null ? null : v ? "sí" : "no";

export default function SensorStatus({ siteId }: { siteId: string }) {
  const status = useResource<Doc>(() => data.status(siteId), [siteId], { pollMs: 60_000 });
  // Fuente aparte: si el historial de energía falla, el estado sigue visible (R-7.3).
  const powerHistory = useResource<Doc>(() => data.power(siteId), [siteId], { pollMs: 300_000 });
  // Para el historial de actividad: las últimas 72 h de eventos, fuente aparte.
  const recent = useResource<Page<DetectionEvent>>(
    () => data.events(siteId, { since: new Date(Date.now() - 72 * 3_600_000), limit: 500 }),
    [siteId], { pollMs: 300_000 });

  return (
    <>
    <Panel
      title="Estado del sensor"
      resource={status}
      emptyMessage="El equipo no ha publicado su estado. No sabemos si está bien o mal — no es lo mismo que estar bien."
      actions={status.data?.last_seen && (
        <span className="panel-age">último contacto {timeAgo(status.data.last_seen)}</span>
      )}
    >
      {(doc) => {
        const health = (doc.health ?? {}) as Doc;
        const detection = (doc.detection ?? {}) as Doc;
        const thresholds = (detection.thresholds ?? {}) as Doc;
        const audio = (doc.audio ?? {}) as Doc;
        const power = (doc.power ?? {}) as Doc;
        const network = (doc.network ?? {}) as Doc;
        const system = (doc.system ?? {}) as Doc;
        const extraHealth = Object.entries(health).filter(([k]) => !KNOWN_HEALTH.has(k));

        return (
          <>
            <div className="sensor-headline">
              <HealthBadge status={doc} />
              <span className="sensor-device">
                {doc.device ?? "equipo sin identificar"} · v{doc.software_version ?? "?"}
              </span>
            </div>

            {doc.schema_version !== 2 && (
              <div className="banner error" role="alert">
                Versión de esquema desconocida ({String(doc.schema_version)}). Se
                muestra lo que se entiende; puede faltar información.
              </div>
            )}

            <h3 className="section-head">Salud</h3>
            <StatGrid stats={[
              { label: "Detector operativo", value: bool(health.detector_ok),
                absent: "el equipo no publica estado del detector" },
              { label: "Audio con señal", value: bool(health.audio_ok) },
              { label: "Ciclo de trabajo", value: health.duty_cycle_pct, unit: "%", digits: 1,
                warn: (v) => v < 90,
                absent: "aún no hay ventana medida" },
              { label: "Clips descartados", value: health.clips_dropped, warn: (v) => v > 0 },
              { label: "Subidas pendientes", value: health.upload_backlog, warn: (v) => v > 0 },
            ]} />

            {health.degraded_reason && (
              <p className="degraded-reason" role="alert">
                <strong>Motivo del estado degradado:</strong> {health.degraded_reason}
              </p>
            )}

            {/* Campos nuevos del equipo: se muestran, no se descartan. */}
            {extraHealth.length > 0 && (
              <>
                <h3 className="section-head">
                  Otros indicadores de salud
                  <span className="section-note">
                    publicados por el equipo, aún sin presentación propia
                  </span>
                </h3>
                <StatGrid stats={extraHealth.map(([k, v]) => ({
                  label: k, value: typeof v === "boolean" ? bool(v) : (v as Stat["value"]),
                }))} />
              </>
            )}

            <h3 className="section-head">
              Detección
              <span className="section-note">valores en vigor en el equipo</span>
            </h3>
            <StatGrid stats={[
              { label: "Detectores", value: Array.isArray(detection.detectors)
                  ? detection.detectors.join(", ") : detection.detectors },
              { label: "Último RMS", value: detection.last_rms, digits: 4 },
              { label: "Pausa entre avisos", value: detection.cooldown_s, unit: " s" },
              { label: "Puntaje mínimo", value: thresholds.score_min, digits: 2 },
              { label: "RMS mínimo", value: thresholds.rms_min, digits: 3 },
              { label: "Umbral PSD", value: thresholds.psd_threshold_db, unit: " dB" },
              { label: "Banda PSD", value: thresholds.psd_f_min != null && thresholds.psd_f_max != null
                  ? `${thresholds.psd_f_min}–${thresholds.psd_f_max} Hz` : null },
            ]} />

            <h3 className="section-head">Audio</h3>
            <StatGrid stats={[
              { label: "Dispositivo", value: audio.device },
              { label: "Frecuencia de muestreo", value: audio.sample_rate, unit: " Hz" },
              { label: "Canales", value: audio.channels },
            ]} />

            <h3 className="section-head">Energía</h3>
            <StatGrid stats={[
              { label: "Batería", value: power.battery_voltage_v, unit: " V", digits: 2,
                warn: (v) => v < 11.8,
                absent: "el equipo no reporta el controlador solar" },
              { label: "Corriente de batería", value: power.battery_current_a, unit: " A", digits: 2 },
              { label: "Panel", value: power.panel_power_w, unit: " W" },
              { label: "Estado de carga", value: power.charge_state },
              { label: "Consumo del sistema", value: power.system_load_w, unit: " W", digits: 1 },
              { label: "Producción hoy", value: power.yield_today_kwh, unit: " kWh", digits: 2 },
            ]} />

            <h3 className="section-head">Red</h3>
            <StatGrid stats={[
              { label: "Señal", value: network.signal_bars, unit: "/5", warn: (v) => v <= 1,
                absent: "el equipo no reporta módem" },
              { label: "RSSI", value: network.signal_rssi, unit: " dBm" },
              { label: "Tipo de red", value: network.network_type },
            ]} />

            <h3 className="section-head">Sistema</h3>
            <StatGrid stats={[
              { label: "Temperatura CPU", value: system.cpu_temp_c, unit: " °C", digits: 1,
                warn: (v) => v > 75 },
              { label: "Disco usado", value: system.disk_used_pct, unit: "%", digits: 1,
                warn: (v) => v > 85 },
              { label: "Disco libre", value: system.disk_free_gb, unit: " GB", digits: 1 },
              { label: "RAM usada", value: system.ram_used_pct, unit: "%", digits: 1,
                warn: (v) => v > 90 },
              { label: "Encendido desde", value: doc.session_start ? formatDateTime(doc.session_start) : null },
              { label: "Tiempo en marcha", value: doc.uptime_seconds != null
                  ? `${Math.floor(doc.uptime_seconds / 86400)} d ${Math.floor((doc.uptime_seconds % 86400) / 3600)} h`
                  : null },
            ]} />
          </>
        );
      }}
    </Panel>

    <Panel
      title="Historial de actividad del sensor"
      resource={recent}
      emptyMessage="No hay detecciones publicadas para este sitio en las últimas 72 horas."
    >
      {(page) => (
        <UptimeGrid
          events={page.items.map((e) => e.captured_utc)}
          sessionStart={status.data?.session_start as string | undefined}
        />
      )}
    </Panel>

    <Panel
      title="Historial de energía"
      resource={powerHistory}
      emptyMessage="El equipo no ha publicado historial de energía para este sitio."
    >
      {(doc) => <PowerChart doc={doc} />}
    </Panel>
    </>
  );
}