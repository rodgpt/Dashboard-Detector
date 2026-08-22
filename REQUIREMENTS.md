# Technical requirements — OceanKind dashboard

A dashboard with authentication, backed by an API we own, that runs anywhere.

`MUST` is contracted. `SHOULD` is expected unless there's a reason. Last updated 2026-08-22.

---

## Scope

Three containers: a Postgres database, a FastAPI backend serving JSON only, and a React frontend served by nginx which proxies `/api/` to the backend. The backend authenticates users, holds every secret, and serves paginated data read from blob storage (D-019).

**Portable by construction.** No cloud-specific auth, no cloud-specific runtime. Azure today because that's where the storage is. AWS, or your own server, by changing an environment variable and one storage class.

We build the plumbing. The client provides the detection science.

---

## R-1 Portability

**R-1.1 MUST** run as a single Docker container with no dependency on any cloud provider's identity, runtime or configuration service.

*Test:* `docker compose up` works on a laptop with no cloud account.

**R-1.2 MUST** access object storage through one interface with swappable implementations. Azure Blob today; adding S3 is one new class and no change anywhere else.

*Test:* the fixture-backed local implementation and the Azure one are interchangeable by environment variable.

**R-1.3 MUST** take all configuration from environment variables. No config baked into the image.

**R-1.4 MUST NOT** use any managed identity provider. Authentication is ours.

---

## R-2 Authentication

**R-2.1 MUST** require login for the entire application. No page and no endpoint returns data to an unauthenticated caller, except the login route itself and a health check.

**R-2.2 MUST** store passwords hashed with a modern algorithm and a per-user salt. Never reversible, never logged.

**R-2.3 MUST** issue a session credential on login, expire it, and allow logout to invalidate it.

**R-2.4 MUST** implement rate limiting on login. Repeated failures are throttled.

**R-2.5 MUST** provide `login`, `logout` and `me`.

---

## R-3 Users and access

**R-3.1 MUST** support distinct users with differentiated access, per the presupuesto: which users see which sites is data, not code.

**R-3.2 MUST** provide two roles at minimum: an operator who reads their assigned sites, and an administrator who additionally manages users and assignments.

**R-3.3 MUST** provide an administration screen to create and remove users and assign them to sites. This is the "panel de administración" the contract promises and it must not require cloud console access.

**R-3.4 MUST** filter every data response by the caller's site permissions. A user with no access to a site cannot read it by guessing the URL.

*Test:* an operator scoped to one site receives 403 for the other, on every endpoint.

**R-3.5 MUST** ship a way to create the first administrator on a fresh deployment without an existing session.

---

## R-4 Secrets

**R-4.1 MUST** hold every secret server-side: storage credentials, Twilio, the session signing key, the device config HMAC key (`OCEANKIND_CONFIG_HMAC_KEY`), per-device keys.

**R-4.2 MUST NOT** ever send a secret, a storage credential or a SAS token to the browser.

**R-4.3 MUST** refuse to start if a required secret is missing, rather than falling back to a default.

**R-4.4 MUST NOT** log secrets, even at debug level.

---

## R-5 Data access

**R-5.1 MUST** serve paginated, filtered detections. Filters: site, time range, event type, minimum score, suppressed. The browser receives a page, never the full history.

*Test:* a request for 50 events returns 50 records regardless of how many exist.

**R-5.2 MUST** resolve time and site filters by reading only the relevant date-partitioned blob prefixes, not by scanning everything.

**R-5.3 MUST** serve sites, status, power history, acoustic indicators and ocean conditions.

**R-5.4 MUST** serve audio clips through the API. The browser never holds a storage credential.

**R-5.5 MUST** keep the storage container private.

**R-5.6 MUST** validate everything read from storage against the data contract and degrade visibly rather than crashing on a malformed or unknown-version blob.

**R-5.7 SHOULD** support conditional requests so unchanged data is not re-sent.

---

## R-6 Device-facing

**R-6.1 MUST** authenticate devices separately from users, with a per-device credential. A compromised browser session cannot write.

**R-6.2 MUST** publish signed, clamped configuration to devices by **writing `sites/{site_id}/remote_config.json`**, which the device polls and verifies. Replaces the unsigned, unclamped config blob that anything holding the storage key could rewrite (F-10).

*Revised 2026-08-22 (D-020).* This was built as `GET /api/devices/config`. The canonical contract specifies blob transport, and the two sides canonicalise different objects, so pointing the device at the endpoint would fail every signature check **silently** — configuration would simply stop applying. The endpoint may remain as a read-only debugging view returning byte-identical content.

**R-6.2.1 MUST** hold the signing key in `OCEANKIND_CONFIG_HMAC_KEY`, and refuse to publish rather than publish unsigned when it is absent.

**R-6.3 SHOULD** accept event uploads from devices, so the device stops needing storage credentials of its own.

---

## R-7 Failure behaviour

**R-7.1 MUST** make every failure visibly failed in the interface. Stale data rendered as current is the worst possible output from a monitoring tool.

**R-7.2 MUST** show, per panel, when data was last successfully loaded.

**R-7.3 MUST** survive any single data source being absent or malformed, without taking the rest down.

**R-7.4 MUST** surface device health prominently. A unit reporting `detector_ok: false` or a falling duty cycle must look different at a glance, without opening a tab.

---

## R-8 Interface

**R-8.1 MUST** keep the five existing views: detections, acoustic monitoring, sea conditions, analysis, sensor status. Plus login and administration.

**R-8.2 MUST** show suppressed detections, marked, never hidden. Any filter that hides events must be visible.

**R-8.3 MUST** distinguish `vessel`, `blast` and `unknown` visually.

**R-8.4 MUST** display `captured_utc` as the event time, not upload time.

**R-8.5 MUST** support `?play=` deep links against **v2** clip paths, so a link shared from the dashboard resolves for anyone with permission on that site.

*Revised 2026-08-22 (D-020).* This previously required links already sent over WhatsApp to keep resolving. Those point at v1 blob names in the prototype container, which is frozen, in a different account, and read by nothing we ship — the canonical contract states "no deep-link preservation across the boundary". They cannot resolve and pretending otherwise would be the false claim, not the broken link. A link to a clip that is absent must say so visibly (R-7.1), which also covers the suppressed case: a suppressed event carries a `clip.path` whose audio was deliberately never kept.

**R-8.6 MUST** preserve gaps in power history. Absent buckets are how outages are detected; never interpolate.

**R-8.7 MUST** keep the interface in Spanish.

**R-8.8 SHOULD** meet WCAG 2.2 AA. Colour is never the only signal.

**R-8.9 SHOULD** stay usable on a phone.

---

## R-9 Stack and build

**R-9.1 MUST** be FastAPI on the backend and React 18 + TypeScript + Vite on the frontend, per the `lynchLocalDev` protocol variant (D-019).

**R-9.2 MUST** use PostgreSQL for users, roles, site assignments and device records, in its own container with a named volume. Detections stay in blob storage. Schema changes go through Alembic migrations, never by hand.

*Revised 2026-08-21 (D-019).* This previously mandated SQLite as "one file, no server". On a container host the filesystem is ephemeral, so that file destroys every user, device credential and tuned device config on the first restart.

**R-9.3 MUST** deploy as **separate backend and frontend containers**. The frontend builds to static assets served by nginx, which proxies `/api/` to the backend over the internal network. The backend serves no HTML and no static assets.

*Test:* the frontend image serves the interface with the backend container stopped, and returns a visible failure for data rather than a blank page.

*Revised 2026-08-21 (D-019).* This previously forbade a bundler and a frontend framework — a rule inherited from the static-site protocol variant this repository was wrongly scaffolded on.

**R-9.4 MUST** be developable end to end against local fixtures with no cloud account.

**R-9.5 MUST** type the API contract once and share it, so the frontend cannot drift from what the backend returns.

---

## R-10 Contract conformance

**R-10.1 MUST** keep `docs/DATA-CONTRACT.md` matching the canonical copy in `Rpi-Detector`. CI enforces it.

**R-10.2 MUST** update the contract in the same change as any code assuming a new field.

---

## R-11 Contract compatibility — WITHDRAWN 2026-08-22 (D-020)

Required the backend to read the v1 blob layout and return v2 shapes while the production units still wrote v1. **The premise is gone:** neither we nor the client can reach the v1 unit, and the canonical `DATA-CONTRACT.md` is now v2-only and normative.

It did its job. R-11.2 confined every line of v1 knowledge to one module and marked blocks, which is exactly why the removal was mechanical rather than archaeological — 11 blocks, 3 files, no dangling references, the v2 suite green.

Reading the frozen prototype container, if it is ever wanted, is a one-off offline import and belongs to neither codebase.

---

## Out of scope

Detection science. Deploying to the production devices. A database for detections. Any managed identity provider.

---

## Open, blocked on the client

In `Rpi-Detector/docs/CLIENT-DEPENDENCIES.md`. Affecting this codebase: `ram_total_mb` and `ram_used_mb` are rendered but not produced; `deg` is rendered but not produced; the acoustic aggregator exists in neither repository; and whether detections mean vessels, blasts or both (F-21). None block R-1 through R-9.
