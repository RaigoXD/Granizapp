"""Respaldos del archivo SQLite (copia en caliente con la API de backup de SQLite)."""
from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

PREFIX = "granizapp_"


def backup_sqlite(db_path: Path, dest_dir: Path, keep: int = 30, tag: str = "auto") -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{PREFIX}{datetime.now():%Y%m%d_%H%M%S}_{tag}.db"
    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    prune(dest_dir, keep)
    return target


def list_backups(dest_dir: Path) -> list[Path]:
    if not dest_dir.exists():
        return []
    return sorted(dest_dir.glob(f"{PREFIX}*.db"), key=lambda p: p.stat().st_mtime, reverse=True)


def prune(dest_dir: Path, keep: int) -> None:
    autos = [p for p in list_backups(dest_dir) if p.stem.endswith("_auto")]
    for old in autos[max(keep, 1):]:
        try:
            old.unlink()
        except OSError:
            pass


def backed_up_today(dest_dir: Path) -> bool:
    today = datetime.now().strftime("%Y%m%d")
    return any(p.name.startswith(f"{PREFIX}{today}") for p in list_backups(dest_dir))


def restore(backup_file: Path, db_path: Path) -> Path:
    """Reemplaza la base actual por un respaldo (la actual se guarda antes por si acaso).
    La aplicación debe cerrar la conexión antes y reiniciarse después."""
    safety = db_path.with_name(f"{db_path.stem}_antes_de_restaurar_{datetime.now():%Y%m%d_%H%M%S}.db")
    if db_path.exists():
        shutil.copy2(db_path, safety)
    for suffix in ("-wal", "-shm"):
        side = db_path.with_name(db_path.name + suffix)
        if side.exists():
            side.unlink()
    shutil.copy2(backup_file, db_path)
    return safety
