"""Configuración propia de este PC (no se sincroniza).

Lo que es del negocio (nombre, NIT, base de caja, etc.) vive en la tabla `settings` de la
base de datos y sí se sincroniza. Aquí solo va lo que depende del equipo: qué base de
datos usar, la URL de Postgres, el identificador del dispositivo y los respaldos.
"""
from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from granizapp.paths import app_home, default_backup_dir

CONFIG_FILE = "config.json"


@dataclass
class AppConfig:
    # "sqlite": trabaja sobre el archivo local (recomendado en el bar, funciona sin internet).
    # "postgres": trabaja directamente sobre el servidor Postgres (requiere internet).
    db_mode: str = "sqlite"
    sqlite_path: str = ""
    postgres_url: str = ""
    # Sincronización SQLite <-> Postgres (solo en modo sqlite)
    sync_enabled: bool = False
    sync_interval_min: int = 10
    # Identidad del equipo: prefijo de los consecutivos de venta y de la caja
    device_id: str = field(default_factory=lambda: secrets.token_hex(2).upper())
    device_name: str = "Caja principal"
    # Cuenta de cajón de este equipo (si hay varias cajas, cada una tiene la suya)
    drawer_account_id: str = ""
    # Respaldos automáticos del archivo SQLite
    backup_dir: str = ""
    backup_keep: int = 30
    theme: str = "light"
    last_username: str = ""
    # Ayuda: guías rápidas que el usuario ocultó en este equipo y si ya vio la bienvenida
    help_hidden: list[str] = field(default_factory=list)
    welcome_seen: bool = False

    @property
    def resolved_sqlite_path(self) -> Path:
        return Path(self.sqlite_path) if self.sqlite_path else app_home() / "granizapp.db"

    @property
    def resolved_backup_dir(self) -> Path:
        return Path(self.backup_dir) if self.backup_dir else default_backup_dir()

    def database_url(self) -> str:
        if self.db_mode == "postgres" and self.postgres_url:
            return normalize_pg_url(self.postgres_url)
        return f"sqlite:///{self.resolved_sqlite_path.as_posix()}"

    # --- persistencia -------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        path = path or app_home() / CONFIG_FILE
        cfg = cls()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                known = {f.name for f in fields(cls)}
                for key, value in data.items():
                    if key in known:
                        setattr(cfg, key, value)
            except (OSError, ValueError):
                pass  # un config dañado no debe impedir abrir la caja
        else:
            cfg.save(path)
        return cfg

    def save(self, path: Path | None = None) -> None:
        path = path or app_home() / CONFIG_FILE
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")


def normalize_pg_url(url: str) -> str:
    """Acepta URLs tal como las entregan Supabase/Neon/Railway y las adapta a psycopg 3."""
    url = url.strip()
    for prefix in ("postgres://", "postgresql://", "postgresql+psycopg2://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def mask_url(url: str) -> str:
    """Oculta la contraseña para mostrar la URL en pantalla o en logs."""
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, host = rest.rsplit("@", 1)
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:****@{host}"
