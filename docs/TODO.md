# TODO — dashboard

Pending items outside the phase roadmap in `PROGRESS.md`. Anything phased goes there.

Add TODOs the moment they occur. Context compression eats undocumented ones.

Cross-cutting items, or anything that also touches the device, go in `TODO.md`.

Categories: `[UI]` `[Data]` `[Perf]` `[A11y]` `[Sec]` `[DX]`

---

## Pending

- [ ] **[DX] Palette to CSS custom properties** — Twenty occurrences of the same blue as hex literals. Lift the palette in `STYLEGUIDE.md` into `:root` before Phase 4 multiplies the component count. Mechanical, zero risk, saves every later visual change. *Partially done 2026-08-13: the login and admin pages ship the tokens in `web/static/css/auth.css`; `index.html` still uses hex literals and should adopt the same tokens when it splits in Phase 2.*

- [ ] **[DX] STYLEGUIDE describes dead styling** — The guide (extracted 2026-08-02) documents the light CSS at the top of `index.html`, but a final "TEMA OSCURO MAR FUTURA" `<style>` block overrides it wholesale with `!important` and `--mf-*` variables: the shipped design is dark (`#0c2230` bg, `#12303f` panels, `#64b1c5` brand). The drift warning in `STYLEGUIDE.md` records the real values. Re-extract the guide from the dark layer when the monolith splits in Phase 2, and drop the dead light CSS in the same move — two full theme layers in one file is how the next mismatch happens.

- [ ] **[UI] Two status components doing one job** — `.status-pill` and `.online-badge` are near-duplicates with their own dot elements and offline modifiers. Merge before Phase 4 adds per-device status in three places.

- [ ] **[Data] Manifest timestamp is upload time, not detection time** — The dashboard presents `timestamp` as when the event happened. It is when the manifest was rewritten, after the upload, which over cellular can be tens of seconds later. Either label it accurately or wait for the device to publish both. See `DATA-CONTRACT.md`.

- [ ] **[Data] `current_threshold` is displayed and means nothing** — The sensor tab shows a sensitivity value that does not control detection (F-09). Currently misleading. Either hide it until the device publishes the real parameters, or label it clearly as legacy.

- [ ] **[DX] Device blob fields are not type-checked in the frontend** — `make types` generates TypeScript from the OpenAPI schema, which covers every path, query parameter and backend-composed envelope. It does not cover the device blobs inside them, which are deliberate pass-throughs so unknown fields survive (see `API-CONTRACT.md`). A misspelt `event.captured_utc` therefore still compiles. The fix is generating types from `DATA-CONTRACT.md` itself, not putting response models over the pass-throughs.

- [ ] **[A11y] No accessibility pass has been done** — Contrast of the muted greys on dark surfaces is untested, the tabs may not be keyboard reachable, and the spectrogram canvas has no text alternative. Worth one `wcag-checker` run to find out how bad it is before deciding what to fix.

- [ ] **[Perf] Full history parsed every 30 seconds** — Beyond the bandwidth issue in F-18, at the 5000-entry manifest cap the browser re-parses and re-renders the entire list on every poll. On a phone over cellular that is noticeable. Pagination in Phase 4 fixes the fetch; also check the render path.

- [ ] **[Sec] Coordinates render at full precision** — Six decimal places locates hardware to roughly ten centimetres. Even after the container is private, consider whether the dashboard needs that precision or whether a coarser display would do for everyone except whoever services the unit.

- [ ] **[UI] No indication of data age** — The dashboard shows values without showing when they were last updated, except through the offline pill after three minutes. A visible "last updated" on each panel would make staleness obvious rather than inferred.

- [ ] **[DX] The v2 dashboard is still 1,779 lines in one HTML file** — It moved into `web/static/` intact and unmodified, which was right for the move but is not where it stays. It is now served by our own container behind authentication, so the reason it was one file (no backend, no build step) no longer applies. TypeScript compilation exists; the file needs splitting into modules that use `web/src/api.ts` instead of fetching blobs directly. Scoped with the Phase 4 data work, not before.

---

## Done

<!--
  Format: - [x] **[Category] Title** DONE (YYYY-MM-DD) — how it was resolved.
-->

- [x] **[DX] `make test` collected zero tests** DONE (2026-08-13) — the image only copies `app/` and the compose file did not mount `api/tests`, so `pytest` inside the container found nothing and exited green. Mounted `api/tests` and `api/pytest.ini` read-only in `docker-compose.yml`. A green run now means the 15 tests actually ran.

- [x] **[DX] `email-validator` missing from the image** DONE (2026-08-13) — `EmailStr` in the auth and admin routers needs it; the app failed at import inside the container. `pydantic>=2.9` became `pydantic[email]>=2.9` in `api/requirements.txt`.

- [x] **[Sec] Bootstrap could create an administrator that can never log in** DONE (2026-08-13) — `OCEANKIND_BOOTSTRAP_ADMIN_EMAIL` was written to the database unvalidated, but login validates with `EmailStr`, so a reserved-domain address (e.g. `admin@x.local`) bootstrapped a dead admin silently. `init_db` now refuses to start on an invalid bootstrap email or a bootstrap password under 12 characters, matching the create-user rules.

- [x] **[Sec] SPA fallback served paths outside `/web` on raw `../` requests** DONE (2026-08-13) — `WEB_DIR / full_path` in `main.py` did no containment check, so a client sending an unnormalised `/../app/...` path could read files outside the web root. The fallback now resolves candidates and requires them inside `/web`.
