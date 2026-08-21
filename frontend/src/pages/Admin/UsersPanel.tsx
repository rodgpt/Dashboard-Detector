import { useState, type FormEvent } from "react";
import { admin, type AdminUser, type Site } from "@/api/client";
import { messageFor } from "@/pages/Admin";

interface Props {
  sites: Site[];
  users: AdminUser[];
  meEmail: string;
  onChanged: (users: AdminUser[]) => void;
  onError: (message: string) => void;
}

export default function UsersPanel({ sites, users, meEmail, onChanged, onError }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"operator" | "admin">("operator");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [feedback, setFeedback] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);

  const siteName = (id: string) => sites.find((s) => s.id === id)?.name ?? id;

  function toggle(set: Set<string>, id: string): Set<string> {
    const next = new Set(set);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    setFeedback(null);
    if (!email.trim()) { setFeedback({ kind: "error", text: "Ingresa un correo electrónico." }); return; }
    if (password.length < 12) {
      setFeedback({ kind: "error", text: "La contraseña debe tener al menos 12 caracteres." });
      return;
    }
    if (role === "operator" && selected.size === 0 && sites.length > 0 &&
        !confirm("Sin sitios asignados esta cuenta no verá ningún dato. ¿Crearla igual?")) {
      return;
    }
    setBusy(true);
    try {
      const created = await admin.createUser({
        email: email.trim().toLowerCase(), password, role, sites: [...selected],
      });
      onChanged([...users, created]);
      setEmail(""); setPassword(""); setRole("operator"); setSelected(new Set());
      setFeedback({ kind: "ok", text: `Cuenta ${created.email} creada.` });
    } catch (err) {
      setFeedback({ kind: "error", text: messageFor(err, "No se pudo crear la cuenta.") });
    } finally {
      setBusy(false);
    }
  }

  async function remove(u: AdminUser) {
    if (!confirm(`¿Eliminar la cuenta ${u.email}? Esta acción no se puede deshacer.`)) return;
    try {
      await admin.deleteUser(u.id);
      onChanged(users.filter((x) => x.id !== u.id));
    } catch (err) {
      onError(messageFor(err, "No se pudo eliminar la cuenta."));
    }
  }

  async function saveSites(u: AdminUser, next: string[]) {
    try {
      const updated = await admin.setSites(u.id, next);
      onChanged(users.map((x) => (x.id === u.id ? updated : x)));
      setEditing(null);
    } catch (err) {
      onError(messageFor(err, "No se pudo guardar la asignación."));
    }
  }

  return (
    <section className="panel">
      <h2>Usuarios</h2>

      <form onSubmit={create} noValidate>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="new-email">Correo electrónico</label>
            <input id="new-email" type="email" autoComplete="off" required
                   value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="new-password">Contraseña</label>
            <input id="new-password" type="password" autoComplete="new-password" minLength={12} required
                   value={password} onChange={(e) => setPassword(e.target.value)} />
            <p className="hint">Mínimo 12 caracteres.</p>
          </div>
          <div className="field">
            <label htmlFor="new-role">Rol</label>
            <select id="new-role" value={role}
                    onChange={(e) => setRole(e.target.value as "operator" | "admin")}>
              <option value="operator">Operación — ve sus sitios asignados</option>
              <option value="admin">Administración — ve todo y gestiona usuarios</option>
            </select>
          </div>
        </div>

        <div className="field">
          <label>Sitios asignados</label>
          <div className="site-checks">
            {sites.length === 0 && <span className="chip none">no hay sitios disponibles</span>}
            {sites.map((s) => (
              <label key={s.id}>
                <input type="checkbox" checked={selected.has(s.id)}
                       onChange={() => setSelected((p) => toggle(p, s.id))} />
                {s.name || s.id}
              </label>
            ))}
          </div>
          <p className="hint">
            Una cuenta de administración ve todos los sitios; las casillas sólo
            aplican al rol de operación.
          </p>
        </div>

        {feedback && (
          <div className={`form-feedback ${feedback.kind}`} role="alert">{feedback.text}</div>
        )}
        <button type="submit" className="btn btn-primary" disabled={busy}>Crear usuario</button>
      </form>

      <div className="table-wrap" style={{ marginTop: 20 }}>
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Correo</th><th scope="col">Rol</th>
              <th scope="col">Sitios</th><th scope="col">Acciones</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.email}{!u.active && " (inactiva)"}{u.email === meEmail && " — tú"}</td>
                <td>
                  <span className={u.role === "admin" ? "role-badge admin" : "role-badge"}>
                    {u.role === "admin" ? "administración" : "operación"}
                  </span>
                </td>
                <td>
                  {u.role === "admin" ? (
                    <span className="chip">todos los sitios</span>
                  ) : editing === u.id ? (
                    <SiteEditor sites={sites} initial={u.sites}
                                onCancel={() => setEditing(null)}
                                onSave={(next) => void saveSites(u, next)} />
                  ) : u.sites.length === 0 ? (
                    <span className="chip none">sin sitios asignados</span>
                  ) : (
                    u.sites.map((id) => <span className="chip" key={id}>{siteName(id)}</span>)
                  )}
                </td>
                <td className="actions">
                  {u.role !== "admin" && editing !== u.id && (
                    <button type="button" className="btn btn-ghost btn-sm"
                            onClick={() => setEditing(u.id)}>Editar sitios</button>
                  )}
                  <button type="button" className="btn btn-danger btn-sm"
                          disabled={u.email === meEmail}
                          title={u.email === meEmail ? "No puedes eliminar tu propia cuenta" : undefined}
                          onClick={() => void remove(u)}>Eliminar</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function SiteEditor({ sites, initial, onSave, onCancel }: {
  sites: Site[]; initial: string[];
  onSave: (next: string[]) => void; onCancel: () => void;
}) {
  const [sel, setSel] = useState<Set<string>>(new Set(initial));
  return (
    <div className="row-editor">
      <div className="site-checks">
        {sites.map((s) => (
          <label key={s.id}>
            <input type="checkbox" checked={sel.has(s.id)} onChange={() => {
              setSel((p) => { const n = new Set(p); n.has(s.id) ? n.delete(s.id) : n.add(s.id); return n; });
            }} />
            {s.name || s.id}
          </label>
        ))}
      </div>
      <button type="button" className="btn btn-primary btn-sm" onClick={() => onSave([...sel])}>
        Guardar
      </button>
      <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>Cancelar</button>
    </div>
  );
}
