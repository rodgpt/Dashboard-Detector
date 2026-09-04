# Server infrastructure — dashboard

This app only. Ports, containers and the deployment shape.

Adapted from `lynchLocalDev` on one point: this deploys to a **client's Azure subscription**, not the home server. So there is no Cloudflare Tunnel in the deployment, no shared port registry, and no `SERVER-INFRASTRUCTURE.md` master file to reconcile against. Azure Container Apps terminates TLS at its own edge, which preserves the protocol's rule that we never run a reverse proxy for ingress or manage certificates ourselves.

> **A Cloudflare Tunnel does exist, as a bench rig, and is not the deployment shape.**
> `marfutura.buenalynch.com` fronts a developer machine so the bench Pi can be
> tested against a real hostname and real TLS without going to a coastline. It is
> a faithful analogue of production — public hostname, TLS terminated upstream,
> backend unaware — which is exactly why it is useful and exactly why it is easy
> to mistake for the architecture. **Nothing in the client's deployment depends on
> Cloudflare.** See *The bench tunnel* below.

Last updated 2026-08-22 (D-019, D-020).

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
                                          read for data; written for one thing only,
                                          sites/{id}/remote_config.json (D-020)

device
  -> https://<host>/api/devices/events    X-Device-Id / X-Device-Key, not a cookie
       -> backend -> db                   the low-latency event path (R-6.3, D-022)
```

The device reaches the same public ingress the browser does, on the device headers rather than a session cookie. **No inbound path to the device exists** and none is added by this: it polls for configuration and posts events, both outbound. That property is why an unattended node on a cellular link needs no port forwarding, no VPN and no static address.

The browser never reaches the backend directly and never reaches storage at all. Audio is proxied through `/api/sites/{site}/clips/...` so the storage container stays private (R-5.4, R-5.5).

Because nginx serves the app and proxies the API under one origin, the session cookie is same-origin. No CORS in production. The Vite dev server proxies `/api` the same way, so development matches.

---

## Volumes

| Volume | Holds | Loss means |
|---|---|---|
| `pgdata` | users, roles, site assignments, device credentials, tuned device configs | every account and every device key gone; re-provision the fleet |
| `pgdata` | the **derived** `detection_events` index (D-021) | a rebuild, not data loss — repopulate from the container (R-12.2) |

`pgdata` is the only stateful thing in the stack. Detections, clips and telemetry live in blob storage and are not this app's to lose.

**The index does not change that, and it is designed not to.** `detection_events` is a queryable copy of blobs that remain in storage, so dropping the volume costs a reconcile pass rather than a detection. That property is load-bearing: it is why the device keeps writing the event blob even though it also pushes to the API (D-022), and it is what stops Postgres becoming the sole record of a detonation — which would demand a backup and point-in-time-recovery regime this deployment does not have.

**The storage credential must be write-capable** as of D-020. The backend publishes `sites/{site_id}/remote_config.json` there; everything else it does with storage is read-only. A read-only credential will not fail at boot — it fails the first time somebody tunes a device, which is worth knowing before the first deploy.

**This volume is why the SQLite file was abandoned** (D-019, R-9.2). On a container host the writable filesystem is ephemeral; a database file inside the image or on the container's own disk disappears on the first restart, taking the fleet's credentials with it. A named volume — or a managed Postgres — is the fix.

---

## Deployment constraints

**One backend replica.** Not a cost choice, a correctness one, and there are now two reasons.

`backend/app/core/rate_limit.py` counts login failures in process memory, so a second replica makes the R-2.4 login throttle bypassable by reconnecting.

The reconcile timer (`services/scheduler.py`) also lives in the application process. Two replicas means two timers — *harmless*, because `index_event` is idempotent on `event_id` (R-12.3), but duplicated work. It adds no new constraint, since the throttle already pins this to one; it does mean lifting that pin later has to account for both. Moving the throttle counter to Postgres or Redis is not on its own enough.

**The reconcile pass runs in-process, on a timer** (R-12.4, D-022). Deliberately not a platform scheduler: an Azure Container Apps job or an EventBridge rule would be the cloud runtime dependency R-1.1 forbids — the same objection that removed Event Grid. `OCEANKIND_RECONCILE_INTERVAL_HOURS=0` disables it for a deployment driving the pass from outside; it is logged at warning level, because an index with no reconcile is a supported configuration but never an accidental one.

### Tuning the silence alert without drowning in notifications

Two rates, and conflating them is what produces a flood:

| | Setting | Default | Effect |
|---|---|---|---|
| how often we **look** | `SILENCE_CHECK_INTERVAL_MINUTES` | 5 min | none on volume — one small blob per site |
| how long before the **first** warning | `SILENCE_AFTER_MISSED_HEARTBEATS` × the device's `heartbeat_interval_s`, floored by `SILENCE_MIN_MINUTES` | 20 beats / 15 min floor | 20 min at a 60 s heartbeat |
| how often it **repeats** | `SILENCE_RENOTIFY_HOURS` | 24 h | **this is the anti-flood knob** |

The threshold is in *missed heartbeats* rather than minutes because `heartbeat_interval_s` is remotely tunable from 30 s to 3600 s: a fixed "one hour" would be 120 missed beats on one setting and less than one on another. The floor stops a fast heartbeat making the system twitchy.

One `DeviceAlert` row per outage is what holds the line. The check may run 288 times a day; a unit down for a week produces **7 messages, not 2,016**. Set `SILENCE_RENOTIFY_HOURS=0` for exactly one message per outage and no repeats.

**If warnings are arriving too eagerly** — a flaky cellular link resolving itself — raise `SILENCE_AFTER_MISSED_HEARTBEATS`. Do not raise the check interval; that only delays noticing, it does not reduce messages.

**Health probe** is `GET /api/health` on the backend and `GET /` on the frontend. Neither requires authentication and neither returns data.

**Secrets** come from the environment and nothing else (R-1.3). Required at boot or the backend refuses to start (R-4.3):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection |
| `OCEANKIND_SESSION_SECRET` | signs session cookies |
| `OCEANKIND_CONFIG_HMAC_KEY` | signs device configuration (R-6.2). Missing = tuning is refused with 503; never persisted-but-unpublished, never published unsigned. The same key goes to each device's `/etc/oceankind.env` |
| `OCEANKIND_AZURE_CONNECTION_STRING` | storage, when `STORAGE_BACKEND=azure` |
| `OCEANKIND_COOKIE_SECURE` | `true` in production. `false` only for local http |
| `OCEANKIND_RECONCILE_INTERVAL_HOURS` | How often the index is checked against storage. Default 24. `0` disables the in-process timer |
| `OCEANKIND_RECONCILE_WINDOW_DAYS` | How far back each pass looks. Default 14. **A commitment, not a knob**: events from a device offline longer than this are lost silently (R-12.4) |
| `OCEANKIND_SILENCE_ALERTS_ENABLED` | Device-silence alerting on/off. Default true |
| `OCEANKIND_SILENCE_CHECK_INTERVAL_MINUTES` | How often we **look**. Default 5. Does not affect how often anyone is told |
| `OCEANKIND_SILENCE_AFTER_MISSED_HEARTBEATS` | Missed heartbeats before the **first** warning. Default 20 |
| `OCEANKIND_SILENCE_MIN_MINUTES` | Floor under that threshold. Default 15 |
| `OCEANKIND_SILENCE_RENOTIFY_HOURS` | **Anti-flood.** How often a still-down unit is mentioned again. Default 24. `0` = once per outage, never repeated |
| `OCEANKIND_SILENCE_WEBHOOK_URL` | Where a notification goes. Empty = log only |

**No cloud-specific runtime.** Azure Container Apps today because the storage is there. The stack is three ordinary containers and moves to any host that runs them (R-1.1).

---

## The bench tunnel (test rig, not deployment)

The device path is the reason this exists. A LAN test proves the uploader's logic and skips the entire transport: plain HTTP to a raw IP on a trusted network, versus HTTPS to a hostname through a public ingress. What that skips is DNS, TLS, certificate validation and ingress behaviour — and, most importantly, **the device's clock**. A Pi with no RTC that boots with a wrong date fails certificate validation outright, and the error looks nothing like a networking problem. Better found at a bench than on a coastline.

**Point the tunnel at the `frontend` container, not the backend.**

```
cloudflared  ->  http://localhost:3000        (frontend / nginx)
                   /       -> the built app
                   /api/   -> proxy_pass http://backend:8000
```

One hostname serving both, exactly as production does. Pointing it at the backend instead would expose the API with no app in front of it and break the same-origin session cookie, which is the whole reason nginx owns both paths.

The device then posts to `https://marfutura.buenalynch.com/api/devices/events` — through nginx, on `X-Device-Id`/`X-Device-Key` headers rather than a cookie.

`OCEANKIND_COOKIE_SECURE=true` becomes both possible and correct once TLS is in front. **Consequence:** the session cookie is no longer set over plain http, so `http://localhost:3000` can no longer log in. Use the tunnel hostname for everything while it is up, or set the flag back to `false` to work offline.

### Going public changes the threat model

This rig makes a development instance reachable from the internet, with fixture data and whatever accounts the database happens to hold. Two things that are acceptable on a LAN are not acceptable on a public hostname:

- **Any weak account is now exposed.** There is no password-change route in the API (`admin.py` creates and deletes users; it does not update passwords), and `init_db` only bootstraps when the user table is *empty* — so editing `OCEANKIND_BOOTSTRAP_ADMIN_PASSWORD` does nothing to an account that already exists. To rotate: create a second administrator with a strong password, log in as that one, delete the first.
- **The device routes are not throttled.** `/api/auth/login` is (R-2.4, five failures per five minutes) precisely because argon2 verification is deliberately expensive. `/api/devices/events` and `/api/devices/config` do the same argon2 work on `X-Device-Key` with no limit. An unknown `device_id` is cheap — it fails the lookup before hashing — but a *known* one with a wrong key is not, and device ids are guessable (`Rpi_bench`). Worth a throttle before this is exposed for any length of time.

---

## Local development

```bash
make dev        # fixtures + db + backend + frontend
```

| | |
|---|---|
| app | http://localhost:3000 |
| backend direct (debugging only) | `http://localhost:${BACKEND_PORT}/api/health` — **check `.env`, it is not always 8000** |
| database | `docker compose exec db psql -U oceankind oceankind` |

**The host port is a variable, and on at least one dev machine it has to be.** `BACKEND_PORT` only affects the host publish; inside the compose network the backend is always `backend:8000` and nginx proxies to that. If another project on the machine already holds the port, `docker compose up` fails with `Bind for 127.0.0.1:<port> failed` — a line that is easy to miss, after which the API appears to 404 because the *other* service is answering on that port. If a route you just added returns 404, check what is actually listening before you debug the route:

```bash
docker ps --format '{{.Names}}\t{{.Ports}}' | grep <port>
```

Talk to the app on 3000, not 8000. Hitting the backend directly bypasses nginx, which means a different origin and a session cookie that will not behave the way it does in production.
