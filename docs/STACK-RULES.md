# OceanKind / Mar Futura — Claude Code Instructions

Umbrella instructions for the whole stack. Each codebase also has its own `CLAUDE.md` with domain rules. Read this one first, always.

Adapted from the Lynch Protocol. The core principle is unchanged: **docs are the only thing that survives.** Context gets compressed, sessions end, memory fails. If it is not written down here it does not exist.

---

## Before ANY task

Read in this order. Do not skip to the code.

1. **`README.md`** — What the system is, what actually runs, folder map
2. **`docs/FINDINGS.md`** — Twenty verified defects. Four can silently stop detection. Read before writing a line
3. **`DECISIONS.md`** — What has been decided for the whole stack, and what is still open
4. **`docs/ARCHITECTURE.md`** — How the Pi, blob storage, the dashboard and the future backend fit together
5. **`docs/DATA-CONTRACT.md`** — The exact shape of everything crossing between the two codebases
6. **`docs/PROGRESS.md`** — Stack-level phase state
7. **`docs/TODO.md`** — Cross-cutting pending items

Then the CLAUDE.md of whichever codebase you are touching.

---

## Why there is an umbrella and also local rules

The Pi and the dashboard are one system. They are coupled through blob storage, and a change on either side can break the other silently, because nothing validates the contract between them. That coupling is why the shared documents exist: when working on one side you must be able to check the state of the other without opening it.

The local `CLAUDE.md` files exist for constraints that are genuinely domain-specific and would be nonsense applied across. "Never write to `/boot/firmware`" means nothing to a browser page. "Stay one file, no build step" means nothing to embedded Python.

So: anything about the system as a whole, the contract between the two, or a decision that affects both goes in the umbrella. Only physical or platform constraints go local.

---

## The one rule that matters most

**A change on one side of the data contract is a change on both sides.**

The Pi writes `manifest.json`, `status.json`, `power_history.json` and WAV clips. The dashboard reads them. Nothing validates this. No schema, no version field, no test. If the Pi starts writing a field differently, the dashboard breaks in a browser somewhere and nobody finds out.

Before changing anything that touches those files:

1. Read `docs/DATA-CONTRACT.md`
2. Update it in the same change
3. Check the other codebase's `docs/PROGRESS.md` for whether it is mid-migration
4. Say explicitly in your summary that the contract changed

Phase 1 moves the blob layout to per-device paths. That is a deliberate, coordinated break of this contract and it has to land on both sides together.

---

## Scope: plumbing, not water

We build everything that carries a detection from the hydrophone to a human. We do not decide what
counts as a detection. See D-015.

In practice this means: when a question is about signal science, thresholds on scientific grounds,
whether a detector works, or what to train on, it goes to `Rpi-Detector/docs/CLIENT-DEPENDENCIES.md` rather than
into an implementation. And it means three things are non-negotiable on our side, because the
boundary is dishonest otherwise. The detector interface must express any event type. No event a
detector produces may be lost by our code. Every threshold must be remotely tunable without a
firmware update.

---

## Rules

**Read the actual docs.** Before using any library, driver or Azure service, read its official documentation. Not training data, not memory. Azure SDKs and audio libraries change APIs and deprecate methods. Verify.

**Every TODO goes in a TODO.md immediately.** Cross-cutting ones in `docs/TODO.md`, domain ones in that domain's. No "I will add it later." Context compression eats it.

**Every decision that affects both codebases goes in `DECISIONS.md`.** It is at the root because it feeds downward: a decision recorded there becomes concrete tasks in `raspberry-pi/docs/PROGRESS.md` and `dashboard/docs/PROGRESS.md`. Do not record a stack-level decision inside one codebase.

**New library or Azure service?** Follow the three-stage pipeline in `docs/research/RESEARCH.md`: research, then analysis doc, then deployment doc.

**Do not run git commands** unless explicitly asked. This repository is deliberately not under version control.

**Never fail quietly.** This applies on both sides. The system's entire purpose is to notice something, and a component that degrades without saying so defeats it. Several existing defects have exactly this shape.

**Do not develop in `legacy/`.** Nothing there runs. If something in it is worth having, port it forward as new work.

---

## After completing a feature

1. **`README.md`** if what runs, or where it lives, changed
2. **`docs/DATA-CONTRACT.md`** if anything crossing between the codebases changed. Not optional
3. **`DECISIONS.md`** if a choice was made that affects both sides
4. **`docs/PROGRESS.md`** and the relevant domain `PROGRESS.md`
5. **`docs/TODO.md`** or the domain `TODO.md`
6. **`docs/FINDINGS.md`** if a catalogued defect was fixed. Mark it, do not delete it
7. **`docs/ARCHITECTURE.md`** if the process model, threading or system design changed
8. **`docs/research/RESEARCH.md`** if a new analysis doc was written

Do this before considering anything done.

---

## Project constraints

Sixty hours total, roughly two hours a day. There is no absorption capacity, so scope discipline matters more than speed.

One unit in production, on solar power, on a coastline, with no physical access and no working rollback. A bad deployment is not recoverable remotely today.

A bench Raspberry Pi Zero 2W exists. Everything gets tested there first.

Azure access has not been granted. Everything in the security workstream is blocked on it, so front-load work that does not need it.

More units are confirmed for roughly six months out. Build the data layout for that now; build the admin tooling for it later.

---

## Vocabulary

| Term | Meaning |
|---|---|
| Deaf window | Time when the hydrophone is not recording because the loop is busy |
| Silent-deaf | Detects nothing, reports itself healthy. The worst failure mode |
| The contract | The blob schemas in `docs/DATA-CONTRACT.md`. The only coupling between the codebases |
| Bench unit | The Pi Zero 2W. Never the production node |
| Production node | The single deployed unit at Lagunillas, Navidad |
| Phase 1 | The contracted work: device reliability, security, multi-device foundation |
| Phase 2 | The backend, authentication and admin panel. Specified, not contracted |
