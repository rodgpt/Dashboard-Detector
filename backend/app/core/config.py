"""Configuration. Everything from the environment, nothing baked into the image (R-1.3).

Refuses to start when a required secret is missing rather than falling back to a
default. That fallback is how a live Twilio token ended up in source, a backup,
two bytecode caches and a git remote (R-4.3, F-04).
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OCEANKIND_", env_file=".env", extra="ignore")

    # required
    session_secret: str                       # openssl rand -hex 32
    storage_backend: str = "local"            # local | azure | s3

    # storage: local
    local_storage_root: str = "/fixtures"
    # storage: azure
    azure_connection_string: str = ""
    azure_container: str = "alerts"
    # storage: s3
    s3_bucket: str = ""


    # Postgres in its own container (R-9.2, D-019). SQLite is still accepted so
    # the test suite can run against a temp file without a database service.
    db_url: str = "postgresql+psycopg://oceankind:oceankind@db:5432/oceankind"
    session_hours: int = 12
    # Secure cookies require https. Off only for local http development.
    cookie_secure: bool = True

    # How much the application says about itself. INFO shows the two timers
    # starting and each reconcile pass; WARNING and above always reaches the
    # stream, since that is where device alerts and drift warnings go.
    log_level: str = "INFO"

    # first-run bootstrap. blank in normal operation (R-3.5)
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""

    # ── alerting: the backend is the only sender (Rpi-Detector D-020) ─────────
    #
    # Every WhatsApp and voice alert the system produces leaves from here, with
    # the one Twilio credential, held on behalf of the fleet (R-4.1, R-4.2). No
    # device holds any of this. Without SID, token and a sender number the
    # transport is "log-only": alerts are recorded and shown on the dashboard,
    # and nobody is paged — /api/health says so.
    alerts_enabled: bool = True
    twilio_sid: str = ""
    twilio_token: str = ""
    twilio_from: str = ""                    # whatsapp:+56...
    # Recipients, comma-separated `whatsapp:+56...`. ALERT_TO gets detections;
    # TECH_TO gets silence, degradation, battery and the periodic heartbeat
    # message. TECH_TO defaults to ALERT_TO when empty.
    alert_to: str = ""
    tech_to: str = ""
    # Voice call on a cluster of detections (the old device behaviour, moved).
    call_from: str = ""                      # +1...
    call_to: str = ""                        # comma-separated +56...
    call_cluster_count: int = 3
    call_cluster_window_s: float = 240.0
    call_cooldown_s: float = 900.0
    # Approved WhatsApp content templates (SIDs are not secrets). Same three the
    # device used; the heartbeat template is the one with a free-text field and
    # doubles as the carrier for every operational message.
    wa_tpl_alert: str = "HX901414845dda773c146ce65d79f79863"
    wa_tpl_heartbeat: str = "HXe9015f651079907384ecabf3add8dd69"
    wa_tpl_battery: str = "HX9cad665cd4be3a5a5482162d1776d1ba"
    wa_tpl_version: str = "3"
    # Public URL of this dashboard, for the ?play= link in detection alerts.
    dashboard_url: str = ""
    # The periodic "I am alive" message to the technical contact, hours. 0 = off.
    alert_heartbeat_hours: float = 12.0
    # Battery thresholds (V), debounced over consecutive heartbeats. Moved from
    # the device unchanged.
    battery_warning_v: float = 11.8
    battery_critical_v: float = 11.2
    battery_emergency_v: float = 10.8
    battery_recovery_v: float = 12.2
    battery_debounce_heartbeats: int = 10
    # Timezone for the times quoted in messages.
    site_tz: str = "America/Santiago"

    # ── releases (Rpi-Detector D-021) ───────────────────────────────────────
    # GitHub repository whose tags are offered as releases in the admin panel.
    release_repo: str = "rodgpt/Rpi-Detector"

    # --- the reconcile pass (R-12.4, D-021, D-022) ---------------------------
    #
    # How often the index is checked against storage. 0 disables the in-process
    # timer, for tests and for a deployment driving the pass from outside.
    #
    # Daily rather than the weekly D-022 first specified. The pass turned out to
    # cost nothing in steady state — it diffs blob *names* against indexed
    # `event_id`s and fetches only what is new, so a clean run is a few list
    # calls and one query. Weekly was chosen when the cost was assumed higher,
    # and it sets the worst-case delay for an event whose push failed at seven
    # days. Daily makes that one day for the same effectively-zero cost.
    reconcile_interval_hours: float = 24.0

    # How far back each pass looks. This is a commitment, not a tuning knob:
    # "we will not lose events from a device that was offline for less than
    # this". Partitions are keyed on capture time, so a spooled device draining
    # late writes into prefixes already read to the end of — a window shorter
    # than the outage loses those events silently (R-12.4).
    reconcile_window_days: int = 14

    # ── device-silence alerting (R-7.5, D-022) ───────────────────────────────
    #
    # ALL FOUR KNOBS THAT CONTROL NOTIFICATION VOLUME ARE HERE. Nothing else in
    # the codebase decides when or how often somebody is told. If you are getting
    # too many notifications, or want them sooner, this block is the only place
    # to change — see `services/silence.py` for the state machine they drive.
    #
    # 1. Off switch.
    silence_alerts_enabled: bool = True

    # 2. HOW OFTEN WE LOOK. Cheap: one small blob per site. Does not affect how
    #    often anyone is *told* — that is governed by 3 and 4. Looking often and
    #    telling rarely is the intended shape.
    silence_check_interval_minutes: float = 5.0

    # 3. HOW LONG BEFORE THE FIRST WARNING. Expressed in missed heartbeats rather
    #    than minutes, because `heartbeat_interval_s` is remotely tunable from
    #    30 s to 3600 s: a fixed "one hour" would be 120 missed beats on one
    #    setting and less than one on another. `silence_min_minutes` is a floor
    #    so that a fast heartbeat cannot make the system twitchy — with the
    #    defaults, a 60 s heartbeat warns after 20 minutes of true silence, and a
    #    30 s heartbeat still waits 15 rather than 10.
    #
    #    Raise `silence_after_missed_heartbeats` if a flaky cellular link is
    #    producing warnings for outages that resolve themselves.
    silence_after_missed_heartbeats: int = 20
    silence_min_minutes: float = 15.0

    # 4. HOW OFTEN WE REPEAT OURSELVES while a unit stays down. **This is the
    #    anti-flood setting.** An open alert notifies once and then goes quiet
    #    for this long, however many times the check runs in between. A unit down
    #    for a week produces 7 messages at the default, not 2,016.
    #    Set to 0 to notify exactly once per outage and never repeat.
    silence_renotify_hours: float = 24.0

    # Where a silence notification goes: the Twilio transport above (D-020).
    # The webhook that used to be here was never configured anywhere and the
    # client decided against a second notification service.

    # Fallback when no tuned configuration exists for a site's device. Matches
    # the contract's default for `heartbeat_interval_s`.
    assumed_heartbeat_s: float = 60.0

    # How far ahead of the server a heartbeat's `last_seen` may be before it is
    # rejected as a wrong device clock (400). Generous enough for drift on a
    # unit whose NTP is a little behind; tight enough that a Pi booting without
    # a time source cannot poison its own status row (review BE-02).
    heartbeat_max_future_s: float = 300.0


    def validate_runtime(self) -> None:
        if len(self.session_secret) < 32:
            raise RuntimeError("OCEANKIND_SESSION_SECRET missing or too short (need 32+ chars)")
        if self.storage_backend == "azure" and not self.azure_connection_string:
            raise RuntimeError("storage_backend=azure but OCEANKIND_AZURE_CONNECTION_STRING is unset")
        # Only backends `services/storage.get_storage` can build. `s3` is a
        # documented option with no class behind it yet; accepting it here let
        # the process boot and then 500 on every data request while /api/health
        # said ok (review BE-07b). Refuse to start instead.
        if self.storage_backend not in ("local", "azure"):
            raise RuntimeError(
                f"storage_backend={self.storage_backend!r} is not implemented "
                "(services/storage.py knows local and azure)")


@lru_cache
def settings() -> Settings:
    s = Settings()
    s.validate_runtime()
    return s
