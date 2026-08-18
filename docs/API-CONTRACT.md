# API contract — backend to browser

The second contract. `DATA-CONTRACT.md` governs device to storage; this one governs backend to browser.

**The generated schema is authoritative.** FastAPI derives it from the code, so it cannot drift:

```bash
make openapi          # writes docs/openapi.json
```

This document is the part a generator cannot produce: why the surface is shaped this way, and what a client is obliged to do with it.

Last updated 2026-08-13. Requirement IDs refer to `../REQUIREMENTS.md`.

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
| `GET` | `/api/admin/devices` | cookie, admin | List devices with last contact time |
| `POST` | `/api/admin/devices` | cookie, admin | Register a device. **The key is in this response only** |
| `DELETE` | `/api/admin/devices/{id}` | cookie, admin | Revoke a device credential |
| `GET` | `/api/devices/config` | device headers | Signed configuration. See `DATA-CONTRACT.md` |
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
| `501` | Route exists, not implemented yet | Currently only `/api/devices/config` |

Body is FastAPI's `{"detail": "..."}` throughout. `detail` is written to be shown to a user; it never contains a secret, a path or a stack trace (R-4.4).

**`401` and `403` are different and the client must treat them differently.** Conflating them logs a user out every time they open a site they do not have. `api.ts` exposes `ApiError.isAuth` and `ApiError.isForbidden` for exactly this.

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
  "items":         [ /* event blobs, newest first, exactly as DATA-CONTRACT.md defines them */ ],
  "total":         412,      // matching the filter, not the container
  "limit":         50,
  "offset":        0,
  "has_more":      true,
  "scanned_blobs": 118       // how much storage the query actually touched
}
```

`scanned_blobs` is deliberately in the response. It is the number that tells you whether a query is walking the right prefixes, and it is what F-18 would have made obvious before it became a bill.

**Ordering is newest first**, by `captured_utc`, which the date-partitioned path layout gives for free.

**`include_suppressed` defaults to `true`.** Suppressed detections are real detections whose notification was withheld; hiding them by default is how the record quietly stops matching reality (R-8.2, F-03).

Filtering resolves to a prefix listing over the days in the range (R-5.2). A one-day query reads one day of blobs regardless of how many years the container holds.

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

`web/src/api.ts` is the hand-written layer on top: `ApiError` with `isAuth` / `isForbidden`, and the `auth`, `data` and `admin` namespaces.

---

## Devices

`GET /api/devices/config` authenticates with `X-Device-Id` and `X-Device-Key`, not a session cookie. A compromised browser cannot reconfigure a device (R-6.1). Full payload, signature scheme, clamp ranges and expiry semantics are in `DATA-CONTRACT.md` under **Device configuration**, because the device is the consumer and the device repository mirrors that file.

Currently returns `501`. The route, the credential check and the settings entry exist; the signing and clamping do not.

**Credential issuance** (R-6.1, D-017): `POST /api/admin/devices` generates the key server-side and returns it in the creation response, once. It is stored only as an argon2 hash; there is no route that reads it back, by construction. A lost key means revoke and reissue. The device's `site_id` must exist in `_sites.json` — sites are data, and a typo here would otherwise mint a credential for a site that never existed. Every successful device authentication stamps `last_seen`, which the admin panel shows as provisioning feedback: a freshly keyed unit that never connects is visible, not assumed working. `DELETE` is revocation — the unit gets `401` on its next poll and keeps its last valid configuration, per the expiry semantics in `DATA-CONTRACT.md`.

A wrong device id and a wrong key return the same `401` with the same body; the response does not say which half was wrong.

`POST /api/devices/events` is specified nowhere yet. It is R-6.3, a `SHOULD`, and it stays unspecified until the device stops holding storage credentials of its own.

---

## The `contract` block (temporary)

While `OCEANKIND_CONTRACT_VERSION=1`, every response carries an extra `contract` object:

```jsonc
{
  "version": 1, "normalized_to": 2,
  "unknown_fields": ["event_type", "detector"],
  "time_is_upload": true,
  "suppressed_undercounts": true,
  "note": "..."
}
```

It is absent under v2. A client must treat its presence as "label these fields as unknown", never as a reason to hide them or fill them in. It exists because the alternative, silently rendering a guess, is the same class of failure as a device reporting itself healthy while deaf.

Everything else in this document is identical under both versions. That is the point of the adapter: the API surface does not change, only what the backend had to do to produce it. See D-016, and `make drop-v1`.

---

## Versioning

There is no `/v1` prefix and there will not be one while the browser and the backend ship in the same container from the same commit. If a third client ever appears, this is the first thing to revisit.

Breaking changes to a route change `web/src/api.ts` in the same commit. CI compiles the frontend against the generated types, so a broken contract is a failed build rather than a runtime blank panel.
