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
- [x] Paginated, filtered detections (R-5.1). *Mechanism superseded by D-021: this was resolved by
      date-partitioned prefix listing plus one GET per blob, which met R-5.1 and failed R-5.2 —
      the slice happened after all the I/O. Phase 1I replaces the mechanism, not the endpoint*
- [x] Rollups and clip proxying, so the container can be private (R-5.3, R-5.4, R-5.5)
- [x] Malformed and unknown-version blobs surfaced, not swallowed, and never a 500 (R-5.6)
- [x] Typed client, compiling clean. Now `frontend/src/api/client.ts`
- [x] `docs/API-CONTRACT.md` plus generated `openapi.json` and `frontend/src/api/generated.ts` (R-9.5)
- [x] ~~v1 compatibility layer~~ — built, served its purpose, then deleted whole in Phase 1V (D-020). R-11 withdrawn
- [x] Login screen at `/login` and administration screen at `/admin` (R-3.3). Spanish, no
      framework, everything through the typed client. 401 redirects to login, 403 shows a
      permission message, never conflated. Sites come from the API, never a hardcoded list.
      Rebuilt as React pages in Phase 1R; the palette now lives in `frontend/src/styles.css`

- [x] Per-device credential issuance in the admin panel (R-6.1, D-017). Key generated
      server-side, shown once at creation, stored argon2-hashed, never readable again.
      `last_seen` stamped on every device authentication so provisioning failures are
      visible in the panel. Delete = revocation; the unit keeps its last valid config
      (2026-08-13)

- [x] Signed, clamped device configuration (R-6.2). Tuning is `PUT /api/admin/devices/{id}/config`
      plus a "Configurar" editor in the panel; out-of-range values are clamped and reported,
      inverted PSD bands and enum typos rejected, a missing key refuses rather than publishing
      unsigned. *Built 2026-08-18 as an HTTP endpoint; moved to blob transport 2026-08-22 when
      the canonical contract specified it (D-020, Phase 1V).* Closes F-10 on our side

- [x] Conditional requests, `ETag` on rollups (R-5.7). Strong tag over the stored bytes;
      an unchanged rollup costs a 304 and no body (2026-08-25)

### Open
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

## Phase 2 build list — extracted from the client's views, 2026-08-25

**Why this exists.** The first four views were built from the *fixture shapes* — "here is what `status.json` contains, here is a reasonable way to show it" — instead of from the client's existing views. The result follows their palette and their tab names but is not their product: whole sections were missing and nobody had noticed, because nothing was comparing the two.

`web/static/index.html` is the specification for what each view contains. This table is that file, read section by section. **Build against this list, not against the fixtures.**

Legend: **ok** ported · **partial** exists but under-built · **missing** never built · **drop** deliberately not ported, with the reason

### Detecciones (`tab-alertas`)

| Section in the original | Source | State |
|---|---|---|
| Filtro de confianza (`#confidence-slider`) | `min_score` | **ok** — slider, and it announces what it is hiding |
| `#include-legacy` toggle | v1 manifest | **drop** — a v1 artifact. No legacy tier exists under v2 (D-020) |
| `#timeline-chart` | events | **ok** |
| Alertas por hora del día (`#alertDielChart`) | events | **ok** |
| Alertas registradas (tabla) | events | **ok** — plus suppressed/failed/never-kept clip states the original conflated (F-13) |

### Monitoreo acústico (`tab-acustico`)

| Section | Source | State |
|---|---|---|
| Línea de tiempo (`#acTimelineChart`) | `acoustic.timeline` | **ok** |
| Ciclo diel NDSI (`#acDielNdsiChart`) | `acoustic.diel` | **ok** — split back out. A dual axis over 0..1 and tens of Hz manufactures a correlation |
| Ciclo diel clicks (`#acDielClickChart`) | `acoustic.diel` | **ok** |

### Condiciones del mar (`tab-oceano`)

| Section | Source | State |
|---|---|---|
| Olas — swell y energía del mar (`#ocWaveChart`) | `swell_m`, `wave_m` | **ok** |
| Viento — velocidad y ráfaga (`#ocWindChart`) | `wind_kmph`, `gust_kmph` | **ok** |
| Nubosidad (`#ocCloudChart`) | `cloud_pct` | **ok** |
| Definir "mar bueno para bucear" | `thresholds` + 13 inputs | **ok** — both modes (`energy` = swell²·período default 25, and `swellperiod`), wind cap, 8 directions. Persists in `localStorage` as the original did, and the panel says so |
| — | `water_temp_c`, `weather_desc` | **ok** — surfaced in the stat grid |

### Análisis (`tab-analisis`)

| Section | Source | State |
|---|---|---|
| Línea de tiempo integrada (`#anTimelineChart`) | events | **ok** |
| Alertas por estado de mar (`#anSeaChart`) | events + ocean | **ok** — bucketed by sea energy at capture hour; events with no sea data for their hour are counted aside, never dropped into a bucket |
| NDSI vs click rate (`#anNdsiClickChart`) | acoustic | **ok** |
| Click de camarón vs energía del mar (`#anEnergyChart`) | acoustic + ocean | **ok** |

All four built. These are the only charts needing two sources at once, so each names the missing source instead of drawing empty: an empty correlation chart reads as "no relationship", which is a claim rather than an absence.

### Estado del sensor (`tab-sensor`)

| Section | Source | State |
|---|---|---|
| Historial de actividad del sensor | events + `session_start` | **ok** — four states ported (`active`/`session`/`empty`/`future`). "Not yet happened" is not "was silent" |
| Conectividad y captura | `status.network`, `audio` | **ok** |
| Energía solar — Victron BlueSolar MPPT | `status.power` | **ok** |
| Sistema — estado interno de la Raspberry Pi | `status.system` | **ok** |
| Energía — últimas 72 horas (`#powerHistoryChart`) | `power_history` | **ok** — plus gap preservation the original did not have (R-8.6) |
| Espectrograma (`#spec-canvas`) | clip audio | **ok** — WebAudio decode plus an in-house radix-2 FFT, no new dependency. Has the text alternative the original lacked, and fails visibly rather than rendering a black rectangle that reads as silence |

### Defect found while writing this list

- [x] **`is_forecast` is in the contract and `Ocean.tsx` ignored it.** FIXED 2026-08-25. The view derived the observed/forecast boundary by comparing each timestamp to `now`, while the producer publishes the answer per point — and all 168 fixture points carry it, so the heuristic was running with the authoritative flag sitting right there. Now reads `is_forecast`, falls back to the clock only when the field is absent, and says so in the chart note when it does. `wave_m`, `gust_kmph`, `cloud_pct`, `water_temp_c` and `weather_desc` are surfaced in the same change; all five were in the contract and rendered nowhere.

### Decided while building

- [x] **Where "mar bueno para bucear" persists.** `localStorage`, as the original did — it is the viewer's preference, not system state. The panel says so out loud, because a dive window someone tuned and silently lost is exactly the small betrayal this project tries not to commit. If the client wants it per user and across devices, that is a table and two routes; still worth asking.

  Original wording: **Where does "mar bueno para bucear" persist?** The original gives the operator thirteen inputs — mode, swell, period, energy, wind, eight direction checkboxes — and the contract publishes `thresholds` as producer-side defaults. So: does the operator's override live in the browser (`localStorage`, per device, lost on a new machine), or server-side per user (a real preference, needs a table and routes)? The original almost certainly did the former. It is worth asking whether that is what the client wants, because a dive window someone tuned and then lost is a small betrayal of exactly the kind this project is trying to avoid.

---

### V-3. Consequential — ~1–2 h

- [x] `?play=` retargeted at v2 clip paths (R-8.5 revised). A missing or never-kept clip must fail visibly
- [x] Suppressed events carry a `clip.path` whose audio was deliberately never kept — the UI must not offer playback that will 404
- [x] Confirm `health` extra fields pass through untouched (`deaf_seconds_total`, `suppressed_count`, `events_dropped`, `wa_pending`, `archive_queue`, `capture_overflows`). The no-`response_model` rule should already cover this; assert it
- [x] `status.json → audio.device` is a selection rule string (`by-name:…`), never an ALSA index. Display only

### Open, needs one decision — not blocking the bench test

- [ ] The device merges its own entry into `_sites.json` at startup. The backend now owns the registry in Postgres and ignores the blob whenever the table has rows, so a self-registering device would not appear. Either the backend imports on a schedule, or the panel surfaces "seen in storage, not registered", or the device stops writing it

**Done when:** no v1 remains in the tree, the backend publishes a signed `remote_config.json` that verifies on an independent recompute, and the bench unit can read its configuration from storage without an API call.

---

## Phase 1I: The detection index **SUBSTANTIALLY COMPLETE**

Dashboard-local, like 1R and 1V, so it does not consume a shared phase number. Needs no Azure account and no device change; the fixture tree exercises all of it. See D-021, **D-022** and R-12.

**Why — measured 2026-08-26 (D-022).** D-021 justified this with ~864 events/device/day from an unsourced 5% alert rate. The client reports **~10 WhatsApp alerts on a typical day**, which under the v1 cooldown multiplier (F-03) bounds the real rate at **10–1,200 events/day**, planning figure a few hundred. 864 is inside that range, so the original figure was unsourced rather than wrong — an earlier revision of this note called it refuted and overstated the case.

Both justifications therefore hold. **Queryability and freshness** is the better one and stands on its own: a 90-day or cross-site question costs one query instead of thousands of reads, and a detonation appears in seconds rather than at the next poll of a scan. **Page cost** is real too at the upper half of the range — 500/day over a seven-day window is ~3,500 blobs.

⚠️ **The fixtures cannot validate this.** 2–3 events/day is below the measured lower bound, and `LocalStorage` makes thousands of reads instant — the two things that hid the original defect. Raise the generator's rate before calling this phase done (`TODO.md`).

- [x] `detection_events` table: indexed `site_id`, `captured_utc`, `event_type`, `detector`, `score`, `suppressed`, plus `event_id` unique and the full document as `jsonb` (R-12.1). Migration `7deafd5e87df`. Two fields beyond the requirement: `indexed_utc` (freshness — the honest replacement for `scanned_blobs`) and `first_seen_via` (`push`/`reconcile`, which is the drift metric for the push path: if every row says `reconcile`, the device push has silently stopped)
- [x] Index on `(site_id, captured_utc)`. Created ascending, not DESC: Postgres scans a btree backwards at the same cost for a single sort direction. Monthly partitioning still not needed
- [x] Indexer: `services/indexer.py`, upsert on `event_id` inside a SAVEPOINT (R-12.3). Idempotency is enforced by the unique constraint rather than check-then-insert — two concurrent pushes of one event both see nothing and both insert, so the constraint has to be the mechanism
- [x] Reconcile pass over a trailing window (R-12.4), `services/reconcile.py`, **scheduled daily** by `services/scheduler.py`. Verified at realistic volume: 4,985 blobs indexed in 2.3 s, and a clean re-pass fetches **0** blobs in 0.17 s. Never opens a clip, asserted by test
- [x] Scheduler: an asyncio task in the app lifespan, not a cloud trigger (that would be the runtime dependency R-1.1 forbids) and not a scheduler library (a dependency and a second process for one periodic call). `OCEANKIND_RECONCILE_INTERVAL_HOURS=0` disables it, logged at warning level
- [x] `IndexerRun` table (migration `3f3ca891ece9`): every pass recorded, **including a failed one**. "The reconcile has been crashing for a week" must not look like "the reconcile keeps finding nothing", and from outside they are identical unless the attempt is written down
- [x] `POST /api/devices/events` as the latency path (R-6.3, D-022). Idempotent on `event_id`, `202` for a replay and never `409`. Rejections stamped on the device row beside `last_seen`, because a 4xx returned to an unattended box is seen by nobody
- [ ] ~~Blob-created notification path~~ — **dropped, not deferred (D-022).** It meant Azure Event Grid, the only cloud-specific runtime dependency the stack would have had, against R-1.1 and R-1.4. A device posting to an endpoint we own is both portable and simpler
- [x] `list_events` reads Postgres. Same envelope, same field names (R-12.1). Measured: a 90-day page of 50 costs **2.2 ms** and zero storage reads, the same as a 7-day one — R-5.2 met as an outcome, not just in mechanism
- [x] Drift metric per day and per site: `GET /api/admin/index`, read-only, opens no blob. Reports `last_run_utc` alongside, because zero drift that has never been checked is not evidence of anything (R-12.5)
- [x] Rebuild: `POST /api/admin/index/rebuild`, requires the site id typed twice. Test asserts a rebuild reproduces byte-identical query results (R-12.2)
- [x] `scanned_blobs` **removed**, replaced by `index_updated_utc`. Served from an index that count is always zero, and a field returning a plausible number describing no work is worse than absent. `null` renders as "índice vacío" in amber
- [x] Cross-site query (R-12.7). `list_events` takes a list of sites; the route passes one today

**Tests that must exist, because these are the failure modes:**

- [x] An event blob written into a prefix a week in the past appears in the index without intervention — `test_reconcile.py::test_an_event_landing_in_a_past_prefix_is_still_found`
- [x] Indexing the same blob twice produces one row — `test_indexer.py::test_indexing_the_same_event_twice_produces_one_row`
- [x] The same event arriving by push and by reconcile produces one row (R-12.3, D-022) — `test_indexer.py::test_push_then_reconcile_produces_one_row`
- [x] An event that was pushed but whose push failed still reaches the index from storage — covered by the reconcile pass tests; the blob is the source either way
- [x] **The high-water-mark trap** — `test_reconcile.py::test_an_event_landing_in_a_past_prefix_is_still_found`. Index up to day N, then write a blob into day N−3. It must still be found. A mark tracks capture date while what varies is arrival, so once a mark passes a partition anything landing there afterwards is unreachable — permanently and silently. This is the reason the trailing window exists and the test that proves it was not quietly replaced by a mark
- [x] A malformed blob is skipped, counted and surfaced, and does not stall the pass — `test_reconcile.py::test_a_malformed_blob_is_counted_and_does_not_stall_the_pass`
- [x] Timezone-aware comparison at a day boundary, since this class of bug has already bitten once — `test_indexer.py::test_non_utc_offset_is_accepted_and_refers_to_the_right_instant`
- [x] A naive (offset-less) `since` does not 500 — see the two defects below — `test_list_events.py::test_a_naive_since_does_not_raise`
- [x] After a rebuild, a fixed query returns byte-identical results — `test_index_admin.py::test_rebuild_reproduces_the_same_answers`
- [x] No path in the indexer or the reconcile opens a `.wav` — `test_reconcile.py::test_the_pass_never_opens_a_clip`

### Two defects in the code Phase 1I replaces — found 2026-08-26

Both live in `services/events.py` and are wrong at any event volume.

- [x] **A naive `since` returns 500.** FIXED 2026-08-26 — `_as_utc()` reads an offset-less bound as UTC, documented in `API-CONTRACT.md` as a convention rather than left to be inferred. `since`/`until` arrive from the query string as `datetime`; an offset-less value stays naive while `until` defaults to aware UTC. The comparison at `events.py:60` then raises `TypeError`, and it sits *outside* the `try` above it, so it propagates as an unhandled 500. Violates R-5.6. Not reachable from our own UI — `client.ts` sends `toISOString()` — but reachable by any direct API caller. **One line; do not wait for Phase 1I**
- [x] **Offset timestamps select the wrong day partitions.** FIXED 2026-08-26 — `reconcile._utc_date()` normalises to UTC before taking `.date()`, and the storage-walking `_day_prefixes` it afflicted is no longer on the query path at all. `_day_prefixes` uses `since.date()`/`until.date()`, which for a non-UTC offset yields the *local* date while partitions are keyed on UTC `captured_utc`. A window expressed in Chile time silently omits a prefix at each boundary — events that exist, are permitted, and do not appear. Carry into the index as a test

**Done when:** a page of 50 events is served with zero reads against object storage, and the drift metric reads zero across every site and day in the fixture tree.

---

## Phase 2: The five views, in React **COMPLETE except deleting `web/`**

**Foundation done 2026-08-25.** Phase 3's per-panel failure contract was built into the shell rather than bolted on afterwards, because the cheap moment to make a failed fetch look failed is while writing the fetch. `hooks/useResource.ts` holds the rules once: a failed refresh never erases the last good value, it marks it stale and says when it was good; a source that never loaded reports failed, not empty; each resource fails alone; 401 leaves for login; 403 and 404 are terminal and get no retry loop. It also carries a generation guard, so a slow response for a site you have navigated away from cannot overwrite the one you are looking at. `components/Panel.tsx` draws those four states the same way everywhere, so no view can invent a fifth.

The client's five views are rebuilt as React pages reading the API. The 3,129-line monolith is deleted when the last view leaves it. No new features — this is the same product, correctly built.

**Built against the extracted build list above, not against the fixtures.** The first four views were written from the fixture shapes and silently omitted ten sections of the client's product; that was caught, inventoried, and closed. All 23 sections in that list are now ported.

- [x] `pages/views/Detections.tsx` — paginated events endpoint, not `manifest.json` (F-18). Filters for period, type and suppressed; a filter that hides events announces itself (2026-08-25)
- [x] `pages/views/SensorStatus.tsx` — health first and in words; `null` rendered as absence,
      never zero; thresholds shown as the values *in force* on the device (F-09's honest half);
      health fields the device sends but this version does not know are displayed raw rather
      than dropped (2026-08-25)
- [x] `pages/views/Acoustic.tsx` — NDSI and click rate with their interquartile band, plus the
      diel cycle. A median alone understates how noisy a day was (2026-08-25)
- [x] `pages/views/Ocean.tsx` — observed drawn solid, forecast drawn dashed, because past the
      current hour it stops being a measurement. A 404 here says nothing about device health
      and the message says so (2026-08-25)
- [x] `pages/views/Analysis.tsx` — all four cross-source charts. Each names the source it is
      missing instead of drawing empty, because an empty correlation chart reads as "no
      relationship", which is a claim rather than an absence (2026-08-25)
- [x] `components/PowerChart.tsx` on `react-chartjs-2` (R-8.6). **Gaps preserved**: a bucket
      absent for more than 1.5 intervals inserts a null point so the line breaks instead of
      spanning the silence, and the count of breaks is stated in words underneath. Buckets
      present but null-valued are counted separately — device alive, sensor not reporting.
      Verified against the fixture's deliberate 5 h outage: 135 buckets in, 136 points out,
      one break (2026-08-25)
- [x] `components/SiteMap.tsx` on `react-leaflet`. Coordinates rendered at 4 decimals and zoom
      capped at 12 on purpose: it places the site, not the box. The threat model includes the
      people the system detects (2026-08-25)
- [x] `?play=` deep links resolve to `pages/views/ClipDetail.tsx`, on any tab (R-8.5). The three
      outcomes are distinguished rather than conflated: no session, no permission, and a clip
      whose upload failed after the alert was sent (F-13). Suppressed events say the audio was
      deliberately never kept (D-008) (2026-08-25)
- [x] Spectrogram ported — WebAudio decode plus an in-house radix-2 FFT, no new dependency.
      Carries the text alternative the original lacked, and fails visibly instead of leaving a
      black rectangle that reads as silence (2026-08-25)
- [x] Sites from `GET /api/sites` via `components/SitePicker.tsx`; nothing hardcoded
- [x] The v2 event schema surfaced: `captured_utc` as the event time, `event_type` distinguished by mark *and* word, `detector`, `score`, `suppressed` shown and flagged, `clip.*` split into uploaded / failed / never-kept (R-8.2 to R-8.4, F-13)
- [x] Grouped `status.json` consumed: `health`, `detection`, `audio`, `power`, `network`, `system`
      (`SensorStatus.tsx:54-60`; verified 2026-08-26)
- [x] Unknown `schema_version` renders a visible warning, never a blank page (`SensorStatus.tsx:72`;
      verified 2026-08-26)
- [x] Every numeric field tolerates `null` and renders it as absence, never as zero
- [x] No storage URL anywhere in the frontend. The only surviving `SAS_URL_KEY` is in
      `web/static/index.html:1289` and goes with the folder (X-01; verified 2026-08-26)
- [ ] `web/` deleted — **the only thing left in Phase 2.** Every view is ported; the folder is
      now dead weight. Not deleted unilaterally: it is 3,129 lines of the client's original and
      removing it is the one irreversible step here

**Done when:** the whole interface runs against `make dev` with no storage credential in the browser, and `web/static/index.html` no longer exists.

---

## Phase 3: Make failure visible **SUBSTANTIALLY COMPLETE**

The monitoring tool must be honest about its own state. This is the half of the contract that is about trust rather than features.

- [ ] `health` surfaced at site-picker level: a degraded unit is obvious without opening a tab (R-7.4).
      `HealthBadge` exists and is wired for the *selected* site in `Dashboard.tsx`; what is missing is
      per-site health in `SitePicker`, which is the multi-site half of the requirement
- [x] **An alert when a device stops reporting (R-7.5, D-022).** `services/silence.py`, on its own
      5-minute timer separate from the daily reconcile — "is the index complete?" is a daily
      question, "is the unit alive?" is not. Liveness from `status.json → last_seen`, **not**
      `Device.last_seen`: that column only stamps when a device authenticates to our API, which
      under D-022 happens when it has an event to push, so a healthy unit in a quiet week would
      have looked dead. Threshold is missed heartbeats × the device's *tuned* `heartbeat_interval_s`
      with a floor, since the interval is remotely tunable 30–3600 s.
      **Anti-flood:** one `DeviceAlert` row per outage. The check runs 288×/day; a unit down a week
      sends 7 messages, not 2,016. All four volume knobs are in one block in `core/config.py` and
      documented in `SERVER-INFRASTRUCTURE.md`. Transport is a portable webhook, log-only until one
      is configured — Twilio stays blocked on F-04, and the alert is recorded either way
- [x] Per-panel "last loaded" timestamp (R-7.2) — every `Panel` carries "actualizado hace X" (2026-08-25)
- [x] Every failed fetch visibly failed, with retry (R-7.1) — `hooks/useResource.ts` holds the rule once (2026-08-25)
- [x] Each source fails independently; one 404 never takes the page down (R-7.3) — per-resource state, generation-guarded
- [x] Suppressed detections shown and marked, never hidden (R-8.2) — shown by default; any filter that hides them announces itself
- [x] `vessel`, `blast` and `unknown` visually distinct (R-8.3) — distinguished by mark *and* word, not colour alone
- [x] Missing and failed-upload clips handled distinctly (F-13) — uploaded / failed / never-kept are three states, not one
- [x] Power history gaps preserved, never interpolated (R-8.6) — verified against the fixture's deliberate 5 h outage
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
- [x] **`make drop-v1`** and R-11 withdrawn — done 2026-08-22 ahead of Phase 4, because the premise (unreachable v1 units) collapsed. See D-020 and Phase 1V

---

## Phase 5: Deployment **NOT STARTED**

### Blockers found 2026-08-21, before any deploy is attempted

These were found by inspecting the image and the storage seam rather than by deploying. Each one makes a deployment either fail or be quietly useless.

- [x] **The image ships no frontend.** Fixed by Phase 1R: the frontend is its own image. Was — `api/Dockerfile` copies `app/` only; the compiled interface reaches the running container purely through the `./web/dist:/web:ro` mount in `docker-compose.yml`. `main.py` guards the static routes with `if WEB_DIR.is_dir()`, which is false in the image, so a deployed container serves the API and returns 404 for `/`, `/login` and `/admin`. Needs a multi-stage build (node compile then copy) or a copy of a prebuilt `dist`
- [x] **Site registry is manageable.** Sites live in Postgres and are created, deactivated and deleted in the admin panel; `_sites.json` stays a read fallback so a fixture tree still works with no setup, and `POST /api/admin/sites/import` seeds the table from it. Verified against a genuinely empty container: register a site, then a device, no blob involved. Deleting a site referenced by a device or a user assignment is refused (2026-08-21)
- [x] **SQLite sits on an ephemeral filesystem.** Fixed by Phase 1R: Postgres with a named volume. Was — `sqlite:////data/oceankind.db` survives locally because `./data` is a bind mount. On Azure Container Apps (and most container hosts) the filesystem is ephemeral, so every restart or scale event destroys users, device credentials and tuned device configs. Decide: Azure Files volume, or Postgres by connection string (R-9.2 allows either)
- [ ] **Single replica is a correctness requirement, not a cost choice.** `core/rate_limit.py` counts login failures in process memory and says so in its own docstring; two replicas means the R-2.4 throttle is bypassable by reconnecting. Pin to one replica and write down why
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
