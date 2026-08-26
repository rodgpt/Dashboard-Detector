/**
 * A unit's health, at a glance, without opening a tab (R-7.4).
 *
 * Reads the `health` block from `status.json` defensively: the contract says a
 * consumer must tolerate more health fields than it knows, and every numeric
 * field may be null. Null is not false and it is not zero — a device that has
 * not reported `detector_ok` is *unknown*, which is its own state and must not
 * be drawn as healthy.
 *
 * Colour is never the only signal: each state carries a word and a shape.
 */
import { isStale, timeAgo } from "@/lib/time";

export type HealthState = "ok" | "degraded" | "unknown" | "offline";

interface Health {
  detector_ok?: boolean | null;
  audio_ok?: boolean | null;
  duty_cycle_pct?: number | null;
  degraded_reason?: string | null;
}

export function readHealth(status: Record<string, unknown> | null): {
  state: HealthState; reason: string | null; lastSeen: string | null;
} {
  if (!status) return { state: "unknown", reason: null, lastSeen: null };

  const lastSeen = typeof status.last_seen === "string" ? status.last_seen : null;
  const health = (status.health ?? {}) as Health;

  // Liveness first: a unit that stopped reporting is offline whatever its last
  // heartbeat claimed about itself.
  if (lastSeen && isStale(lastSeen)) {
    return { state: "offline", reason: `sin contacto ${timeAgo(lastSeen)}`, lastSeen };
  }

  const failing: string[] = [];
  if (health.detector_ok === false) failing.push("detector caído");
  if (health.audio_ok === false) failing.push("audio sin señal");
  if (typeof health.duty_cycle_pct === "number" && health.duty_cycle_pct < 90) {
    failing.push(`ciclo de trabajo ${health.duty_cycle_pct.toFixed(1)}%`);
  }
  if (health.degraded_reason) failing.push(health.degraded_reason);
  if (failing.length) {
    return { state: "degraded", reason: failing.join("; "), lastSeen };
  }

  // No health surface at all is unknown, never "ok". Absence of evidence.
  if (health.detector_ok == null && health.audio_ok == null) {
    return { state: "unknown", reason: "el equipo no publica estado de salud", lastSeen };
  }
  return { state: "ok", reason: null, lastSeen };
}

const LABEL: Record<HealthState, string> = {
  ok: "operativo",
  degraded: "degradado",
  unknown: "desconocido",
  offline: "sin contacto",
};

const MARK: Record<HealthState, string> = {
  ok: "●", degraded: "▲", unknown: "?", offline: "■",
};

export default function HealthBadge({ status }: { status: Record<string, unknown> | null }) {
  const { state, reason } = readHealth(status);
  return (
    <span className={`health-badge ${state}`} title={reason ?? undefined}>
      <span className="health-mark" aria-hidden="true">{MARK[state]}</span>
      {LABEL[state]}
      {reason && <span className="health-reason">{reason}</span>}
    </span>
  );
}
