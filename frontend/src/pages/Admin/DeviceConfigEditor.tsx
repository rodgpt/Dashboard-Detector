/**
 * Ajuste de umbrales por dispositivo (R-6.2, D-015).
 *
 * Los umbrales son del cliente; los límites son nuestros. El servidor ajusta y
 * devuelve lo que quedó en vigor, así que después de guardar los campos se
 * reescriben con la respuesta — nunca con lo que se tecleó.
 */
import { useEffect, useState } from "react";
import { admin, type DeviceConfig, type DeviceConfigState } from "@/api/client";
import { messageFor } from "@/pages/Admin";

/** Etiquetas y rangos según la tabla de DATA-CONTRACT.md. El servidor es quien
 *  ajusta; esto sólo orienta a quien escribe. */
const FIELDS: { key: keyof Omit<DeviceConfig, "detection_mode">; label: string; min: number; max: number }[] = [
  { key: "score_min",            label: "Puntaje mínimo (score)",     min: 0.05,  max: 0.95 },
  { key: "alert_min_rms",        label: "RMS mínimo de alerta",       min: 0,     max: 0.20 },
  { key: "alert_threshold",      label: "Umbral de alerta RMS",       min: 0.005, max: 0.50 },
  { key: "psd_threshold_db",     label: "Umbral PSD (dB)",            min: 3,     max: 30 },
  { key: "psd_f_min",            label: "Frecuencia mínima PSD (Hz)", min: 20,    max: 2000 },
  { key: "psd_f_max",            label: "Frecuencia máxima PSD (Hz)", min: 100,   max: 20000 },
  { key: "cooldown_s",           label: "Pausa entre avisos (s)",     min: 10,    max: 3600 },
  { key: "heartbeat_interval_s", label: "Intervalo de latido (s)",    min: 30,    max: 3600 },
];

export default function DeviceConfigEditor({ deviceId, onClose }: {
  deviceId: number; onClose: () => void;
}) {
  const [state, setState] = useState<DeviceConfigState | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [mode, setMode] = useState<DeviceConfig["detection_mode"]>("psd");
  const [feedback, setFeedback] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  function adopt(s: DeviceConfigState) {
    setState(s);
    setMode(s.config.detection_mode);
    setDraft(Object.fromEntries(FIELDS.map((f) => [f.key, String(s.config[f.key])])));
  }

  useEffect(() => {
    let cancelled = false;
    admin.getDeviceConfig(deviceId)
      .then((s) => { if (!cancelled) adopt(s); })
      .catch((err) => {
        if (!cancelled) setFeedback({ kind: "error", text: messageFor(err, "No se pudo cargar la configuración.") });
      });
    return () => { cancelled = true; };
  }, [deviceId]);

  async function save() {
    setFeedback(null);
    const body: Record<string, unknown> = { detection_mode: mode };
    for (const f of FIELDS) {
      const raw = (draft[f.key] ?? "").trim();
      if (raw === "") { setFeedback({ kind: "error", text: `Falta un valor: ${f.label}.` }); return; }
      const n = Number(raw);
      if (!Number.isFinite(n)) { setFeedback({ kind: "error", text: `Valor no numérico en: ${f.label}.` }); return; }
      body[f.key] = n;
    }
    setBusy(true);
    try {
      const updated = await admin.setDeviceConfig(deviceId, body as unknown as DeviceConfig);
      adopt(updated);   // el servidor es la verdad, ajustes incluidos
      setFeedback({
        kind: "ok",
        text: updated.clamp_notes.length
          ? `Guardada (versión ${updated.version}). Valores ajustados al rango permitido: ${updated.clamp_notes.join("; ")}`
          : `Guardada (versión ${updated.version}).`,
      });
    } catch (err) {
      setFeedback({ kind: "error", text: messageFor(err, "No se pudo guardar.") });
    } finally {
      setBusy(false);
    }
  }

  if (!state) {
    return (
      <div className="row-editor">
        {feedback
          ? <div className={`form-feedback ${feedback.kind}`} role="alert">{feedback.text}</div>
          : <div className="loading">Cargando configuración…</div>}
        <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>Cerrar</button>
      </div>
    );
  }

  return (
    <div className="row-editor">
      <p className="hint">
        {state.is_default
          ? "Configuración por defecto (versión 1). Aún nadie la ha ajustado."
          : `Versión ${state.version}. El equipo la aplica en su próxima consulta.`}
      </p>

      <div className="form-grid">
        <div className="field">
          <label htmlFor={`mode-${deviceId}`}>Modo de detección</label>
          <select id={`mode-${deviceId}`} value={mode}
                  onChange={(e) => setMode(e.target.value as DeviceConfig["detection_mode"])}>
            <option value="psd">psd</option>
            <option value="rms">rms</option>
            <option value="auto">auto</option>
          </select>
        </div>
        {FIELDS.map((f) => (
          <div className="field" key={f.key}>
            <label htmlFor={`${f.key}-${deviceId}`}>{f.label}</label>
            <input id={`${f.key}-${deviceId}`} type="number" step="any" min={f.min} max={f.max}
                   value={draft[f.key] ?? ""}
                   onChange={(e) => setDraft((p) => ({ ...p, [f.key]: e.target.value }))} />
            <p className="hint">Rango {f.min} – {f.max}</p>
          </div>
        ))}
      </div>

      {feedback && <div className={`form-feedback ${feedback.kind}`} role="alert">{feedback.text}</div>}
      <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => void save()}>
        Guardar configuración
      </button>
      <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>Cerrar</button>
    </div>
  );
}
