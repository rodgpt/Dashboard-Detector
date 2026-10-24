/**
 * Historial de actividad del sensor.
 *
 * Cuatro estados, portados del panel original (`.uptime-cell active|session|
 * empty|future`). Responde de un vistazo a la única pregunta que importa de
 * verdad: **¿ha estado escuchando este equipo?**
 *
 * `empty` y `future` son distintos a propósito. Una hora que aún no ha ocurrido
 * no es una hora en la que el equipo estuvo callado, y pintarlas igual
 * convertiría el futuro en una avería.
 *
 * Recibe cuentas por hora del backend (`/events/summary?hourly=true`), no una
 * página de eventos: la página se cortaba en 500 y, al volumen real, las horas
 * más viejas de las 72 se pintaban como silencio — un equipo escuchando dibujado
 * como sordo (review FE-03, 2026-10-24).
 */
import type { HourBucket } from "@/api/client";
import { formatDateTime } from "@/lib/time";

type CellState = "active" | "session" | "empty" | "future";

const LABEL: Record<CellState, string> = {
  active: "con actividad",
  session: "en esta sesión, sin detecciones",
  empty: "sin datos",
  future: "aún no ocurre",
};

const hourKey = (d: Date) => d.toISOString().slice(0, 13);

export default function UptimeGrid({ hourly, sessionStart, hours = 72 }: {
  /** Cuenta de detecciones por hora UTC, del backend. */
  hourly: HourBucket[];
  /** `status.session_start`: desde cuándo el proceso actual lleva corriendo. */
  sessionStart?: string | null;
  hours?: number;
}) {
  const now = new Date();
  const start = new Date(now.getTime() - hours * 3_600_000);
  const session = sessionStart ? new Date(sessionStart) : null;

  const perHour = new Map<string, number>();
  for (const b of hourly) {
    const d = new Date(b.ts);
    if (isNaN(d.getTime())) continue;
    perHour.set(hourKey(d), (perHour.get(hourKey(d)) ?? 0) + b.count);
  }

  const cells = Array.from({ length: hours }, (_, i) => {
    const t = new Date(start.getTime() + i * 3_600_000);
    const count = perHour.get(hourKey(t)) ?? 0;

    let state: CellState;
    if (t > now) state = "future";
    else if (count > 0) state = "active";
    else if (session && t >= session) state = "session";
    else state = "empty";

    return { t, state, count };
  });

  const active = cells.filter((c) => c.state === "active").length;
  const covered = cells.filter((c) => c.state === "active" || c.state === "session").length;
  const past = cells.filter((c) => c.state !== "future").length;

  return (
    <>
      <div className="uptime-grid" role="img"
           aria-label={`Actividad de las últimas ${hours} horas: ${active} horas con detecciones, ${covered} de ${past} horas cubiertas por el equipo.`}>
        {cells.map((c) => (
          <span key={c.t.toISOString()} className={`uptime-cell ${c.state}`}
                title={`${formatDateTime(c.t)} — ${LABEL[c.state]}${c.count ? `, ${c.count} detección${c.count === 1 ? "" : "es"}` : ""}`} />
        ))}
      </div>

      <div className="uptime-legend">
        {(Object.keys(LABEL) as CellState[]).map((s) => (
          <span key={s} className="uptime-key">
            <span className={`uptime-cell ${s}`} aria-hidden="true" /> {LABEL[s]}
          </span>
        ))}
      </div>

      <p className="chart-note">
        {covered} de {past} horas cubiertas por el equipo en las últimas {hours} h,
        {" "}{active} con detecciones.
        {session
          ? <> La sesión actual empezó {formatDateTime(session)}; antes de eso no
              sabemos si estuvo escuchando, sólo que no hay detecciones.</>
          : <> El equipo no publica <code>session_start</code>, así que las horas
              sin detecciones no se pueden distinguir de las horas sin equipo.</>}
      </p>
    </>
  );
}
