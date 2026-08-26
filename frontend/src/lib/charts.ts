/**
 * Configuración compartida de Chart.js.
 *
 * Ocho gráficos repartidos en cuatro vistas. Sin esto, cada uno reinventa ejes,
 * colores y tooltips, y la primera vez que alguien cambie la paleta quedarán
 * siete iguales y uno distinto.
 *
 * Una regla se repite en todos y es requisito, no estética: **`spanGaps: false`**.
 * Un hueco en los datos se dibuja como hueco (R-8.6).
 */
import {
  BarElement, CategoryScale, Chart as ChartJS, Filler, Legend, LinearScale,
  LineElement, PointElement, TimeScale, Tooltip,
} from "chart.js";
import "chartjs-adapter-date-fns";
import { es } from "date-fns/locale";
import type { ChartOptions } from "chart.js";

ChartJS.register(TimeScale, LinearScale, CategoryScale, PointElement, LineElement,
                 BarElement, Tooltip, Legend, Filler);

const css = getComputedStyle(document.documentElement);
export const token = (name: string, fallback: string) =>
  css.getPropertyValue(name).trim() || fallback;

export const COLORS = {
  brand: token("--brand", "#64b1c5"),
  amber: "#f59e0b",
  green: "#86efac",
  red: "#e03e52",
  violet: "#a78bfa",
  dim: token("--dim", "#9fbcc8"),
  grid: "rgba(120,175,195,.14)",
};

/** "sin dato" en vez de omitir el punto: la ausencia se lee, no se adivina. */
const nullAwareTooltip = {
  callbacks: {
    label: (c: any) => c.parsed?.y == null
      ? `${c.dataset.label}: sin dato`
      : `${c.dataset.label}: ${c.parsed.y}`,
  },
};

export const legend = {
  labels: { color: COLORS.dim, usePointStyle: true, boxHeight: 7 },
};

/** Eje temporal en español, con la rejilla del tema. */
export const timeScale = {
  type: "time" as const,
  adapters: { date: { locale: es } },
  grid: { color: COLORS.grid },
  ticks: { color: COLORS.dim, maxRotation: 0, autoSkipPadding: 20 },
};

export const catScale = {
  grid: { color: COLORS.grid },
  ticks: { color: COLORS.dim, autoSkipPadding: 14 },
};

export function valueScale(text: string, position: "left" | "right" = "left") {
  return {
    type: "linear" as const,
    position,
    title: { display: true, text, color: COLORS.dim },
    grid: position === "left" ? { color: COLORS.grid } : { drawOnChartArea: false },
    ticks: { color: COLORS.dim },
  };
}

/** Base para líneas y barras sobre eje temporal o categórico. */
export function baseOptions(scales: Record<string, unknown>): ChartOptions<any> {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    scales,
    plugins: { legend, tooltip: nullAwareTooltip },
  };
}

/** Dispersión: `index` no sirve, cada punto es su propia observación. */
export function scatterOptions(xTitle: string, yTitle: string): ChartOptions<any> {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "nearest", intersect: true },
    scales: { x: valueScale(xTitle, "left"), y: valueScale(yTitle, "left") },
    plugins: {
      legend,
      tooltip: {
        callbacks: {
          label: (c: any) => `${c.dataset.label}: (${c.parsed.x}, ${c.parsed.y})`,
        },
      },
    },
  };
}

/** Serie temporal a partir de filas con `ts`. Null preservado, huecos incluidos. */
export function series<T extends { ts: string }>(rows: T[], key: keyof T) {
  return rows.map((r) => ({
    x: new Date(r.ts).getTime(),
    y: (r[key] as number | null | undefined) ?? null,
  }));
}

export const lineStyle = (color: string, extra: Record<string, unknown> = {}) => ({
  borderColor: color,
  backgroundColor: color,
  borderWidth: 2,
  pointRadius: 0,
  pointHoverRadius: 4,
  tension: 0.25,
  spanGaps: false,      // requisito, no preferencia
  ...extra,
});
