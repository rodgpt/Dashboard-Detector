#!/usr/bin/env python3
"""
Generate a complete v2-shaped fixture tree for local dashboard development.

No Azure, no device, no network. Produces every blob the dashboard reads,
in the exact layout and schema of docs/DATA-CONTRACT-v2.md, including real
playable WAV clips so the spectrogram works.

    python3 tools/generate_fixtures.py            # default: ./fixtures
    python3 tools/generate_fixtures.py --out /tmp/fx --days 14 --seed 7

Standard library only. Deterministic for a given seed.
"""

import argparse, json, math, random, struct, uuid, wave
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = 2
SR, CHANNELS, CLIP_S = 48000, 2, 5.0

SITES = [
    {"id": "zapallar", "name": "Zapallar", "lat": -32.552665, "lon": -71.465068,
     "device": "Rpi_zapallar", "active": True},
    {"id": "matanzas", "name": "Matanzas", "lat": -33.986651, "lon": -71.860234,
     "device": "Rpi_matanzas", "active": True},
]

DETECTORS = {
    "vessel": "psd_tonal",
    "blast":  "ml_mfcc",
}


# ── audio ─────────────────────────────────────────────────────────────────────

def _write_wav(path: Path, samples):
    """samples: list of float -1..1, mono. Written as SR/CHANNELS/16-bit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = bytearray()
    for s in samples:
        v = max(-1.0, min(1.0, s))
        packed = struct.pack("<h", int(v * 32767))
        frames += packed * CHANNELS
    with wave.open(str(path), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(frames))


def _vessel_audio(rng):
    """Sustained narrowband harmonics. What psd_tonal is built to find."""
    n = int(SR * CLIP_S)
    f0 = rng.uniform(70, 180)
    harm = [(f0 * k, 0.30 / k) for k in range(1, 6)]
    out = []
    for i in range(n):
        t = i / SR
        v = sum(a * math.sin(2 * math.pi * f * t) for f, a in harm)
        out.append(v + rng.gauss(0, 0.02))
    return out


def _blast_audio(rng):
    """Sub-second broadband impulse with exponential decay, on a quiet floor."""
    n = int(SR * CLIP_S)
    onset = int(SR * rng.uniform(1.0, 3.5))
    tau = SR * 0.18
    out = []
    for i in range(n):
        v = rng.gauss(0, 0.01)
        if i >= onset:
            v += rng.gauss(0, 1.0) * math.exp(-(i - onset) / tau) * 0.9
        out.append(v)
    return out


def _background_audio(rng):
    n = int(SR * CLIP_S)
    return [rng.gauss(0, 0.015) for _ in range(n)]


# ── helpers ───────────────────────────────────────────────────────────────────

def iso(dt): return dt.astimezone(timezone.utc).isoformat()

def envelope(site, device, now, **payload):
    d = {"schema_version": SCHEMA_VERSION, "site": site, "device": device,
         "generated_utc": iso(now)}
    d.update(payload)
    return d

def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False))


# ── generators ────────────────────────────────────────────────────────────────

def gen_events(out: Path, site, now, days, rng, clips=True):
    """One blob per detection, date-partitioned. Returns the list written."""
    written = []
    n = rng.randint(28, 46)
    for _ in range(n):
        captured = now - timedelta(seconds=rng.uniform(0, days * 86400))
        etype = rng.choices(["vessel", "blast", "unknown"], weights=[70, 22, 8])[0]
        suppressed = rng.random() < 0.22
        score = round(rng.uniform(0.62, 0.98), 4) if etype != "unknown" else round(rng.uniform(0.60, 0.72), 4)
        eid = str(uuid.UUID(int=rng.getrandbits(128), version=4))
        day = captured.strftime("%Y/%m/%d")
        stamp = captured.strftime("%Y-%m-%dT%H-%M-%S")
        clip_rel = f"sites/{site['id']}/clips/{day}/{eid}.wav"
        uploaded = (rng.random() > 0.06) and clips   # a few genuinely failed uploads

        ev = envelope(site["id"], site["device"], captured,
            event_id=eid,
            captured_utc=iso(captured),
            uploaded_utc=iso(captured + timedelta(seconds=rng.uniform(2, 25))),
            event_type=etype,
            detector=DETECTORS.get(etype, "unknown"),
            score=score,
            suppressed=suppressed,
            audio_level=round(rng.uniform(0.011, 0.240), 4),
            peak_db=round(rng.uniform(-42.0, -8.0), 1),
            bearing_deg=None,
            clip={"path": clip_rel, "sample_rate": SR, "channels": CHANNELS,
                  "duration_s": CLIP_S, "uploaded": uploaded},
            detector_meta={"tonal_seconds": rng.randint(0, 5)} if etype == "vessel" else {},
        )
        write_json(out / f"sites/{site['id']}/events/{day}/{stamp}_{eid}.json", ev)

        if clips and uploaded:
            gen = {"vessel": _vessel_audio, "blast": _blast_audio}.get(etype, _background_audio)
            _write_wav(out / clip_rel, gen(rng))
        written.append(ev)
    return sorted(written, key=lambda e: e["captured_utc"], reverse=True)


def gen_status(out: Path, site, now, rng, healthy=True):
    s = envelope(site["id"], site["device"], now,
        software_version="2.0.0",
        last_seen=iso(now - timedelta(seconds=rng.randint(5, 90))),
        session_start=iso(now - timedelta(days=rng.randint(2, 30))),
        uptime_seconds=rng.randint(60_000, 900_000),
        system_uptime_s=rng.randint(100_000, 1_200_000),
        health={
            "detector_ok": healthy,
            "audio_ok": healthy,
            "duty_cycle_pct": round(rng.uniform(98.6, 99.9), 1) if healthy else 61.2,
            "clips_dropped": 0 if healthy else rng.randint(3, 40),
            "upload_backlog": 0 if healthy else rng.randint(1, 12),
            "degraded_reason": None if healthy else "detector failed to load",
        },
        detection={
            "detectors": ["psd_tonal"] if healthy else [],
            "thresholds": {"psd_threshold_db": 8, "psd_f_min": 55, "psd_f_max": 1000,
                           "score_min": 0.60, "rms_min": 0.010},
            "cooldown_s": 600,
            "last_rms": round(rng.uniform(0.004, 0.05), 4),
        },
        audio={"device": "plughw:3,0", "sample_rate": SR, "channels": CHANNELS},
        power={
            "battery_voltage_v": round(rng.uniform(12.1, 13.4), 2),
            "battery_current_a": round(rng.uniform(-1.8, 3.2), 2),
            "panel_voltage_v": round(rng.uniform(0.0, 21.0), 2),
            "panel_power_w": rng.randint(0, 62),
            "charge_state": rng.choice(["Bulk", "Absorption", "Float", "Off"]),
            "charge_state_id": rng.choice([3, 4, 5, 0]),
            "yield_today_kwh": round(rng.uniform(0.05, 0.62), 2),
            "yield_total_kwh": round(rng.uniform(40, 160), 1),
            "max_power_today_w": rng.randint(20, 78),
            "system_load_w": round(rng.uniform(2.6, 4.4), 2),
        },
        network={"signal_bars": rng.randint(1, 5), "signal_rssi": rng.randint(-105, -58),
                 "network_type": rng.choice(["LTE", "LTE+", "WCDMA", "NR5G"])},
        system={"cpu_temp_c": round(rng.uniform(38, 63), 1),
                "disk_used_pct": round(rng.uniform(22, 58), 1),
                "disk_free_gb": round(rng.uniform(9, 22), 2),
                "disk_total_gb": 29.0,
                "ram_used_pct": round(rng.uniform(30, 71), 1),
                "ram_used_mb": rng.randint(600, 1500),
                "ram_total_mb": 2048},
    )
    write_json(out / f"sites/{site['id']}/status.json", s)


def gen_power_history(out: Path, site, now, rng, hours=72, bucket_s=1800):
    hist, t = [], now - timedelta(hours=hours)
    while t < now:
        # a deliberate multi-hour gap, so uptime reconstruction has something to find
        in_outage = 22 < (now - t).total_seconds() / 3600 < 27
        if not in_outage:
            hour = t.hour + t.minute / 60
            sun = max(0.0, math.sin((hour - 6.5) / 12 * math.pi))
            hist.append({
                "ts": iso(t),
                "sys_w": round(rng.uniform(2.8, 4.1), 2),
                "panel_w": round(sun * rng.uniform(40, 68), 1) if sun > 0 else 0.0,
                "bat_v": round(11.9 + sun * 1.4 + rng.uniform(-0.15, 0.15), 2),
            })
        t += timedelta(seconds=bucket_s)
    write_json(out / f"sites/{site['id']}/power_history.json",
               envelope(site["id"], site["device"], now,
                        bucket_s=bucket_s, window_h=hours, history=hist))


def gen_acoustic(out: Path, site, now, rng, days=14):
    def trio(base, spread):
        med = round(rng.uniform(base - spread, base + spread), 3)
        return med, round(med - abs(rng.uniform(0.02, spread)), 3), round(med + abs(rng.uniform(0.02, spread)), 3)

    timeline = []
    t = now - timedelta(days=days)
    while t < now:
        nm, nq1, nq3 = trio(0.32, 0.14)
        cm, cq1, cq3 = trio(12.0, 6.0)
        timeline.append({"ts": iso(t), "ndsi_med": nm, "ndsi_q1": nq1, "ndsi_q3": nq3,
                         "click_med": round(abs(cm), 2), "click_q1": round(abs(cq1), 2),
                         "click_q3": round(abs(cq3), 2)})
        t += timedelta(hours=6)

    diel = []
    for h in range(24):
        night = 1.25 if (h < 6 or h > 20) else 1.0
        nm, nq1, nq3 = trio(0.30 * night, 0.10)
        cm, cq1, cq3 = trio(11.0 * night, 4.0)
        diel.append({"hour": h, "ndsi_med": nm, "ndsi_q1": nq1, "ndsi_q3": nq3,
                     "click_med": round(abs(cm), 2), "click_q1": round(abs(cq1), 2),
                     "click_q3": round(abs(cq3), 2)})

    write_json(out / f"sites/{site['id']}/acoustic_indicators.json",
               envelope(site["id"], site["device"], now,
                        latest={"click_rate_hz": round(rng.uniform(4, 26), 2),
                                "ndsi": round(rng.uniform(0.15, 0.52), 3)},
                        timeline=timeline, diel=diel))


DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

def gen_ocean(out: Path, site, now, rng, past_d=3, fcst_d=4):
    def point(t, forecast):
        deg = rng.randint(0, 359)
        swell = round(max(0.3, rng.gauss(1.7, 0.6)), 2)
        return {"ts": iso(t), "swell_m": swell,
                "swell_period_s": round(rng.uniform(7, 16), 1),
                "swell_dir": rng.choice(DIRS),
                "wind_kmph": round(max(0.0, rng.gauss(15, 7)), 1),
                "wind_deg": deg, "wind_dir": DIRS[round(deg / 45) % 8],
                "gust_kmph": round(max(0.0, rng.gauss(24, 9)), 1),
                "wave_m": round(swell + rng.uniform(0, 0.6), 2),
                "water_temp_c": round(rng.uniform(12.5, 17.0), 1),
                "cloud_pct": rng.randint(0, 100),
                "weather_desc": rng.choice(["Despejado", "Parcial", "Nublado", "Llovizna"]),
                "is_forecast": forecast}

    hourly, t = [], now - timedelta(days=past_d)
    while t < now + timedelta(days=fcst_d):
        hourly.append(point(t, t > now))
        t += timedelta(hours=1)

    daily = []
    for d in range(-past_d, fcst_d):
        day = (now + timedelta(days=d)).replace(hour=12, minute=0, second=0, microsecond=0)
        p = point(day, d > 0); p["date"] = day.strftime("%Y-%m-%d")
        daily.append(p)

    write_json(out / f"sites/{site['id']}/ocean_conditions.json",
               envelope(site["id"], site["device"], now,
                        location={"name": site["name"], "lat": site["lat"], "lon": site["lon"]},
                        current=point(now, False), hourly=hourly, daily=daily,
                        thresholds={"swell_max_m": 2.0, "period_min_s": 9.0,
                                    "wind_max_kmph": 20.0,
                                    "wind_dirs": ["N", "NE", "E", "SE"]}))


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="fixtures")
    ap.add_argument("--days", type=int, default=14, help="history depth for events")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-clips", action="store_true", help="skip WAV generation (fast)")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    out = Path(args.out)
    now = datetime(2026, 8, 8, 18, 0, 0, tzinfo=timezone.utc)   # fixed, so runs are reproducible

    write_json(out / "_sites.json",
               {"schema_version": SCHEMA_VERSION, "generated_utc": iso(now), "sites": SITES})

    for i, site in enumerate(SITES):
        events = gen_events(out, site, now, args.days, rng, clips=not args.no_clips)
        gen_status(out, site, now, rng, healthy=(i == 0))   # matanzas ships degraded on purpose
        gen_power_history(out, site, now, rng)
        gen_acoustic(out, site, now, rng)
        gen_ocean(out, site, now, rng)
        sup = sum(1 for e in events if e["suppressed"])
        print(f"  {site['id']:<10} {len(events):>3} events ({sup} suppressed)")

    n_files = sum(1 for _ in out.rglob("*") if _.is_file())
    mb = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1e6
    print(f"\n{n_files} files, {mb:.1f} MB in {out}/")
    print("Serve with:  ./tools/serve.sh     then open  http://localhost:8080/src/?data=/fixtures/")


if __name__ == "__main__":
    main()
