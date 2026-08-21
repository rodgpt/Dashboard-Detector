# CLAUDE.md — OceanKind Dashboard

Rules for working in this repository. Lynch Protocol **`lynchLocalDev`** variant — full-stack: separate backend and frontend containers, a database container, and a real build pipeline.

Adapted on one point: deployment targets a client's Azure subscription, not the home server, so there is no Cloudflare Tunnel and no shared port registry. `docs/SERVER-INFRASTRUCTURE.md` covers this app only.

> **Read D-019 before proposing any structural change.** This repository spent its first phases scaffolded on `lyncHtmlDev` — the *static site* variant — with a backend bolted on. The result was a FastAPI app serving a single 3,129-line HTML file, no frontend/backend divide, and a deployable image that contained no frontend at all. If a rule here looks like it came from a static-site project, check D-019 before obeying it.

Self-contained. Everything referenced here is in this repository.

---

## Before ANY task

1. **`REQUIREMENTS.md`** — what this must do. Numbered, testable. The spec
2. **`docs/DATA-CONTRACT.md`** — the exact shape of everything the device writes and the backend reads. **Read before touching any storage or render path.** Every numeric field can be `null`. Canonical copy lives in `Rpi-Detector`; `make contract` checks the match
3. **`docs/API-CONTRACT.md`** — the backend-to-browser contract. Read before adding a route or a fetch
4. **`docs/PROGRESS.md`** — what's built, what phase the work is in
5. **`docs/TODO.md`** — known issues outside the roadmap
6. **`docs/STYLEGUIDE.md`** — palette, components. Consistency is not negotiable
7. **`docs/SERVER-INFRASTRUCTURE.md`** — ports, containers, deployment shape. **Read before any Docker, networking or deployment decision**
8. **`DECISIONS.md`** — why things are the way they are. **D-019 first**

If your change assumes a field the device might not produce yet, check [`Rpi-Detector/raspberry-pi/docs/PROGRESS.md`](https://github.com/rodgpt/Rpi-Detector/blob/main/raspberry-pi/docs/PROGRESS.md) before building against it.

---

## The premise

This is the only window anyone has into a system sitting on a coastline that nobody can visit. When the dashboard is wrong, nothing else tells them. Being visibly broken always beats being quietly stale.

We build the plumbing, not the detection science. Nothing here decides what counts as a detection.

---

## Shape

Three containers. The browser talks only to nginx; nginx proxies `/api/` to the backend over the compose network. Postgres holds users, roles, site assignments and device records; detections stay in blob storage.

```
db          postgres:16-alpine, pgdata volume. never exposed to the host
backend     FastAPI, :8000. serves JSON only — no HTML, no static assets
frontend    vite build -> nginx:alpine, :80. serves the app, proxies /api/
```

```
backend/app/core/       config, database, models, security, rate_limit
backend/app/routers/    auth, admin, data, devices
backend/app/services/   storage (the portability seam), events (pagination),
                        deviceconfig (clamping + HMAC signing)
backend/alembic/        migrations. schema changes never happen by hand
frontend/src/api/       client.ts — the only thing that talks to the backend
frontend/src/pages/     one per route: Login, Admin, Detections, Acoustic, …
frontend/src/components/ shared UI
```

**The backend serves no HTML.** If you find yourself adding `StaticFiles` or a
`FileResponse` to a router, stop — that is the old shape reasserting itself.

---

## Hard rules

**Portable by construction.** No cloud provider's identity service, no cloud-specific runtime, no configuration service. Azure today because that is where the storage is. Moving to S3 is one new class in `services/storage.py` and an environment variable. Anything that breaks that is a decision, not an implementation detail.

**All storage access goes through `Storage`.** Never import an Azure SDK outside `services/storage.py`. That file is the entire cost of changing provider, and it stays that way.

**The browser never holds a credential.** No storage key, no SAS token, no connection string reaches the client, ever. Audio is proxied through the API. The container stays private.

**Every route is authenticated and site-scoped.** `/api/health` and `/api/auth/login` are the only exceptions and neither returns data. Site permission is checked per request, on the server, not by hiding links in the interface.

**Refuse to start rather than fall back.** A missing required secret raises at boot. A default value in place of a secret is exactly how a live Twilio token reached source, a backup, two bytecode caches and a git remote.

**Never log a secret**, not even at debug level, not even truncated.

**The client never writes to storage.** No writes of any kind, and no write-capable credential anywhere in the frontend. A dead `SAS_URL_KEY` constant in the v1 page is the basis of a false claim in a published audit. Delete it rather than implement it.

**A failed fetch must look failed.** Never render stale data as current. Every source can be missing, malformed or cached. Show the failure and show when the data was last good. One dead source never takes the page down.

**Guard every `JSON.parse`.** One unguarded parse of `Infinity` blanked this dashboard in production. Degrade to a visible error, never an empty page.

**Every numeric field can be `null`.** Not zero, not absent. Null. The backend passes nulls through unchanged; it does not coerce them.

**Device blobs pass through untouched.** No `response_model` over them. FastAPI would drop unknown fields, and a field the device adds must reach the browser and be surfaced, not silently eaten. `DATA-CONTRACT.md` is their only schema.

**Gaps in `power_history` are data.** Absent buckets are how outages are detected. Never interpolate, backfill or densify — not in the backend, not in the chart.

**Suppressed detections are shown, not hidden.** A cooldown withholds a notification; it does not make the event less real. Any filter that hides events must be visible in the UI.

**Don't break `?play=`.** Links in people's WhatsApp history point at v1 blob names and must keep resolving through the v2 path change.

**Coordinates are sensitive.** They locate unattended hardware in a remote place, and the threat model includes the people the system detects. Do not widen their exposure.

**No hardcoded site list.** Sites come from `_sites.json`, filtered by permission. Adding a unit is a data change.

**401 and 403 are different.** 401 means log in. 403 means you are logged in and may not see this. Conflating them logs a user out every time they open a site they do not have.

---

## Working with data

Develop against fixtures. No cloud account, no device, no detection science:

```bash
make dev            # fixtures + db + backend + frontend, all three up
make rebuild        # after backend dependency or Dockerfile changes
make test           # backend tests
make migrate m="…"  # generate an Alembic revision. never edit the schema by hand
make openapi types  # regenerate the schema and the frontend types
make contract       # DATA-CONTRACT.md still matches the canonical copy
```

Use the Makefile targets, not raw `docker compose`, unless the Makefile does not
cover the case.

The fixtures deliberately include the awkward cases: a degraded site, suppressed detections, failed uploads, a multi-hour telemetry gap, null-valued fields, and forecast data past the observation boundary. If a change works against fixtures it works against production.

Bandwidth is a hard constraint. The backend exists partly so the browser stops downloading the whole history every thirty seconds (F-18). Keep pagination, time windowing and conditional requests in `backend/app/services/events.py` and `frontend/src/api/client.ts`, one place each.

Assume more than one site, always.

---

## Language

The interface is Spanish. Tab identifiers, labels, user-facing strings, and the existing code comments. Keep it that way. Documentation and code identifiers are English.

---

## Testing

Backend: `make test`. Every access rule that matters has a test that asserts an operator gets 403 for a site they do not have. Add to it rather than around it.

Frontend: open it in a browser. Test with the network throttled and with each source unreachable in turn. Those are field conditions on a cellular-connected device, not edge cases.

Test `?play=` against a clip that does not exist. That happens whenever an upload failed after a notification was sent, which is a known device-side defect.

---

## After completing a feature

1. **`docs/DATA-CONTRACT.md`** if your change assumes anything new about what the device writes. Not optional, and the canonical copy lives in `Rpi-Detector` so both must match
2. **`docs/API-CONTRACT.md`** and `make openapi types` if you added, removed or changed a route
3. **`docs/PROGRESS.md`** — check items off
4. **`docs/TODO.md`** — add what you found, check off what you fixed
5. **`docs/STYLEGUIDE.md`** if a new colour, component or pattern appeared
6. **`docs/SERVER-INFRASTRUCTURE.md`** if ports, containers or the deployment shape changed
7. **`REQUIREMENTS.md`** if the spec itself changed, which should be rare and deliberate
8. **`README.md`** if the data sources or the run instructions changed

Do it before considering anything done. Context gets compressed, sessions end, the docs are what survives.

**Do not run git commands** unless explicitly asked.
