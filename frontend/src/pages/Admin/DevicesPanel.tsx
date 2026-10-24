import { Fragment, useState, type FormEvent } from "react";
import { admin, type AdminDevice, type Site } from "@/api/client";
import { messageFor } from "@/pages/Admin";
import DeviceConfigEditor from "@/pages/Admin/DeviceConfigEditor";
import { formatDateTime, timeAgo } from "@/lib/time";

/**
 * Push health in words (D-022). The contract promises a refused push is visible
 * here, next to last contact — a unit whose every POST is rejected otherwise
 * looks identical to a quiet one. An error newer than the last success means
 * the push path is broken right now.
 */
function pushHealth(d: AdminDevice): { text: string; bad: boolean } {
  const ok = d.last_push_utc ? new Date(d.last_push_utc).getTime() : 0;
  const err = d.last_push_error_utc ? new Date(d.last_push_error_utc).getTime() : 0;
  if (!ok && !err) return { text: "sin envíos todavía", bad: false };
  if (err > ok) {
    return { text: `rechazado ${timeAgo(d.last_push_error_utc!)}: ${d.last_push_error ?? "sin detalle"}`, bad: true };
  }
  return { text: `último envío ${timeAgo(d.last_push_utc!)}`, bad: false };
}

interface Props {
  sites: Site[];
  devices: AdminDevice[];
  onChanged: (devices: AdminDevice[]) => void;
  onError: (message: string) => void;
}

const DEVICE_ID = /^[A-Za-z0-9_-]{3,64}$/;

export default function DevicesPanel({ sites, devices, onChanged, onError }: Props) {
  const [deviceId, setDeviceId] = useState("");
  const [siteId, setSiteId] = useState("");
  const [feedback, setFeedback] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [configuring, setConfiguring] = useState<number | null>(null);
  /** Plaintext key, held only until dismissed. Never stored in the device list. */
  const [issued, setIssued] = useState<{ device_id: string; key: string } | null>(null);
  const [copied, setCopied] = useState(false);

  const siteName = (id: string) => sites.find((s) => s.id === id)?.name ?? id;

  async function create(e: FormEvent) {
    e.preventDefault();
    setFeedback(null);
    setIssued(null);
    const id = deviceId.trim();
    if (!DEVICE_ID.test(id)) {
      setFeedback({ kind: "error", text: "El identificador debe tener 3–64 caracteres: letras, dígitos, guion o guion bajo." });
      return;
    }
    const site = siteId || sites[0]?.id;
    if (!site) { setFeedback({ kind: "error", text: "Selecciona un sitio." }); return; }

    setBusy(true);
    try {
      const created = await admin.createDevice({ device_id: id, site_id: site });
      const { key, ...rest } = created;
      onChanged([...devices, rest]);
      setDeviceId("");
      setIssued({ device_id: created.device_id, key });
      setCopied(false);
    } catch (err) {
      setFeedback({ kind: "error", text: messageFor(err, "No se pudo crear el dispositivo.") });
    } finally {
      setBusy(false);
    }
  }

  async function remove(d: AdminDevice) {
    if (!confirm(`¿Eliminar el dispositivo ${d.device_id}? Su clave deja de funcionar en el `
      + `próximo contacto y el equipo conservará su última configuración válida.`)) return;
    try {
      await admin.deleteDevice(d.id);
      onChanged(devices.filter((x) => x.id !== d.id));
    } catch (err) {
      onError(messageFor(err, "No se pudo eliminar el dispositivo."));
    }
  }

  async function resetStatus(d: AdminDevice) {
    if (!confirm(`¿Olvidar la última lectura de estado de ${d.device_id}? Se usa cuando el reloj `
      + `del equipo se adelantó y ninguna lectura correcta logra reemplazarla. El historial se conserva.`)) return;
    try {
      await admin.resetDeviceStatus(d.id);
      setFeedback({ kind: "ok", text: `Lectura de estado de ${d.device_id} olvidada. El próximo heartbeat la repone.` });
    } catch (err) {
      onError(messageFor(err, "No se pudo reiniciar el estado del dispositivo."));
    }
  }

  return (
    <section className="panel">
      <h2>Dispositivos</h2>
      <p className="panel-note">
        Cada equipo se autentica con una clave propia, separada de las sesiones
        de usuario. La clave se muestra una sola vez al crearla; se copia al
        archivo <code>/etc/oceankind.env</code> del equipo durante la preparación
        en banco.
      </p>

      <form onSubmit={create} noValidate>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="device-id">Identificador del equipo</label>
            <input id="device-id" type="text" autoComplete="off" placeholder="Rpi_zapallar"
                   value={deviceId} onChange={(e) => setDeviceId(e.target.value)} required />
            <p className="hint">3–64 caracteres: letras, dígitos, guion o guion bajo.</p>
          </div>
          <div className="field">
            <label htmlFor="device-site">Sitio</label>
            <select id="device-site" value={siteId || sites[0]?.id || ""}
                    onChange={(e) => setSiteId(e.target.value)}>
              {sites.map((s) => <option key={s.id} value={s.id}>{s.name || s.id}</option>)}
            </select>
          </div>
        </div>
        {feedback && (
          <div className={`form-feedback ${feedback.kind}`} role="alert">{feedback.text}</div>
        )}
        <button type="submit" className="btn btn-primary" disabled={busy}>Crear dispositivo</button>
      </form>

      {issued && (
        <div className="key-reveal" role="alert">
          <p>
            <strong>Clave creada. Se muestra una sola vez.</strong> Cópiala ahora
            y pégala en <code>/etc/oceankind.env</code> del equipo. Si se pierde,
            elimina el dispositivo y crea uno nuevo.
          </p>
          <div className="key-line"><span>Identificador:</span> <code>{issued.device_id}</code></div>
          <div className="key-line"><span>Clave:</span> <code>{issued.key}</code></div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={async () => {
            try { await navigator.clipboard.writeText(issued.key); setCopied(true); } catch { setCopied(false); }
          }}>{copied ? "Copiada ✓" : "Copiar clave"}</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setIssued(null)}>
            Ya la guardé — ocultar
          </button>
        </div>
      )}

      <div className="table-wrap" style={{ marginTop: 20 }}>
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Equipo</th><th scope="col">Sitio</th>
              <th scope="col">Última conexión</th><th scope="col">Envío de eventos</th>
              <th scope="col">Acciones</th>
            </tr>
          </thead>
          <tbody>
            {devices.length === 0 && (
              <tr><td colSpan={5} className="loading">Sin dispositivos registrados.</td></tr>
            )}
            {devices.map((d) => {
              const push = pushHealth(d);
              return (
              <Fragment key={d.id}>
                <tr>
                  <td>{d.device_id}</td>
                  <td><span className="chip">{siteName(d.site_id)}</span></td>
                  <td>{d.last_seen ? formatDateTime(d.last_seen) : "nunca se ha conectado"}</td>
                  <td className={push.bad ? "push-bad" : undefined} role={push.bad ? "alert" : undefined}>
                    {push.text}
                  </td>
                  <td className="actions">
                    <button type="button" className="btn btn-ghost btn-sm"
                            onClick={() => setConfiguring(configuring === d.id ? null : d.id)}>
                      {configuring === d.id ? "Cerrar" : "Configurar"}
                    </button>
                    <button type="button" className="btn btn-ghost btn-sm"
                            title="Olvidar la última lectura de estado (reloj adelantado)"
                            onClick={() => void resetStatus(d)}>Reiniciar estado</button>
                    <button type="button" className="btn btn-danger btn-sm"
                            onClick={() => void remove(d)}>Eliminar</button>
                  </td>
                </tr>
                {configuring === d.id && (
                  <tr>
                    <td colSpan={5}>
                      <DeviceConfigEditor deviceId={d.id} onClose={() => setConfiguring(null)} />
                    </td>
                  </tr>
                )}
              </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
