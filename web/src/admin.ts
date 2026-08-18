/**
 * Panel de administración: usuarios y asignación de sitios (R-3.3).
 *
 * Reglas que esta pantalla respeta a propósito:
 *  - 401 redirige al acceso; 403 muestra un mensaje. Nunca son lo mismo.
 *  - Los sitios vienen de la API, jamás de una lista codificada.
 *  - Todo dato de usuario entra al DOM con textContent, nunca con innerHTML.
 *  - Cada fallo es visible y reintentabile; nada falla en silencio (R-7.1).
 */
import { auth, data, admin, ApiError } from "./api.js";
import type { Me, Site, AdminUser, AdminDevice } from "./api.js";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

const appEl = $<HTMLElement>("app");
const forbiddenEl = $<HTMLElement>("forbidden");
const whoEl = $<HTMLSpanElement>("who");
const pageError = $<HTMLDivElement>("page-error");
const pageErrorText = $<HTMLSpanElement>("page-error-text");
const usersBody = $<HTMLTableSectionElement>("users-body");
const usersTable = $<HTMLTableElement>("users-table");
const usersLoading = $<HTMLDivElement>("users-loading");
const createForm = $<HTMLFormElement>("create-form");
const createFeedback = $<HTMLDivElement>("create-feedback");

let me: Me;
let sites: Site[] = [];
let users: AdminUser[] = [];
let devices: AdminDevice[] = [];

function toLogin(): void {
  location.replace("/login?next=%2Fadmin");
}

function showPageError(message: string): void {
  pageErrorText.textContent = message;
  pageError.hidden = false;
}

function feedback(el: HTMLElement, kind: "ok" | "error", message: string): void {
  el.classList.remove("ok", "error");
  el.classList.add(kind);
  el.textContent = message;
  el.hidden = false;
}

/** Casillas de sitios generadas desde la API. Devuelve el lector de selección. */
function siteChecks(container: HTMLElement, selected: ReadonlySet<string>): () => string[] {
  container.textContent = "";
  if (sites.length === 0) {
    const none = document.createElement("span");
    none.className = "chip none";
    none.textContent = "no hay sitios disponibles";
    container.appendChild(none);
  }
  for (const s of sites) {
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = s.id;
    box.checked = selected.has(s.id);
    label.appendChild(box);
    label.appendChild(document.createTextNode(s.name || s.id));
    container.appendChild(label);
  }
  return () =>
    Array.from(container.querySelectorAll<HTMLInputElement>("input:checked")).map(b => b.value);
}

function siteName(id: string): string {
  return sites.find(s => s.id === id)?.name ?? id;
}

function renderUsers(): void {
  usersBody.textContent = "";
  for (const u of users) {
    const tr = document.createElement("tr");

    const tdEmail = document.createElement("td");
    tdEmail.textContent = u.email + (u.active ? "" : " (inactiva)") + (u.email === me.email ? " — tú" : "");
    tr.appendChild(tdEmail);

    const tdRole = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = u.role === "admin" ? "role-badge admin" : "role-badge";
    badge.textContent = u.role === "admin" ? "administración" : "operación";
    tdRole.appendChild(badge);
    tr.appendChild(tdRole);

    const tdSites = document.createElement("td");
    renderSitesCell(tdSites, u);
    tr.appendChild(tdSites);

    const tdActions = document.createElement("td");
    tdActions.className = "actions";
    if (u.role !== "admin") {
      const edit = document.createElement("button");
      edit.type = "button";
      edit.className = "btn btn-ghost btn-sm";
      edit.textContent = "Editar sitios";
      edit.addEventListener("click", () => openEditor(tdSites, u, edit));
      tdActions.appendChild(edit);
    }
    const del = document.createElement("button");
    del.type = "button";
    del.className = "btn btn-danger btn-sm";
    del.textContent = "Eliminar";
    if (u.email === me.email) {
      del.disabled = true;
      del.title = "No puedes eliminar tu propia cuenta";
    }
    del.addEventListener("click", () => deleteUser(u, del));
    tdActions.appendChild(del);
    tr.appendChild(tdActions);

    usersBody.appendChild(tr);
  }
  usersLoading.hidden = true;
  usersTable.hidden = false;
}

function renderSitesCell(td: HTMLElement, u: AdminUser): void {
  td.textContent = "";
  if (u.role === "admin") {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = "todos los sitios";
    td.appendChild(chip);
    return;
  }
  if (u.sites.length === 0) {
    const chip = document.createElement("span");
    chip.className = "chip none";
    chip.textContent = "sin sitios asignados";
    td.appendChild(chip);
    return;
  }
  for (const id of u.sites) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = siteName(id);
    td.appendChild(chip);
  }
}

function openEditor(td: HTMLElement, u: AdminUser, trigger: HTMLButtonElement): void {
  trigger.disabled = true;
  const editor = document.createElement("div");
  editor.className = "row-editor";
  const checks = document.createElement("div");
  checks.className = "site-checks";
  const readSelection = siteChecks(checks, new Set(u.sites));
  editor.appendChild(checks);

  const errBox = document.createElement("div");
  errBox.className = "form-feedback";
  errBox.hidden = true;
  editor.appendChild(errBox);

  const save = document.createElement("button");
  save.type = "button";
  save.className = "btn btn-primary btn-sm";
  save.textContent = "Guardar";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "btn btn-ghost btn-sm";
  cancel.textContent = "Cancelar";
  cancel.style.marginLeft = "8px";
  editor.appendChild(save);
  editor.appendChild(cancel);

  cancel.addEventListener("click", () => {
    renderSitesCell(td, u);
    trigger.disabled = false;
  });
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      const updated = await admin.setSites(u.id, readSelection());
      users = users.map(x => (x.id === u.id ? updated : x));
      renderUsers();
    } catch (err) {
      if (err instanceof ApiError && err.isAuth) { toLogin(); return; }
      feedback(errBox, "error", err instanceof ApiError ? err.message : "No se pudo guardar.");
      save.disabled = false;
    }
  });

  td.appendChild(editor);
}

async function deleteUser(u: AdminUser, button: HTMLButtonElement): Promise<void> {
  if (!confirm(`¿Eliminar la cuenta ${u.email}? Esta acción no se puede deshacer.`)) return;
  button.disabled = true;
  try {
    await admin.deleteUser(u.id);
    users = users.filter(x => x.id !== u.id);
    renderUsers();
  } catch (err) {
    if (err instanceof ApiError && err.isAuth) { toLogin(); return; }
    showPageError(err instanceof ApiError
      ? `No se pudo eliminar la cuenta: ${err.message}`
      : "No se pudo eliminar la cuenta.");
    button.disabled = false;
  }
}

// ── dispositivos (R-6.1, D-017) ──────────────────────────────────────────────

const devicesBody = $<HTMLTableSectionElement>("devices-body");
const devicesTable = $<HTMLTableElement>("devices-table");
const devicesLoading = $<HTMLDivElement>("devices-loading");
const keyReveal = $<HTMLDivElement>("key-reveal");

function lastSeenText(iso: string | null): string {
  if (!iso) return "nunca se ha conectado";
  const t = new Date(iso);
  return isNaN(t.getTime()) ? iso : t.toLocaleString("es-CL");
}

function renderDevices(): void {
  devicesBody.textContent = "";
  if (devices.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 4;
    td.className = "loading";
    td.textContent = "Sin dispositivos registrados.";
    tr.appendChild(td);
    devicesBody.appendChild(tr);
  }
  for (const d of devices) {
    const tr = document.createElement("tr");

    const tdId = document.createElement("td");
    tdId.textContent = d.device_id;
    tr.appendChild(tdId);

    const tdSite = document.createElement("td");
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = siteName(d.site_id);
    tdSite.appendChild(chip);
    tr.appendChild(tdSite);

    const tdSeen = document.createElement("td");
    tdSeen.textContent = lastSeenText(d.last_seen);
    tr.appendChild(tdSeen);

    const tdActions = document.createElement("td");
    tdActions.className = "actions";
    const del = document.createElement("button");
    del.type = "button";
    del.className = "btn btn-danger btn-sm";
    del.textContent = "Eliminar";
    del.addEventListener("click", () => deleteDevice(d, del));
    tdActions.appendChild(del);
    tr.appendChild(tdActions);

    devicesBody.appendChild(tr);
  }
  devicesLoading.hidden = true;
  devicesTable.hidden = false;
}

function renderDeviceSites(): void {
  const select = $<HTMLSelectElement>("device-site");
  select.textContent = "";
  for (const s of sites) {
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = s.name || s.id;
    select.appendChild(opt);
  }
}

function showKey(deviceId: string, key: string): void {
  $<HTMLElement>("key-device-id").textContent = deviceId;
  $<HTMLElement>("key-value").textContent = key;
  keyReveal.hidden = false;
}

function hideKey(): void {
  // fuera del DOM, no sólo oculta: la clave no debe sobrevivir en la página
  $<HTMLElement>("key-device-id").textContent = "";
  $<HTMLElement>("key-value").textContent = "";
  keyReveal.hidden = true;
}

async function deleteDevice(d: AdminDevice, button: HTMLButtonElement): Promise<void> {
  if (!confirm(`¿Eliminar el dispositivo ${d.device_id}? Su clave deja de funcionar en el `
      + `próximo contacto y el equipo conservará su última configuración válida.`)) return;
  button.disabled = true;
  try {
    await admin.deleteDevice(d.id);
    devices = devices.filter(x => x.id !== d.id);
    renderDevices();
  } catch (err) {
    if (err instanceof ApiError && err.isAuth) { toLogin(); return; }
    showPageError(err instanceof ApiError
      ? `No se pudo eliminar el dispositivo: ${err.message}`
      : "No se pudo eliminar el dispositivo.");
    button.disabled = false;
  }
}

$<HTMLFormElement>("device-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const deviceFeedback = $<HTMLDivElement>("device-feedback");
  deviceFeedback.hidden = true;
  hideKey();

  const deviceId = $<HTMLInputElement>("device-id").value.trim();
  const siteId = $<HTMLSelectElement>("device-site").value;
  if (!/^[A-Za-z0-9_-]{3,64}$/.test(deviceId)) {
    feedback(deviceFeedback, "error",
      "El identificador debe tener 3–64 caracteres: letras, dígitos, guion o guion bajo.");
    return;
  }
  if (!siteId) {
    feedback(deviceFeedback, "error", "Selecciona un sitio.");
    return;
  }

  const submit = $<HTMLButtonElement>("device-submit");
  submit.disabled = true;
  try {
    const created = await admin.createDevice({ device_id: deviceId, site_id: siteId });
    // la clave vive en el aviso de una sola vez, no en la lista en memoria
    devices = [...devices, { id: created.id, device_id: created.device_id,
                             site_id: created.site_id, active: created.active,
                             last_seen: created.last_seen }];
    renderDevices();
    $<HTMLFormElement>("device-form").reset();
    showKey(created.device_id, created.key);
  } catch (err) {
    if (err instanceof ApiError && err.isAuth) { toLogin(); return; }
    feedback(deviceFeedback, "error",
      err instanceof ApiError ? err.message : "No se pudo crear el dispositivo.");
  } finally {
    submit.disabled = false;
  }
});

$<HTMLButtonElement>("key-copy").addEventListener("click", async () => {
  const key = $<HTMLElement>("key-value").textContent ?? "";
  const button = $<HTMLButtonElement>("key-copy");
  try {
    await navigator.clipboard.writeText(key);
    button.textContent = "Copiada ✓";
    setTimeout(() => { button.textContent = "Copiar clave"; }, 2000);
  } catch {
    // sin permiso de portapapeles: la clave sigue visible y es seleccionable
    button.textContent = "Selecciónala y copia manualmente";
  }
});

$<HTMLButtonElement>("key-dismiss").addEventListener("click", hideKey);

// ── carga ────────────────────────────────────────────────────────────────────

async function loadData(): Promise<void> {
  pageError.hidden = true;
  usersLoading.hidden = false;
  devicesLoading.hidden = false;
  // Independientes a propósito: si una fuente falla, las otras igual se muestran (R-7.3)
  const [sitesRes, usersRes, devicesRes] = await Promise.allSettled(
    [data.sites(), admin.users(), admin.devices()]);

  const authFailure = [sitesRes, usersRes, devicesRes].find(
    (r): r is PromiseRejectedResult =>
      r.status === "rejected" && r.reason instanceof ApiError && r.reason.isAuth);
  if (authFailure) { toLogin(); return; }

  if (sitesRes.status === "fulfilled") {
    sites = sitesRes.value.sites;
    siteChecks($<HTMLDivElement>("new-sites"), new Set());
    renderDeviceSites();
  } else {
    showPageError("No se pudo cargar la lista de sitios. Las asignaciones no se pueden editar hasta reintentar.");
  }

  if (usersRes.status === "fulfilled") {
    users = usersRes.value;
    renderUsers();
  } else {
    usersLoading.textContent = "No se pudo cargar la lista de usuarios.";
    showPageError("No se pudo cargar la lista de usuarios.");
  }

  if (devicesRes.status === "fulfilled") {
    devices = devicesRes.value;
    renderDevices();
  } else {
    devicesLoading.textContent = "No se pudo cargar la lista de dispositivos.";
    showPageError("No se pudo cargar la lista de dispositivos.");
  }
}

createForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  createFeedback.hidden = true;
  const email = $<HTMLInputElement>("new-email").value.trim().toLowerCase();
  const password = $<HTMLInputElement>("new-password").value;
  const role = $<HTMLSelectElement>("new-role").value as "operator" | "admin";
  const selected = Array.from(
    document.querySelectorAll<HTMLInputElement>("#new-sites input:checked")).map(b => b.value);

  if (!email) { feedback(createFeedback, "error", "Ingresa un correo electrónico."); return; }
  if (password.length < 12) {
    feedback(createFeedback, "error", "La contraseña debe tener al menos 12 caracteres.");
    return;
  }
  if (role === "operator" && selected.length === 0 && sites.length > 0 &&
      !confirm("Sin sitios asignados esta cuenta no verá ningún dato. ¿Crearla igual?")) {
    return;
  }

  const submit = $<HTMLButtonElement>("create-submit");
  submit.disabled = true;
  try {
    const created = await admin.createUser({ email, password, role, sites: selected });
    users = [...users, created];
    renderUsers();
    createForm.reset();
    siteChecks($<HTMLDivElement>("new-sites"), new Set());
    feedback(createFeedback, "ok", `Cuenta ${created.email} creada.`);
  } catch (err) {
    if (err instanceof ApiError && err.isAuth) { toLogin(); return; }
    feedback(createFeedback, "error",
      err instanceof ApiError ? err.message : "No se pudo crear la cuenta.");
  } finally {
    submit.disabled = false;
  }
});

$<HTMLButtonElement>("logout").addEventListener("click", async () => {
  try { await auth.logout(); } catch { /* la cookie igual se descarta en el servidor */ }
  location.replace("/login");
});

$<HTMLButtonElement>("retry").addEventListener("click", () => { void loadData(); });

(async function init() {
  try {
    me = await auth.me();
  } catch (err) {
    if (err instanceof ApiError && err.isAuth) { toLogin(); return; }
    document.body.textContent = "Sin conexión con el servidor. Recarga la página para reintentar.";
    return;
  }
  whoEl.textContent = me.email;
  if (me.role !== "admin") {
    forbiddenEl.hidden = false;   // 403: mensaje, no redirección
    return;
  }
  appEl.hidden = false;
  await loadData();
})();
