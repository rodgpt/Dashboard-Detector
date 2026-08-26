/**
 * Condiciones de mar derivadas — portadas del panel del cliente, no inventadas.
 *
 * La fórmula de energía es la que su propia etiqueta declara:
 *   "Energía del mar máx (swell²·período)"
 * y el modo por defecto de la ventana de buceo es `energy`, con límite 25.
 *
 * Nada de esto es ciencia nuestra (D-015). Son las reglas con las que el cliente
 * ya decide si vale la pena ir al sitio; aquí sólo se reproducen.
 */

export type DiveMode = "energy" | "swellperiod";

export interface DiveWindow {
  mode: DiveMode;
  /** Sólo en modo `energy`. */
  energy_max: number;
  /** Sólo en modo `swellperiod`. */
  swell_max: number;
  period_min: number;
  wind_max: number;
  /** Direcciones de viento aceptables. Vacío = cualquiera. */
  dirs: string[];
}

export const DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"] as const;

/** Los valores por defecto del panel original. */
export const DIVE_DEFAULTS: DiveWindow = {
  mode: "energy",
  energy_max: 25,
  swell_max: 2.0,
  period_min: 10,
  wind_max: 25,
  dirs: [],
};

/** swell² · período. Null si falta cualquiera de los dos — nunca cero. */
export function seaEnergy(swellM?: number | null, periodS?: number | null): number | null {
  if (swellM == null || periodS == null) return null;
  return +(swellM * swellM * periodS).toFixed(2);
}

export interface SeaPoint {
  swell_m?: number | null;
  swell_period_s?: number | null;
  wind_kmph?: number | null;
  wind_dir?: string | null;
  swell_dir?: string | null;
}

/**
 * ¿Es buceable esta hora?
 *
 * Devuelve `null` cuando falta el dato necesario, y eso **no** es lo mismo que
 * "no buceable". Un pronóstico incompleto no autoriza ni prohíbe nada.
 */
export function isDiveable(p: SeaPoint, w: DiveWindow): boolean | null {
  const windOk = p.wind_kmph == null ? null : p.wind_kmph <= w.wind_max;

  const dir = p.wind_dir ?? p.swell_dir ?? null;
  const dirOk = w.dirs.length === 0 ? true : (dir == null ? null : w.dirs.includes(dir));

  let seaOk: boolean | null;
  if (w.mode === "energy") {
    const e = seaEnergy(p.swell_m, p.swell_period_s);
    seaOk = e == null ? null : e <= w.energy_max;
  } else {
    seaOk = (p.swell_m == null || p.swell_period_s == null)
      ? null
      : p.swell_m <= w.swell_max && p.swell_period_s >= w.period_min;
  }

  if (seaOk === null || windOk === null || dirOk === null) return null;
  return seaOk && windOk && dirOk;
}

/**
 * Persistencia de la ventana de buceo.
 *
 * Vive en el navegador, como en el panel original. Es una preferencia de quien
 * mira, no un dato del sistema: no viaja entre equipos y se pierde al limpiar
 * el navegador. Si el cliente la quiere por usuario y entre dispositivos, eso
 * es una tabla y unas rutas — está anotado en PROGRESS como pregunta abierta.
 */
const KEY = "oceankind.dive-window";

export function loadDiveWindow(): DiveWindow {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...DIVE_DEFAULTS };
    const s = JSON.parse(raw) as Partial<DiveWindow>;
    return {
      mode: s.mode === "swellperiod" ? "swellperiod" : "energy",
      energy_max: Number(s.energy_max ?? DIVE_DEFAULTS.energy_max),
      swell_max: Number(s.swell_max ?? DIVE_DEFAULTS.swell_max),
      period_min: Number(s.period_min ?? DIVE_DEFAULTS.period_min),
      wind_max: Number(s.wind_max ?? DIVE_DEFAULTS.wind_max),
      dirs: Array.isArray(s.dirs) ? s.dirs.filter((d) => (DIRS as readonly string[]).includes(d)) : [],
    };
  } catch {
    // Un JSON corrupto en localStorage no puede tumbar la vista.
    return { ...DIVE_DEFAULTS };
  }
}

export function saveDiveWindow(w: DiveWindow): void {
  try { localStorage.setItem(KEY, JSON.stringify(w)); } catch { /* modo privado */ }
}
