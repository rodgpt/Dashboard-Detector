import { useState, type FormEvent } from "react";
import { admin, type Site, type SitesSource } from "@/api/client";
import { messageFor } from "@/pages/Admin";

interface Props {
  sites: Site[];
  source: SitesSource;
  onChanged: (sites: Site[], source: SitesSource) => void;
  onError: (message: string) => void;
}

const SITE_ID = /^[a-z0-9][a-z0-9_-]{1,62}$/;

/** Coordinates locate unattended hardware and the threat model includes the
 *  people the system detects, so they are shown at reduced precision here.
 *  ~4 decimals is about 11 m — enough to place a site on a map, not enough to
 *  walk to the box. The stored value is untouched. */
const coarse = (n: number | null | undefined) =>
  n == null ? "—" : n.toFixed(4);

export default function SitesPanel({ sites, source, onChanged, onError }: Props) {
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [device, setDevice] = useState("");
  const [feedback, setFeedback] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function create(e: FormEvent) {
    e.preventDefault();
    setFeedback(null);
    const sid = id.trim().toLowerCase();
    if (!SITE_ID.test(sid)) {
      setFeedback({ kind: "error", text: "El identificador debe tener 2–63 caracteres: minúsculas, dígitos, guion o guion bajo." });
      return;
    }
    if (!name.trim()) { setFeedback({ kind: "error", text: "Ingresa un nombre." }); return; }
    const num = (v: string) => (v.trim() === "" ? null : Number(v));
    if ([lat, lon].some((v) => v.trim() !== "" && !Number.isFinite(Number(v)))) {
      setFeedback({ kind: "error", text: "Latitud y longitud deben ser numéricas." });
      return;
    }
    setBusy(true);
    try {
      const created = await admin.createSite({
        id: sid, name: name.trim(), lat: num(lat), lon: num(lon),
        device: device.trim() || null,
      });
      onChanged([...sites, created], "database");
      setId(""); setName(""); setLat(""); setLon(""); setDevice("");
      setFeedback({ kind: "ok", text: `Sitio ${created.id} creado.` });
    } catch (err) {
      setFeedback({ kind: "error", text: messageFor(err, "No se pudo crear el sitio.") });
    } finally {
      setBusy(false);
    }
  }

  async function importFromStorage() {
    try {
      const body = await admin.importSites();
      onChanged(body.sites, body.source);
      setFeedback({ kind: "ok", text: `Importados desde el almacenamiento: ${body.sites.length} sitio(s).` });
    } catch (err) {
      onError(messageFor(err, "No se pudo importar desde el almacenamiento."));
    }
  }

  async function remove(s: Site) {
    if (!confirm(`¿Eliminar el sitio ${s.name || s.id}?`)) return;
    try {
      await admin.deleteSite(s.id);
      onChanged(sites.filter((x) => x.id !== s.id), "database");
    } catch (err) {
      // 409 aquí es informativo, no un fallo: el sitio sigue en uso
      onError(messageFor(err, "No se pudo eliminar el sitio."));
    }
  }

  async function toggleActive(s: Site) {
    try {
      const updated = await admin.updateSite(s.id, { active: !s.active });
      onChanged(sites.map((x) => (x.id === s.id ? updated : x)), "database");
    } catch (err) {
      onError(messageFor(err, "No se pudo actualizar el sitio."));
    }
  }

  return (
    <section className="panel">
      <h2>Sitios</h2>

      {source === "storage" && (
        <div className="form-feedback" style={{ background: "var(--warn-fill)", border: "1px solid var(--warn)", color: "var(--text)" }} role="status">
          Estos sitios vienen del archivo <code>_sites.json</code> en el
          almacenamiento y todavía no se gestionan aquí. Impórtalos para poder
          editarlos; en un contenedor nuevo ese archivo no existe y no habrá
          ningún sitio hasta crear el primero.
          <div>
            <button type="button" className="btn btn-ghost btn-sm" style={{ marginTop: 10 }}
                    onClick={() => void importFromStorage()}>
              Importar desde el almacenamiento
            </button>
          </div>
        </div>
      )}

      {source === "empty" && (
        <p className="panel-note">
          No hay ningún sitio registrado. Crea el primero: sin un sitio no se
          puede registrar ningún dispositivo, porque la clave de un equipo se
          emite siempre contra un sitio conocido.
        </p>
      )}

      <form onSubmit={create} noValidate>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="site-id">Identificador</label>
            <input id="site-id" type="text" autoComplete="off" placeholder="lagunillas"
                   value={id} onChange={(e) => setId(e.target.value)} required />
            <p className="hint">Se usa como ruta en el almacenamiento. No se puede cambiar después.</p>
          </div>
          <div className="field">
            <label htmlFor="site-name">Nombre</label>
            <input id="site-name" type="text" autoComplete="off" placeholder="Lagunillas"
                   value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="site-lat">Latitud</label>
            <input id="site-lat" type="number" step="any" value={lat}
                   onChange={(e) => setLat(e.target.value)} />
            <p className="hint">Opcional. Vacío es honesto; 0 no.</p>
          </div>
          <div className="field">
            <label htmlFor="site-lon">Longitud</label>
            <input id="site-lon" type="number" step="any" value={lon}
                   onChange={(e) => setLon(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="site-device">Equipo esperado</label>
            <input id="site-device" type="text" autoComplete="off" placeholder="Rpi_lagunillas"
                   value={device} onChange={(e) => setDevice(e.target.value)} />
            <p className="hint">Opcional, informativo.</p>
          </div>
        </div>
        {feedback && (
          <div className={`form-feedback ${feedback.kind}`} role="alert">{feedback.text}</div>
        )}
        <button type="submit" className="btn btn-primary" disabled={busy}>Crear sitio</button>
      </form>

      <div className="table-wrap" style={{ marginTop: 20 }}>
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Identificador</th><th scope="col">Nombre</th>
              <th scope="col">Coordenadas</th><th scope="col">Estado</th>
              <th scope="col">Acciones</th>
            </tr>
          </thead>
          <tbody>
            {sites.length === 0 && (
              <tr><td colSpan={5} className="loading">Sin sitios registrados.</td></tr>
            )}
            {sites.map((s) => (
              <tr key={s.id}>
                <td><code>{s.id}</code></td>
                <td>{s.name}</td>
                <td title="Precisión reducida a propósito">
                  {coarse(s.lat)}, {coarse(s.lon)}
                </td>
                <td>
                  <span className={s.active ? "role-badge" : "chip none"}>
                    {s.active ? "activo" : "inactivo"}
                  </span>
                </td>
                <td className="actions">
                  {source === "database" && (
                    <>
                      <button type="button" className="btn btn-ghost btn-sm"
                              onClick={() => void toggleActive(s)}>
                        {s.active ? "Desactivar" : "Activar"}
                      </button>
                      <button type="button" className="btn btn-danger btn-sm"
                              onClick={() => void remove(s)}>Eliminar</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
