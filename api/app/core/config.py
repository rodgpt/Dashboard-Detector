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

    # LEGACY-V1-BEGIN
    # 1 = read the v1 layout through services/legacy_v1.py and
    # normalize to v2. 2 = the real thing. Explicit, never auto-detected: a
    # wrong guess renders an empty dashboard, which is the exact silent failure
    # this project exists to remove.
    contract_version: int = 2
    v1_base_url: str = "https://marfuturatest.blob.core.windows.net/alerts"
    v1_root_site: str = "zapallar"
    v1_sites: str = ("zapallar:Zapallar:-32.552665:-71.465068,"
                     "matanzas:Matanzas:-33.986651:-71.860234")
    # LEGACY-V1-END

    db_url: str = "sqlite:////data/oceankind.db"
    session_hours: int = 12
    # Secure cookies require https. Off only for local http development.
    cookie_secure: bool = True

    # first-run bootstrap. blank in normal operation (R-3.5)
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""

    # held on behalf of devices. never leave the server (R-4.1, R-4.2)
    twilio_sid: str = ""
    twilio_token: str = ""
    config_signing_key: str = ""

    # LEGACY-V1-BEGIN
    def v1_site_list(self) -> list[dict]:
        """v1 has no `_sites.json`; the dashboard hardcoded the table."""
        out = []
        for row in filter(None, (r.strip() for r in self.v1_sites.split(","))):
            f = row.split(":")
            if len(f) != 4:
                raise RuntimeError(f"OCEANKIND_V1_SITES malformed near {row!r}")
            out.append({"id": f[0], "name": f[1], "lat": float(f[2]),
                        "lon": float(f[3]), "device": None, "active": True})
        return out
    # LEGACY-V1-END

    def validate_runtime(self) -> None:
        # LEGACY-V1-BEGIN
        if self.contract_version not in (1, 2):
            raise RuntimeError("OCEANKIND_CONTRACT_VERSION must be 1 or 2")
        if self.contract_version == 1:
            self.v1_site_list()                         # fail at boot, not per request
        # LEGACY-V1-END
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
