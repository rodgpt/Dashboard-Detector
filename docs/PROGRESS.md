# Implementation progress — dashboard

Phased build plan. Each phase produces something runnable. Phase numbers are shared with the device: Phase 4 means the same thing in both repositories.

Requirement IDs refer to `../REQUIREMENTS.md`. Defect IDs refer to the register in `Rpi-Detector/docs/FINDINGS.md`.

Develop against fixtures throughout: `make dev`.

---

## Current status

**Phase 0 complete.** Repository self-contained, fixtures generate, local loop works.
**Phase 1 complete as backend logic.** Auth, roles, site scoping, device credentials and signed device config are built and tested. 25 backend tests pass. None of that work is affected by the restructure below.
**Phase 1R complete — the structural correction (D-019).** This repository was scaffolded on `lyncHtmlDev`, the static-site protocol variant, and grew a backend inside it. There was no backend/frontend divide: the "frontend" was a folder of files bind-mounted into the API container, and the deployable image contained no frontend at all. Rebuilt on `lynchLocalDev`: three containers, React + Vite, Postgres + Alembic. Done 2026-08-21.
**Azure access not granted for the client's account.** A sandbox subscription of our own is available for an end-to-end test; see Phase 4.

`web/` is now **superseded reference material only** — nothing in it runs or is served (see `web/README.md`). `web/static/index.html`, the client's 3,129-line v2 dashboard, is kept solely as the source for Phase 2, which rebuilds its five views as React pages. It is **deleted, not split**, once the last view leaves it.

---

## Phase 0: Workable repository **COMPLETE**

- [x] Repository self-contained
- [x] `REQUIREMENTS.md` rewritten around the contracted scope: auth, users, a backend we own
- [x] `docs/DATA-CONTRACT.md` mirrored from the canonical copy, `make contract` enforces it
- [x] Fixture generator producing a full v2 tree with real audio, one site degraded on purpose
- [x] One-command local loop, no cloud account

---

## Phase 1: The backend **SUBSTANTIALLY COMPLETE**

Everything the presupuesto promises that a static page structurally cannot do. No cloud account needed; the local storage backend reads fixtures.

### Built
- [x] FastAPI in one container, no cloud identity, no cloud runtime (R-1.1, R-1.4)
- [x] `Storage` interface with local and Azure implementations, swapped by environment variable. S3 is one new class (R-1.2)
- [x] All configuration from the environment; refuses to start on a missing secret (R-1.3, R-4.3)
- [x] Login, logout, me. Argon2 passwords, signed expiring session cookie, throttled login (R-2.1 to R-2.5)
- [x] Users, roles and site assignments in the database; admin API to manage them (R-3.1 to R-3.3, R-9.2). SQLite at the time; Postgres since Phase 1R
- [x] Every data route site-scoped server-side, with a test asserting 403 across sites (R-3.4)
- [x] First-administrator bootstrap for a fresh deployment (R-3.5)
- [x] Secrets held server-side only; none reachable from the browser (R-4.1, R-4.2)
- [x] Paginated, filtered detections resolved by date-partitioned prefix listing (R-5.1, R-5.2)
- [x] Rollups and clip proxying, so the container can be private (R-5.3, R-5.4, R-5.5)
- [x] Malformed and unknown-version blobs surfaced, not swallowed, and never a 500 (R-5.6)
- [x] Typed client, compiling clean. Now `frontend/src/api/client.ts`
- [x] `docs/API-CONTRACT.md` plus generated `openapi.json` and `frontend/src/api/generated.ts` (R-9.5)
- [x] v1 compatibility layer: reads the live v1 container, returns v2 shapes, removable with `make drop-v1` (R-11, D-016)
- [x] Login screen at `/login` and administration screen at `/admin` (R-3.3). Spanish, no
      framework, everything through the typed client. 401 redirects to login, 403 shows a
      permission message, never conflated. Sites come from the API, never a hardcoded list.
      Rebuilt as React pages in Phase 1R; the palette now lives in `frontend/src/styles.css`

- [x] Per-device credential issuance in the admin panel (R-6.1, D-017). Key generated
      server-side, shown once at creation, stored argon2-hashed, never readable again.
      `last_seen` stamped on every device authentication so provisioning failures are
      visible in the panel. Delete = revocation; the unit keeps its last valid config
      (2026-08-13)

- [x] Signed, clamped device configuration (R-6.2). `GET /api/devices/config` serves the
      DATA-CONTRACT payload: tuned values from the database, clamped server-side before signing,
      hex HMAC-SHA256 over the canonical JSON, monotonic `config_version`, 24 h refresh
      window. Tuning is `PUT /api/admin/devices/{id}/config` plus a "Configurar" editor in
      the panel; out-of-range values are clamped and reported, inverted PSD bands and enum
      typos rejected. Missing signing key = `503`, never an unsigned payload. This is the
      replacement path for F-10; the finding closes when the device stops reading
      `remote_config.json`, which is device-repo Phase 2 work (2026-08-18)

### Open
- [ ] Conditional requests, `ETag` on rollups (R-5.7)
- [ ] Types generated from `DATA-CONTRACT.md` so device fields are checked too. See `TODO.md`

**Done when:** a fresh deployment can be logged into, an operator sees only their sites on every endpoint, and no secret exists anywhere the browser can reach.

---

## Phase 1R: The backend/frontend divide **COMPLETE**

The structural correction from D-019. No features change. When this lands, the repository has the shape it should have had at scaffold time.

- [x] `api/` becomes `backend/`, matching the `lynchLocalDev` scaffold layout
- [x] `core/db.py` becomes `core/database.py`; `core/ratelimit.py` becomes `core/rate_limit.py`
- [x] Postgres replaces the SQLite file. `db` service, `pgdata` named volume, no host port
- [x] Alembic wired, initial revision generated from the models. No hand-edited schema, ever
- [x] `frontend/` created: Vite + React 18 + TypeScript, its own `Dockerfile`, `nginx.conf` proxying `/api/` to `backend:8000`
- [x] `web/src/api.ts` becomes `frontend/src/api/client.ts`, unchanged in substance
- [x] Login ported to `frontend/src/pages/Login.tsx`
- [x] Admin ported to `frontend/src/pages/Admin/` — users, devices, device config editor
- [x] Backend stops serving HTML: `StaticFiles`, the SPA fallback and `WEB_DIR` all deleted from `main.py`
- [x] `docker-compose.yml` becomes three services; Makefile gains `rebuild` and `migrate`
- [x] 25 backend tests still green against Postgres
- [x] Dead light-theme CSS layer dropped; the dark `--mf-*` palette becomes the token set (see `STYLEGUIDE.md`)

**Done when:** `make dev` brings up three containers, the app answers on :3000 through nginx, the backend serves no HTML, and the frontend image contains the built app — verifiable by running it with the backend stopped.

---

## Phase 2: The five views, in React **NOT STARTED**

The client's five views are rebuilt as React pages reading the API. The 3,129-line monolith is deleted when the last view leaves it. No new features — this is the same product, correctly built.

The largest single piece of remaining work, ~20–30 h. That is the honest cost of the wrong scaffold (D-019), and it is recorded rather than buried.

- [ ] `pages/Detections.tsx` — paginated events endpoint, not `manifest.json` (F-18)
- [ ] `pages/Acoustic.tsx`, `pages/Ocean.tsx`, `pages/Analysis.tsx`, `pages/SensorStatus.tsx`
- [ ] `components/PowerChart.tsx` on `react-chartjs-2`, replacing the CDN Chart.js tags
- [ ] `components/SiteMap.tsx` on `react-leaflet`, replacing the CDN Leaflet tags
- [ ] `components/AudioPlayer.tsx` — clips proxied through the API, and `?play=` deep links still resolve (R-8.5)
- [ ] Spectrogram canvas ported, with a text alternative this time (A11y)
- [ ] Sites from `GET /api/sites`; the hardcoded `SITES` table dies with the monolith
- [ ] The v2 event schema surfaced: `captured_utc` not upload time, `event_type`, `detector`, `score`, `suppressed`, `clip.*` (R-8.2 to R-8.4)
- [ ] Grouped `status.json` consumed: `health`, `detection`, `audio`, `power`, `network`, `system`
- [ ] Unknown `schema_version` renders a visible warning, never a blank page
- [ ] Every numeric field tolerates `null`; no `JSON.parse` without a guard
- [ ] No storage URL anywhere in the frontend. The dead `SAS_URL_KEY` constant goes with the file (X-01)
- [ ] `web/` deleted

**Done when:** the whole interface runs against `make dev` with no storage credential in the browser, and `web/static/index.html` no longer exists.

---

## Phase 3: Make failure visible **NOT STARTED**

The monitoring tool must be honest about its own state. This is the half of the contract that is about trust rather than features.

- [ ] `health` surfaced at site-picker level: a degraded unit is obvious without opening a tab (R-7.4)
- [ ] Per-panel "last loaded" timestamp (R-7.2)
- [ ] Every failed fetch visibly failed, with retry (R-7.1)
- [ ] Each source fails independently; one 404 never takes the page down (R-7.3)
- [ ] Suppressed detections shown and marked, never hidden (R-8.2)
- [ ] `vessel`, `blast` and `unknown` visually distinct (R-8.3)
- [ ] Missing and failed-upload clips handled distinctly (F-13)
- [ ] Power history gaps preserved, never interpolated (R-8.6)
- [ ] Accessibility pass, colour never the only signal (R-8.8)

**Done when:** deleting any single fixture file leaves the rest working and the affected panel explaining itself. The Matanzas fixture ships degraded on purpose; it should be obvious at a glance.

---

## Phase 4: Contract cutover and multi-site **BLOCKED — needs Azure access**

Ships simultaneously with the device's Phase 4. Not before, not after.

- [ ] Azure storage backend exercised against a real account
- [ ] Container made private; scoped credential held by the backend only (R-5.5, F-07)
- [ ] Site selector across every tab, map renders every site with health colour
- [ ] Detection list carries a site column and filter
- [ ] v1 `?play=` deep links still resolve after the path change (R-8.5)
- [ ] Bandwidth measured: an hour with the dashboard open transfers under 50 MB (F-18)
- [ ] **`make drop-v1`** once the units write v2, then delete R-11 from `REQUIREMENTS.md`

---

## Phase 5: Deployment **NOT STARTED**

### Blockers found 2026-08-21, before any deploy is attempted

These were found by inspecting the image and the storage seam rather than by deploying. Each one makes a deployment either fail or be quietly useless.

- [ ] **The image ships no frontend.** `api/Dockerfile` copies `app/` only; the compiled interface reaches the running container purely through the `./web/dist:/web:ro` mount in `docker-compose.yml`. `main.py` guards the static routes with `if WEB_DIR.is_dir()`, which is false in the image, so a deployed container serves the API and returns 404 for `/`, `/login` and `/admin`. Needs a multi-stage build (node compile then copy) or a copy of a prebuilt `dist`
- [ ] **`_sites.json` has no author outside fixtures.** Only `tools/generate_fixtures.py` writes it. A fresh private container has no site registry, so `GET /api/sites` returns empty, the dashboard shows nothing, and `POST /api/admin/devices` rejects every device with "unknown site (known: none)". Seed it as a provisioning step, or give it a writer. Sites are data (R-3.1), so a hardcoded fallback is not the answer
- [ ] **SQLite sits on an ephemeral filesystem.** `sqlite:////data/oceankind.db` survives locally because `./data` is a bind mount. On Azure Container Apps (and most container hosts) the filesystem is ephemeral, so every restart or scale event destroys users, device credentials and tuned device configs. Decide: Azure Files volume, or Postgres by connection string (R-9.2 allows either)
- [ ] **Single replica is a correctness requirement, not a cost choice.** `core/ratelimit.py` counts login failures in process memory and says so in its own docstring; two replicas means the R-2.4 throttle is bypassable by reconnecting. SQLite imposes the same limit. Pin to one replica and write down why
- [ ] **`get_storage()` builds a new client per request.** It is not cached, so the Azure backend constructs a fresh `ContainerClient` — new HTTP pipeline, re-parsed credential — on every single request. Free with `LocalStorage`, expensive against a real account. Cache it per process alongside `settings()`
- [ ] **No timeout on storage calls.** A hung blob read hangs the request with nothing to bound it

### Then

- [ ] Deployment documented for a container host, with the Azure and the not-Azure path both written down (R-1.1)
- [ ] GitHub Actions: backend tests, frontend compile, `make contract` (R-10.1)
- [ ] Session secret and storage credential rotation procedure
- [ ] Handover. **We do not deploy; the client does** (D-015). A test deployment in our own subscription is not handover and does not change that

---

## Continuous

- [ ] `docs/DATA-CONTRACT.md` stays identical to the canonical copy (R-10.1). `make contract` locally, Actions once Phase 5 sets it up
- [ ] `make openapi types` re-run in the same change as any route change (R-10.2)
- [ ] Palette lifted into CSS custom properties before Phase 3 multiplies the component count
- [ ] The two near-duplicate status components merged into one

---

## Blocked on the client

Three fields the interface renders that nothing produces: `ram_total_mb`, `ram_used_mb`, `deg`. The acoustic aggregator that turns per-clip values into medians and quartiles exists in neither repository. And F-21: whether a detection means a vessel, a blast or both.

Full list in `Rpi-Detector/docs/CLIENT-DEPENDENCIES.md`.

None of them block Phases 1 to 3. The fixtures supply all of them, so the interface can be built and tested regardless.
