/** Fecha y hora en español de Chile, y "hace cuánto" para la frescura de datos. */

export function formatDateTime(value: string | Date | null | undefined): string {
  if (value == null) return "—";
  const d = typeof value === "string" ? new Date(value) : value;
  return isNaN(d.getTime()) ? String(value) : d.toLocaleString("es-CL");
}

export function formatTime(value: string | Date | null | undefined): string {
  if (value == null) return "—";
  const d = typeof value === "string" ? new Date(value) : value;
  return isNaN(d.getTime()) ? String(value) : d.toLocaleTimeString("es-CL");
}

/**
 * "hace 2 min". Deliberately coarse: a monitoring tool showing "hace 3 s" invites
 * the reader to trust a number that will be wrong a second later. What matters
 * is the order of magnitude, and whether it is growing.
 */
export function timeAgo(value: Date | string | null | undefined, now = new Date()): string {
  if (value == null) return "nunca";
  const d = typeof value === "string" ? new Date(value) : value;
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
  const d = typeof value === "string" ? new Date(value) : value;
  return isNaN(d.getTime()) || now.getTime() - d.getTime() > STALE_AFTER_MS;
}
