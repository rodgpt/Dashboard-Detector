/**
 * Condiciones del mar.
 *
 * Este blob no lo produce el equipo — es un pronóstico de una fuente externa
 * (el contrato lo marca como "non-device producer"). Dos consecuencias que el
 * panel hace visibles en vez de esconder:
 *
 *  1. Los datos pasada la hora actual son **pronóstico**, no observación. Se
 *     marcan como tal; presentarlos igual que lo medido sería inventar certeza.
 *  2. Que falte no dice nada sobre la salud del equipo. Un 404 aquí no es un
 *     sensor caído, y el mensaje lo aclara.
 *
 * `thresholds` viene del blob: son las condiciones que le importan a quien va a
 * ir al sitio. No las decidimos nosotros, sólo las señalamos.
 */
import { useState } from "react";
import { Line } from "react-chartjs-2";

import Panel from "@/components/Panel";
import DiveWindowEditor from "@/components/DiveWindow";
import { COLORS, baseOptions, lineStyle, series, timeScale, valueScale } from "@/lib/charts";
import { isDiveable, loadDiveWindow, seaEnergy, type DiveWindow } from "@/lib/sea";
import StatGrid from "@/components/StatGrid";
import { useResource } from "@/hooks/useResource";
import { data } from "@/api/client";
import { formatDateTime } from "@/lib/time";

type Doc = Record<string, any>;
interface Hour {
  ts: string;
  swell_m?: number | null; swell_period_s?: number | null; swell_dir?: string | null;
  wave_m?: number | null;
  wind_kmph?: number | null; gust_kmph?: number | null;
  wind_deg?: number | null; wind_dir?: string | null;
  cloud_pct?: number | null; water_temp_c?: number | null;
  weather_desc?: string | null;
  /** Publicado por el productor. Autoritativo sobre cualquier cálculo local. */
  is_forecast?: boolean;
}

export default function Ocean({ siteId }: { siteId: string }) {
  const ocean = useResource<Doc>(() => data.ocean(siteId), [siteId], { pollMs: 900_000 });
  const [dive, setDive] = useState<DiveWindow>(() => loadDiveWindow());

  return (
    <>
    <Panel
      title="Condiciones del mar"
      resource={ocean}
      emptyMessage="No hay pronóstico publicado para este sitio. Esto no dice nada sobre el estado del equipo — es una fuente externa."
    >
      {(doc) => {
        const current = (doc.current ?? {}) as Doc;
        const th = (doc.thresholds ?? {}) as Doc;
        const hourly: Hour[] = Array.isArray(doc.hourly) ? doc.hourly : [];
        const now = Date.now();

        // La frontera entre lo observado y lo pronosticado la publica el
        // productor en `is_forecast`, punto por punto. Se usa esa, no la hora
        // del reloj: deducirla comparando contra `now` discrepa del productor
        // en la hora del límite y con cualquier reloj desajustado, y una
        // discrepancia así no se ve — sólo se dibuja mal.
        //
        // Si el campo falta (productor viejo), se cae al reloj y se dice.
        const hasFlag = hourly.some((h) => typeof h.is_forecast === "boolean");
        const isForecast = (h: Hour) =>
          hasFlag ? h.is_forecast === true : new Date(h.ts).getTime() > now;
        const observed = hourly.filter((h) => !isForecast(h));
        const forecast = hourly.filter(isForecast);

        const diveable = hourly.filter((h) => isDiveable(h, dive) === true).length;
        const unknownDive = hourly.filter((h) => isDiveable(h, dive) === null).length;

        return (
          <>
            <StatGrid stats={[
              { label: "Oleaje", value: current.swell_m, unit: " m", digits: 2,
                warn: (v) => th.swell_max_m != null && v > th.swell_max_m },
              { label: "Periodo", value: current.swell_period_s, unit: " s", digits: 1,
                warn: (v) => th.period_min_s != null && v < th.period_min_s },
              { label: "Dirección del oleaje", value: current.swell_dir },
              { label: "Viento", value: current.wind_kmph, unit: " km/h", digits: 1,
                warn: (v) => th.wind_max_kmph != null && v > th.wind_max_kmph },
              { label: "Dirección del viento", value: current.wind_deg, unit: "°" },
              { label: "Altura de ola", value: current.wave_m, unit: " m", digits: 2 },
              { label: "Ráfaga", value: current.gust_kmph, unit: " km/h", digits: 1,
                warn: (v) => th.wind_max_kmph != null && v > th.wind_max_kmph },
              { label: "Nubosidad", value: current.cloud_pct, unit: "%" },
              { label: "Temperatura del agua", value: current.water_temp_c, unit: " °C", digits: 1 },
              { label: "Cielo", value: current.weather_desc },
              { label: "Medición", value: current.ts ? formatDateTime(current.ts) : null },
            ]} />

            {(th.swell_max_m != null || th.wind_max_kmph != null) && (
              <p className="panel-note">
                Umbrales de referencia del sitio: oleaje ≤ {th.swell_max_m ?? "—"} m,
                periodo ≥ {th.period_min_s ?? "—"} s, viento ≤ {th.wind_max_kmph ?? "—"} km/h
                {Array.isArray(th.wind_dirs) && th.wind_dirs.length > 0
                  && `, viento desde ${th.wind_dirs.join("/")}`}.
                Vienen del pronóstico, no los define el panel.
              </p>
            )}

            {hourly.length > 0 && (
              <>
                <h3 className="section-head">
                  Próximos días
                  <span className="section-note">
                    la línea continua es lo ya transcurrido; la punteada es pronóstico
                  </span>
                </h3>
                <div className="chart-box">
                  <Line
                    data={{
                      datasets: [
                        { label: "Swell (m)", data: series(observed, "swell_m"),
                          ...lineStyle(COLORS.brand), yAxisID: "m" },
                        { label: "Swell (pronóstico)", data: series(forecast, "swell_m"),
                          ...lineStyle(COLORS.brand, { borderDash: [5, 4] }), yAxisID: "m" },
                        { label: "Altura de ola (m)", data: series(observed, "wave_m"),
                          ...lineStyle(COLORS.violet), yAxisID: "m" },
                        { label: "Altura de ola (pronóstico)", data: series(forecast, "wave_m"),
                          ...lineStyle(COLORS.violet, { borderDash: [5, 4] }), yAxisID: "m" },
                      ],
                    }}
                    options={baseOptions({ x: timeScale, m: valueScale("m") })}
                  />
                </div>

                <h3 className="section-head">
                  Viento
                  <span className="section-note">velocidad y ráfaga</span>
                </h3>
                <div className="chart-box">
                  <Line
                    data={{
                      datasets: [
                        { label: "Viento (km/h)", data: series(observed, "wind_kmph"),
                          ...lineStyle(COLORS.amber), yAxisID: "k" },
                        { label: "Viento (pronóstico)", data: series(forecast, "wind_kmph"),
                          ...lineStyle(COLORS.amber, { borderDash: [5, 4] }), yAxisID: "k" },
                        { label: "Ráfaga (km/h)", data: series(observed, "gust_kmph"),
                          ...lineStyle(COLORS.red), yAxisID: "k" },
                        { label: "Ráfaga (pronóstico)", data: series(forecast, "gust_kmph"),
                          ...lineStyle(COLORS.red, { borderDash: [5, 4] }), yAxisID: "k" },
                      ],
                    }}
                    options={baseOptions({ x: timeScale, k: valueScale("km/h") })}
                  />
                </div>

                <h3 className="section-head">Nubosidad</h3>
                <div className="chart-box short">
                  <Line
                    data={{
                      datasets: [
                        { label: "Nubosidad (%)", data: series(observed, "cloud_pct"),
                          ...lineStyle(COLORS.dim, { fill: true,
                            backgroundColor: "rgba(159,188,200,.18)" }), yAxisID: "p" },
                        { label: "Nubosidad (pronóstico)", data: series(forecast, "cloud_pct"),
                          ...lineStyle(COLORS.dim, { borderDash: [5, 4] }), yAxisID: "p" },
                      ],
                    }}
                    options={baseOptions({ x: timeScale, p: valueScale("%") })}
                  />
                </div>

                <p className="chart-note">
                  {observed.length} horas observadas, {forecast.length} de pronóstico.
                  Lo pronosticado puede cambiar; no es una medición.
                  {!hasFlag && (
                    <> El productor no publica <code>is_forecast</code> en estos datos,
                    así que la frontera está deducida de la hora — puede no coincidir
                    con lo que el productor considera medido.</>
                  )}
                </p>

                <p className="chart-note">
                  Con la ventana de buceo actual:{" "}
                  <strong className="dive-count">{diveable}</strong> de {hourly.length} horas
                  buceables
                  {unknownDive > 0 && (
                    <>, <strong className="gap-note">{unknownDive} sin datos suficientes
                    para decidir</strong> — que no es lo mismo que no buceables</>
                  )}. Energía del mar ahora:{" "}
                  {seaEnergy(current.swell_m, current.swell_period_s) ?? "sin dato"} (swell²·período).
                </p>
              </>
            )}
          </>
        );
      }}
    </Panel>

    <DiveWindowEditor value={dive} onChange={setDive} />
    </>
  );
}