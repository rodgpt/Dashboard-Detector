# TODO — dashboard

Pending items outside the phase roadmap in `PROGRESS.md`. Anything phased goes there.

Add TODOs the moment they occur. Context compression eats undocumented ones.

Cross-cutting items, or anything that also touches the device, go in `TODO.md`.

Categories: `[UI]` `[Data]` `[Perf]` `[A11y]` `[Sec]` `[DX]`

---

## Pending

- [ ] **[DX] Build views from the client's views, not from the fixture shapes** — The first four Phase 2 views were written by reading `status.json` and inventing a reasonable presentation. That produced something coherent in the right palette that was **not the client's product**: `Nubosidad` absent, the "mar bueno para bucear" configurator absent, the sensor uptime grid absent, the whole `Análisis` tab absent, and five contract fields rendered nowhere — none of it noticed, because nothing compared the two. The extracted inventory is now in `PROGRESS.md` ("Phase 2 build list"). **Check each new view against it before calling it done**, and record any departure as a decision rather than discovering it as an omission.

> **Cleared 2026-08-22 by D-020.** Five items here described the prototype unit's v1 output — a contract section that overstated what was on the wire, a device mislabelled `Zapallar` at Matanzas coordinates, all-null power telemetry, upload-time timestamps, and a meaningless `current_threshold`. That container is frozen, in a different account, and read by nothing we ship. The observations are preserved in the D-020 entry and in this file's Done section; they are not work items any more. If the prototype history is ever imported, re-read them first — every one of them is a trap for whoever writes that script.

- [ ] **[Data] A self-registering device lands in a blob the backend ignores** — `DATA-CONTRACT.md` has the device merge its own entry into `_sites.json` at startup, calling it "tolerable until the backend owns the registry". The backend now owns it (Postgres, 2026-08-21) and ignores the blob whenever the table has rows, so a device that provisions itself is invisible in the panel. Three ways out: import on a schedule, surface "seen in storage, not registered" in the sites panel, or have the device stop writing it. The middle one makes the situation visible rather than resolving it silently, which is why it is the recommendation. Not blocking the bench test.

- [ ] **[Sec] The per-device credential now has no consumer** — R-6.1 issuance exists and works, but D-020 moved configuration to blob transport, so nothing authenticates with `X-Device-Id`/`X-Device-Key` except the debug view. It is kept deliberately: it is the foundation for R-6.3 event upload and it makes revoking one unit possible. But it is infrastructure ahead of its use, and that should stay written down rather than be rediscovered as "why does this exist". *Resolved by design 2026-08-26 (D-022): `POST /api/devices/events` is the second consumer. Closes when that route ships.*

- [x] **[Data] The event volume this system will actually see is unmeasured** DONE (2026-08-26) — client reports ~10 WhatsApp alerts on a typical day. Applying the v1 cooldown multiplier (each alert masked up to `600 s / 5 s` = 120 events, F-03) bounds the v2 rate at **10–1,200 events/day**, planning figure a few hundred. D-021's 864 sits inside that range, so it was unsourced rather than wrong; D-022 records the partial reversal.

- [x] **[DX] The fixtures cannot validate the index** DONE (2026-08-26) — `generate_fixtures.py` writes `n = rng.randint(28, 46)` events per site over 14 days: 2–3 per day, **below the lower bound** of the measurement above and roughly 100× below the planning figure. An index, a reconcile pass and a drift metric tested against 128 events prove nothing about their behaviour at a few hundred a day — and `LocalStorage` turns thousands of blob reads into instant local file reads, which is precisely how the original defect stayed invisible through every `make dev` for months. Fixed by generating **episodes** rather than isolated events: the device records one event per alerting window including suppressed ones (D-008), so one sound source is a run of consecutive events, not a single one. ~10 episodes/day now yields **~340 events/site/day** — inside the measured band — with ~10 clips/day, because suppressed events never keep audio. That also stopped the tree exploding in size: 9,545 events in 261 MB. `--episodes-per-day` lowers it for a cheap tree when working on the interface. Verified at that volume: 4,985 blobs indexed in 2.3 s, clean re-pass fetches 0, a 90-day page of 50 costs 2.2 ms.

- [x] **[Data] `scanned_blobs` will start lying** DONE (2026-08-26) — removed rather than made to report zero, and replaced by `index_updated_utc` (the most recent `indexed_utc` for the queried sites). `null` renders as "índice vacío" in amber rather than being hidden, because an empty event list reads identically whether there were no detections or no data is reaching us, and those mean opposite things. Backend, `client.ts`, `Detections.tsx`, `openapi.json` and the generated types moved together.

- [ ] **[DX] `docs/CHANGELOG-v2.md` describes a file that no longer runs** — It diffs `src/index.html` against the August 2 audit and is explicit that its blob-shape claims are inferred, not verified. That file is now superseded reference material (`web/README.md`) and the canonical `DATA-CONTRACT.md` is normative and verified end to end. Either retire the changelog with a pointer to the contract, or keep it as provenance for how the v2 fields were originally derived — but it must not be read as a source of truth.

- [x] **[UI] Empty-but-present telemetry buckets need their own visual state** DONE (2026-08-25) — `PowerChart` distinguishes three things: a bucket that is absent (line breaks, counted as "interrupción en el reporte"), a bucket present with null values (counted as "lecturas sin valor — el equipo reportó a tiempo pero el sensor no entregó dato"), and a real zero. None of them is drawn as any of the others.

- [ ] **[DX] Palette to CSS custom properties** — Twenty occurrences of the same blue as hex literals. Lift the palette in `STYLEGUIDE.md` into `:root` before Phase 4 multiplies the component count. Mechanical, zero risk, saves every later visual change. *Done for the live app 2026-08-22: the tokens are in `frontend/src/styles.css` and the React pages use them. What remains is only the superseded `web/static/index.html`, which is deleted in Phase 2 rather than fixed.*

- [ ] **[DX] STYLEGUIDE describes dead styling** — The guide (extracted 2026-08-02) documents the light CSS at the top of `index.html`, but a final "TEMA OSCURO MAR FUTURA" `<style>` block overrides it wholesale with `!important` and `--mf-*` variables: the shipped design is dark (`#0c2230` bg, `#12303f` panels, `#64b1c5` brand). The drift warning in `STYLEGUIDE.md` records the real values. Re-extract the guide from the dark layer when the monolith splits in Phase 2, and drop the dead light CSS in the same move — two full theme layers in one file is how the next mismatch happens.

- [ ] **[UI] Two status components doing one job** — `.status-pill` and `.online-badge` are near-duplicates with their own dot elements and offline modifiers. Merge before Phase 4 adds per-device status in three places.

- [ ] **[DX] Device blob fields are not type-checked in the frontend** — `make types` generates TypeScript from the OpenAPI schema, which covers every path, query parameter and backend-composed envelope. It does not cover the device blobs inside them, which are deliberate pass-throughs so unknown fields survive (see `API-CONTRACT.md`). A misspelt `event.captured_utc` therefore still compiles. The fix is generating types from `DATA-CONTRACT.md` itself, not putting response models over the pass-throughs.

- [ ] **[A11y] No accessibility pass has been done** — Contrast of the muted greys on dark surfaces is untested, the tabs may not be keyboard reachable, and the spectrogram canvas has no text alternative. Worth one `wcag-checker` run to find out how bad it is before deciding what to fix.

- [ ] **[Perf] Full history parsed every 30 seconds** — Beyond the bandwidth issue in F-18, at the 5000-entry manifest cap the browser re-parses and re-renders the entire list on every poll. On a phone over cellular that is noticeable. Pagination in Phase 4 fixes the fetch; also check the render path.

- [ ] **[Sec] Coordinates render at full precision** — Six decimal places locates hardware to roughly ten centimetres. *Partly addressed 2026-08-21: the admin sites table displays 4 decimals (~11 m); the stored value is untouched.* The five views in Phase 2 have not been through this yet, and the map is the one that matters.

- [x] **[UI] No indication of data age** DONE (2026-08-25, R-7.2) — every `Panel` carries its own "actualizado hace X", and a panel whose refresh failed switches to "sin actualizar desde X" in amber with the reason and a retry. Staleness is stated, not inferred.

- [ ] **[DX] The client's dashboard is still 3,129 lines in one HTML file** — Superseded and no longer served (`web/README.md`), but still the only record of what the five views contain, which is why it survives. Phase 2 rebuilds those views as React pages against the API and deletes the file. It is not split, not fixed, and not read at runtime. *This entry was the early warning that went unheeded: it noted the one-file rationale had expired while the file grew from 1,779 to 3,129 lines. See D-019.*

---

## Done

- [x] **[DX] Fixtures were anchored to a fixed date and rotted** DONE (2026-08-25) — `generate_fixtures.py` pinned `now` to 2026-08-08 "so runs are reproducible". Every default query window is relative to today, so weeks later `make dev` produced a dashboard with **zero detections** — indistinguishable from a broken one, which is the exact confusion this project exists to remove, reproduced in the development loop. Now anchored to the current time by default, with `--now` to pin it; the seed still makes the content reproducible, only the timestamps move.

- [x] **[Perf] Conditional requests on rollups** DONE (2026-08-25, R-5.7) — strong `ETag` over the exact bytes in storage, `If-None-Match` returns 304 with an empty body. Verified: 1094 bytes unconditional, 0 bytes conditional. Hashing the stored bytes rather than the parsed document is deliberate — it is what actually changed, and it cannot be fooled by two serialisations of the same values.

- [x] **[Data] v2-only cutover** DONE (2026-08-22) — v1 adapter deleted (11 marked blocks, `legacy_v1.py`, its tests, the drop tool itself). Device configuration moved from `GET /api/devices/config` to a backend-written signed blob at `sites/{site_id}/remote_config.json`, per the canonical contract. `config_version` became an opaque string, `expires_utc` removed, `window_hop_s` added to the clamp table, `OCEANKIND_CONFIG_SIGNING_KEY` renamed to `OCEANKIND_CONFIG_HMAC_KEY`. Verified: independent HMAC recompute passes, and the debug endpoint returns the blob byte for byte. See D-020.

- [x] **[DX] `Storage` gained a write** DONE (2026-08-22) — `put()` on the interface and both implementations, for exactly one caller: publishing the config blob. Local writes temp-then-rename so a polling device cannot read a torn document; Azure's blob PUT is already atomic. The dev fixtures mount had to become writable, which is how the first publish failed — loudly, with `Errno 30`, rather than silently.

- [x] **[DX] `make drop-v1` pointed at the pre-restructure paths** DONE (2026-08-22) — it still said `api/` after Phase 1R renamed it to `backend/`, so it would have failed to find its own targets. Fixed to refuse outright when its paths are wrong (a partial removal is worse than none), extended to TypeScript, and taught to skip `node_modules`. Then used, and deleted itself as designed.

<!--
  Format: - [x] **[Category] Title** DONE (YYYY-MM-DD) — how it was resolved.
-->

- [x] **[DX] `make test` collected zero tests** DONE (2026-08-13) — the image only copies `app/` and the compose file did not mount `api/tests`, so `pytest` inside the container found nothing and exited green. Mounted `api/tests` and `api/pytest.ini` read-only in `docker-compose.yml`. A green run now means the 15 tests actually ran.

- [x] **[DX] `email-validator` missing from the image** DONE (2026-08-13) — `EmailStr` in the auth and admin routers needs it; the app failed at import inside the container. `pydantic>=2.9` became `pydantic[email]>=2.9` in `api/requirements.txt`.

- [x] **[Sec] Bootstrap could create an administrator that can never log in** DONE (2026-08-13) — `OCEANKIND_BOOTSTRAP_ADMIN_EMAIL` was written to the database unvalidated, but login validates with `EmailStr`, so a reserved-domain address (e.g. `admin@x.local`) bootstrapped a dead admin silently. `init_db` now refuses to start on an invalid bootstrap email or a bootstrap password under 12 characters, matching the create-user rules.

- [x] **[Sec] SPA fallback served paths outside `/web` on raw `../` requests** DONE (2026-08-13) — `WEB_DIR / full_path` in `main.py` did no containment check, so a client sending an unnormalised `/../app/...` path could read files outside the web root. The fallback now resolves candidates and requires them inside `/web`.
