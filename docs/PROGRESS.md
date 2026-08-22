# Implementation progress — dashboard

Phased build plan. Each phase produces something runnable. Phase numbers are shared with the device: Phase 4 means the same thing in both repositories.

Requirement IDs refer to `../REQUIREMENTS.md`. Defect IDs refer to the register in `Rpi-Detector/docs/FINDINGS.md`.

Develop against fixtures throughout: `make dev`.

---

## Current status

**Phase 0 complete.** Repository self-contained, fixtures generate, local loop works.
**Phase 1 complete as backend logic.** Auth, roles, site scoping, device credentials and signed device config are built and tested. 25 backend tests pass. None of that work is affected by the restructure below.
**Phase 1R complete — the structural correction (D-019).** This repository was scaffolded on `lyncHtmlDev`, the static-site protocol variant, and grew a backend inside it. There was no backend/frontend divide: the "frontend" was a folder of files bind-mounted into the API container, and the deployable image contained no frontend at all. Rebuilt on `lynchLocalDev`: three containers, React + Vite, Postgres + Alembic. Done 2026-08-21.
**v2 only, done 2026-08-22 (D-020).** The v1 layer is deleted and device configuration is published as a signed blob, matching the canonical contract. Verified: the document verifies on an independent HMAC recompute, and the debug endpoint returns it byte for byte.
**Azure access not granted for the client's account.** A sandbox subscription of our own, plus a bench unit emitting v2 into a fresh container, is the end-to-end test; see Phase 4.

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

## Phase 1V: v2 only **COMPLETE**

The cutover from D-020. Two separate jobs that happen to land together: delete the v1 layer, and move device configuration onto the transport the canonical contract specifies. Neither changes a feature. Both must land before the bench unit points at anything.

The canonical `DATA-CONTRACT.md` (2026-08-22) already lists the mismatches in its own convergence table, so this is a translation with a written spec, not a design task.

### V-1. Delete the v1 layer — ~1 h, mechanical, rehearsed

- [x] `make drop-v1`: 11 marked blocks, `services/legacy_v1.py`, `tests/test_legacy_v1.py`
- [x] Remove the `drop-v1` target from the Makefile and the `LEGACY-V1` block from `.env`/`.env.example`
- [x] Drop the `contract` note section from `docs/API-CONTRACT.md` and `ContractNote` from the generated types
- [x] `make test && make openapi types`

Rehearsed on a throwaway copy 2026-08-22: 11 blocks, 3 files, 22 tests green, no dangling references.

### V-2. Device config becomes a backend-written blob — ~4–6 h, the real work

The contract's convergence table is the checklist. We are already correct on the version key, the signature scope, and refusing rather than publishing unsigned; the device moves on those. We move on the rest.

- [x] **`Storage` gains `put(path, data, content_type)`.** It has been read-only by design — `list`, `get`, `exists` — so this widens the portability seam and every implementation changes: `LocalStorage`, `AzureBlobStorage`, and the commented S3 stub. The browser-never-writes rule is untouched
- [x] Publish `sites/{site_id}/remote_config.json` whenever configuration is tuned, and on demand
- [x] `config_version` becomes an arbitrary string (`"2026-08-22-01"`), not a monotonic integer. The device re-applies when it *differs*, not when it increases
- [x] Drop `expires_utc`. There is no expiry: a configuration stays in force until a different `config_version` verifies
- [x] Add `window_hop_s`, clamp 1.0–5.0, default 5.0. Tenth key, so the panel grows a field
- [x] `device_id` becomes optional; `null` means the document applies to the whole site. Configuration is addressed per **site**, with an optional device narrowing — our model is currently per-device only
- [x] Rename `OCEANKIND_CONFIG_HMAC_KEY` to `OCEANKIND_CONFIG_HMAC_KEY` everywhere
- [x] `GET /api/devices/config` survives only as a read-only debugging view and must return byte-identical content to the blob
- [x] Tests: published blob verifies against an independent HMAC recompute; refuses to publish with no key; a clamped tune is what lands in the blob

### V-3. Consequential — ~1–2 h

- [x] `?play=` retargeted at v2 clip paths (R-8.5 revised). A missing or never-kept clip must fail visibly
- [x] Suppressed events carry a `clip.path` whose audio was deliberately never kept — the UI must not offer playback that will 404
- [x] Confirm `health` extra fields pass through untouched (`deaf_seconds_total`, `suppressed_count`, `events_dropped`, `wa_pending`, `archive_queue`, `capture_overflows`). The no-`response_model` rule should already cover this; assert it
- [x] `status.json → audio.device` is a selection rule string (`by-name:…`), never an ALSA index. Display only

### Open, needs one decision — not blocking the bench test

- [ ] The device merges its own entry into `_sites.json` at startup. The backend now owns the registry in Postgres and ignores the blob whenever the table has rows, so a self-registering device would not appear. Either the backend imports on a schedule, or the panel surfaces "seen in storage, not registered", or the device stops writing it

**Done when:** no v1 remains in the tree, the backend publishes a signed `remote_config.json` that verifies on an independent recompute, and the bench unit can read its configuration from storage without an API call.

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

- [x] **The image ships no frontend.** Fixed by Phase 1R: the frontend is its own image. Was — `api/Dockerfile` copies `app/` only; the compiled interface reaches the running container purely through the `./web/dist:/web:ro` mount in `docker-compose.yml`. `main.py` guards the static routes with `if WEB_DIR.is_dir()`, which is false in the image, so a deployed container serves the API and returns 404 for `/`, `/login` and `/admin`. Needs a multi-stage build (node compile then copy) or a copy of a prebuilt `dist`
- [x] **Site registry is manageable.** Sites live in Postgres and are created, deactivated and deleted in the admin panel; `_sites.json` stays a read fallback so a fixture tree still works with no setup, and `POST /api/admin/sites/import` seeds the table from it. Verified against a genuinely empty container: register a site, then a device, no blob involved. Deleting a site referenced by a device or a user assignment is refused (2026-08-21)
- [x] **SQLite sits on an ephemeral filesystem.** Fixed by Phase 1R: Postgres with a named volume. Was — `sqlite:////data/oceankind.db` survives locally because `./data` is a bind mount. On Azure Container Apps (and most container hosts) the filesystem is ephemeral, so every restart or scale event destroys users, device credentials and tuned device configs. Decide: Azure Files volume, or Postgres by connection string (R-9.2 allows either)
- [ ] **Single replica is a correctness requirement, not a cost choice.** `core/ratelimit.py` counts login failures in process memory and says so in its own docstring; two replicas means the R-2.4 throttle is bypassable by reconnecting. SQLite imposes the same limit. Pin to one replica and write down why
- [x] **`get_storage()` cached per process** with `lru_cache`, so the Azure client and its HTTP pipeline are built once, not per request (2026-08-21)
- [x] **Timeouts on storage calls**: 10 s connect, 60 s read on the Azure client, so a hung blob read cannot hold a request open indefinitely (2026-08-21)

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
