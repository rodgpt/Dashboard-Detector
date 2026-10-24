/**
 * The only place that talks to the backend.
 *
 * Every call is cookie-authenticated and every failure is explicit, because a
 * monitoring tool that renders stale data as current is worse than one that is
 * visibly broken (R-7.1).
 *
 * There is no version prefix and no configurable base URL: nginx proxies /api/
 * to the backend on the same origin, in development and in production alike.
 * See docs/API-CONTRACT.md and docs/SERVER-INFRASTRUCTURE.md.
 *
 * Types come from `generated.ts` (openapi-typescript over docs/openapi.json,
 * `make types`) wherever the backend composes the envelope — that is R-9.5, and
 * until 2026-10-24 the generated file was regenerated faithfully and imported by
 * nothing (review FE-04). The device's own documents (events, status, rollups)
 * are deliberate pass-throughs with no response model, so they stay hand-typed
 * here from DATA-CONTRACT.md; every number in them may be null.
 */
import type { components } from "./generated";

type Schemas = components["schemas"];

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
  /** 401: no session. Send them to login. */
  get isAuth() { return this.status === 401; }
  /** 403: logged in, not permitted. Show a message — never a login redirect. */
  get isForbidden() { return this.status === 403; }
  /** 0: the request never reached the server. */
  get isOffline() { return this.status === 0; }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { credentials: "same-origin", ...init });
  } catch {
    throw new ApiError(0, "sin conexión con el servidor");
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    const message = (detail as { detail?: string }).detail
      ?? (res.status === 401 ? "no autenticado" : `error ${res.status}`);
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  // Guard every parse. A captive portal or a proxy error page can answer 200
  // with HTML; before this it surfaced as "sin conexión", blaming the network
  // for a server that did answer (review FE-08, repo rule "guard every JSON.parse").
  try {
    return await res.json() as T;
  } catch {
    throw new ApiError(res.status, "respuesta del servidor no válida (no es JSON)");
  }
}

const json = (body: unknown): RequestInit => ({
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

// ── device documents: hand-typed from DATA-CONTRACT.md, pass-throughs ───────

export type EventType = "vessel" | "blast" | "unknown";

/** `_sites.json` / the site registry. Coordinates are nullable: an unsurveyed
 *  site is honest, 0,0 is not. */
export interface Site {
  id: string; name: string; lat: number | null; lon: number | null;
  device: string | null; active: boolean;
}

export interface Clip {
  path: string; sample_rate: number; channels: number;
  duration_s: number; uploaded: boolean;
}

export interface DetectionEvent {
  schema_version: number; site: string; device: string;
  event_id: string; captured_utc: string; uploaded_utc: string;
  event_type: EventType; detector: string; score: number | null; suppressed: boolean;
  audio_level: number | null; peak_db: number | null; bearing_deg: number | null;
  clip: Clip; detector_meta: Record<string, unknown>;
  _unknown_schema?: boolean;
}

// ── backend envelopes: from the generated schema ───────────────────────────

export type Page<T> = Omit<Schemas["EventsPage"], "items"> & { items: T[] };

export interface HourBucket { ts: string; count: number }

/** Counts over the whole filtered window, not a page of it — backs every chart
 *  and the uptime grid, which must answer for the period asked, not for
 *  whichever page of events happened to be loaded. */
export type EventsSummary = Omit<Schemas["EventsSummary"], "by_day" | "hourly"> & {
  by_day: { date: string; count: number }[];
  /** Only when requested with `hourly: true`. One bucket per UTC clock hour. */
  hourly: HourBucket[];
};

export type Me = Schemas["Me"];
export type AdminUser = Schemas["UserOut"];
/** Carries push health (D-022) and release state (Rpi-Detector D-021):
 *  `installed_release`/`installed_sha` from the heartbeat's `ota` block,
 *  `assigned_release`/`hold` from the signed configuration, `failed_*` when the
 *  unit tried an assignment and rolled back. `needs_reprovision` = created
 *  before the one-secret model (D-020); nothing can be signed for it. */
export type AdminDevice = Schemas["DeviceOut"];
/** `key` is the ONE device secret (Rpi-Detector D-020): in the creation
 *  response only, never readable again. */
export type AdminDeviceCreated = Schemas["DeviceCreated"];
/** Tags GitHub lists for the device repository (may be empty when unreachable)
 *  plus the release a NEW device is assigned at creation. */
export type Releases = Schemas["ReleasesOut"];
/** An outage `silence.py` recorded (R-7.5). `open` = not yet cleared. */
export type DeviceAlert = Schemas["AlertOut"];
export type IndexDay = Schemas["IndexDayOut"];
export type IndexSite = Schemas["IndexSiteOut"];
export type ReconcileResult = Schemas["ReconcileOut"];
export type Health = Schemas["Health"];

/** Where the site registry came from. "storage" means it is still the
 *  `_sites.json` fallback and nobody has managed it yet. */
export type SitesSource = "database" | "storage" | "empty";
export type AdminSites = { sites: Site[]; source: SitesSource };

/** Mirrors the clamp table in DATA-CONTRACT.md "Device configuration" (R-6.2). */
export interface DeviceConfig {
  detection_mode: "psd" | "rms" | "auto";
  score_min: number; alert_min_rms: number; alert_threshold: number;
  psd_threshold_db: number; psd_f_min: number; psd_f_max: number;
  cooldown_s: number; heartbeat_interval_s: number; window_hop_s: number;
}

export type DeviceConfigState = Omit<Schemas["DeviceConfigOut"], "config"> & { config: DeviceConfig };

// ── calls ───────────────────────────────────────────────────────────────────

/** Unauthenticated liveness. `alerts` says whether anything this backend
 *  decides to alert about reaches a human (`twilio`) or only the log and this
 *  dashboard (`log-only` / `off`) — Rpi-Detector D-020. */
export const ops = {
  health: () => req<Health>("/health"),
};

export const auth = {
  login: (email: string, password: string) =>
    req<Schemas["Ok"]>("/auth/login", { method: "POST", ...json({ email, password }) }),
  logout: () => req<Schemas["Ok"]>("/auth/logout", { method: "POST" }),
  me: () => req<Me>("/auth/me"),
};

export interface EventQuery {
  since?: Date; until?: Date; event_type?: EventType; min_score?: number;
  include_suppressed?: boolean; limit?: number; offset?: number;
}

/** The filter subset `/events` and `/events/summary` share — everything
 *  except pagination, which the summary route has no use for. */
function filterParams(q: EventQuery): URLSearchParams {
  const p = new URLSearchParams();
  if (q.since) p.set("since", q.since.toISOString());
  if (q.until) p.set("until", q.until.toISOString());
  if (q.event_type) p.set("event_type", q.event_type);
  if (q.min_score != null) p.set("min_score", String(q.min_score));
  if (q.include_suppressed != null) p.set("include_suppressed", String(q.include_suppressed));
  return p;
}

const seg = encodeURIComponent;

export const data = {
  sites: () => req<{ sites: Site[] }>("/sites"),

  events(siteId: string, q: EventQuery = {}) {
    const p = filterParams(q);
    p.set("limit", String(q.limit ?? 50));
    p.set("offset", String(q.offset ?? 0));
    return req<Page<DetectionEvent>>(`/sites/${seg(siteId)}/events?${p}`);
  },

  /** One event by id — the `?play=` lookup (R-8.5). 404 when the index does
   *  not hold it, which is a real answer, not a scan that ran out of page. */
  event: (siteId: string, eventId: string) =>
    req<DetectionEvent>(`/sites/${seg(siteId)}/events/${seg(eventId)}`),

  /** Counts for the whole filtered period — never a page of it (see
   *  `EventsSummary`). `hourly` adds one bucket per clock hour. */
  eventsSummary(siteId: string, q: EventQuery = {}, opts: { hourly?: boolean } = {}) {
    const p = filterParams(q);
    if (opts.hourly) p.set("hourly", "true");
    return req<EventsSummary>(`/sites/${seg(siteId)}/events/summary?${p}`);
  },

  status: (s: string) => req<Record<string, unknown>>(`/sites/${seg(s)}/status`),
  /** Open device-silence alerts for this site — the outages the backend noticed
   *  while nobody had the page open. */
  alerts: (s: string) => req<{ alerts: DeviceAlert[] }>(`/sites/${seg(s)}/alerts`),
  power: (s: string) => req<Record<string, unknown>>(`/sites/${seg(s)}/power`),
  acoustic: (s: string) => req<Record<string, unknown>>(`/sites/${seg(s)}/acoustic`),
  ocean: (s: string) => req<Record<string, unknown>>(`/sites/${seg(s)}/ocean`),

  /** Audio is proxied by the API, so no storage credential ever reaches here.
   *  Accepts the full `clip.path` (`sites/{site}/clips/YYYY/MM/DD/{id}.wav`) or
   *  the part after `clips/`; each segment is encoded. */
  clipUrl: (siteId: string, clipPath: string) => {
    const rel = clipPath.includes("/clips/") ? clipPath.split("/clips/")[1]! : clipPath;
    return `/api/sites/${seg(siteId)}/clips/${rel.split("/").map(seg).join("/")}`;
  },
};

export const admin = {
  users: () => req<AdminUser[]>("/admin/users"),
  createUser: (b: { email: string; password: string; role: "operator" | "admin"; sites: string[] }) =>
    req<AdminUser>("/admin/users", { method: "POST", ...json(b) }),
  setSites: (id: number, sites: string[]) =>
    req<AdminUser>(`/admin/users/${id}/sites`, { method: "PUT", ...json({ sites }) }),
  deleteUser: (id: number) => req<void>(`/admin/users/${id}`, { method: "DELETE" }),

  sites: () => req<AdminSites>("/admin/sites"),
  createSite: (b: { id: string; name: string; lat?: number | null; lon?: number | null;
                    device?: string | null; active?: boolean }) =>
    req<Site>("/admin/sites", { method: "POST", ...json(b) }),
  updateSite: (id: string, b: Partial<Omit<Site, "id">>) =>
    req<Site>(`/admin/sites/${seg(id)}`, { method: "PUT", ...json(b) }),
  deleteSite: (id: string) => req<void>(`/admin/sites/${seg(id)}`, { method: "DELETE" }),
  importSites: () => req<AdminSites>("/admin/sites/import", { method: "POST" }),

  index: () => req<IndexSite[]>("/admin/index"),
  reconcile: (siteId?: string) =>
    req<ReconcileResult[]>(`/admin/index/reconcile${siteId ? `?site_id=${seg(siteId)}` : ""}`,
      { method: "POST" }),
  rebuildIndex: (siteId: string) =>
    req<ReconcileResult>("/admin/index/rebuild",
      { method: "POST", ...json({ site_id: siteId, confirm_site_id: siteId }) }),

  devices: () => req<AdminDevice[]>("/admin/devices"),
  createDevice: (b: { device_id: string; site_id: string }) =>
    req<AdminDeviceCreated>("/admin/devices", { method: "POST", ...json(b) }),
  deleteDevice: (id: number) => req<void>(`/admin/devices/${id}`, { method: "DELETE" }),
  /** Forget the device's current heartbeat reading (history kept). For a unit
   *  whose clock ran ahead and left a reading no correct heartbeat can beat. */
  resetDeviceStatus: (id: number) => req<void>(`/admin/devices/${id}/status`, { method: "DELETE" }),

  alerts: (openOnly = true) =>
    req<DeviceAlert[]>(`/admin/alerts?open_only=${openOnly ? "true" : "false"}`),

  getDeviceConfig: (id: number) => req<DeviceConfigState>(`/admin/devices/${id}/config`),
  setDeviceConfig: (id: number, config: DeviceConfig) =>
    req<DeviceConfigState>(`/admin/devices/${id}/config`, { method: "PUT", ...json(config) }),

  // ── releases (Rpi-Detector D-021): publish a tag, then choose who takes it ──
  releases: () => req<Releases>("/admin/releases"),
  /** The release a NEW device gets at creation. Existing assignments untouched. */
  setFleetRelease: (release: string | null) =>
    req<Releases>("/admin/releases/default", { method: "PUT", ...json({ release }) }),
  /** Assign a release and/or set the hold for one device. Re-signs and
   *  re-publishes its configuration; the unit acts at its next poll (≤ 300 s). */
  assignRelease: (id: number, body: { release?: string | null; hold?: boolean }) =>
    req<DeviceConfigState>(`/admin/devices/${id}/release`, { method: "PUT", ...json(body) }),
};
