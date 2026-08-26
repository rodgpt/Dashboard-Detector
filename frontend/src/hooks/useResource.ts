/**
 * One fetch, with the failure rules attached.
 *
 * Every panel in this app polls a source that can be missing, malformed, slow or
 * gone. R-7.1 to R-7.3 say what must happen when it is, and those rules are the
 * same for all of them, so they live here once rather than in five views:
 *
 *  - A failed refresh **never** erases what was last good. It marks it stale and
 *    says when it was good, because blanking the panel hides the outage and
 *    silently redrawing old numbers as current is worse still.
 *  - A source that has never loaded reports failed, not empty.
 *  - Each resource fails alone. One dead rollup does not touch the others.
 *  - 401 is not an error to display — the session is gone and the app leaves.
 *  - 403 is terminal for this resource: retrying an access you do not have just
 *    produces a retry loop with no outcome.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/api/client";

export interface Resource<T> {
  /** Last good value. Survives a failed refresh, by design. */
  data: T | null;
  /** Why the most recent attempt failed. Null when the last attempt succeeded. */
  error: ApiError | null;
  /** A request is in flight and there is nothing to show yet. */
  loading: boolean;
  /** A request is in flight over data we already have. */
  refreshing: boolean;
  /** When `data` was last known good. Null until the first success (R-7.2). */
  lastLoadedAt: Date | null;
  /** We have data, and the newest attempt failed. Show it, marked. */
  stale: boolean;
  /** Nothing to show and the last attempt failed. */
  failed: boolean;
  /** Retrying will not help: 403, or a 404 that means the blob is not there. */
  terminal: boolean;
  reload: () => void;
}

interface Options {
  /** Poll interval in ms. Omit for one-shot. */
  pollMs?: number;
  /** Skip fetching entirely, e.g. before a site is chosen. */
  enabled?: boolean;
  /** Called on 401 so the app can leave for the login page. */
  onUnauthenticated?: () => void;
}

export function useResource<T>(
  fetcher: () => Promise<T>,
  deps: unknown[],
  { pollMs, enabled = true, onUnauthenticated }: Options = {},
): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [lastLoadedAt, setLastLoadedAt] = useState<Date | null>(null);
  const [inFlight, setInFlight] = useState(false);

  // Kept in refs so the effect below does not re-subscribe on every render.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const onUnauthRef = useRef(onUnauthenticated);
  onUnauthRef.current = onUnauthenticated;

  /** Guards against a slow response from a previous site overwriting a newer
   *  one. Without this, switching sites twice quickly can leave the second
   *  site's panel showing the first site's data, which is the worst kind of
   *  wrong: plausible and unmarked. */
  const generation = useRef(0);

  const run = useCallback(async () => {
    const mine = ++generation.current;
    setInFlight(true);
    try {
      const value = await fetcherRef.current();
      if (mine !== generation.current) return;
      setData(value);
      setError(null);
      setLastLoadedAt(new Date());
    } catch (err) {
      if (mine !== generation.current) return;
      const apiErr = err instanceof ApiError ? err : new ApiError(0, String(err));
      if (apiErr.isAuth) { onUnauthRef.current?.(); return; }
      // data and lastLoadedAt are deliberately left alone
      setError(apiErr);
    } finally {
      if (mine === generation.current) setInFlight(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    // A dependency change means a different subject. Drop the old value rather
    // than showing site A's numbers under site B's heading.
    generation.current++;
    setData(null);
    setError(null);
    setLastLoadedAt(null);
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, ...deps]);

  useEffect(() => {
    if (!enabled || !pollMs) return;
    const id = setInterval(() => { void run(); }, pollMs);
    return () => clearInterval(id);
  }, [enabled, pollMs, run]);

  const terminal = !!error && (error.isForbidden || error.status === 404);

  return {
    data, error, lastLoadedAt,
    loading: inFlight && data === null && error === null,
    refreshing: inFlight && data !== null,
    stale: data !== null && error !== null,
    failed: data === null && error !== null,
    terminal,
    reload: () => { void run(); },
  };
}
