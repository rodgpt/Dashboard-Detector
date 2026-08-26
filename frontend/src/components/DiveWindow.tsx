/**
 * "Definir mar bueno para bucear" — portado del panel del cliente.
 *
 * Dos modos que comparten el formulario, como en el original: `energy` (un solo
 * número, swell²·período) y `swellperiod` (límites separados). Más viento máximo
 * y ocho direcciones.
 *
 * Se guarda en el navegador, igual que antes. Eso significa que es de quien
 * mira, no del sistema: no viaja a otro computador. El panel lo dice, porque
 * una ventana que alguien afinó y luego perdió sin aviso es exactamente la
 * clase de pequeña traición que este proyecto intenta no cometer.
 */
import { useState } from "react";
import {
  DIRS, DIVE_DEFAULTS, loadDiveWindow, saveDiveWindow, type DiveWindow,
} from "@/lib/sea";

export default function DiveWindowEditor({ value, onChange }: {
  value: DiveWindow;
  onChange: (w: DiveWindow) => void;
}) {
  const [saved, setSaved] = useState(false);

  const set = (patch: Partial<DiveWindow>) => {
    const next = { ...value, ...patch };
    onChange(next);
    setSaved(false);
  };

  const toggleDir = (d: string) => {
    const dirs = value.dirs.includes(d)
      ? value.dirs.filter((x) => x !== d)
      : [...value.dirs, d];
    set({ dirs });
  };

  return (
    <section className="panel">
      <div className="panel-head"><h2>Definir “mar bueno para bucear”</h2></div>
      <p className="panel-note">
        Se guarda en este navegador. No se comparte con otras cuentas ni viaja a
        otro equipo, y se pierde si limpias los datos del sitio.
      </p>

      <div className="form-grid">
        <div className="field">
          <label htmlFor="dive-mode">Criterio de mar</label>
          <select id="dive-mode" value={value.mode}
                  onChange={(e) => set({ mode: e.target.value === "swellperiod" ? "swellperiod" : "energy" })}>
            <option value="energy">Energía del mar</option>
            <option value="swellperiod">Swell y período por separado</option>
          </select>
        </div>

        {value.mode === "energy" ? (
          <div className="field">
            <label htmlFor="dive-energy">Energía del mar máx</label>
            <input id="dive-energy" type="number" step={1} min={0} value={value.energy_max}
                   onChange={(e) => set({ energy_max: Number(e.target.value) })} />
            <p className="hint">swell² · período</p>
          </div>
        ) : (
          <>
            <div className="field">
              <label htmlFor="dive-swell">Swell máx</label>
              <input id="dive-swell" type="number" step={0.1} min={0} value={value.swell_max}
                     onChange={(e) => set({ swell_max: Number(e.target.value) })} />
              <p className="hint">metros</p>
            </div>
            <div className="field">
              <label htmlFor="dive-period">Período mín</label>
              <input id="dive-period" type="number" step={0.5} min={0} value={value.period_min}
                     onChange={(e) => set({ period_min: Number(e.target.value) })} />
              <p className="hint">segundos</p>
            </div>
          </>
        )}

        <div className="field">
          <label htmlFor="dive-wind">Viento máx</label>
          <input id="dive-wind" type="number" step={1} min={0} value={value.wind_max}
                 onChange={(e) => set({ wind_max: Number(e.target.value) })} />
          <p className="hint">km/h</p>
        </div>
      </div>

      <div className="field">
        <label>Direcciones de viento aceptables</label>
        <div className="site-checks">
          {DIRS.map((d) => (
            <label key={d}>
              <input type="checkbox" checked={value.dirs.includes(d)}
                     onChange={() => toggleDir(d)} />
              {d}
            </label>
          ))}
        </div>
        <p className="hint">
          Ninguna marcada significa cualquier dirección, no ninguna dirección.
        </p>
      </div>

      <button type="button" className="btn btn-primary btn-sm"
              onClick={() => { saveDiveWindow(value); setSaved(true); }}>
        Guardar ventana
      </button>
      <button type="button" className="btn btn-ghost btn-sm" style={{ marginLeft: 8 }}
              onClick={() => { const d = { ...DIVE_DEFAULTS }; onChange(d); saveDiveWindow(d); setSaved(true); }}>
        Restablecer
      </button>
      {saved && <span className="save-note">Guardada en este navegador.</span>}
    </section>
  );
}

export { loadDiveWindow };
