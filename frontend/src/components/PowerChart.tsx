/**
 * Historial de energía.
 *
 * **Los huecos son datos** (R-8.6). Un bucket ausente significa que el equipo no
 * reportó — un corte, un reinicio, una caída de red — y esa es exactamente la
 * información que buscamos. Interpolarlo, rellenarlo o densificarlo lo borra.
 *
 * Dos ausencias distintas, dibujadas distinto:
 *   bucket ausente        la línea se corta. Hubo un silencio.
 *   bucket con `null`     el equipo escribió a tiempo y el sensor no dio valor.
 *
 * Chart.js une puntos salteándose los `null` sólo si `spanGaps` es falso, que es
 * el valor por defecto y que aquí se fija explícitamente para que nadie lo
 * "arregle" más adelante.
 */
import { Line } from "react-chartjs-2";
import {
  CategoryScale, Chart as ChartJS, Filler, Legend, LinearScale, LineElement,
  PointElement, TimeScale, Tooltip,
} from "chart.js";
import "chartjs-adapter-date-fns";
import { es } from "date-fns/locale";

ChartJS.register(TimeScale, LinearScale, CategoryScale, PointElement, LineElement,
                 Tooltip, Legend, Filler);

interface Bucket { ts: string; sys_w?: number | null; panel_w?: number | null; bat_v?: number | null; }

const CSS = getComputedStyle(document.documentElement);
const token = (name: string, fallback: string) =>
  CSS.getPropertyValue(name).trim() || fallback;

export default function PowerChart({ doc }: { doc: Record<string, any> }) {
  const history: Bucket[] = Array.isArray(doc.history) ? doc.history : [];
  const bucketS: number = typeof doc.bucket_s === "number" ? doc.bucket_s : 1800;

  if (history.length === 0) {
    return <p className="loading">El equipo no ha publicado historial de energía.</p>;
  }

  // Un hueco real: dos buckets separados por más de un intervalo. Se inserta un
  // punto nulo para que la línea se corte en vez de saltar por encima del
  // silencio y aparentar continuidad.
  const points: { x: number; sys: number | null; panel: number | null; bat: number | null }[] = [];
  let gaps = 0;
  history.forEach((b, i) => {
    const t = new Date(b.ts).getTime();
    if (i > 0) {
      const prev = new Date(history[i - 1]!.ts).getTime();
      if (t - prev > bucketS * 1000 * 1.5) {
        gaps++;
        points.push({ x: prev + bucketS * 1000, sys: null, panel: null, bat: null });
      }
    }
    points.push({
      x: t,
      sys: b.sys_w ?? null, panel: b.panel_w ?? null, bat: b.bat_v ?? null,
    });
  });

  const nulls = history.filter((b) => b.sys_w == null && b.panel_w == null && b.bat_v == null).length;

  const brand = token("--brand", "#64b1c5");
  const dim = token("--dim", "#9fbcc8");
  const grid = "rgba(120,175,195,.14)";

  const datasets = [
    { label: "Consumo (W)", key: "sys" as const, color: brand, axis: "w" },
    { label: "Panel (W)", key: "panel" as const, color: "#f59e0b", axis: "w" },
    { label: "Batería (V)", key: "bat" as const, color: "#86efac", axis: "v" },
  ];

  return (
    <>
      <div className="chart-box">
        <Line
          data={{
            datasets: datasets.map((d) => ({
              label: d.label,
              data: points.map((p) => ({ x: p.x, y: p[d.key] })),
              borderColor: d.color,
              backgroundColor: d.color,
              borderWidth: 2,
              pointRadius: 0,
              pointHoverRadius: 4,
              yAxisID: d.axis,
              tension: 0.25,
              // No unir por encima de un hueco. Ver la nota de arriba: esto es
              // el requisito, no una preferencia estética.
              spanGaps: false,
            })),
          }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            scales: {
              x: {
                type: "time",
                adapters: { date: { locale: es } },
                time: { tooltipFormat: "PPpp" },
                grid: { color: grid },
                ticks: { color: dim, maxRotation: 0, autoSkipPadding: 20 },
              },
              w: {
                type: "linear", position: "left",
                title: { display: true, text: "W", color: dim },
                grid: { color: grid }, ticks: { color: dim },
              },
              v: {
                type: "linear", position: "right",
                title: { display: true, text: "V", color: dim },
                grid: { drawOnChartArea: false }, ticks: { color: dim },
              },
            },
            plugins: {
              legend: { labels: { color: dim, usePointStyle: true, boxHeight: 7 } },
              tooltip: {
                callbacks: {
                  label: (c) => c.parsed.y == null
                    ? `${c.dataset.label}: sin dato`
                    : `${c.dataset.label}: ${c.parsed.y}`,
                },
              },
            },
          }}
        />
      </div>

      <p className="chart-note">
        {history.length} lecturas cada {Math.round(bucketS / 60)} min sobre{" "}
        {doc.window_h ?? "?"} h.
        {gaps > 0 && (
          <>
            {" "}
            <strong className="gap-note">
              {gaps} interrupción{gaps === 1 ? "" : "es"} en el reporte
            </strong>
            {" "}— la línea se corta ahí a propósito: el equipo no reportó y eso
            no se rellena.
          </>
        )}
        {nulls > 0 && (
          <>
            {" "}
            <strong className="gap-note">{nulls} lecturas sin valor</strong> — el
            equipo reportó a tiempo pero el sensor no entregó dato. No es cero.
          </>
        )}
      </p>
    </>
  );
}
