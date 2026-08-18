# Implementation progress — dashboard

Phased build plan. Each phase produces something runnable. Phase numbers are shared with the device: Phase 4 means the same thing in both repositories.

Requirement IDs refer to `../REQUIREMENTS.md`. Defect IDs refer to the register in `Rpi-Detector/docs/FINDINGS.md`.

Develop against fixtures throughout: `make dev`.

---

## Current status

**Phase 0 complete.** Repository self-contained, fixtures generate, local loop works.
**Phase 1 in progress.** The backend exists, is tested, and enforces access. The interface has not moved onto it yet.
**Azure access not granted.** Phase 4 cannot begin. Nothing before it is blocked.

`web/static/index.html` is the client's v2 dashboard, moved in intact. It still reads the **v1** blob layout directly from storage. Moving it onto the API is Phase 2.

---

## Phase 0: Workable repository **COMPLETE**

- [x] Repository self-contained
- [x] `REQUIREMENTS.md` rewritten around the contracted scope: auth, users, a backend we own
- [x] `docs/DATA-CONTRACT.md` mirrored from the canonical copy, `make contract` enforces it
- [x] Fixture generator producing a full v2 tree with real audio, one site degraded on purpose
- [x] One-command local loop, no cloud account

---

## Phase 1: The backend **IN PROGRESS**

Everything the presupuesto promises that a static page structurally cannot do. No cloud account needed; the local storage backend reads fixtures.

### Built
- [x] FastAPI in one container, no cloud identity, no cloud runtime (R-1.1, R-1.4)
- [x] `Storage` interface with local and Azure implementations, swapped by environment variable. S3 is one new class (R-1.2)
- [x] All configuration from the environment; refuses to start on a missing secret (R-1.3, R-4.3)
- [x] Login, logout, me. Argon2 passwords, signed expiring session cookie, throttled login (R-2.1 to R-2.5)
- [x] Users, roles and site assignments in SQLite; admin API to manage them (R-3.1 to R-3.3, R-9.2)
- [x] Every data route site-scoped server-side, with a test asserting 403 across sites (R-3.4)
- [x] First-administrator bootstrap for a fresh deployment (R-3.5)
- [x] Secrets held server-side only; none reachable from the browser (R-4.1, R-4.2)
- [x] Paginated, filtered detections resolved by date-partitioned prefix listing (R-5.1, R-5.2)
- [x] Rollups and clip proxying, so the container can be private (R-5.3, R-5.4, R-5.5)
- [x] Malformed and unknown-version blobs surfaced, not swallowed, and never a 500 (R-5.6)
- [x] Typed client `web/src/api.ts`, compiling clean
- [x] `docs/API-CONTRACT.md` plus generated `openapi.json` and `web/src/generated/api-types.ts` (R-9.5)
- [x] v1 compatibility layer: reads the live v1 container, returns v2 shapes, removable with `make drop-v1` (R-11, D-016)
- [x] Login screen at `/login` and administration screen at `/admin` (R-3.3). Spanish, no
      framework, everything through `web/src/api.ts`. 401 redirects to login, 403 shows a
      permission message, never conflated. Sites come from the API, never a hardcoded list.
      Palette lives as `:root` custom properties in `web/static/css/auth.css` (2026-08-13)

- [x] Per-device credential issuance in the admin panel (R-6.1, D-017). Key generated
      server-side, shown once at creation, stored argon2-hashed, never readable again.
      `last_seen` stamped on every device authentication so provisioning failures are
      visible in the panel. Delete = revocation; the unit keeps its last valid config
      (2026-08-13)

### Open
- [ ] `GET /api/devices/config` returns 501. Needs the signing key wired and the clamp table from `DATA-CONTRACT.md` implemented (R-6.2, F-10)
- [ ] Conditional requests, `ETag` on rollups (R-5.7)
- [ ] Types generated from `DATA-CONTRACT.md` so device fields are checked too. See `TODO.md`

**Done when:** a fresh deployment can be logged into, an operator sees only their sites on every endpoint, and no secret exists anywhere the browser can reach.

---

## Phase 2: Point the interface at the API **NOT STARTED**

The existing dashboard stops reading storage and starts reading the API. No new features.

- [ ] Every fetch goes through `web/src/api.ts`. No storage URL anywhere in the frontend
- [ ] Delete the dead `SAS_URL_KEY` constant (X-01)
- [ ] Login redirect on 401, permission message on 403. They are not the same thing
- [ ] Sites from `GET /api/sites`, hardcoded `SITES` table deleted
- [ ] Detections from the paginated events endpoint instead of `manifest.json` (F-18)
- [ ] Map the v2 event schema: `captured_utc` not upload time, `event_type`, `detector`, `score`, `suppressed`, `clip.*` (R-8.2 to R-8.4)
- [ ] Read the restructured `status.json`: `health`, `detection`, `audio`, `power`, `network`, `system`
- [ ] Unknown `schema_version` renders a visible warning, never a blank page
- [ ] Guard every `JSON.parse`; tolerate `null` in every numeric field
- [ ] Split the 1,779-line file into modules as it moves. See `TODO.md`

**Done when:** the whole interface runs against `make dev` with no storage credential in the browser.

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

- [ ] Deployment documented for a container host, with the Azure and the not-Azure path both written down (R-1.1)
- [ ] GitHub Actions: backend tests, frontend compile, `make contract` (R-10.1)
- [ ] Session secret and storage credential rotation procedure
- [ ] Handover. **We do not deploy; the client does** (D-015)

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
