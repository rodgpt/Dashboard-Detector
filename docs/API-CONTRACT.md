# API contract — backend to browser

The second contract. `DATA-CONTRACT.md` governs device to storage; this one governs backend to browser.

**The generated schema is authoritative.** FastAPI derives it from the code, so it cannot drift:

```bash
make openapi          # writes docs/openapi.json
```

This document is the part a generator cannot produce: why the surface is shaped this way, and what a client is obliged to do with it.

Last updated 2026-08-22. Requirement IDs refer to `../REQUIREMENTS.md`.

---

## Shape

Base path `/api`. JSON in, JSON out. Session state in an HttpOnly cookie, never in a header the page's JavaScript can read.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/auth/login` | none | Email and password in, session cookie out |
| `POST` | `/api/auth/logout` | cookie | Clears the cookie |
| `GET` | `/api/auth/me` | cookie | Who am I, what role, which sites |
| `GET` | `/api/sites` | cookie | Site registry, **filtered to what the caller may see** |
| `GET` | `/api/sites/{site}/events` | cookie | Paginated, filtered detections |
| `GET` | `/api/sites/{site}/status` | cookie | `status.json` for that site |
| `GET` | `/api/sites/{site}/power` | cookie | `power_history.json` |
| `GET` | `/api/sites/{site}/acoustic` | cookie | `acoustic_indicators.json` |
| `GET` | `/api/sites/{site}/ocean` | cookie | `ocean_conditions.json` |
| `GET` | `/api/sites/{site}/clips/{path}` | cookie | Audio, proxied. `audio/wav` |
| `GET` | `/api/admin/users` | cookie, admin | List users with their site assignments |
| `POST` | `/api/admin/users` | cookie, admin | Create a user |
| `PUT` | `/api/admin/users/{id}/sites` | cookie, admin | Replace a user's site assignments |
| `DELETE` | `/api/admin/users/{id}` | cookie, admin | Delete a user |
| `GET` | `/api/admin/sites` | cookie, admin | Site registry with its source |
| `POST` | `/api/admin/sites` | cookie, admin | Register a site |
| `PUT` | `/api/admin/sites/{id}` | cookie, admin | Rename, move, activate or deactivate |
| `DELETE` | `/api/admin/sites/{id}` | cookie, admin | Remove a site. Refused while referenced |
| `POST` | `/api/admin/sites/import` | cookie, admin | Seed the table from `_sites.json` |
| `GET` | `/api/admin/index` | cookie, admin | Index drift per site and per day, plus when the pass last ran (R-12.5) |
| `POST` | `/api/admin/index/reconcile` | cookie, admin | Run the reconcile now. `?site_id=` for one, omitted for all |
| `POST` | `/api/admin/index/rebuild` | cookie, admin | Drop a site's index rows and rebuild from storage (R-12.2) |
| `GET` | `/api/admin/devices` | cookie, admin | List devices with last contact time |
| `POST` | `/api/admin/devices` | cookie, admin | Register a device. **The key is in this response only** |
| `DELETE` | `/api/admin/devices/{id}` | cookie, admin | Revoke a device credential |
| `GET` | `/api/admin/devices/{id}/config` | cookie, admin | Effective (clamped) config, version, default or tuned |
| `PUT` | `/api/admin/devices/{id}/config` | cookie, admin | Tune. Clamped on write; adjustments reported back |
| `GET` | `/api/devices/config` | device headers | **Debug view** of the published config blob, byte for byte. Not the delivery path |
| `POST` | `/api/devices/events` | device headers | One detection, pushed. Low-latency path; idempotent on `event_id` (R-6.3, D-022) |
| `GET` | `/api/health` | none | Liveness and which storage backend is wired |

Everything not in that table requires a session. `/api/health` and `/api/auth/login` are the only two exceptions, and neither returns data (R-2.1).

---

## Authentication

`POST /api/auth/login` takes `{ "email": "...", "password": "..." }` and sets `oceankind_session`: HttpOnly, SameSite=Lax, `Secure` unless `OCEANKIND_COOKIE_SECURE=false` for local http development. The cookie is a signed, timestamped user id (itsdangerous); it carries no role and no site list, so revoking access takes effect on the next request rather than at expiry.

Sessions expire after `OCEANKIND_SESSION_HOURS`, default 12.

**Login does not enumerate accounts.** A missing user, an inactive user and a wrong password all return the same `401` with the same body, and cost the same work.

**Login is throttled** (R-2.4): five failures per client-address-and-email inside five minutes returns `429`. Success clears the counter.

Passwords are argon2id. Minimum 12 characters, enforced at creation.

---

## Authorisation

Two roles. `operator` reads the sites assigned to it. `admin` reads every site and manages users.

**Site scoping is enforced per request, on every data route** (R-3.4), not by hiding links in the interface. `GET /api/sites` returns only permitted sites, and every `/api/sites/{site}/...` route re-checks. Guessing a site id returns `403`, not data. There is a test that asserts exactly this.

Admin routes return `403` to an operator, never `404`.

---

## Errors

| Status | Meaning | What the client does |
|---|---|---|
| `400` | Malformed input | Show the message. It is safe to display |
| `401` | No session, or it expired | Redirect to login. Do not retry |
| `403` | Authenticated, not permitted | Show a permission message. Do not retry, do not redirect to login |
| `404` | The resource genuinely is not there, including an absent blob | Render the panel as unavailable, keep the rest of the page |
| `409` | Conflict, e.g. duplicate email | Show the message |
| `422` | Query parameter failed validation | A client bug. Fix the caller |
| `429` | Login throttled | Show the wait. Do not retry automatically |
| `503` | A server-side prerequisite is missing | Currently only `/api/devices/config` without `OCEANKIND_CONFIG_HMAC_KEY`. Loud by design: it must never degrade to an unsigned payload |

Body is FastAPI's `{"detail": "..."}` throughout. `detail` is written to be shown to a user; it never contains a secret, a path or a stack trace (R-4.4).

**`401` and `403` are different and the client must treat them differently.** Conflating them logs a user out every time they open a site they do not have. `frontend/src/api/client.ts` exposes `ApiError.isAuth` and `ApiError.isForbidden` for exactly this.

---

## The site registry

`GET /api/sites` (any session, filtered by permission) and `GET /api/admin/sites` (admin, unfiltered) read one registry with one rule:

**Postgres wins when it has rows; otherwise `_sites.json` in storage.**

`GET /api/admin/sites` returns `source`, which is `database`, `storage` or `empty`. That distinction is surfaced rather than hidden: `storage` means the registry is still the blob fallback and nothing has been managed yet, and `empty` means a fresh container where the first site has to be created before any device can be registered.

The fallback exists so a fixture tree works with no setup. The table exists because nothing writes that blob outside the fixture generator, so a fresh private container had no registry at all — which made `/api/sites` empty and made device registration impossible, since a device credential is always issued against a known site. `POST /api/admin/sites/import` copies the blob into the table, explicitly; it is never done automatically, because silently materialising rows would leave it unclear which side is authoritative.

`site_id` is immutable. It is a storage path segment (`sites/{site_id}/…`), so renaming one would orphan every event, clip and rollup already written under it. `DELETE` is refused with `409` while any device or user assignment still references the site.

The device never reads the registry — it writes to `sites/{site_id}/…` and nothing else — so which side is authoritative is the dashboard's to decide. `DATA-CONTRACT.md` still documents the blob, unchanged, because it remains a valid artifact when present.

---

## Pagination

Only `/events` is paginated, because it is the only unbounded collection.

```
GET /api/sites/zapallar/events?since=2026-08-01T00:00:00Z&until=2026-08-12T00:00:00Z
    &event_type=vessel&min_score=0.5&include_suppressed=true&limit=50&offset=0
```

| Parameter | Type | Default | Bounds |
|---|---|---|---|
| `since` | ISO 8601 datetime | `until` minus 7 days | |
| `until` | ISO 8601 datetime | now | |
| `event_type` | enum | all | `vessel` \| `blast` \| `unknown` |
| `min_score` | float | 0.0 | 0.0 - 1.0 |
| `include_suppressed` | bool | `true` | |
| `limit` | int | 50 | 1 - 500 |
| `offset` | int | 0 | >= 0 |

Response:

```jsonc
{
  "items":   [ /* event blobs, newest first, exactly as DATA-CONTRACT.md defines them */ ],
  "total":   412,       // matching the filter, not the container
  "limit":   50,
  "offset":  0,
  "has_more": true,
  "index_updated_utc": "2026-08-26T14:02:11+00:00"   // or null
}
```

**`scanned_blobs` was removed 2026-08-26, replaced by `index_updated_utc`.** The old field reported how much storage a query touched, which was the number that told you whether it was walking the right prefixes. Served from the index that number is always zero, and a field that keeps returning a plausible count describing no work at all is worse than absent.

What a caller actually needs to know is whether the answer is **current**. A page served from an index that stopped updating three days ago, with no way to tell, is the same class of lie as a device reporting itself healthy while deaf. So the replacement reports freshness: the most recent `indexed_utc` across the queried sites.

**`null` means nothing has ever been indexed for those sites** — a fresh deployment, or an indexer that has never run. It is rendered, not hidden: an empty list of events reads identically whether there were no detections or no data is reaching us, and those mean opposite things.

**Timestamps without an offset are read as UTC.** `?since=2026-08-01T00:00:00` is accepted and treated as UTC rather than rejected. Stated here so it is a convention rather than something inferred from behaviour. The previous implementation compared such a value against an offset-aware one and raised `TypeError` *outside* its guard, so it surfaced as an unhandled `500` — which R-5.6 forbids.

**Ordering is newest first**, by `captured_utc`. The date-partitioned path layout gave this for free while the endpoint read storage; under D-021 it becomes an `ORDER BY` on an indexed column, which is the same answer arrived at more cheaply.

**`include_suppressed` defaults to `true`.** Suppressed detections are real detections whose notification was withheld; hiding them by default is how the record quietly stops matching reality (R-8.2, F-03).

**Filtering is a query against the index, not a walk over storage** (D-021, R-12.1). A page of events costs one Postgres query and **zero** blob reads, at any window size — a 90-day question costs what a one-day question costs, and a cross-site question becomes expressible at all (R-12.7).

*Superseded 2026-08-22 (D-021), corrected here 2026-08-26.* This section previously read "filtering resolves to a prefix listing over the days in the range… a one-day query reads one day of blobs regardless of how many years the container holds." That described the mechanism accurately and its cost misleadingly: listing a prefix is cheap, but the implementation then issued one GET per blob the listing returned, sequentially, and applied `limit`/`offset` in Python afterwards. So `limit=50` cost the same as `limit=500`, and `total` required reading everything. R-5.2 states the outcome for that reason.

**No response is ever served from audio.** Clips are fetched one at a time through the clip route when a human asks for one; nothing in this endpoint, the index or the reconcile pass ever opens a WAV.

---

## Rollup routes

`/status`, `/power`, `/acoustic` and `/ocean` return the blob for that site, unmodified. The backend does not reshape, merge or enrich them. `DATA-CONTRACT.md` is the schema for all four.

Three rules carry through unchanged, and they are the backend's obligation now rather than the browser's:

- **`null` stays `null`.** Any numeric field may be null, meaning absent. Never coerced to zero.
- **Gaps in `power_history.history` stay gaps.** No backfill, no interpolation (R-8.6).
- **An unknown `schema_version` is surfaced, not swallowed.** Event items get `_unknown_schema: true`; the client must render a visible warning and still show what it understood.

A blob that is absent or unparseable returns `404` for that route alone. The other four still answer. One broken source never takes the page down (R-7.3).

---

## Clips

```
GET /api/sites/{site}/clips/2026/08/08/{event_id}.wav
```

Returns `audio/wav`. The path is what `clip.path` carries in the event blob, minus the `sites/{site}/clips/` prefix.

**The browser never receives a storage credential or a SAS token** (R-4.2). Audio is proxied, so the container stays private (R-5.5).

`?play=` deep links already sitting in people's WhatsApp history resolve through this route (R-8.5).

---

## Types

Generated, not hand-written (R-9.5):

```bash
make openapi                 # docs/openapi.json, straight from the app definition
make types                   # web/src/generated/api-types.ts, from that schema
```

Both generated files are committed. A reviewer sees the contract move in the diff, and the frontend compiles against the schema rather than against somebody's memory of it.

**What is typed, and what deliberately is not.**

Every path, every query parameter and every parameter bound is generated, on every route. So is the response body of everything the backend itself composes: `Ok` (login, logout), `Me`, `Health`, `UserOut`, `SitesOut`, and `EventsPage` — the pagination envelope.

The four rollup routes (`/status`, `/power`, `/acoustic`, `/ocean`) and the `items` inside `EventsPage` are typed as plain objects on purpose. They are device blobs, and `DATA-CONTRACT.md` is their schema. Putting a `response_model` over them would make FastAPI **drop any field not in the model**, so the day the device adds a field the backend would silently eat it and the dashboard would never know it existed. Unknown fields must survive to the browser and be surfaced (`_unknown_schema`), not filtered out on the way through. One schema, in one place, and the pass-through stays honest.

The consequence is a real gap and it is worth naming: a typo in `event.captured_utc` in frontend code will not fail the build. Closing it means generating TypeScript types from `DATA-CONTRACT.md` itself, which is tracked in `TODO.md`, not by bolting response models onto the pass-throughs.

`frontend/src/api/client.ts` is the hand-written layer on top: `ApiError` with `isAuth` / `isForbidden`, and the `auth`, `data` and `admin` namespaces.

---

## Devices

**Configuration reaches devices through storage, not through this API** (D-020).

The backend writes `sites/{site_id}/remote_config.json`, signed; the device polls it every 300 s and applies a document only when `config_version` differs from the one in force. The document shape, signature scheme, clamp ranges and unreachable-blob semantics live in `DATA-CONTRACT.md` under **Device configuration**, because the device is the consumer and that file is canonical in the device repository.

`PUT /api/admin/devices/{id}/config` is where an administrator tunes it. That route clamps, signs and publishes in one operation: saving without publishing would leave the panel showing a configuration no device will ever apply. It returns `published_to` (the blob path) and, when the site holds more than one device, `publish_warning` — a site has exactly one configuration blob, so a second device's tune replaces the first's document, and that is said out loud rather than done silently.

With no `OCEANKIND_CONFIG_HMAC_KEY` configured the tune is refused with `503`. It is never persisted-but-unpublished and never published unsigned (R-6.2.1).

`GET /api/devices/config` authenticates with `X-Device-Id` and `X-Device-Key`, not a session cookie (R-6.1). It is a **read-only debugging view**: it returns the stored blob byte for byte and composes nothing of its own. Reading the document here and reading it from storage must never produce two different bytes, because that is precisely how a signature mismatch hides. If nothing has been published for the site it answers `404` — the honest answer, since the device keeps its last valid configuration and never falls back to defaults.

**Historical note.** Until 2026-08-22 this route served a payload it composed itself, with an `expires_utc` and an integer `config_version`. The canonical contract specifies blob transport, a string `config_version` and no expiry; the two sides canonicalised different objects, so configuration would have silently stopped applying. See D-020.

### `POST /api/devices/events` — the low-latency event path (R-6.3, D-022)

Authenticated with `X-Device-Id` and `X-Device-Key`, like the config debug view. The device posts each event as it is detected, in the same shape it writes to the blob (`DATA-CONTRACT.md` is the schema; this route composes nothing of its own and puts no `response_model` over the document, for the same reason the rollup routes do not).

Three properties are contractual and each exists to stop a specific failure:

- **Idempotent on `event_id`** (R-12.3). A re-post is a no-op, not a duplicate. Retries, an ambiguous timeout and an overlapping reconcile are then safe by construction rather than by care.
- **Allowed to fail.** The device MUST continue writing the event blob regardless, and MUST NOT treat a failed post as a lost event. Correctness rests on the reconcile pass (R-12.4), never on this route succeeding.
- **Never the sole record.** Nothing indexed here is absent from storage, which is what keeps the index derived (R-12.2) and keeps the drift metric (R-12.5) meaningful.

*Historical note.* Until 2026-08-26 this section read "specified nowhere yet… stays unspecified until the device stops holding storage credentials of its own." That precondition was wrong: the device keeps its storage credentials and keeps writing the blob. D-022 records why — the event JSON is ~0.06% of the WAV it accompanies, and the blob is what the reconcile compares the index against. Drop it and the reconcile compares Postgres to itself.

*Not in `DATA-CONTRACT.md`.* That file is canonical in `Rpi-Detector` and covers device→storage. A device→backend path is a change to the coupling itself and starts in the device repository.

---

## The detection index

`GET /api/admin/index` reports, per site: blobs in storage over the reconcile window, rows indexed, the **drift** between them, and the days any drift falls on. It lists blob names and runs one query — it opens no blob and indexes nothing, so it is safe to call from a panel that refreshes.

**Non-zero drift is a fault, not a statistic.** It means events exist in storage that the dashboard will not show, which is the same failure as a device reporting itself healthy while deaf.

`last_run_utc` is reported alongside and is `null` until the pass has run. That pairing is the point: **zero drift that has never been checked is not evidence of anything**, and without it "the reconcile has been crashing for a week" looks identical to "the reconcile keeps finding nothing".

`POST /api/admin/index/reconcile` runs the pass on demand. Safe to press twice — every write goes through the indexer, which is idempotent on `event_id` (R-12.3). It does not replace the timer; it exists so somebody investigating drift can act without waiting a day.

`POST /api/admin/index/rebuild` drops a site's rows and repopulates them from object storage. It requires `site_id` and `confirm_site_id` to match, because a destructive action that needs no confirmation is one somebody performs by accident. **This is the proof that the index is derived** (R-12.2): if a rebuild cannot reproduce the same answers, something existed only in Postgres and the index had quietly become a second source of truth. Worth running deliberately, not only when something looks wrong.

---

## Versioning

There is no `/v1` prefix and there will not be one while the browser and the backend ship in the same container from the same commit. If a third client ever appears, this is the first thing to revisit.

Breaking changes to a route change `frontend/src/api/client.ts` in the same commit. CI compiles the frontend against the generated types, so a broken contract is a failed build rather than a runtime blank panel.
