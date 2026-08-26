/**
 * Monitoreo acústico: NDSI y tasa de clics, con su dispersión.
 *
 * La banda entre Q1 y Q3 se dibuja porque una mediana sola miente sobre lo
 * ruidoso que fue el día. Los huecos del timeline se respetan igual que en el
 * gráfico de energía: `spanGaps: false`.
 *
 * Nada aquí decide qué es un buen NDSI. Eso es ciencia de detección y no es
 * nuestra (D-015); el panel muestra el número y su dispersión, sin juzgarlo.
 */
import { Line } from "react-chartjs-2";

import Panel from "@/components/Panel";
import { COLORS, baseOptions, catScale, lineStyle, timeScale, valueScale } from "@/lib/charts";
import StatGrid from "@/components/StatGrid";
import { useResource } from "@/hooks/useResource";
import { data } from "@/api/client";

type Doc = Record<string, any>;

interface Row { ts: string; [k: string]: unknown }

/** Mediana con banda intercuartil. `spanGaps:false` en las tres series. */
function Spread({ rows, med, q1, q3, label, color, unit }: {
  rows: Row[]; med: string; q1: string; q3: string;
  label: string; color: string; unit: string;
}) {
  const pt = (k: string) => rows.map((r) => ({ x: new Date(r.ts).getTime(), y: (r[k] as number) ?? null }));

  return (
    <div className="chart-box">
      <Line
        data={{
          datasets: [
            { label: `${label} Q3`, data: pt(q3), borderColor: "transparent",
              backgroundColor: color.replace("rgb", "rgba").replace(")", ",.16)"),
              pointRadius: 0, fill: "+1", spanGaps: false, tension: .25 },
            { label: `${label} Q1`, data: pt(q1), borderColor: "transparent",
              pointRadius: 0, fill: false, spanGaps: false, tension: .25 },
            { label: `${label} mediana`, data: pt(med), borderColor: color,
              borderWidth: 2, pointRadius: 0, pointHoverRadius: 4,
              spanGaps: false, tension: .25 },
          ],
        }}
        options={{
          ...baseOptions({ x: timeScale, y: valueScale(unit) }),
          plugins: {
            ...baseOptions({}).plugins,
            legend: { labels: { color: COLORS.dim, usePointStyle: true, boxHeight: 7,
                                filter: (i: any) => !i.text?.endsWith("Q1") } },
          },
        }}
      />
    </div>
  );
}

export default function Acoustic({ siteId }: { siteId: string }) {
  const acoustic = useResource<Doc>(() => data.acoustic(siteId), [siteId], { pollMs: 300_000 });

  return (
    <Panel
      title="Monitoreo acústico"
      resource={acoustic}
      emptyMessage="No hay indicadores acústicos publicados para este sitio. El agregador que los produce todavía no existe en ninguno de los dos repositorios — ver CLIENT-DEPENDENCIES."
    >
      {(doc) => {
        const latest = (doc.latest ?? {}) as Doc;
        const timeline: Row[] = Array.isArray(doc.timeline) ? doc.timeline : [];
        const diel: Row[] = Array.isArray(doc.diel) ? doc.diel : [];

        return (
          <>
            <StatGrid stats={[
              { label: "NDSI actual", value: latest.ndsi, digits: 3 },
              { label: "Tasa de clics", value: latest.click_rate_hz, unit: " Hz", digits: 2 },
              { label: "Ventanas en la serie", value: timeline.length || null },
            ]} />

            {timeline.length > 0 && (
              <>
                <h3 className="section-head">
                  NDSI
                  <span className="section-note">mediana y rango intercuartil</span>
                </h3>
                <Spread rows={timeline} med="ndsi_med" q1="ndsi_q1" q3="ndsi_q3"
                        label="NDSI" color="rgb(100,177,197)" unit="NDSI" />

                <h3 className="section-head">
                  Tasa de clics
                  <span className="section-note">mediana y rango intercuartil</span>
                </h3>
                <Spread rows={timeline} med="click_med" q1="click_q1" q3="click_q3"
                        label="Clics" color="rgb(245,158,11)" unit="Hz" />
              </>
            )}

            {diel.length > 0 && (
              <>
                {/* Dos gráficos, no uno con doble eje. El original los separa y
                    tiene razón: superponer NDSI (0..1) con clics (decenas de Hz)
                    en un mismo panel invita a leer una correlación que el eje
                    doble fabricó. */}
                <h3 className="section-head">
                  Ciclo diel — NDSI
                  <span className="section-note">mediana por hora del día, UTC</span>
                </h3>
                <div className="chart-box short">
                  <Line
                    data={{
                      labels: diel.map((d) => `${String(d.hour).padStart(2, "0")}`),
                      datasets: [{ label: "NDSI", data: diel.map((d) => (d.ndsi_med as number) ?? null),
                                   ...lineStyle(COLORS.brand, { tension: .3 }) }],
                    }}
                    options={baseOptions({ x: catScale, y: valueScale("NDSI") })}
                  />
                </div>

                <h3 className="section-head">
                  Ciclo diel — tasa de clics
                  <span className="section-note">mediana por hora del día, UTC</span>
                </h3>
                <div className="chart-box short">
                  <Line
                    data={{
                      labels: diel.map((d) => `${String(d.hour).padStart(2, "0")}`),
                      datasets: [{ label: "Clics", data: diel.map((d) => (d.click_med as number) ?? null),
                                   ...lineStyle(COLORS.amber, { tension: .3 }) }],
                    }}
                    options={baseOptions({ x: catScale, y: valueScale("Hz") })}
                  />
                </div>

                <p className="chart-note">
                  La hora es UTC. Si el sitio necesita hora local, es una decisión
                  pendiente del contrato, no un ajuste de este panel.
                </p>
              </>
            )}
          </>
        );
      }}
    </Panel>
  );
}
