# Style guide — dashboard

Extracted from `src/index.html` as built, not designed in advance. This documents what is already there so changes stay consistent, and flags where the current usage is inconsistent.

**Last extracted:** 2026-08-02

> **Drift warning (2026-08-13).** The palette below describes the *light* CSS at the top of `index.html`, which is **dead styling**: a final `<style>` block — "TEMA OSCURO MAR FUTURA" — overrides it with `!important` and `--mf-*` custom properties. What the client actually sees is that dark theme: background `#0c2230` (gradient from `#0b2030`), panels `#12303f`, text `#e7f1f5`, muted `#9fbcc8`, brand `#64b1c5` with `#062028` text on brand buttons, borders `rgba(120,175,195,.16)`. The portada uses `assets/portada.jpg` under a dark gradient with a translucent glass card, and the logo is `assets/logo.png` (inverted to white on the portada). The login and admin pages replicate the dark layer via the tokens in `web/static/css/auth.css`. Re-extract this whole guide from the dark layer when the monolith splits in Phase 2; tracked in `TODO.md`.

---

## Approach

Plain CSS in a `<style>` block at the top of the single file. No framework, no preprocessor, no custom properties. Colours are written as hex literals inline, which is why the same blue appears twenty times.

**First improvement worth making:** lift the palette below into `:root` custom properties. It is a mechanical change, it makes every subsequent visual change one edit instead of twenty, and it costs nothing at runtime. Do this before Phase 4 adds a device selector and multiplies the component count.

---

## Palette

Counts are occurrences in the current file, which is a decent proxy for how load-bearing each colour is.

### Structure

| Colour | Uses | Role |
|---|---|---|
| `#0a4a7c` | 20 | Primary deep blue. Headers, primary surfaces |
| `#1a2636` | 9 | Near-black. Body text, dark surfaces |
| `#1a6fb5` | 4 | Mid blue. Links, active states |
| `#185fa5` | 3 | Mid blue, hover |

### Text and borders

| Colour | Uses | Role |
|---|---|---|
| `#9ab0c0` | 15 | Muted text on dark. Secondary labels |
| `#7a9ab0` | 13 | Muted text, dimmer |
| `#5a7a9a` | 6 | Muted, dimmest |
| `#d0dce8` | 7 | Light borders and dividers |
| `#c5d5e5` | 4 | Light border, stronger |
| `#edf2f7` | 4 | Light background fill |

### Semantic

| State | Fill | Text | Border | Notes |
|---|---|---|---|---|
| Success / online | `#22c55e` dot, `#e6f4ec` fill | `#1a6e3a` | `#a8d5b5` | |
| Warning | `#f59e0b` | | | Amber, sparse |
| Error / offline | `#ef4444` dot, `#fdecea` fill | `#b91c1c` | `#f5b8b5` | |
| Alert accent | `#e03e52` | | | Detection emphasis |
| Alert accent, warm | `#d85a30` | | | |

**Known inconsistency.** Two greens (`#22c55e` for dots, `#1a6e3a` for text) and two reds (`#ef4444` for dots, `#b91c1c` for text) coexist. That is defensible as dot-versus-text contrast, but it is not written down anywhere and the next person will pick one at random. It is written down now: **`#22c55e` and `#ef4444` are indicator dots. `#1a6e3a` and `#b91c1c` are text on light fills.**

---

## Typography

```css
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
```

System stack, one family throughout, no web fonts. Keep it. A monitoring dashboard loading a font over cellular is a bad trade.

---

## Components in use

`.status-pill` with `.offline` modifier, containing `.status-dot` which pulses when online and is static when offline. `.online-badge` with `.offline` and `.online-dot` is a near-duplicate of the same idea. **These two should be one component.** Worth merging before Phase 4 adds per-device status to the map and the list.

`.badge-device` already exists, which is convenient, since Phase 4 needs exactly this.

`.cfg-feedback` with `.ok` and error variants, using the light-fill semantic pattern.

### Login and admin pages (`web/static/css/auth.css`, added 2026-08-13, dark since same day)

The first stylesheet with the palette as `:root` custom properties, and the values are the **dark theme's** (`--mf-*` layer), because that is the design the client ships. Mappings worth knowing: `--bg`/`--bg2`/`--panel`/`--panel2`/`--text`/`--dim`/`--border`/`--brand`/`--brand-soft` mirror their `--mf-*` counterparts; `--on-brand: #062028` is the dark text on brand-filled buttons (from `.refresh-btn`); semantic ok/err states become translucent fills with light text (`rgba(34,197,94,.14)` + `#86efac`, `rgba(239,68,68,.14)` + `#fca5a5`) since the light theme's pastel fills don't work on dark panels.

Treatments copied from the monolith: login = the portada (photo `assets/portada.jpg` under `rgba(9,26,36,.42→.80)` gradient, glass card `rgba(16,42,57,.82)` with `backdrop-filter: blur(7px)`, logo inverted to white); admin = the monitoring pages (gradient `#0b2030→#0c2230` fixed, `.panel` on `--panel` with the brand left-fillet on `h2`, table hover `--brand-soft`, `.chip` styled like `.badge-device`). The logo is `assets/logo.png` via `.brand-logo`, never a monogram.

Components: `.auth-card`, `.panel`, `.form-feedback` with `.ok`/`.error`, `.banner.error` (page-level failure with retry — a failed load is shown, never blank), `.chip`/`.chip.none` (dashed = "sin sitios asignados"), `.role-badge`/`.role-badge.admin`, `.btn` with `-primary` (brand fill, `--on-brand` text, weight 700), `-ghost` (transparent, brand border — like `.site-back-btn`), `-danger`, `-sm`, `.site-checks` (generated from the API's site list, never hardcoded).

Colour is never the only signal: feedback boxes carry text, disabled buttons change label ("Ingresando…"), and the forbidden state is a full sentence, not a red tint.

`.key-reveal`: the one-time device-key display. Amber (`--warn`) on purpose — it is not an error, it is a moment that does not repeat, and it says so in words. The key `<code>` uses `user-select: all` so one click selects the whole key. `.panel-note` is the muted explanatory paragraph under a panel heading.

---

## Rules

**Match the existing pattern before inventing one.** Semantic states use a light fill, a darker text colour and a mid border. Follow that trio.

**Colour is never the only signal.** Online and offline differ by dot colour *and* by animation *and* by label. Keep that. Some users cannot distinguish the red from the green, and the information here matters.

**Spanish interface.** All user-facing strings, labels and tab identifiers stay Spanish. `tab-alertas`, `tab-mapa`, `tab-sensor`.

**A failure looks like a failure.** Stale data rendered as current is the worst possible output from a monitoring tool. Every failed fetch gets a visible state, not a silent fallback to whatever was last drawn.

**No inline `style=` attributes** for anything reusable. The file is already large and inline styles are how it becomes unmaintainable.

---

## External libraries

Loaded from CDN at runtime. All pinned to exact versions, which is correct.

| Library | Version | Used for |
|---|---|---|
| Chart.js | 4.4.1 | Power history chart |
| chartjs-adapter-date-fns | 3.0.0 | Time axis |
| chartjs-plugin-zoom | 2.0.1 | Chart pan and zoom |
| Hammer.js | 2.0.8 | Touch gestures for the zoom plugin |
| Leaflet | 1.9.4 | Device map |

Read the actual documentation before changing chart or map configuration. Chart.js in particular changed its options structure significantly across major versions and training-data recall for it is unreliable.

---

## Phase 4 additions

The device selector, per-device map markers and the detection list device column all need visual decisions that do not exist yet. Extract the palette to custom properties first, merge the two status components second, then build. Update this file in the same change.
