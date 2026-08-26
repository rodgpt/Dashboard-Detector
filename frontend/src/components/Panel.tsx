/**
 * A panel that cannot lie about its own state.
 *
 * Every data surface in the app goes through this, so the four states are drawn
 * the same way everywhere and no view can quietly invent a fifth:
 *
 *   loading   nothing yet, a request is out
 *   ok        data, fresh, with when it was loaded (R-7.2)
 *   stale     data, and the newest refresh failed — shown and marked (R-7.1)
 *   failed    nothing to show, and why
 *
 * `terminal` failures (403, or a rollup that is genuinely absent) get no retry
 * button, because retrying an access you do not have is a loop with no outcome.
 */
import type { ReactNode } from "react";
import type { Resource } from "@/hooks/useResource";
import { timeAgo } from "@/lib/time";

interface Props<T> {
  title: string;
  resource: Resource<T>;
  children: (data: T) => ReactNode;
  /** Shown when the source is absent — a 404 is data about the device, not a bug. */
  emptyMessage?: string;
  actions?: ReactNode;
}

export default function Panel<T>({ title, resource, children, emptyMessage, actions }: Props<T>) {
  const { data, error, loading, refreshing, lastLoadedAt, stale, failed, terminal, reload } = resource;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{title}</h2>
        <div className="panel-meta">
          {refreshing && <span className="panel-refreshing" aria-live="polite">actualizando…</span>}
          {lastLoadedAt && (
            <span className={stale ? "panel-age stale" : "panel-age"}>
              {stale ? "sin actualizar desde " : "actualizado "}
              <time dateTime={lastLoadedAt.toISOString()}>{timeAgo(lastLoadedAt)}</time>
            </span>
          )}
          {actions}
        </div>
      </div>

      {/* Stale: the data is real but it is not current, and that is the whole point. */}
      {stale && (
        <div className="panel-stale" role="alert">
          <span>
            No se pudo actualizar: {error?.message}. Los datos mostrados son los
            últimos válidos, no los actuales.
          </span>
          {!terminal && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={reload}>
              Reintentar
            </button>
          )}
        </div>
      )}

      {loading && <div className="loading">Cargando…</div>}

      {failed && (
        <div className="banner error" role="alert">
          <span>
            {error?.status === 404
              ? (emptyMessage ?? "Esta fuente no está publicada para este sitio.")
              : error?.isForbidden
                ? "No tienes permiso para ver esta información."
                : `No se pudo cargar: ${error?.message}`}
          </span>
          {!terminal && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={reload}>
              Reintentar
            </button>
          )}
        </div>
      )}

      {data !== null && children(data)}
    </section>
  );
}
