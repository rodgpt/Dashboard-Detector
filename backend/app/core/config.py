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

    # held on behalf of devices. never leave the server (R-4.1, R-4.2)
    twilio_sid: str = ""
    twilio_token: str = ""
    config_hmac_key: str = ""

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

    # Where a notification goes. A plain webhook: portable by construction, so it
    # works with whatever the client already runs. Empty means log-only, which is
    # the current state — Twilio remains blocked on client console access (F-04),
    # and the alert is recorded either way so nothing is lost when a transport
    # finally exists.
    silence_webhook_url: str = ""

    # Fallback when no tuned configuration exists for a site's device. Matches
    # the contract's default for `heartbeat_interval_s`.
    assumed_heartbeat_s: float = 60.0


    def validate_runtime(self) -> None:
        if len(self.session_secret) < 32:
            raise RuntimeError("OCEANKIND_SESSION_SECRET missing or too short (need 32+ chars)")
        if self.storage_backend == "azure" and not self.azure_connection_string:
            raise RuntimeError("storage_backend=azure but OCEANKIND_AZURE_CONNECTION_STRING is unset")
        if self.storage_backend == "s3" and not self.s3_bucket:
            raise RuntimeError("storage_backend=s3 but OCEANKIND_S3_BUCKET is unset")


@lru_cache
def settings() -> Settings:
    s = Settings()
    s.validate_runtime()
    return s
