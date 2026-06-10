from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://kio:kio@localhost:5432/kio"
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_prefix: str = "kio/dev"
    # External MQTT address advertised to Pi nodes via /agent/config.
    # Separate from mqtt_host which may be an internal k8s service address.
    mqtt_node_host: str = ""
    mqtt_node_port: int = 1883
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:4173"]
    node_offline_threshold_seconds: int = 90
    log_level: str = "INFO"
    # Expose the interactive API docs (/docs, /redoc, /openapi.json).
    # Off by default (locked down); enable per-env (e.g. dev) via DOCS_ENABLED=true.
    docs_enabled: bool = False

    # Auth
    # Set to true to disable all dashboard auth (local dev only).
    auth_disabled: bool = False
    # Authentik OIDC issuer URL, e.g. https://auth.example.com/application/o/kio/
    # If set, Bearer JWTs issued by Authentik are accepted on dashboard routes.
    authentik_issuer: str = ""
    # Static credentials for local dev (no Authentik). POST /auth/login to get a token.
    dev_username: str = ""
    dev_password: str = ""
    # Comma-separated static API keys for programmatic clients (HACS, etc.).
    # Each key should start with "kio_" by convention.
    api_keys: list[str] = []

    @property
    def api_keys_set(self) -> set[str]:
        return set(self.api_keys)


settings = Settings()
