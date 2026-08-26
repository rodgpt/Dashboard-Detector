/**
 * Lecturas del equipo.
 *
 * Una regla, y es la que importa: **`null` no es cero.** Un sensor que no
 * reporta y un sensor que reporta cero se ven distintos, siempre. Dibujar
 * "0 W" cuando el controlador solar no respondió es exactamente la mentira
 * silenciosa que este sistema existe para eliminar.
 */
import type { ReactNode } from "react";

export interface Stat {
  label: string;
  value: number | string | null | undefined;
  unit?: string;
  digits?: number;
  /** Cuándo este valor debe leerse como problema. */
  warn?: (v: number) => boolean;
  /** Qué significa que falte, si se sabe. */
  absent?: string;
}

function render(s: Stat): { text: ReactNode; bad: boolean; missing: boolean } {
  if (s.value == null || s.value === "") {
    return {
      text: <span className="null-value" title={s.absent ?? "el equipo no publica este dato"}>sin dato</span>,
      bad: false, missing: true,
    };
  }
  if (typeof s.value === "number") {
    const bad = s.warn?.(s.value) ?? false;
    const shown = s.digits != null ? s.value.toFixed(s.digits) : String(s.value);
    return { text: <>{shown}{s.unit ? <span className="stat-unit">{s.unit}</span> : null}</>, bad, missing: false };
  }
  return { text: <>{s.value}{s.unit ? <span className="stat-unit">{s.unit}</span> : null}</>, bad: false, missing: false };
}

export default function StatGrid({ stats }: { stats: Stat[] }) {
  return (
    <div className="stat-grid">
      {stats.map((s) => {
        const { text, bad, missing } = render(s);
        return (
          <div key={s.label}
               className={`stat${bad ? " bad" : ""}${missing ? " missing" : ""}`}>
            <div className="stat-label">{s.label}</div>
            <div className="stat-value">{text}</div>
          </div>
        );
      })}
    </div>
  );
}
