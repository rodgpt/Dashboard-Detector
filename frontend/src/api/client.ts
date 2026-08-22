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
 */

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
  return res.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

// ── contract types. mirror docs/DATA-CONTRACT.md. every number may be null ──

export type EventType = "vessel" | "blast" | "unknown";

export interface Site {
  id: string; name: string; lat: number; lon: number;
  device: string; active: boolean;
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


export interface Page<T> {
  items: T[]; total: number; limit: number; offset: number;
  has_more: boolean; scanned_blobs: number;
}

export interface Me { email: string; role: "operator" | "admin"; sites: string[]; }

export interface AdminUser {
  id: number; email: string; role: "operator" | "admin";
  active: boolean; sites: string[];
}

/** Where the site registry came from. "storage" means it is still the
 *  `_sites.json` fallback and nobody has managed it yet. */
export type SitesSource = "database" | "storage" | "empty";

export interface AdminSites { sites: Site[]; source: SitesSource; }

export interface AdminDevice {
  id: number; device_id: string; site_id: string;
  active: boolean; last_seen: string | null;
}

/** `key` exists in the creation response only, never readable again (D-017). */
export interface AdminDeviceCreated extends AdminDevice { key: string; }

/** Mirrors the clamp table in DATA-CONTRACT.md "Device configuration" (R-6.2). */
export interface DeviceConfig {
  detection_mode: "psd" | "rms" | "auto";
  score_min: number; alert_min_rms: number; alert_threshold: number;
  psd_threshold_db: number; psd_f_min: number; psd_f_max: number;
  cooldown_s: number; heartbeat_interval_s: number; window_hop_s: number;
}

export interface DeviceConfigState {
  device_id: string; site_id: string;
  version: number;
  /** What the device compares. Opaque string; changes on every tune. */
  config_version: string;
  is_default: boolean;
  updated_utc: string | null;
  config: DeviceConfig;
  clamp_notes: string[];
  /** Blob path the signed document was written to. Transport is storage (D-020). */
  published_to: string | null;
  /** Set when the site holds other devices and this publish replaced their document. */
  publish_warning: string | null;
}

// ── calls ───────────────────────────────────────────────────────────────────

export const auth = {
  login: (email: string, password: string) =>
    req<{ ok: true }>("/auth/login", { method: "POST", ...json({ email, password }) }),
  logout: () => req<{ ok: true }>("/auth/logout", { method: "POST" }),
  me: () => req<Me>("/auth/me"),
};

export interface EventQuery {
  since?: Date; until?: Date; event_type?: EventType; min_score?: number;
  include_suppressed?: boolean; limit?: number; offset?: number;
}

export const data = {
  sites: () => req<{ sites: Site[] }>("/sites"),

  events(siteId: string, q: EventQuery = {}) {
    const p = new URLSearchParams();
    if (q.since) p.set("since", q.since.toISOString());
    if (q.until) p.set("until", q.until.toISOString());
    if (q.event_type) p.set("event_type", q.event_type);
    if (q.min_score != null) p.set("min_score", String(q.min_score));
    if (q.include_suppressed != null) p.set("include_suppressed", String(q.include_suppressed));
    p.set("limit", String(q.limit ?? 50));
    p.set("offset", String(q.offset ?? 0));
    return req<Page<DetectionEvent>>(`/sites/${siteId}/events?${p}`);
  },

  status: (s: string) => req<Record<string, unknown>>(`/sites/${s}/status`),
  power: (s: string) => req<Record<string, unknown>>(`/sites/${s}/power`),
  acoustic: (s: string) => req<Record<string, unknown>>(`/sites/${s}/acoustic`),
  ocean: (s: string) => req<Record<string, unknown>>(`/sites/${s}/ocean`),

  /** Audio is proxied by the API, so no storage credential ever reaches here. */
  clipUrl: (siteId: string, clipPath: string) =>
    `/api/sites/${siteId}/clips/${clipPath.split("/clips/")[1] ?? ""}`,
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
    req<Site>(`/admin/sites/${id}`, { method: "PUT", ...json(b) }),
  deleteSite: (id: string) => req<void>(`/admin/sites/${id}`, { method: "DELETE" }),
  importSites: () => req<AdminSites>("/admin/sites/import", { method: "POST" }),

  devices: () => req<AdminDevice[]>("/admin/devices"),
  createDevice: (b: { device_id: string; site_id: string }) =>
    req<AdminDeviceCreated>("/admin/devices", { method: "POST", ...json(b) }),
  deleteDevice: (id: number) => req<void>(`/admin/devices/${id}`, { method: "DELETE" }),

  getDeviceConfig: (id: number) => req<DeviceConfigState>(`/admin/devices/${id}/config`),
  setDeviceConfig: (id: number, config: DeviceConfig) =>
    req<DeviceConfigState>(`/admin/devices/${id}/config`, { method: "PUT", ...json(config) }),
};
