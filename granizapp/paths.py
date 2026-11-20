"""Rutas de datos de la aplicación.

La base de datos local vive en %LOCALAPPDATA%\\GranizApp (fuera de OneDrive, que corrompe
archivos SQLite abiertos). Los respaldos van a Documentos\\GranizApp\\Respaldos, donde sí
conviene que OneDrive los copie. La variable de entorno GRANIZAPP_HOME permite aislar
los datos (pruebas, varias sucursales en el mismo PC).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from granizapp import APP_NAME


def app_home() -> Path:
    env = os.environ.get("GRANIZAPP_HOME")
    if env:
        path = Path(env)
    else:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
        path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_backup_dir() -> Path:
    env = os.environ.get("GRANIZAPP_HOME")
    if env:
        return Path(env) / "Respaldos"
    return Path.home() / "Documents" / APP_NAME / "Respaldos"


def resource_path(relative: str) -> Path:
    """Ruta a un recurso empaquetado (funciona igual con PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative
