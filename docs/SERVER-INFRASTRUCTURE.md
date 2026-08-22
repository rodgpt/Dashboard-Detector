# Server infrastructure — dashboard

This app only. Ports, containers and the deployment shape.

Adapted from `lynchLocalDev` on one point: this deploys to a **client's Azure subscription**, not the home server. So there is no Cloudflare Tunnel, no shared port registry, and no `SERVER-INFRASTRUCTURE.md` master file to reconcile against. Azure Container Apps terminates TLS at its own edge, which preserves the protocol's rule that we never run a reverse proxy for ingress or manage certificates ourselves.

Last updated 2026-08-21 (D-019).

---

## Containers

| Service | Image | Internal | Host (dev) | Exposed publicly |
|---|---|---|---|---|
| `db` | `postgres:16-alpine` | 5432 | none | never |
| `backend` | built from `backend/` | 8000 | `${BACKEND_PORT:-8000}` | never — only through `frontend` |
| `frontend` | built from `frontend/` | 80 | `${FRONTEND_PORT:-3000}` | yes, this is the app |

`db` publishes no host port. Reach it with `docker compose exec db psql`.

In production only `frontend` is reachable. The backend is an internal service on the compose network; nginx proxies `/api/` to `http://backend:8000`.

---

## Traffic

```
browser
  -> https://<host>                      TLS terminated by the platform edge
  -> frontend container (nginx :80)
       /            -> static Vite build, SPA fallback to index.html
       /api/        -> proxy_pass http://backend:8000
  -> backend (FastAPI :8000)
       -> db (postgres :5432)            internal only
       -> blob storage                   credential held here and nowhere else
```

The browser never reaches the backend directly and never reaches storage at all. Audio is proxied through `/api/sites/{site}/clips/...` so the storage container stays private (R-5.4, R-5.5).

Because nginx serves the app and proxies the API under one origin, the session cookie is same-origin. No CORS in production. The Vite dev server proxies `/api` the same way, so development matches.

---

## Volumes

| Volume | Holds | Loss means |
|---|---|---|
| `pgdata` | users, roles, site assignments, device credentials, tuned device configs | every account and every device key gone; re-provision the fleet |

`pgdata` is the only stateful thing in the stack. Detections, clips and telemetry live in blob storage and are not this app's to lose.

**This volume is why the SQLite file was abandoned** (D-019, R-9.2). On a container host the writable filesystem is ephemeral; a database file inside the image or on the container's own disk disappears on the first restart, taking the fleet's credentials with it. A named volume — or a managed Postgres — is the fix.

---

## Deployment constraints

**One backend replica.** Not a cost choice, a correctness one. `backend/app/core/rate_limit.py` counts login failures in process memory, so a second replica makes the R-2.4 login throttle bypassable by reconnecting. Moving the counter to Postgres or Redis is what lifts this restriction; until then, one replica.

**Health probe** is `GET /api/health` on the backend and `GET /` on the frontend. Neither requires authentication and neither returns data.

**Secrets** come from the environment and nothing else (R-1.3). Required at boot or the backend refuses to start (R-4.3):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection |
| `OCEANKIND_SESSION_SECRET` | signs session cookies |
| `OCEANKIND_CONFIG_HMAC_KEY` | signs device configuration (R-6.2). Missing = `/api/devices/config` returns 503, never an unsigned payload |
| `OCEANKIND_AZURE_CONNECTION_STRING` | storage, when `STORAGE_BACKEND=azure` |
| `OCEANKIND_COOKIE_SECURE` | `true` in production. `false` only for local http |

**No cloud-specific runtime.** Azure Container Apps today because the storage is there. The stack is three ordinary containers and moves to any host that runs them (R-1.1).

---

## Local development

```bash
make dev        # fixtures + db + backend + frontend
```

| | |
|---|---|
| app | http://localhost:3000 |
| backend direct (debugging only) | http://localhost:8000/api/health |
| database | `docker compose exec db psql -U oceankind oceankind` |

Talk to the app on 3000, not 8000. Hitting the backend directly bypasses nginx, which means a different origin and a session cookie that will not behave the way it does in production.
