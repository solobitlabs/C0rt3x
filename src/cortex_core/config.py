"""Configuracoes tipadas e seguras do C0rt3x Core."""

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CortexSettings(BaseSettings):
    """Parametros de configuracao carregados exclusivamente via ambiente/.env."""

    model_config = SettingsConfigDict(
        env_prefix="CORTEX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Domus C0rt3x Core"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000

    # Banco de dados (postgres-domus na rede interna domus_db)
    database_url: Optional[str] = None

    # PC Gamer Slave (Worker GPU sob demanda via S3 Wake-on-LAN)
    slave_mac: str = ""
    slave_host: str = ""
    slave_port: int = 8090
    slave_wol_port: int = 9
    slave_broadcast_ip: str = "255.255.255.255"
    slave_idle_timeout_seconds: int = Field(default=600, ge=30, le=86400)
    slave_wake_timeout_seconds: float = Field(default=12.0, ge=1.0, le=60.0)

    # Notificacoes externas (Apprise na rede notify_bus)
    apprise_url: str = "http://apprise:8000/notify/apprise"
    apprise_default_tag: str = "admin"

    # Integracoes SoloBit via HTTPS (sem ponte de rede Docker)
    despensa_api_url: str = "https://despensa.solobit.com.br"
    despensa_api_token: str = ""
    carteira_api_url: str = "https://carteira.solobit.com.br"
    carteira_api_token: str = ""

    # Seguranca & Privacidade
    home_wifi_ssid: str = "DOMUS-LAN-5G"
    default_reply_window_seconds: int = Field(default=8, ge=0, le=60)

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.strip().upper()
        if upper not in allowed:
            raise ValueError(f"log_level invalido: {value}")
        return upper

    @field_validator("slave_mac")
    @classmethod
    def _normalize_mac(cls, value: str) -> str:
        cleaned = value.strip().upper().replace("-", ":")
        if not cleaned:
            return ""
        parts = cleaned.split(":")
        if len(parts) != 6 or any(len(p) != 2 or not all(c in "0123456789ABCDEF" for c in p) for p in parts):
            raise ValueError("slave_mac deve estar no formato AA:BB:CC:DD:EE:FF")
        return cleaned

    def redacted_summary(self) -> dict[str, object]:
        """Retorna resumo seguro da configuracao sem expor segredos."""
        return {
            "app_name": self.app_name,
            "log_level": self.log_level,
            "database_configured": bool(self.database_url),
            "slave_configured": bool(self.slave_mac and self.slave_host),
            "slave_idle_timeout_seconds": self.slave_idle_timeout_seconds,
            "apprise_url": self.apprise_url,
            "despensa_configured": bool(self.despensa_api_token),
            "carteira_configured": bool(self.carteira_api_token),
        }


@lru_cache(maxsize=1)
def get_settings() -> CortexSettings:
    """Retorna instancia cacheada das configuracoes."""
    return CortexSettings()
