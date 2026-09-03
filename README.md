# OceanKind Dashboard

Dashboard for an underwater acoustic monitoring network. FastAPI backend, React +
TypeScript frontend, Postgres. Three containers, runs anywhere.

Authentication, users and secrets are **ours**. No managed identity provider, no
cloud-specific runtime. Moving to AWS or a bare server is an environment variable
and one storage class.

Companion repository: [`Rpi-Detector`](https://github.com/rodgpt/Rpi-Detector), the
device that produces what this reads.

---

## Run it

```bash
cp .env.example .env          # then set OCEANKIND_SESSION_SECRET
make dev
```

`make dev` generates local fixtures, builds the images, starts `db`, `backend` and
`frontend`, and applies migrations. The app is on **http://localhost:3000**. No
cloud account, no device, no network.

The backend is also published for debugging on `BACKEND_PORT` (see `.env` — it
defaults to 8000 but is moved when another project on the machine holds that
port). Use :3000 — that goes through nginx, which is the same origin and the same
cookie behaviour as production. Hitting the backend directly is neither.

Set `OCEANKIND_BOOTSTRAP_ADMIN_EMAIL` and `OCEANKIND_BOOTSTRAP_ADMIN_PASSWORD` in
`.env` to create the first administrator on a fresh database. The email must be a
real-format address (reserved domains like `.local` are rejected, because login
validates them) and the password at least 12 characters; the API refuses to start
otherwise rather than bootstrap an account that cannot log in.

Then sign in at http://localhost:3000/login. User, site-assignment and device
management lives at http://localhost:3000/admin (administrators only; operators
get a permission message, not a login loop).

```bash
make test               # backend tests, including the access-control ones
make rebuild            # after dependency or Dockerfile changes
make migrate m="..."    # generate an Alembic revision
make psql               # shell on the database
make logs s=frontend    # follow one service
make down
```

---

## Architecture

```
browser
  └─ https ─> frontend  (nginx, serves the React build)
                 ├─ /            static assets, SPA fallback
                 └─ /api/  ────>  backend  (FastAPI, JSON only)
                                     ├─ db  (postgres, internal, never exposed)
                                     ├─ blob storage (private, credential here)
                                     └─ secrets: twilio, storage, signing keys
```

Three containers. The browser talks only to nginx and never touches storage or
holds a credential. The backend is internal in production; only `frontend` is
reachable. Ports, volumes and deployment constraints are in
[`docs/SERVER-INFRASTRUCTURE.md`](docs/SERVER-INFRASTRUCTURE.md).

**Portability** lives in `backend/app/services/storage.py`. One `Storage` interface,
a `LocalStorage` for development and an `AzureBlobStorage` for production. S3 is a
third subclass and one line in `get_storage()`; nothing else in the codebase knows
which cloud it is on.

**Postgres** holds users, roles, site assignments, device credentials, tuned device
configs — and a **derived index of detection events** (D-021). Object storage
remains the record for detections; the index is a queryable copy of it, rebuildable
from the container, and losing it costs a rebuild rather than data. Schema changes
go through Alembic migrations — never by hand, never by `create_all`.

---

## Layout

```
├── REQUIREMENTS.md        what this must do, numbered and testable
├── CLAUDE.md              rules for AI assistants
├── backend/               FastAPI. JSON only, serves no HTML
│   ├── app/
│   │   ├── core/          config, database, models, security, rate_limit
│   │   ├── routers/       auth, admin, data, devices
│   │   └── services/      storage (portability seam), events, deviceconfig
│   ├── alembic/           migrations. the schema lives here
│   └── tests/
├── frontend/              React + TypeScript + Vite, built into nginx
│   ├── src/api/client.ts  the typed client. the only thing that calls the backend
│   ├── src/api/generated.ts  from openapi.json. do not edit
│   ├── src/pages/         one per route
│   ├── src/components/    shared UI
│   ├── nginx.conf         serves the build, proxies /api/ to the backend
│   └── Dockerfile         node build -> nginx
├── web/                   SUPERSEDED. reference only, see web/README.md
├── docs/
│   ├── DATA-CONTRACT.md   device to storage. mirrors the canonical copy in Rpi-Detector
│   ├── API-CONTRACT.md    backend to browser. openapi.json is the generated half
│   ├── SERVER-INFRASTRUCTURE.md  ports, containers, deployment constraints
│   ├── PROGRESS.md
│   └── TODO.md
└── tools/
    ├── generate_fixtures.py
    └── dump_openapi.py
```

---

## Endpoints

| | |
|---|---|
| `POST /api/auth/login` · `POST /api/auth/logout` · `GET /api/auth/me` | sessions |
| `GET /api/sites` | only sites the caller may see |
| `GET /api/sites/{id}/events` | paginated, filtered by time, type, score, suppressed |
| `GET /api/sites/{id}/status` · `/power` · `/acoustic` · `/ocean` | rollups |
| `GET /api/sites/{id}/clips/{path}` | audio, proxied |
| `GET/POST/PUT/DELETE /api/admin/users` | user and site-assignment management |
| `GET/POST/DELETE /api/admin/sites` | site registry. adding a unit is a data change |
| `GET/POST/DELETE /api/admin/devices` | device registry. the key appears in the creation response, once |
| `PUT /api/admin/devices/{id}/config` | tune thresholds. clamps, signs and publishes the blob |
| `GET /api/devices/config` | read-only debug view of the signed config blob |
| `POST /api/devices/events` | one detection, pushed by the device. idempotent on `event_id` |

Every data route is authenticated and site-scoped. An operator assigned to one site
receives 403 on another, on every endpoint, and the site does not appear in
`/api/sites` either. That is covered by tests.

---

## Things to know

**Detections are answered from an index, not from storage.** `detection_events` in
Postgres is a *derived* copy of the event blobs: one query per page, zero blob
reads, at any window size (D-021). Object storage stays the record and the index
is rebuildable from it — nothing writes to that table but the indexer.

Two paths carry an event to us and that is deliberate (D-022). The device POSTs it
to `/api/devices/events` for latency, and writes the blob for durability. The push
may fail; a weekly reconcile pass then picks the event up from storage, so nothing
is lost and only freshness suffers.

**Audio is never bulk-read.** Clips are fetched one at a time, when a human asks
for one. The event table, the index and the reconcile pass never open a `.wav` —
an event JSON is ~600 bytes against ~960 KB of audio, so the difference between
listing detections and downloading them is roughly three orders of magnitude (F-18).

**Every numeric field can be `null`.** The device serialises non-finite floats that
way, because Python emits `Infinity`, which is not valid JSON and once blanked the
whole dashboard.

**Gaps in power history are data.** Absent buckets are how outages are detected.
Never interpolate them.

**Cookies are `secure` by default**, which requires https. `OCEANKIND_COOKIE_SECURE=false`
for local http development only.

**The backend serves no HTML.** nginx owns everything that is not `/api/`,
including the SPA fallback. If a `StaticFiles` mount appears in the backend, the
old single-container shape is creeping back — see D-019.

**Device configuration travels through storage, not the API.** The backend writes
a signed `sites/{site}/remote_config.json`; the device polls it. `GET
/api/devices/config` is a read-only debug view that returns that blob byte for
byte. This means the storage credential must be **write-capable** — see D-020.

**One backend replica, deliberately.** The login throttle counts failures in
process memory, so a second replica makes it bypassable. See
`docs/SERVER-INFRASTRUCTURE.md` before scaling anything.
