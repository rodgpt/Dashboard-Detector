import { Fragment, useEffect, useState, type FormEvent } from "react";
import { admin, type AdminDevice, type Releases, type Site } from "@/api/client";
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

/**
 * Release state in words (Rpi-Detector D-021). Installed comes from the unit's
 * heartbeat (`ota` block); assigned from the signed configuration. The two
 * disagreeing is normal for up to one poll plus one verify window; `failed_*`
 * set on the assigned tag means the unit tried it and rolled back — that is the
 * one state a human has to act on, so it is the one painted red.
 */
function releaseState(d: AdminDevice): { text: string; tone: "ok" | "bad" | "pending" | "muted" } {
  const inst = d.installed_release ?? (d.installed_sha ? `commit ${d.installed_sha}` : null);
  if (d.needs_reprovision) {
    return { text: `${inst ?? "versión desconocida"} · re-provisionar (sin clave de firma)`, tone: "bad" };
  }
  if (!d.assigned_release) {
    return { text: inst ? `${inst} · sin asignar` : "sin asignar", tone: "muted" };
  }
  if (d.failed_sha && (d.failed_release === d.assigned_release || !d.failed_release)) {
    return { text: `${inst ?? "?"} · falló ${d.assigned_release}, revertida`, tone: "bad" };
  }
  if (d.hold) return { text: `${inst ?? "?"} · retenida (asignada ${d.assigned_release})`, tone: "pending" };
  if (inst === d.assigned_release) return { text: inst, tone: "ok" };
  return { text: `${inst ?? "?"} → ${d.assigned_release} (pendiente)`, tone: "pending" };
}

const TAG = /^v?[0-9A-Za-z][0-9A-Za-z._-]{0,63}$/;

/** A tag from the list, or one typed by hand (GitHub may be unreachable). */
function ReleasePicker({ id, tags, value, onChange, loading = false }: {
  id: string; tags: string[]; value: string; onChange: (v: string) => void; loading?: boolean;
}) {
  return (
    <div className="field">
      <label htmlFor={id}>Release (tag git)</label>
      <input id={id} list={`${id}-tags`} type="text" autoComplete="off" placeholder="v2.2.0"
             value={value} onChange={(e) => onChange(e.target.value.trim())} />
      <datalist id={`${id}-tags`}>
        {tags.map((t) => <option key={t} value={t} />)}
      </datalist>
      <p className="hint">
        {loading ? "Consultando los tags del repositorio…"
          : tags.length ? `${tags.length} tags publicados en el repositorio (↓ para verlos).`
          : "No se pudo leer la lista de tags; escribe el nombre."}
        {" "}Vacío = sin asignación (el equipo conserva lo que corre).
      </p>
    </div>
  );
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
  const [updating, setUpdating] = useState<number | null>(null);
  /** Plaintext secret, held only until dismissed. Never stored in the device list. */
  const [issued, setIssued] = useState<{ device_id: string; key: string } | null>(null);
  const [copied, setCopied] = useState(false);

  // Releases (D-021): tags + fleet default. Loaded once; the list is advisory.
  const [releases, setReleases] = useState<Releases | null>(null);
  const [releasesError, setReleasesError] = useState<string | null>(null);
  const [releasesLoading, setReleasesLoading] = useState(false);
  const [fleetInput, setFleetInput] = useState("");
  const [assignInput, setAssignInput] = useState("");
  const [assignHold, setAssignHold] = useState(false);

  /** Loaded once on mount from the backend cache, and again, bypassing the
   *  cache, every time an assignment row opens: the tag the operator just
   *  pushed is the one they came here to assign. */
  async function loadReleases(refresh: boolean) {
    setReleasesLoading(true);
    try {
      const r = await admin.releases(refresh);
      setReleases(r);
      setReleasesError(null);
      setFleetInput((cur) => cur || (r.fleet_default ?? ""));
    } catch (err) {
      setReleasesError(messageFor(err, "No se pudo leer la lista de releases."));
    } finally {
      setReleasesLoading(false);
    }
  }

  useEffect(() => { void loadReleases(false); }, []);

  const siteName = (id: string) => sites.find((s) => s.id === id)?.name ?? id;
  const tags = releases?.tags ?? [];

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
    if (!confirm(`¿Eliminar el dispositivo ${d.device_id}? Su secreto deja de funcionar en el `
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

  async function saveFleetDefault(e: FormEvent) {
    e.preventDefault();
    const v = fleetInput.trim();
    if (v && !TAG.test(v)) { setFeedback({ kind: "error", text: "La release debe ser un tag git, p. ej. v2.2.0." }); return; }
    setBusy(true);
    try {
      const r = await admin.setFleetRelease(v || null);
      setReleases(r);
      setFleetInput(r.fleet_default ?? "");
      setFeedback({ kind: "ok", text: r.fleet_default
        ? `Los equipos nuevos se crearán asignados a ${r.fleet_default}. Los existentes no cambian.`
        : "Los equipos nuevos se crearán sin release asignada." });
    } catch (err) {
      setFeedback({ kind: "error", text: messageFor(err, "No se pudo guardar la release predeterminada.") });
    } finally {
      setBusy(false);
    }
  }

  function openUpdate(d: AdminDevice) {
    if (updating === d.id) { setUpdating(null); return; }
    setUpdating(d.id);
    setAssignInput(d.assigned_release ?? "");
    setAssignHold(d.hold);
    void loadReleases(true);
  }

  async function assign(d: AdminDevice, e: FormEvent) {
    e.preventDefault();
    const v = assignInput.trim();
    if (v && !TAG.test(v)) { setFeedback({ kind: "error", text: "La release debe ser un tag git, p. ej. v2.2.0." }); return; }
    setBusy(true);
    try {
      await admin.assignRelease(d.id, { release: v || null, hold: assignHold });
      onChanged(devices.map((x) => x.id === d.id ? { ...x, assigned_release: v || null, hold: assignHold } : x));
      setUpdating(null);
      setFeedback({ kind: "ok", text: assignHold
        ? `${d.device_id} retenido: no se actualizará aunque tenga release asignada.`
        : v ? `${d.device_id} actualizará a ${v} en su próxima consulta (hasta 5 min), con verificación y rollback.`
            : `${d.device_id} sin release asignada: conserva lo que corre.` });
    } catch (err) {
      setFeedback({ kind: "error", text: messageFor(err, "No se pudo asignar la release.") });
    } finally {
      setBusy(false);
    }
  }

  async function toggleHold(d: AdminDevice) {
    setBusy(true);
    try {
      await admin.assignRelease(d.id, { hold: !d.hold });
      onChanged(devices.map((x) => x.id === d.id ? { ...x, hold: !d.hold } : x));
    } catch (err) {
      onError(messageFor(err, "No se pudo cambiar la retención."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Dispositivos</h2>
      <p className="panel-note">
        Cada equipo tiene un único secreto, separado de las sesiones de usuario:
        de él derivan su clave de autenticación y la clave con la que verifica su
        configuración. Se muestra una sola vez al crearlo y se pega en
        <code>/etc/oceankind.env</code> del equipo durante la preparación en banco.
        Las alertas por WhatsApp y voz salen desde este servidor, no desde los equipos.
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
            <strong>Secreto creado. Se muestra una sola vez.</strong> Cópialo ahora
            y pégalo en <code>/etc/oceankind.env</code> del equipo como
            <code>OCEANKIND_DEVICE_SECRET</code>. Si se pierde, elimina el
            dispositivo y crea uno nuevo.
          </p>
          <div className="key-line"><span>Identificador:</span> <code>{issued.device_id}</code></div>
          <div className="key-line"><span>Secreto:</span> <code>{issued.key}</code></div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={async () => {
            try { await navigator.clipboard.writeText(issued.key); setCopied(true); } catch { setCopied(false); }
          }}>{copied ? "Copiado ✓" : "Copiar secreto"}</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setIssued(null)}>
            Ya lo guardé — ocultar
          </button>
        </div>
      )}

      <h3 style={{ marginTop: 28 }}>Versiones</h3>
      <p className="panel-note">
        Publicar una versión es crear un tag en el repositorio del equipo. Aquí se
        decide qué equipos la toman y cuándo: primero el banco, después un sitio,
        después el resto. Cada equipo descarga la release asignada, la verifica
        durante un minuto y vuelve atrás solo si no arranca. Sin asignación, nadie
        se actualiza.
      </p>
      {releasesError && <div className="form-feedback error" role="alert">{releasesError}</div>}
      <form onSubmit={saveFleetDefault} noValidate>
        <div className="form-grid">
          <ReleasePicker id="fleet-release" tags={tags} value={fleetInput} onChange={setFleetInput} />
          <div className="field">
            <label>Predeterminada para equipos nuevos</label>
            <p className="hint">
              {releases?.fleet_default
                ? `Hoy: ${releases.fleet_default}. Se asigna al crear un equipo; los existentes no cambian.`
                : "Hoy ninguna: un equipo nuevo no se actualiza hasta que se le asigne una release."}
            </p>
            <button type="submit" className="btn btn-ghost btn-sm" disabled={busy || releases === null}>
              Guardar predeterminada
            </button>
          </div>
        </div>
      </form>

      <div className="table-wrap" style={{ marginTop: 20 }}>
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Equipo</th><th scope="col">Sitio</th>
              <th scope="col">Última conexión</th><th scope="col">Envío de eventos</th>
              <th scope="col">Versión</th>
              <th scope="col">Acciones</th>
            </tr>
          </thead>
          <tbody>
            {devices.length === 0 && (
              <tr><td colSpan={6} className="loading">Sin dispositivos registrados.</td></tr>
            )}
            {devices.map((d) => {
              const push = pushHealth(d);
              const rel = releaseState(d);
              return (
              <Fragment key={d.id}>
                <tr>
                  <td>{d.device_id}</td>
                  <td><span className="chip">{siteName(d.site_id)}</span></td>
                  <td>{d.last_seen ? formatDateTime(d.last_seen) : "nunca se ha conectado"}</td>
                  <td className={push.bad ? "push-bad" : undefined} role={push.bad ? "alert" : undefined}>
                    {push.text}
                  </td>
                  <td className={`release-${rel.tone}`} role={rel.tone === "bad" ? "alert" : undefined}>
                    {rel.text}
                  </td>
                  <td className="actions">
                    <button type="button" className="btn btn-ghost btn-sm"
                            onClick={() => { setUpdating(null); setConfiguring(configuring === d.id ? null : d.id); }}>
                      {configuring === d.id ? "Cerrar" : "Configurar"}
                    </button>
                    <button type="button" className="btn btn-ghost btn-sm"
                            disabled={d.needs_reprovision}
                            title={d.needs_reprovision ? "Creado antes del secreto único: elimínalo y créalo de nuevo" : "Asignar una release a este equipo"}
                            onClick={() => { setConfiguring(null); openUpdate(d); }}>
                      {updating === d.id ? "Cerrar" : "Actualizar"}
                    </button>
                    <button type="button" className="btn btn-ghost btn-sm"
                            disabled={busy || d.needs_reprovision}
                            title={d.hold ? "Permitir que vuelva a actualizarse" : "Retener: no actualizar aunque tenga release asignada"}
                            onClick={() => void toggleHold(d)}>
                      {d.hold ? "Liberar" : "Retener"}
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
                    <td colSpan={6}>
                      <DeviceConfigEditor deviceId={d.id} onClose={() => setConfiguring(null)} />
                    </td>
                  </tr>
                )}
                {updating === d.id && (
                  <tr>
                    <td colSpan={6}>
                      <form className="row-editor" onSubmit={(e) => void assign(d, e)} noValidate>
                        <div className="form-grid">
                          <ReleasePicker id={`assign-${d.id}`} tags={tags} value={assignInput}
                                         onChange={setAssignInput} loading={releasesLoading} />
                          <div className="field">
                            <label htmlFor={`hold-${d.id}`}>Retener</label>
                            <label className="hint" htmlFor={`hold-${d.id}`} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                              <input id={`hold-${d.id}`} type="checkbox" checked={assignHold}
                                     onChange={(e) => setAssignHold(e.target.checked)} />
                              No actualizar este equipo aunque tenga release asignada.
                            </label>
                            <p className="hint">
                              Instalada: {d.installed_release ?? d.installed_sha ?? "desconocida"}.
                              {d.failed_sha ? ` Falló y revirtió: ${d.failed_release ?? d.failed_sha}.` : ""}
                            </p>
                          </div>
                        </div>
                        <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>Asignar</button>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setUpdating(null)}>Cancelar</button>
                      </form>
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
