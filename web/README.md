# `web/` — superseded, reference only

**Nothing in this folder runs.** It is not built, not served, and not mounted
into any container. The frontend is `../frontend/` (React + Vite + nginx, its own
container). See D-019.

It is kept for exactly one reason: `static/index.html` is the client's v2
dashboard and the **source material for Phase 2**, which rebuilds its five views
— detecciones, monitoreo acústico, condiciones del mar, análisis, estado del
sensor — as React pages against the API. Deleting it before that work is done
would throw away the only record of what those views contain.

Already ported and dead here:

| here | replaced by |
|---|---|
| `src/api.ts` | `frontend/src/api/client.ts` |
| `src/login.ts`, `static/login.html` | `frontend/src/pages/Login.tsx` |
| `src/admin.ts`, `static/admin.html` | `frontend/src/pages/Admin/` |
| `static/css/auth.css` | `frontend/src/styles.css` |
| `static/assets/` | `frontend/public/assets/` |

Do not fix bugs here. Do not add features here. When the last view leaves
`static/index.html`, this whole folder goes (Phase 2, `docs/PROGRESS.md`).

Two things worth knowing before porting from it:

- `static/index.html` contains **two complete CSS theme layers**. The light one
  at the top is dead — a later `<style>` block overrides it wholesale with
  `!important` and `--mf-*` variables. Port from the dark layer; it is the design
  the client ships. Those tokens are already in `frontend/src/styles.css`.
- It fetches **public blob storage directly from the browser**. That is the
  thing the backend exists to stop (F-07, F-18). Every port goes through
  `frontend/src/api/client.ts`.
