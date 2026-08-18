# OceanKind Dashboard

Dashboard for an underwater acoustic monitoring network. FastAPI backend, TypeScript
frontend, one container, runs anywhere.

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

`make dev` generates local fixtures, compiles the frontend and starts the container
on http://localhost:8000. No cloud account, no device, no network.

Set `OCEANKIND_BOOTSTRAP_ADMIN_EMAIL` and `OCEANKIND_BOOTSTRAP_ADMIN_PASSWORD` in
`.env` to create the first administrator on a fresh database. The email must be a
real-format address (reserved domains like `.local` are rejected, because login
validates them) and the password at least 12 characters; the API refuses to start
otherwise rather than bootstrap an account that cannot log in.

Then sign in at http://localhost:8000/login. User and site-assignment management
lives at http://localhost:8000/admin (administrators only; operators get a
permission message, not a login loop).

```bash
make test        # backend tests, including the access-control ones
make logs
make down
```

---

## Architecture

```
browser ──cookie session──> FastAPI ──credential──> blob storage (private)
                               │
                               ├── SQLite: users, roles, site assignments
                               └── secrets: twilio, storage, signing keys
```

The browser never touches storage and never holds a credential. The container is
the only thing with keys, and it reads them from the environment.

**Portability** lives in `api/app/services/storage.py`. One `Storage` interface,
a `LocalStorage` for development and an `AzureBlobStorage` for production. S3 is a
third subclass and one line in `get_storage()`; nothing else in the codebase knows
which cloud it is on.

**SQLite** holds only users, roles and site assignments. Detections stay in blob
storage, so the database file stays small enough to copy around. Swapping to
Postgres is a connection string.

---

## Layout

```
├── REQUIREMENTS.md        what this must do, numbered and testable
├── CLAUDE.md              rules for AI assistants
├── api/
│   ├── app/
│   │   ├── core/          config, models, db, security, rate limiting
│   │   ├── routers/       auth, admin, data, devices
│   │   └── services/      storage interface, event queries
│   └── tests/
├── web/
│   ├── src/api.ts         the typed client. the only thing that calls the backend
│   ├── src/generated/     api-types.ts, generated from openapi.json. do not edit
│   └── static/            html shell, css, assets
├── docs/
│   ├── DATA-CONTRACT.md   device to storage. mirrors the canonical copy in Rpi-Detector
│   ├── API-CONTRACT.md    backend to browser. openapi.json is the generated half
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
| `GET/POST/DELETE /api/admin/devices` | device registry. the key appears in the creation response, once |
| `GET /api/devices/config` | signed, clamped device configuration. needs `OCEANKIND_CONFIG_SIGNING_KEY` |

Every data route is authenticated and site-scoped. An operator assigned to one site
receives 403 on another, on every endpoint, and the site does not appear in
`/api/sites` either. That is covered by tests.

---

## Things to know

**Pagination is written, not free.** `api/app/services/events.py` resolves a time
range to date-partitioned blob prefixes and lists only those. Response includes
`scanned_blobs` so the cost is visible rather than guessed.

**Every numeric field can be `null`.** The device serialises non-finite floats that
way, because Python emits `Infinity`, which is not valid JSON and once blanked the
whole dashboard.

**Gaps in power history are data.** Absent buckets are how outages are detected.
Never interpolate them.

**Cookies are `secure` by default**, which requires https. `OCEANKIND_COOKIE_SECURE=false`
for local http development only.

**The frontend has no bundler and no framework.** `tsc` emits ES modules the browser
loads directly. Chart.js and Leaflet stay as they are.
