# Decisions

Stack-wide decisions live here, at the root, because they feed downward. A decision recorded here becomes concrete tasks in `raspberry-pi/docs/PROGRESS.md` and `dashboard/docs/PROGRESS.md`. Never record a stack-level decision inside one codebase.

Domain-only choices that affect nothing outside their folder can live in that folder's `PROGRESS.md` instead. If in doubt, put it here.

**Statuses.** `OPEN` means nobody has decided. `BLOCKED` means it cannot be decided until something external happens. `PROPOSED` means there is a recommendation waiting for a yes. `DECIDED` means it is settled and has trickled down. `DEFERRED` means deliberately not now.

**Format.** Context, options, decision, consequences, and what it trickles into. A decision with no "trickles into" has not actually landed.

---

## Index

| ID | Status | Decision | Blocks |
|---|---|---|---|
| D-001 | DECIDED | Folder structure and documentation layout | — |
| D-002 | OPEN | SD card protection method | Runbook, OTA design |
| D-003 | BLOCKED | Backend platform | Phase 2 entirely |
| D-004 | PROPOSED | No datastore. Storage layout plus blob index tags | Phase 2 data model |
| D-005 | OPEN | Reconciling the deployed layout with this one | First deployment |
| D-006 | PROPOSED | Capture mechanism for the async pipeline | Phase 1 core work |
| D-007 | PROPOSED | Multi-device blob layout | Both codebases, Phase 1 |
| D-008 | PROPOSED | What happens to cooldown-suppressed detections | Detection semantics |
| D-009 | BLOCKED | Which ADC is actually installed | Any hardware change |
| D-010 | BLOCKED | Which user the service runs as | Provisioning, F-03 severity |
| D-011 | DEFERRED | Compute platform migration | Nothing yet |
| D-012 | OPEN | Documentation language | All future docs |
| D-013 | DECIDED | Two repositories, split by deployment target | Layout, cross-references, CI |
| D-014 | DECIDED | Detector registry, not a selector. Both detectors kept | Phase 2, data contract |
| D-015 | DECIDED | Scope boundary: we build plumbing, client provides detection science | Everything |
| D-016 | DECIDED | Device leads on v2, dashboard follows through a removable adapter | — |
| D-017 | DECIDED | Device credential provisioning on the bench, through the issuance API | R-6.1 shape |
| D-018 | PROPOSED | Fleet-scale credential lifecycle: rotation over the wire, enrollment | R-6.3 scope |
| D-019 | DECIDED | Wrong protocol variant. Rebuild on `lynchLocalDev`: real backend/frontend divide | R-9, every phase |

---

## D-001 — Folder structure and documentation layout

**Status:** DECIDED, 2026-08-02

**Context.** Thirty files in one flat directory, with two Python systems that looked equally live and a provisioning script that installed the wrong one.

**Decision.** Four top-level folders: `raspberry-pi/`, `dashboard/`, `legacy/`, `docs/`. Each code folder is a self-contained root with its own `README.md`, `CLAUDE.md` and `docs/`. Shared concerns live in the top-level `docs/` umbrella. `DECISIONS.md` sits at the root.

**Consequences.** `requirements.txt` moved to `legacy/` because it described the prototype, so the production system currently has no dependency manifest. `raspberry-pi/scripts/setup.sh` still points at an entry point that is now in `legacy/`.

**Trickles into.** `raspberry-pi/docs/PROGRESS.md` Phase 1: write a real manifest, fix the provisioning script.

---

## D-002 — SD card protection method

**Status:** OPEN

**Context.** `protect_sd.sh` currently enables the Raspberry Pi OS whole-root overlay via `raspi-config nonint do_overlayfs 0` and also sets `/boot` read-only. This collides with two things: the telemetry CSV is written to `/boot/firmware` and therefore fails silently (F-16), and the clips directory is symlinked into RAM with no cleanup, which is a memory exhaustion path (F-03).

**Options.**

Whole-root overlayfs as today. Simplest, already working, but every persistent write needs a deliberate escape hatch and the OTA process has to disable and re-enable it, which is the two-reboot dance that can strand the node.

A dedicated writable partition with a read-only root. More setup, but telemetry and state get a real home, and the OTA process no longer has to toggle anything.

Read-write root with aggressive write minimisation. Simplest mentally, relies entirely on discipline, and one careless log line degrades the card.

**Why it is still open.** This choice determines the OTA design, where runtime state lives, and half the runbook. It should be decided before the OTA work in Phase 1, not during.

**Trickles into.** `Rpi-Detector/docs/RUNBOOK.md` (currently a stub, waiting on this), `raspberry-pi/docs/ARCHITECTURE.md` filesystem strategy, `raspberry-pi/docs/PROGRESS.md` Phase 3.

---

## D-003 — Backend platform

**Status:** BLOCKED on Azure access

**Context.** Phase 2 needs a backend. The dashboard currently reads public blobs directly, which is the root cause of most security findings. What matters for tracking is the **scheme**, not the product: what the endpoints are, what authenticates, what holds the credentials. The product choice should be made late and recorded here.

**Options under consideration.** Azure Functions as a standalone HTTP API. Azure Static Web Apps with a managed API, which is interesting because the dashboard is already static-hosted on Azure and this bundles hosting, an API surface and a managed authentication layer in one product, potentially closing two findings at once. Azure Container Apps if the API outgrows serverless. Something non-Azure if there is a reason, though staying inside the existing subscription is worth real weight given the storage account, the IoT Hub and the static hosting already live there.

**Explicitly not decided.** FastAPI plus Postgres is the default elsewhere and is not obviously right here. Do not assume it.

**What to do before deciding.** Verify current capabilities and pricing from Microsoft's own documentation rather than from memory, per the research pipeline in `docs/research/RESEARCH.md`. Write it up as an analysis doc.

**Trickles into.** `Rpi-Detector/docs/BACKEND-SCHEME.md`, and Phase 2 in both `PROGRESS.md` files.

---

## D-004 — Backend datastore

**Status:** PROPOSED, revised 2026-08-08. Likely answer: no datastore at all.

**Context.** The assumption was that filtering and pagination require an index, and `Rpi-Detector/docs/IMPROVEMENT_REPORT.md` §3.5.2 proposed Cosmos DB while conceding SQLite would suffice. Checking what Azure Blob Storage actually does server-side changes that conclusion.

**What storage already provides.**

*Path sharding.* One blob per event under a per-device, per-date prefix makes "device X, last 24 hours" a prefix listing. No index, no query engine, no cost. This is the same change D-007 requires to kill the manifest race, so it is already on the roadmap and the filtering capability comes free with it. Time and device slicing is a path problem, not a query problem.

*Blob index tags.* Up to 10 tags per blob, keys 1-128 characters, values up to 256, 768 bytes per tag. Find Blobs by Tags supports `=`, `>`, `>=`, `<`, `<=`, `AND` and `@container` scoping. Enough for device, event type and confidence filtering server-side. Constraints that matter: comparison is lexicographic so numeric values must be zero-padded; there is no `OR` and no ordering in the query; indexing is usually sub-second but can lag up to ten minutes, which rules it out as the path for a live alert view; requires a general-purpose v2 account; small fixed monthly cost per tag.

*Query Blob Contents.* SQL over a single CSV or JSON blob, returning only matching rows. Block blobs only, 256 KiB maximum query expression, billed on data scanned and data returned. Good fit for the telemetry CSV behind the power chart. Scoped to one blob, so it does not span files.

*Conditional requests.* ETag and `If-None-Match` return 304 with no body when nothing changed. Not filtering, but the cheapest available reduction in polling cost and directly relevant to the Static Web Apps bandwidth cap.

**Proposal.** No datastore. Per-device, per-date blob paths, index tags for the few genuinely queryable attributes, conditional requests on the status endpoint, and client-side filtering within a bounded fetched window. At a few hundred detections a year this carries the system at a hundred times current volume.

**Reopen when.** A requirement appears for `OR` conditions, sorting on arbitrary fields, cross-device aggregates, or joins. None are on the roadmap.

**Consequence for the backend.** It shrinks. The backend is not there to be a query engine; it is there because there is nowhere else to put a secret. Note that Find Blobs by Tags needs a SAS carrying the Filter permission, so the backend still wants to be the caller rather than the browser, but it needs no database behind it.

**Trickles into.** `Rpi-Detector/docs/BACKEND-SCHEME.md`, D-003, D-007, and F-18 on the dashboard side.

---

## D-005 — Reconciling the deployed layout with this one

**Status:** OPEN

**Context.** `update_oceankind.sh` runs `git pull origin main` against a remote at `~/oceankind/code` on the device. This working copy has no version control and no link to that remote. After the restructure the two layouts have diverged.

**Options.** Restructure the remote to match this and update the OTA paths, which is clean but means the next update is a layout migration on a node with no rollback. Or keep the deployed layout flat and treat this repository as the source that gets flattened on deploy, which is safer short term and permanently confusing. Or fold this into the A/B OTA work, so the first A/B deployment is also the layout migration and the rollback path covers it.

**Position.** The third is the only one that does not require a risky one-way step. It does mean nothing deploys until the OTA work is done.

**Trickles into.** `raspberry-pi/docs/PROGRESS.md` Phase 3, `Rpi-Detector/docs/RUNBOOK.md`.

---

## D-006 — Capture mechanism for the async pipeline

**Status:** PROPOSED

**Context.** The main loop calls `arecord` as a blocking subprocess per clip. The whole point of Phase 1 is that capture never stops.

**Options.** A long-running `arecord` piped to stdin, read by a capture thread into a ring buffer. Keeps the existing tool, no new dependency, straightforward to reason about. Or `sounddevice` with a callback and a queue, which `legacy/modular-prototype/audio_capture.py` already implements correctly, including detecting the device by name, and which both prior audits recommend recovering.

**Proposal.** Port the `sounddevice` approach forward, because the working code exists, it solves the hardcoded device index (F-15) in the same move, and callback-driven capture is the right shape. Verify memory behaviour on the 512 MB bench unit before committing.

**Consequence either way.** A bounded queue with an explicit drop policy and a published drop counter. On slower hardware an unbounded queue turns a deaf window into a silent backlog, which is the same failure wearing a different hat.

**Trickles into.** `raspberry-pi/docs/PROGRESS.md` Phase 2, `raspberry-pi/docs/ARCHITECTURE.md` threading model, `docs/DATA-CONTRACT.md` for the new status fields.

---

## D-007 — Multi-device blob layout

**Status:** PROPOSED

**Context.** Everything writes to a single flat container. `manifest.json` is downloaded, modified and re-uploaded on every alert, which already races against the retry path and will silently lose data with a second device (F-14). A second unit is confirmed for roughly six months out.

**Proposal.** Move to `devices/{device_id}/...` and replace the shared manifest with append-only per-event blobs. This removes the race rather than mitigating it, and it makes the second unit a configuration change rather than a rewrite.

**Consequences.** This is a deliberate, coordinated break of the data contract. The Pi and the dashboard have to change together. Existing history needs a migration script. Every WhatsApp alert already sent contains a `?play=` deep link built on the old naming, and those links must keep resolving.

**Trickles into.** Both `PROGRESS.md` files, Phase 4. `docs/DATA-CONTRACT.md` needs a versioned before-and-after.

---

## D-008 — What happens to cooldown-suppressed detections

**Status:** PROPOSED

**Context.** F-03. A detection inside the 600-second cooldown currently falls through both branches: no upload, no manifest entry, no counter, and the clip is never deleted. A blast sequence appears in the data as a single event.

**The real question.** The cooldown exists to avoid spamming WhatsApp. It should never have governed whether an event is recorded. Notification rate-limiting and data retention are different concerns that got fused.

**Proposal.** Separate them. Suppressed detections are recorded as entries flagged `suppressed`, with no notification sent. The clip is deleted on every path regardless. The dashboard shows suppressed events distinctly rather than hiding them, since a hidden default filter on a blast-detection list is a way to mislead someone about how often blasts happened.

**Consequences.** The manifest becomes a truthful record, which changes what any frequency statistic derived from it says. That is the point, and it is worth telling the client explicitly, because their historical numbers undercount.

**Trickles into.** `raspberry-pi/docs/PROGRESS.md` Phase 1, `dashboard/docs/PROGRESS.md`, `docs/DATA-CONTRACT.md` manifest schema.

---

## D-009 — Which ADC is actually installed

**Status:** BLOCKED on field confirmation

**Context.** The code references a HifiBerry DAC+ ADC Pro. A separate system diagram shows a Raspberry Pi Codec Zero. Both prior reports flag the contradiction and neither resolves it.

**Why it matters.** Capture quality determines whether distant, heavily attenuated blasts are detectable at all, and it constrains any future board change. `Rpi-Detector/docs/IMPROVEMENT_REPORT.md` §2.5 argues ADC quality matters more than compute for detection range.

**What is needed.** Someone with physical or SSH access runs `aplay -l` and `arecord -l` on the unit and reports the card name.

**Trickles into.** `raspberry-pi/docs/HARDWARE.md`, D-011.

---

## D-010 — Which user the service runs as

**Status:** BLOCKED on field confirmation

**Context.** F-17. `setup.sh` hardcodes `/home/pi` and `SERVICE_USER="pi"`. `protect_sd.sh` defaults to `marfutura` and creates the clips symlink in that user's home. If they ran as different users, `Path.home()` at runtime resolves somewhere the SD protection does not cover.

**Why it matters.** It determines whether F-03 fills RAM or wears the SD card. Different urgency, different fix.

**What is needed.** `systemctl cat oceankind` on the unit, and `ls -la ~/oceankind/` for the user it names.

**Related free diagnostic.** Does the dashboard's power chart render? If yes, the SD is unprotected. If empty, protection is on and telemetry has been discarded. It cannot currently be both.

**Trickles into.** `raspberry-pi/docs/PROGRESS.md` Phase 1, D-002.

---

## D-011 — Compute platform migration

**Status:** DEFERRED

**Context.** `Rpi-Detector/docs/IMPROVEMENT_REPORT.md` §2 argues the Pi 4 is over-specified: 3.5W for a workload that is one blocking recording, a small FFT and a 53-parameter dot product. It recommends the Pi Zero 2W, or an ESP32-S3 if a simpler ADC suffices.

**Decision.** Not now. It matters only at ten or more units, the ESP32 path means porting feature extraction to C, and the current unit works.

**Free intelligence.** The bench unit is a Zero 2W, which is exactly the recommended target. Every hour of Phase 1 validation on it de-risks this decision at no extra cost. Record memory and feature-extraction timings while working there.

**Reopen when.** Multi-unit rollout is confirmed with numbers, and D-009 is answered.

---

## D-012 — Documentation language

**Status:** OPEN

**Context.** The dashboard interface is Spanish. Code comments in the production monolith are Spanish. The client-facing scope note is Spanish. The audits exist in both. Internal documentation is currently English.

**The question.** Whether internal docs stay English while everything client-facing is Spanish, or the whole repository moves to Spanish. Mixed is the current state and it is the least defensible of the three, because nobody knows which to write next.

**Constraint either way.** The dashboard UI stays Spanish. That is not in question.

**Trickles into.** Everything written from here on. Worth settling early and cheaply.

---

## D-013 — Two repositories, split by deployment target

**Status:** DECIDED, 2026-08-08

**Context.** The client owns two repositories: `github.com/rodgpt/Rpi-Detector` and `github.com/rodgpt/Dashboard-Detector`. Development and deployment both happen there.

**Decision.** Two repositories, split along the deployment boundary. The dashboard deploys via GitHub Actions to Azure static hosting. The device pulls its own repository over cellular. A monorepo would make the Pi clone a dashboard it never runs, onto an SD card over a metered link, and would fire Actions on every device commit without path filters. Deployment mechanics outweigh documentation convenience, and an earlier recommendation for a single repository was wrong on this point.

**Layout.**

`Rpi-Detector` is the current tree minus `dashboard/`: umbrella `CLAUDE.md`, `DECISIONS.md`, `docs/`, `raspberry-pi/`, `legacy/`. Every existing `../docs/...` reference from inside `raspberry-pi/` continues to resolve, so this costs no documentation churn.

`Dashboard-Detector` is the current `dashboard/` folder with its own `CLAUDE.md`, `src/` and `docs/`.

Locally, clone `Dashboard-Detector` into `Rpi-Detector/dashboard/` and gitignore that path. The working tree then looks identical to today, both relative chains resolve during development, and each half pushes to its own remote.

**Consequence: the data contract needs enforcement.** `docs/DATA-CONTRACT.md` is canonical in `Rpi-Detector` and mirrored into `Dashboard-Detector/docs/`. A step in the dashboard's Actions workflow fetches the canonical copy and fails the build on any difference. This turns the unenforced coupling described in `docs/ARCHITECTURE.md` into a hard gate, and it is only available because the repositories are separate.

The dashboard's remaining outward references become GitHub URLs rather than relative paths.

**Still open.** Whether the repositories are public. The Twilio token is present in the code that would be committed, so if public, F-04 becomes an emergency at first push rather than a serious item.

**Trickles into.** `Rpi-Detector/docs/MOVES.md`, the dashboard's relative links, `dashboard/docs/PROGRESS.md` (add the CI contract check), D-005.

---

## D-014 — Detector registry, not a selector

**Status:** DECIDED, 2026-08-08

**Context.** F-21: the device detector was replaced with a PSD tonal-peak algorithm that cannot fire on a sub-second broadband event, while every project document describes a blast detector. The client is unavailable to resolve it and work should not stop.

**Decision.** Keep both detection paths and run them as an ordered chain that emits typed events. Not a selector.

A selector implies the detectors are alternatives. They are not: a blast is impulsive and broadband, a vessel is sustained and narrowband. They look for opposite characteristics in the same audio, so the useful operation is to run both and label what came out, not to choose.

There is also an existing selector, `DETECTION_MODE` with `ml`/`rms`/`auto`, which cannot work (F-01). It is replaced, not supplemented. Two broken selectors is the failure mode to avoid.

**Shape.**

```
raspberry-pi/src/detectors/
    __init__.py      registry, ordered execution, common interface
    psd_tonal.py     detect(clip) -> {type:"vessel", score, meta} | None
    ml_mfcc.py       detect(clip) -> {type:"blast",  score, meta} | None
```

Configuration is one ordered list, not a choice: `OCEANKIND_DETECTORS="psd_tonal,ml_mfcc"`. Every hit carries `event_type` and `detector` into the manifest entry. Both fields are contract additions and go into `docs/DATA-CONTRACT.md` in the same change.

`detector` is recorded per event specifically because the detector already changed once silently, around mid-July, and the manifest now spans two populations with no way to tell them apart. This must not be able to happen again without leaving a trace.

**Constraints this places on us.** The interface must express any event type the client later wants, including ones neither detector produces today. No detector may be able to lose an event through our plumbing. Every threshold must be remotely tunable and clamped, so the client can tune without a firmware update, which is the direct enabler for D-015.

**Cost.** Running both means both feature paths execute per clip. Irrelevant once the async pipeline lands, since detection is a worker; meaningful before then, because it lengthens the deaf window. Sequence the registry with or after the Phase 2 refactor, not before.

**Explicitly not decided here.** Which detector is correct, whether either works, and what the thresholds should be. See D-015 and `Rpi-Detector/docs/CLIENT-DEPENDENCIES.md`.

**Hold.** Do not change which detector runs on a live unit while the client is away. Building the capability is safe; altering the behaviour of a deployed monitoring system without its owner is not.

**Trickles into.** `raspberry-pi/docs/PROGRESS.md` Phase 2, `docs/DATA-CONTRACT.md`, F-01, F-21, F-23, F-24.

---

## D-015 — Scope boundary: plumbing, not water

**Status:** DECIDED, 2026-08-08

**Context.** F-21 raises questions about detection correctness that are not answerable by software work, and the engagement has finite hours.

**Decision.** We build the plumbing. The client provides the water.

Ours: capture, queueing, the classification harness, transport, retry, storage layout, security, updates, telemetry, health reporting, the dashboard. Everything that carries a detection from hydrophone to human.

Theirs: what signal to look for, whether a detector works, threshold values on scientific grounds, the model, labelled validation audio.

**The obligation this creates.** The boundary is only honest if the plumbing never silently constrains the water. Three things stay ours because of that: the detector interface must express any event type, no event a detector produces may be lost by our code, and every threshold must be remotely tunable without a firmware update. A system where the client cannot tune without us is one where we have taken their half by accident.

**Consequence for deployment.** We cannot physically reach the production units. Development and testing run against our own hardware and our own Azure subscription. The contracted work can therefore be completed in full without any of it reaching the field. Who deploys, and when, is a client-side dependency that must be named before the final week. See `Rpi-Detector/docs/CLIENT-DEPENDENCIES.md` item 11.

**Trickles into.** Phase 3 acceptance criteria, `Rpi-Detector/docs/CLIENT-DEPENDENCIES.md`, `CLAUDE.md`.

---

## D-016 — Device leads on v2, dashboard follows through a removable adapter

**Status:** DECIDED, 2026-08-13

**Context.** The device has no rollback and no physical access, so shipping it with the wrong output shape is the expensive mistake. The dashboard has neither constraint. Meanwhile the two production units still write v1 and the client owns deployment, so on the day we hand over they will still be speaking v1.

**Decision.** The device writes v2 from the first line of Phase 2, into our own testing container. No dual write on our side. The dashboard is built for v2 only, and reads v1 through one adapter that converts on the way in.

**The rule that makes it safe.** v1 never crosses the storage boundary. `api/app/services/legacy_v1.py` returns v2 shapes and nothing else. No router, no response model, no line of frontend code contains the string `manifest.json`. Nothing downstream can grow a dependency on v1, because nothing downstream ever sees it.

**Switching** is `OCEANKIND_CONTRACT_VERSION=2`. **Removing** is `make drop-v1`, which deletes the adapter, its tests, itself, and every block marked `LEGACY-V1-BEGIN .. LEGACY-V1-END`. Rehearsed: the v2 suite passes with the layer fully removed and no trace of v1 left in the tree.

**What v1 cannot give us, and what we do about it.** `event_type` and `detector` were never written, so both read `unknown`. `suppressed` detections were discarded rather than flagged (F-03), so historical totals undercount. `timestamp` is upload time, not capture time. Every response carries a `contract` block stating exactly this, so the interface labels the gaps instead of rendering a guess. Inventing plausible values here would be the same failure as a device reporting itself healthy while deaf.

**Convenience worth recording.** The production container is public: `web/static/index.html` fetches it with no credential. So the backend can read live v1 data today with no client action and no Azure account, through the `v1_public` storage backend. That also means the container is a live exposure, closed at Phase 4 with F-07.

**Trickles into.** `REQUIREMENTS.md` R-11, `docs/PROGRESS.md` Phases 1 and 4, `docs/API-CONTRACT.md`, `Rpi-Detector` Phase ordering.

---

## D-017 — Device credential provisioning happens on the bench, through the issuance API

**Status:** DECIDED, 2026-08-13

**Context.** R-6.1 gives every device a per-device API key, held hashed server-side, presented as `X-Device-Id`/`X-Device-Key`. The keys have to get onto the units somehow. Every unit passes through someone's hands at flash time, so provisioning rides that step.

**Decision.** At today's fleet size: key shown once in the admin panel, pasted into `/etc/oceankind.env` over SSH on the bench. Root-owned, mode 600, written with an editor or heredoc so the secret never lands in shell history. A mistyped key fails loud: 401 on the first config poll, named in `health.degraded_reason` after two missed refreshes.

At tens of units the same flow scales without redesign: a bench provisioning script drives the same issuance API the admin panel uses — register the device, receive the key once, write the complete `/etc/oceankind.env` onto the unit. Ten units is ten invocations. This costs nothing today beyond one property, which is the load-bearing part of the decision: **the issuance endpoint returns the plaintext key in the API response, once, at creation.** The panel needs that anyway; it makes the script possible without building anything now.

What this deliberately does not cover: rotating keys on deployed units nobody can reach, and provisioning the client can run without us. That is D-018, proposed, not contracted.

**Trickles into.** `dashboard/docs/PROGRESS.md` Phase 1 (R-6.1 issuance API and panel section), `Rpi-Detector/docs/RUNBOOK.md` provisioning procedure.

---

## D-018 — Fleet-scale credential lifecycle: rotation over the wire, enrollment at the gate

**Status:** PROPOSED

**Context.** D-017 covers getting a key onto a unit that is on the bench. Two problems remain that D-017 cannot reach, and both grow with the fleet.

*Rotation.* Key rotation happens after deployment, on coastlines nobody visits, possibly without working SSH. With D-017 alone, rotating or revoking a compromised key means a site visit per unit. At two units that is an inconvenience; at tens it means rotation will simply not happen, which turns one leaked key into a permanent credential.

*Provisioning without us.* Today adding a unit requires someone who can drive our admin API from a bench. If the client wants to commission units themselves, they need a flow that does not involve us at all.

**Proposal.** Two pieces, sequenced by need, priced separately.

*Rotate-over-the-wire, once R-6.3 lands.* Devices will already talk to the API on a schedule. Add one endpoint: the device requests a new key authenticated with its current one; the new key is returned once; the old key keeps a short grace window so a crash mid-rotation strands nothing. Fleet-wide rotation becomes routine security hygiene — a config flag, no site visits, no SSH dependency. Small, and it removes the single worst operational property of per-device keys.

*First-boot enrollment, when the fleet forces it.* Single-use enrollment tokens minted in the admin panel with an expiry; a freshly flashed unit generates its own key, calls an enrollment endpoint with the token, and appears in the panel awaiting approval. The client commissions units with no involvement from us. This is the hundreds-of-units pattern and it is deliberately not built sooner: it adds an unauthenticated-adjacent endpoint and a token lifecycle to a threat model that includes physical access to unattended hardware. Built at need, it is a contained piece of work; built early, it is standing attack surface with no fleet to justify it.

**Decide when.** Rotate-over-the-wire: with R-6.3, when device event upload is specified. Enrollment: when a rollout beyond tens of units is confirmed, or the client asks to commission units without us.

**Trickles into (if accepted).** `docs/API-CONTRACT.md` device routes, `docs/DATA-CONTRACT.md` device configuration section, `Rpi-Detector` provisioning and runbook, R-6.3 scope.

---

## D-019 — This repository was scaffolded on the wrong protocol variant

**Status:** DECIDED, 2026-08-21

**Context.** The Lynch Protocol has four variants. This repository was scaffolded on `lyncHtmlDev`, which the protocol defines as *"Static HTML/CSS/JS sites, landing pages. No backend, no API docs."* `CLAUDE.md` acknowledged the mismatch in its own first line — "based on the `lyncHtmlDev` variant, **extended**: this is no longer a page on a static host, it is a container that owns users, sessions and secrets" — and extended the variant rather than changing it.

That extension is the root cause of every structural complaint against this codebase, and the complaints are correct:

- There is no backend/frontend divide, because the variant has no concept of one. The frontend is not a service; it is a folder of files bind-mounted into the API container.
- A FastAPI backend serves a single 3,129-line HTML file containing inline `<script>`, inline `<style>`, roughly 389 loose JS declarations and **two complete CSS theme layers**, one of which is dead and overridden with `!important`.
- `docs/TODO.md` has carried "the reason it was one file (no backend, no build step) no longer applies" since it was 1,779 lines. It grew 76% behind that note.
- The deployed image ships no frontend at all (`api/Dockerfile` copies `app/` only). This was invisible locally because the compose bind mount always covered it. In a two-container split the failure is impossible by construction.
- `REQUIREMENTS.md` R-9.3 forbade a bundler and a framework. That rule was inherited from a static-site variant and was never true of this product.

**Decision.** Rebuild on **`lynchLocalDev`** — the protocol's full-stack variant, *"backend + frontend + server deployment. Most projects use this."* Three containers, per the scaffold at `_lynchProtocol/lynch-project-scaffolder.skill`:

```
db        postgres:16-alpine, pgdata volume, healthcheck
backend   FastAPI, its own Dockerfile, :8000
frontend  node build -> nginx:alpine, its own Dockerfile, :80,
          proxies /api/ to http://backend:8000 over the compose network
```

Frontend stack is the protocol default: **React 18 + TypeScript + Vite**, with `react-chartjs-2` and `react-leaflet` replacing the CDN script tags. Backend gains **Postgres + Alembic** in place of the SQLite file.

**What does not change, and it is most of the work.** Every router (`auth`, `admin`, `data`, `devices`), `core/security.py`, `services/storage.py` (the portability seam — R-1.2 is untouched), `services/deviceconfig.py` (clamping and HMAC signing), `services/events.py` (date-partitioned pagination), `services/legacy_v1.py` (the v1 adapter), and all 25 tests. The backend logic was never the problem.

**Two deliberate deviations from the scaffold, recorded so they are not mistaken for drift.**

*Session cookies, not the scaffold's JWT.* The scaffold ships `SECRET_KEY` / `ACCESS_TOKEN_EXPIRE_MINUTES` JWT auth. A JWT in a browser lives somewhere JavaScript can read it, which contradicts this project's hard rule that the browser never holds a credential (R-4.2). HttpOnly signed cookies are already built and tested. They stay. nginx proxying `/api/` keeps browser and API same-origin, so nothing about cookie handling gets harder.

*Postgres over SQLite, reversing R-9.2.* R-9.2 argued one file, no server, small enough to copy around. On any container host the filesystem is ephemeral, so that file takes every user, device credential and tuned device config with it on the first restart. The scaffold's `db` service with a named volume removes the problem rather than documenting it.

**Consequences.** `REQUIREMENTS.md` R-9 is rewritten: R-9.2 (SQLite) and R-9.3 (no bundler, no framework) were artefacts of the wrong variant and are replaced. Phase 2 stops meaning "rewire the monolith's fetches" and becomes "build the five views as React pages against the API"; the monolith is deleted rather than split. The estimate for that is 20–30 hours and it is the honest cost of not having caught this at scaffold time.

**What this does not excuse.** The variant was wrong from the first commit, and the evidence was in the repository the whole time — in `CLAUDE.md`'s own "extended" caveat and in the `TODO.md` note. Several sessions of work were spent adding features inside a structure that should have been challenged instead.

**Trickles into.** `CLAUDE.md`, `README.md`, `REQUIREMENTS.md` R-9, `docs/PROGRESS.md` (re-phased), `docs/STYLEGUIDE.md`, `docs/API-CONTRACT.md` (origin and proxy model), and a new `docs/SERVER-INFRASTRUCTURE.md` per the `lynchLocalDev` doc set.
