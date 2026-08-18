# Dashboard v2 — what changed

Diff of `src/index.html` against the version audited on 2 August 2026, preserved at `https://github.com/rodgpt/Rpi-Detector/blob/main/legacy/superseded-monolith/dashboard/index.html`.

1,779 lines to 3,126. 1,939 changed lines. Compared 8 August 2026.

**Everything below about the two new blob files is inferred from how the dashboard consumes them, not verified against a live blob or a producer.** Confirm before treating it as contract.

---

## The headline

Two sites are live, not one. Two new data files exist that are not in the data contract. The detection record gained a bearing field. And the dashboard is no longer a single self-contained file.

The most important consequence is upstream: something is producing site-prefixed paths, `acoustic_indicators.json`, `ocean_conditions.json` and a `deg` field on detections. None of that comes from the device code in `raspberry-pi/src/`. **The deployed Pi is almost certainly ahead of the copy in this repository.** Re-baseline the device before writing any device code, or Phase 1 will be built against a fiction.

---

## Multi-site went live

```js
const SITES = {
  zapallar: { name: "Zapallar", lat: -32.552665, lon: -71.465068, base: ""          },
  matanzas: { name: "Matanzas", lat: -33.986651, lon: -71.860234, base: "matanzas/" },
};
function dataUrl(name) { return BLOB_BASE_ROOT + siteBase() + name; }
```

Every fetch now routes through `dataUrl()`, which prefixes the blob path with the current site's base.

Matanzas sits at `-33.986651, -71.860234`, which is the location hardcoded in the monolith we audited (`-33.986582, -71.860006`). So Matanzas is the original unit, and **Zapallar is a second unit that took the root path**.

That ordering matters. The first site is at the container root with an empty prefix and the second is namespaced under `matanzas/`. The layout is asymmetric, which means a third site inherits an inconsistent scheme and any future normalisation is a migration rather than a convention.

This partly overtakes D-007. The multi-device layout decision has been made in production, prefix-based, and roughly in the direction proposed. What remains open is whether to normalise Zapallar off the root, and the manifest race condition, which prefixing does not fix on its own.

---

## Tabs: three became five

| Before | After |
|---|---|
| Alertas | Alertas |
| Mapa | *(became the portada)* |
| Sensor | Estado del Sensor |
| | **Monitoreo Acústico** |
| | **Condiciones del mar** |
| | **Análisis** |

The map is now a "portada" landing page with site selection, using ArcGIS and OpenStreetMap tiles. `enterSite()` resets state and reloads when switching sites; `goToPortada()` returns.

---

## Two new blob files, not in the contract

### `acoustic_indicators.json`

Consumed by the Monitoreo Acústico tab. Observed keys: `updated` (timestamp) and `latest` (current values object). Drives a timeline chart and a diel plot, so it carries a time series of soundscape indicators.

Failure copy in the dashboard reads "Aún no hay indicadores acústicos (el sensor debe acumular clips)", which says the producer is the sensor and the file only appears once enough clips exist.

### `ocean_conditions.json`

```jsonc
{ "hourly": [ { "ts": …, "swell_m": …, "swell_period_s": …, "wind_kmph": …, "wind_deg": … } ] }
```

Roughly seven days of coverage, which the code notes constrains the analysis window. Producer unknown and almost certainly not the Pi, since this is forecast or observation data. Worth establishing whether something fetches it from an external marine API and writes it to blob, because that is an undocumented moving part with its own failure mode.

---

## Detection records gained a bearing

`a.deg` appears on manifest entries and is rendered as a direction arrow:

```js
const f = (a.deg + 180) * Math.PI / 180, dx = Math.sin(f), dy = -Math.cos(f);
```

If this is real bearing estimation it likely uses the inter-channel delay between the two hydrophones, which is exactly the unexploited capability logged in [Rpi-Detector raspberry-pi/docs/TODO.md](https://github.com/rodgpt/Rpi-Detector/blob/main/raspberry-pi/docs/TODO.md) under "[Audio] Two hydrophones, no spatial use". Someone may have implemented it. Confirm on the device side.

---

## New analytical feature: dive windows

The Análisis tab cross-references detections against sea state.

`goodWindows(oh, dive, MIN_DIVE_WINDOW_H)` finds continuous stretches of at least 8 hours meeting user-configured thresholds on swell height, swell period, wind speed and wind direction. Each alert is matched to the nearest sea observation within 2 hours and classified good, bad or unknown.

Thresholds persist in `localStorage` under `oceankind_dive_thresholds`.

The implicit hypothesis is that blast fishing correlates with sea conditions that permit diving. That is a real analytical claim and a good one, and it means the detection record now feeds an inference rather than only an alert. Data integrity matters more than it did: the cooldown defect in F-03, which silently drops detections, corrupts this analysis rather than merely thinning a list.

---

## What got better

Loading and error states now exist: `loadingNote()`, `errorNote()`, `clearLoading()`, a `mf-spinner`, and retry buttons wired to the relevant loader. This closes the rule in `STACK-RULES.md` that a failed fetch must look failed. Previously a failure could render as a blank or stale panel.

---

## What did not change

`SAS_URL_KEY` is still declared at line 1286 and still referenced nowhere. **X-01 stands**: the claim in `SYSTEM_REVIEW.md` §4.3 about a write-capable SAS in browser storage remains untrue, now across two versions.

Still no authentication (F-12). Still `AUTO_REFRESH_MS = 30000`. Still no `schema_version`. Still nothing that handles suppressed detections.

**F-18 got materially worse.** The poll cycle now pulls `manifest.json`, `status.json`, `power_history.json`, `acoustic_indicators.json` and `ocean_conditions.json` in full, every 30 seconds, per site. Five files where there were three. Against the Static Web Apps free tier's 100 GB monthly bandwidth cap, and Microsoft stops serving the site rather than billing on overage, this stops being an efficiency concern.

---

## No longer a single file

```
src/index.html        155 KB
src/assets/monitoring.jpg  358 KB
src/assets/portada.jpg     194 KB
src/assets/hero.jpg        158 KB
src/assets/logo.png         49 KB
```

Roughly 760 KB of images. The "one self-contained file, deployment is uploading one file" property stated in `README.md`, `STACK-RULES.md` and `STYLEGUIDE.md` is no longer true. Those three documents need correcting, and the Static Web Apps free tier's 0.25 GB per-deployment storage limit is now worth watching.

CDN dependencies are unchanged: Chart.js, the date-fns adapter, the zoom plugin, Hammer.js and Leaflet. Tile providers ArcGIS and OpenStreetMap are new.

---

## Documents this invalidates

| Document | Problem |
|---|---|
| `DATA-CONTRACT.md` | Missing both new files, the `deg` field and the site prefix |
| `DECISIONS.md` D-007 | Partly decided in production already |
| `README.md`, `STACK-RULES.md` | "Single self-contained file" is false |
| `docs/STYLEGUIDE.md` | Palette and component inventory extracted from v1 |
| `docs/PROGRESS.md` | Written against a three-tab dashboard |
| `FINDINGS.md` | F-18 severity understated; F-03 now corrupts an analysis, not just a list |

---

## Do this before writing code

1. **Re-baseline the device.** Pull whatever is actually running and diff it against `raspberry-pi/src/`. Everything new here implies device changes not in this repository.
2. **Fetch a real sample** of `acoustic_indicators.json` and `ocean_conditions.json` and replace the inferred schemas above with verified ones.
3. **Find the producer of `ocean_conditions.json`.** It is not the Pi. It is an undocumented component with its own failure mode.
4. **Decide whether Zapallar moves off the container root.** Cheap now with two sites, expensive later.
