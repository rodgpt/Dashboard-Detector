/**
 * Fecha y hora **del sitio**, y "hace cuánto" para la frescura de datos.
 *
 * Todo lo que llega del equipo es UTC con desfase explícito. Lo que se muestra
 * es la hora del sitio, no la del navegador: un revisor en otro país tiene que
 * leer la misma hora que quien está en la costa, y el contrato dice que las
 * horas del ciclo diel son locales. Las dos unidades están en Chile, así que la
 * zona es una constante por ahora; si un sitio sale del país, pasa a venir del
 * registro de sitios (review FE-05a, 2026-10-24). Cada fecha lleva la
 * abreviatura de zona para que nadie tenga que adivinarla.
 */

export const SITE_TZ = "America/Santiago";
export const SITE_TZ_LABEL = "hora de Chile";

/**
 * Component options, never `dateStyle`/`timeStyle` together with `timeZoneName`:
 * ECMA-402 forbids the mix and Firefox enforces it with a TypeError. Chrome lets
 * it through, which is how it reached production as a blank page — this ran at
 * module load, so the whole bundle died before the first API call
 * (2026-10-24, found on the live dashboard). Built inside a guard for the same
 * reason: a formatter that cannot be constructed must degrade, not take the app
 * with it.
 */
function formatter(locale: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  try {
    return new Intl.DateTimeFormat(locale, options);
  } catch {
    const { timeZoneName: _dropped, ...rest } = options;
    try { return new Intl.DateTimeFormat(locale, rest); }
    catch { return new Intl.DateTimeFormat(locale); }
  }
}

const DATE_TIME = formatter("es-CL", {
  timeZone: SITE_TZ, day: "2-digit", month: "2-digit", year: "numeric",
  hour: "2-digit", minute: "2-digit", hour12: false, timeZoneName: "short",
});
const HOUR = formatter("en-US", { timeZone: SITE_TZ, hour: "2-digit", hour12: false });

function toDate(value: string | Date): Date {
  return typeof value === "string" ? new Date(value) : value;
}

export function formatDateTime(value: string | Date | null | undefined): string {
  if (value == null) return "—";
  const d = toDate(value);
  return isNaN(d.getTime()) ? String(value) : DATE_TIME.format(d);
}

/** Hora del día (0–23) en la zona del sitio. Para agrupar por hora local. */
export function hourInSiteTz(value: string | Date): number | null {
  const d = toDate(value);
  if (isNaN(d.getTime())) return null;
  const part = HOUR.formatToParts(d).find((p) => p.type === "hour")?.value ?? "0";
  return Number(part) % 24;                 // "24" aparece en algunos motores para medianoche
}

/**
 * "hace 2 min". Deliberately coarse: a monitoring tool showing "hace 3 s" invites
 * the reader to trust a number that will be wrong a second later. What matters
 * is the order of magnitude, and whether it is growing.
 */
export function timeAgo(value: Date | string | null | undefined, now = new Date()): string {
  if (value == null) return "nunca";
  const d = toDate(value);
  if (isNaN(d.getTime())) return "—";

  const secs = Math.floor((now.getTime() - d.getTime()) / 1000);
  if (secs < 0) return "en el futuro";          // clock skew is worth seeing, not hiding
  if (secs < 10) return "recién";
  if (secs < 60) return `hace ${secs} s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `hace ${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `hace ${hours} h`;
  const days = Math.floor(hours / 24);
  return `hace ${days} d`;
}

/** Older than this and a "current" reading is not current any more. */
export const STALE_AFTER_MS = 3 * 60 * 1000;

export function isStale(value: Date | string | null | undefined, now = new Date()): boolean {
  if (value == null) return true;
  const d = toDate(value);
  return isNaN(d.getTime()) || now.getTime() - d.getTime() > STALE_AFTER_MS;
}
