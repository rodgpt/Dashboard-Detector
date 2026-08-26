/**
 * Análisis: las cuatro vistas que cruzan fuentes.
 *
 * Es la única pestaña donde un gráfico necesita **dos** fuentes a la vez, así
 * que la regla de "cada fuente falla sola" necesita una respuesta explícita:
 * cada gráfico dice qué le falta y por qué no se puede dibujar, en vez de salir
 * vacío. Un gráfico de correlación vacío se lee como "no hay correlación", que
 * es una afirmación, no una ausencia.
 *
 * Nada aquí interpreta los cruces. Que los clics suban con la energía del mar
 * puede ser biología o puede ser ruido de fondo; eso es ciencia del cliente
 * (D-015). El panel dibuja, no concluye.
 */
import { useMemo } from "react";
import { Bar, Line, Scatter } from "react-chartjs-2";

import { useResource } from "@/hooks/useResource";
import { data, type DetectionEvent, type Page } from "@/api/client";
import {
  COLORS, baseOptions, catScale, lineStyle, scatterOptions, timeScale, valueScale,
} from "@/lib/charts";
import { seaEnergy } from "@/lib/sea";

type Doc = Record<string, any>;
const WINDOW_DAYS = 30;

/** Panel de un gráfico cruzado: dice qué fuente falta en vez de salir vacío. */
function CrossPanel({ title, note, missing, children }: {
  title: string; note?: string; missing: string[]; children: React.ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{title}</h2>
        {note && <span className="panel-meta panel-count">{note}</span>}
      </div>
      {missing.length > 0 ? (
        <div className="banner error" role="alert">
          No se puede dibujar: falta {missing.join(" y ")}. Un gráfico de
          correlación vacío se leería como “no hay relación”, y eso sería una
          conclusión inventada.
        </div>
      ) : children}
    </section>
  );
}

export default function Analysis({ siteId }: { siteId: string }) {
  const since = useMemo(() => new Date(Date.now() - WINDOW_DAYS * 86_400_000), []);

  // Tres fuentes independientes: si una cae, sólo caen los gráficos que la usan.
  const events = useResource<Page<DetectionEvent>>(
    () => data.events(siteId, { since, limit: 500 }), [siteId], { pollMs: 300_000 });
  const ocean = useResource<Doc>(() => data.ocean(siteId), [siteId], { pollMs: 900_000 });
  const acoustic = useResource<Doc>(() => data.acoustic(siteId), [siteId], { pollMs: 300_000 });

  const evItems = events.data?.items ?? [];
  const hourly: Doc[] = Array.isArray(ocean.data?.hourly) ? ocean.data!.hourly : [];
  const timeline: Doc[] = Array.isArray(acoustic.data?.timeline) ? acoustic.data!.timeline : [];

  /** Índice horario del mar, para pegarle a cada evento su estado de mar. */
  const seaByHour = useMemo(() => {
    const m = new Map<string, Doc>();
    for (const h of hourly) {
      const d = new Date(h.ts);
      if (!isNaN(d.getTime())) m.set(d.toISOString().slice(0, 13), h);
    }
    return m;
  }, [hourly]);

  const byDay = useMemo(() => {
    const m = new Map<string, number>();
    for (const ev of evItems) {
      const d = new Date(ev.captured_utc);
      if (isNaN(d.getTime())) continue;
      const k = d.toISOString().slice(0, 10);
      m.set(k, (m.get(k) ?? 0) + 1);
    }
    return [...m.entries()].sort(([a], [b]) => a.localeCompare(b))
      .map(([ts, n]) => ({ x: new Date(ts + "T00:00:00Z").getTime(), y: n }));
  }, [evItems]);

  /** Eventos agrupados por energía del mar en el momento de la captura. */
  const bySea = useMemo(() => {
    const buckets = [
      { label: "0–10", min: 0, max: 10 },
      { label: "10–25", min: 10, max: 25 },
      { label: "25–50", min: 25, max: 50 },
      { label: "50+", min: 50, max: Infinity },
    ];
    const counts = buckets.map(() => 0);
    let unknown = 0;
    for (const ev of evItems) {
      const d = new Date(ev.captured_utc);
      const sea = isNaN(d.getTime()) ? null : seaByHour.get(d.toISOString().slice(0, 13));
      const e = sea ? seaEnergy(sea.swell_m, sea.swell_period_s) : null;
      if (e == null) { unknown++; continue; }
      const i = buckets.findIndex((b) => e >= b.min && e < b.max);
      if (i >= 0) counts[i]!++;
    }
    return { labels: buckets.map((b) => b.label), counts, unknown };
  }, [evItems, seaByHour]);

  /** NDSI contra tasa de clics, punto por ventana. */
  const ndsiClick = useMemo(() =>
    timeline
      .filter((r) => r.ndsi_med != null && r.click_med != null)
      .map((r) => ({ x: r.ndsi_med as number, y: r.click_med as number })),
    [timeline]);

  /** Clics contra energía del mar, pegados por hora. */
  const clickEnergy = useMemo(() => {
    const out: { x: number; y: number }[] = [];
    for (const r of timeline) {
      if (r.click_med == null) continue;
      const d = new Date(r.ts as string);
      if (isNaN(d.getTime())) continue;
      const sea = seaByHour.get(d.toISOString().slice(0, 13));
      const e = sea ? seaEnergy(sea.swell_m, sea.swell_period_s) : null;
      if (e == null) continue;
      out.push({ x: e, y: r.click_med as number });
    }
    return out;
  }, [timeline, seaByHour]);

  const missEvents = events.failed ? ["las detecciones"] : [];
  const missOcean = ocean.failed ? ["las condiciones del mar"] : [];
  const missAcoustic = acoustic.failed ? ["los indicadores acústicos"] : [];

  return (
    <>
      <p className="panel-note">
        Ventana de {WINDOW_DAYS} días, hasta 500 detecciones. Los cruces se hacen
        por hora: cada evento toma el estado de mar de la hora en que fue
        capturado. Las horas sin dato de mar se cuentan aparte, nunca como cero.
      </p>

      <CrossPanel title="Línea de tiempo integrada"
                  note="detecciones por día"
                  missing={missEvents}>
        <div className="chart-box">
          <Line
            data={{ datasets: [{ label: "Detecciones", data: byDay,
                    ...lineStyle(COLORS.brand, { fill: true,
                      backgroundColor: "rgba(100,177,197,.18)" }) }] }}
            options={baseOptions({ x: timeScale, y: valueScale("eventos") })}
          />
        </div>
      </CrossPanel>

      <CrossPanel title="Alertas por estado de mar"
                  note="energía del mar (swell²·período)"
                  missing={[...missEvents, ...missOcean]}>
        <div className="chart-box short">
          <Bar
            data={{
              labels: bySea.labels,
              datasets: [{ label: "Detecciones", data: bySea.counts,
                           backgroundColor: COLORS.brand, borderRadius: 3 }],
            }}
            options={baseOptions({ x: catScale, y: valueScale("eventos") })}
          />
        </div>
        {bySea.unknown > 0 && (
          <p className="chart-note">
            <strong className="gap-note">{bySea.unknown} detecciones sin estado de mar
            conocido</strong> para su hora. Quedan fuera del gráfico en vez de caer
            en un tramo que no les corresponde.
          </p>
        )}
      </CrossPanel>

      <CrossPanel title="NDSI vs tasa de clics"
                  note={`${ndsiClick.length} ventanas`}
                  missing={missAcoustic}>
        <div className="chart-box">
          <Scatter
            data={{ datasets: [{ label: "Ventana acústica", data: ndsiClick,
                    backgroundColor: COLORS.brand, pointRadius: 3 }] }}
            options={scatterOptions("NDSI", "clics (Hz)")}
          />
        </div>
      </CrossPanel>

      <CrossPanel title="Click de camarón vs energía del mar"
                  note={`${clickEnergy.length} ventanas cruzadas`}
                  missing={[...missAcoustic, ...missOcean]}>
        <div className="chart-box">
          <Scatter
            data={{ datasets: [{ label: "Ventana acústica", data: clickEnergy,
                    backgroundColor: COLORS.amber, pointRadius: 3 }] }}
            options={scatterOptions("energía del mar", "clics (Hz)")}
          />
        </div>
        <p className="chart-note">
          Cruce por hora. Que haya o no relación aquí es una pregunta científica,
          no una conclusión de este panel.
        </p>
      </CrossPanel>
    </>
  );
}
