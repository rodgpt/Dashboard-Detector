/**
 * Detecciones: la página del endpoint paginado, no del historial completo.
 *
 * Cierra F-18. La versión anterior descargaba `manifest.json` entero cada 30 s;
 * aquí el navegador recibe una página y nada más.
 *
 * Reglas que esta vista respeta a propósito:
 *  - Las suprimidas se muestran, marcadas, nunca ocultas (R-8.2). Si un filtro
 *    las esconde, el filtro se ve.
 *  - `captured_utc` es la hora del evento, no la de subida (R-8.4).
 *  - `vessel` / `blast` / `unknown` se distinguen por texto y forma, no sólo
 *    por color (R-8.3, R-8.8).
 *  - Todo número puede ser `null`, y `null` no es cero.
 */
import { useMemo, useState } from "react";
import { Bar, Line } from "react-chartjs-2";
import Panel from "@/components/Panel";
import { COLORS, baseOptions, catScale, lineStyle, timeScale, valueScale } from "@/lib/charts";
import { useResource } from "@/hooks/useResource";
import { data, type DetectionEvent, type EventType, type Page } from "@/api/client";
import { formatDateTime, timeAgo } from "@/lib/time";

const PAGE = 50;

const TYPE_LABEL: Record<EventType, string> = {
  vessel: "embarcación", blast: "detonación", unknown: "desconocido",
};
const TYPE_MARK: Record<EventType, string> = { vessel: "▬", blast: "✦", unknown: "?" };

/** null is absence, 0 is a reading. They must not look the same. */
const num = (v: number | null | undefined, digits = 2) =>
  v == null ? <span className="null-value" title="sin dato">—</span> : v.toFixed(digits);

export default function Detections({ siteId }: { siteId: string }) {
  const [days, setDays] = useState(7);
  const [type, setType] = useState<EventType | "">("");
  const [includeSuppressed, setIncludeSuppressed] = useState(true);
  const [minScore, setMinScore] = useState(0);
  const [offset, setOffset] = useState(0);

  const since = new Date(Date.now() - days * 86_400_000);
  const events = useResource<Page<DetectionEvent>>(
    () => data.events(siteId, {
      since, event_type: type || undefined, min_score: minScore || undefined,
      include_suppressed: includeSuppressed, limit: PAGE, offset,
    }),
    [siteId, days, type, includeSuppressed, minScore, offset],
    { pollMs: 60_000 },
  );

  const reset = (fn: () => void) => { fn(); setOffset(0); };

  /* Los dos gráficos resumen la **página cargada**, no el total del periodo.
     Decirlo importa: un histograma que dice "24 alertas" cuando el periodo
     tiene 300 es exactamente la clase de número que se cita fuera de contexto. */
  const items = events.data?.items ?? [];
  const { byDay, byHour } = useMemo(() => {
    const day = new Map<string, number>();
    const hour = Array.from({ length: 24 }, () => 0);
    for (const ev of items) {
      const d = new Date(ev.captured_utc);
      if (isNaN(d.getTime())) continue;      // una fecha ilegible no rompe el gráfico
      day.set(d.toISOString().slice(0, 10), (day.get(d.toISOString().slice(0, 10)) ?? 0) + 1);
      hour[d.getUTCHours()]!++;
    }
    return {
      byDay: [...day.entries()].sort(([a], [b]) => a.localeCompare(b))
        .map(([ts, n]) => ({ x: new Date(ts + "T00:00:00Z").getTime(), y: n })),
      byHour: hour,
    };
  }, [items]);

  return (
    <>
      <div className="filters">
        <label>
          <span>Periodo</span>
          <select value={days} onChange={(e) => reset(() => setDays(Number(e.target.value)))}>
            <option value={1}>último día</option>
            <option value={7}>últimos 7 días</option>
            <option value={30}>últimos 30 días</option>
            <option value={90}>últimos 90 días</option>
          </select>
        </label>
        <label>
          <span>Tipo</span>
          <select value={type} onChange={(e) => reset(() => setType(e.target.value as EventType | ""))}>
            <option value="">todos</option>
            <option value="vessel">embarcación</option>
            <option value="blast">detonación</option>
            <option value="unknown">desconocido</option>
          </select>
        </label>
        {/* Un filtro que esconde eventos tiene que verse (R-8.2). */}
        <label className="filter-check">
          <input type="checkbox" checked={includeSuppressed}
                 onChange={(e) => reset(() => setIncludeSuppressed(e.target.checked))} />
          <span>Incluir suprimidas</span>
        </label>
        <label>
          <span>Puntaje mínimo</span>
          <input type="range" min={0} max={0.95} step={0.05} value={minScore}
                 onChange={(e) => reset(() => setMinScore(Number(e.target.value)))} />
          <span className="slider-value">{minScore.toFixed(2)}</span>
        </label>
        {minScore > 0 && (
          <span className="filter-warning" role="status">
            Ocultando detecciones bajo {minScore.toFixed(2)}: los totales no reflejan todo lo detectado.
          </span>
        )}
        {!includeSuppressed && (
          <span className="filter-warning" role="status">
            Ocultando detecciones suprimidas: los totales no reflejan todo lo detectado.
          </span>
        )}
      </div>

      {items.length > 0 && (
        <div className="chart-row">
          <section className="panel">
            <div className="panel-head"><h2>Línea de tiempo</h2>
              <span className="panel-meta panel-count">de la página cargada</span></div>
            <div className="chart-box short">
              <Line
                data={{ datasets: [{ label: "Detecciones por día", data: byDay,
                        ...lineStyle(COLORS.brand, { fill: true,
                          backgroundColor: "rgba(100,177,197,.18)" }) }] }}
                options={baseOptions({ x: timeScale, y: valueScale("eventos") })}
              />
            </div>
          </section>

          <section className="panel">
            <div className="panel-head"><h2>Alertas por hora del día</h2>
              <span className="panel-meta panel-count">UTC</span></div>
            <div className="chart-box short">
              <Bar
                data={{
                  labels: Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, "0")}`),
                  datasets: [{ label: "Detecciones", data: byHour,
                               backgroundColor: COLORS.brand, borderRadius: 3 }],
                }}
                options={baseOptions({ x: catScale, y: valueScale("eventos") })}
              />
            </div>
          </section>
        </div>
      )}

      <Panel
        title="Detecciones"
        resource={events}
        emptyMessage="No hay eventos publicados para este sitio."
        actions={events.data && (
          <span className="panel-count">
            {events.data.total} evento{events.data.total === 1 ? "" : "s"}
            {/*
              Frescura del índice, no coste de la consulta. Una página servida
              desde un índice que dejó de actualizarse hace tres días, sin manera
              de saberlo, es la misma clase de mentira que un equipo que se
              reporta sano estando sordo. Por eso `null` se dice en voz alta en
              vez de omitirse.
            */}
            {events.data.index_updated_utc === null ? (
              <span className="panel-scan warn" title="El índice no tiene ningún evento de este sitio">
                · índice vacío
              </span>
            ) : (
              <span className="panel-scan"
                    title={`Última indexación: ${formatDateTime(events.data.index_updated_utc)}`}>
                · índice actualizado {timeAgo(events.data.index_updated_utc)}
              </span>
            )}
          </span>
        )}
      >
        {(page) => (
          <>
            {page.items.length === 0 ? (
              <p className="loading">
                Sin detecciones en este periodo. Eso puede ser silencio real o un
                equipo que no está escuchando — revisa el estado del sensor.
              </p>
            ) : (
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th scope="col">Hora de captura</th>
                      <th scope="col">Tipo</th>
                      <th scope="col">Detector</th>
                      <th scope="col">Puntaje</th>
                      <th scope="col">Nivel</th>
                      <th scope="col">Pico (dB)</th>
                      <th scope="col">Audio</th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.items.map((ev) => (
                      <tr key={ev.event_id} className={ev.suppressed ? "row-suppressed" : undefined}>
                        <td>
                          {formatDateTime(ev.captured_utc)}
                          {ev._unknown_schema && (
                            <span className="chip warn" title="Versión de esquema desconocida">
                              esquema desconocido
                            </span>
                          )}
                        </td>
                        <td>
                          <span className={`type-badge ${ev.event_type}`}>
                            <span aria-hidden="true">{TYPE_MARK[ev.event_type] ?? "?"}</span>
                            {TYPE_LABEL[ev.event_type] ?? ev.event_type}
                          </span>
                          {ev.suppressed && (
                            <span className="chip suppressed" title="Detección real; el aviso se retuvo por la pausa entre avisos">
                              suprimida
                            </span>
                          )}
                        </td>
                        <td>{ev.detector || "—"}</td>
                        <td>{num(ev.score)}</td>
                        <td>{num(ev.audio_level, 3)}</td>
                        <td>{num(ev.peak_db, 1)}</td>
                        <td><ClipCell siteId={siteId} ev={ev} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="pager">
              <button type="button" className="btn btn-ghost btn-sm"
                      disabled={offset === 0}
                      onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                Anteriores
              </button>
              <span className="pager-pos">
                {page.total === 0 ? "0" : `${offset + 1}–${Math.min(offset + PAGE, page.total)}`} de {page.total}
              </span>
              <button type="button" className="btn btn-ghost btn-sm"
                      disabled={!page.has_more}
                      onClick={() => setOffset(offset + PAGE)}>
                Siguientes
              </button>
            </div>
          </>
        )}
      </Panel>
    </>
  );
}

/**
 * Tres estados distintos, y confundirlos es un defecto conocido (F-13):
 * subido, nunca subido (falló la subida), y suprimido (el audio no se guardó
 * nunca, a propósito). Ninguno se dibuja como "reproducir" salvo el primero.
 */
function ClipCell({ siteId, ev }: { siteId: string; ev: DetectionEvent }) {
  if (ev.suppressed) {
    return <span className="clip-none" title="Suprimida: el audio no se conserva">sin audio</span>;
  }
  if (!ev.clip?.uploaded || !ev.clip?.path) {
    return <span className="clip-failed" title="La subida del audio falló">subida fallida</span>;
  }
  return (
    <div className="clip-cell">
      <audio controls preload="none" className="clip-player"
             src={data.clipUrl(siteId, ev.clip.path)}>
        Tu navegador no reproduce audio.
      </audio>
      <a className="clip-link" href={`?play=${encodeURIComponent(ev.clip.path)}`}
         title="Abrir con espectrograma, y enlace compartible">espectrograma</a>
    </div>
  );
}
