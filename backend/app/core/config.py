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

    # first-run bootstrap. blank in normal operation (R-3.5)
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""

    # held on behalf of devices. never leave the server (R-4.1, R-4.2)
    twilio_sid: str = ""
    twilio_token: str = ""
    config_hmac_key: str = ""


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
