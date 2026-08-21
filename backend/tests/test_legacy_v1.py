"""LEGACY-V1: delete this file at cutover along with services/legacy_v1.py.

Asserts the one property that makes the v1 path safe: everything above the
source boundary sees v2 and only v2, and the four things v1 cannot supply are
reported as unknown rather than guessed.
"""
import json
import os
import pathlib

import pytest

V1_MANIFEST = {
    "schema_version": 1,
    "updated": "2026-08-12T10:00:00+00:00",
    "alerts": [
        {   # a typical production entry: no event_type, no detector, no suppressed
            "timestamp": "2026-08-12T09:30:00+00:00",
            "audio_level": 0.084, "peak_db": -21.4,
            "audio_url": "https://marfuturatest.blob.core.windows.net/alerts/clip_a.wav",
            "device": "Rpi_zapallar", "decided_by": "rms+ml",
            "model_label": "FILTRO", "model_proba": 0.8,
        },
        {   # older entry, no model output at all
            "timestamp": "2026-08-11T08:00:00+00:00",
            "audio_level": 0.02, "peak_db": -33.0,
            "audio_url": None, "device": "Rpi_zapallar", "decided_by": "rms",
        },
    ],
}

V1_STATUS = {
    "schema_version": 1, "device": "Rpi_zapallar", "status": "online",
    "last_seen": "2026-08-12T10:00:00+00:00", "software_version": "1.1.0",
    "uptime_seconds": 191700, "current_threshold": 0.08, "last_rms": 0.0142,
    "battery_voltage_v": 12.84, "panel_power_w": 26, "signal_bars": 4,
    "cpu_temp_c": 48.3, "ram_used_mb": 862, "ram_total_mb": 2048,
    "lat": -32.552665, "lon": -71.465068,
}

V1_POWER = {
    "schema_version": 1, "bucket_s": 1800,
    "history": [
        {"ts": "2026-08-12T00:00:00+00:00", "sys_w": 3.4, "panel_w": 0, "bat_v": 12.6},
        # deliberate gap. must survive untouched
        {"ts": "2026-08-12T06:00:00+00:00", "sys_w": 3.5, "panel_w": 22, "bat_v": 12.9},
    ],
}


@pytest.fixture()
def v1(tmp_path, monkeypatch):
    """A v1 tree: first site at the root, second namespaced. That asymmetry is
    the thing v2 removes, so the fixture has to reproduce it."""
    (tmp_path / "manifest.json").write_text(json.dumps(V1_MANIFEST))
    (tmp_path / "status.json").write_text(json.dumps(V1_STATUS))
    (tmp_path / "power_history.json").write_text(json.dumps(V1_POWER))
    (tmp_path / "clip_a.wav").write_bytes(b"RIFF....WAVE")
    mz = tmp_path / "matanzas"; mz.mkdir()
    mz.write_bytes if False else None
    (mz / "manifest.json").write_text(json.dumps({"schema_version": 1, "alerts": []}))

    monkeypatch.setenv("OCEANKIND_CONTRACT_VERSION", "1")
    monkeypatch.setenv("OCEANKIND_STORAGE_BACKEND", "local")
    monkeypatch.setenv("OCEANKIND_LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("OCEANKIND_SESSION_SECRET", "x" * 40)

    from app.core.config import settings
    settings.cache_clear()
    from app.services.storage import LocalStorage
    return LocalStorage(str(tmp_path))


def test_events_come_back_as_v2(v1):
    from app.services.events import list_events
    from datetime import datetime, timezone

    page = list_events(v1, "zapallar",
                       since=datetime(2026, 8, 1, tzinfo=timezone.utc),
                       until=datetime(2026, 8, 13, tzinfo=timezone.utc))

    assert page["total"] == 2
    assert set(page) >= {"items", "total", "limit", "offset", "has_more", "scanned_blobs"}
    assert page["scanned_blobs"] == 1          # the whole history is one blob. that is v1

    ev = page["items"][0]                      # newest first
    assert ev["schema_version"] == 2
    assert ev["captured_utc"] == "2026-08-12T09:30:00+00:00"
    assert ev["score"] == 0.8
    assert ev["clip"]["path"] == "clip_a.wav"  # full URL reduced to container-relative
    assert ev["clip"]["uploaded"] is True


def test_unrecoverable_fields_are_unknown_not_invented(v1):
    from app.services.events import list_events
    page = list_events(v1, "zapallar")
    for ev in page["items"]:
        assert ev["event_type"] == "unknown"
        assert ev["detector"] == "unknown"
        assert ev["suppressed"] is False
    c = page["contract"]
    assert c["version"] == 1 and c["time_is_upload"] is True
    assert c["suppressed_undercounts"] is True


def test_event_ids_are_stable_across_polls(v1):
    from app.services.events import list_events
    a = [e["event_id"] for e in list_events(v1, "zapallar")["items"]]
    b = [e["event_id"] for e in list_events(v1, "zapallar")["items"]]
    assert a == b and all(a)


def test_missing_model_output_becomes_null_not_zero(v1):
    from app.services.events import list_events
    from datetime import datetime, timezone
    # explicit window: the default is "last 7 days from now", and a fixture
    # entry ageing out of it turned this test red purely by calendar
    older = list_events(v1, "zapallar",
                        since=datetime(2026, 8, 1, tzinfo=timezone.utc),
                        until=datetime(2026, 8, 13, tzinfo=timezone.utc))["items"][-1]
    assert older["score"] is None              # null is absence. zero is a reading
    assert older["clip"]["path"] is None
    assert older["clip"]["uploaded"] is False


def test_status_is_grouped_and_health_is_unknown_not_healthy(v1):
    from app.services.events import read_json
    st = read_json(v1, "sites/zapallar/status.json")
    assert st["schema_version"] == 2
    assert st["power"]["battery_voltage_v"] == 12.84
    assert st["system"]["ram_total_mb"] == 2048
    assert st["network"]["signal_bars"] == 4
    # v1 published no health surface. absence is reported, never rendered as ok
    assert st["health"]["detector_ok"] is None
    assert "no health surface" in st["health"]["degraded_reason"]
    # the threshold that never participated in the decision (F-09) stays labelled
    assert st["detection"]["thresholds"]["v1_current_threshold"] == 0.08


def test_power_gaps_survive_untouched(v1):
    from app.services.events import read_json
    p = read_json(v1, "sites/zapallar/power_history.json")
    assert len(p["history"]) == 2               # not backfilled to 12 buckets
    assert p["bucket_s"] == 1800


def test_sites_registry_is_synthesised(v1):
    from app.services.events import read_json
    doc = read_json(v1, "_sites.json")
    ids = [s["id"] for s in doc["sites"]]
    assert ids == ["zapallar", "matanzas"]


def test_absent_blob_is_none_not_a_crash(v1):
    from app.services.events import read_json
    assert read_json(v1, "sites/zapallar/ocean_conditions.json") is None


def test_clip_path_resolves_to_the_v1_location(v1):
    from app.services import legacy_v1
    assert legacy_v1.clip_blob("zapallar", "clip_a.wav", "zapallar") == "clip_a.wav"
    assert legacy_v1.clip_blob("matanzas", "clip_a.wav", "zapallar") == "matanzas/clip_a.wav"


def test_non_finite_floats_become_null(tmp_path, monkeypatch):
    """The scar. Python writes Infinity, which is not valid JSON, and one
    unguarded parse blanked the dashboard in production."""
    (tmp_path / "status.json").write_text('{"schema_version":1,"cpu_temp_c":Infinity}')
    monkeypatch.setenv("OCEANKIND_CONTRACT_VERSION", "1")
    monkeypatch.setenv("OCEANKIND_STORAGE_BACKEND", "local")
    monkeypatch.setenv("OCEANKIND_LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("OCEANKIND_SESSION_SECRET", "x" * 40)
    from app.core.config import settings
    settings.cache_clear()
    from app.services.events import read_json
    from app.services.storage import LocalStorage
    st = read_json(LocalStorage(str(tmp_path)), "sites/zapallar/status.json")
    assert st["system"]["cpu_temp_c"] is None
