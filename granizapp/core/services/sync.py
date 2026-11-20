"""Sincronización entre la base local (SQLite) y un servidor Postgres en internet.

Funciona sin internet en el bar y, cuando hay conexión, sube lo nuevo y baja lo que
hicieron otros equipos (p. ej. el portátil del dueño):

1. **Subir**: filas locales con `dirty = true`. En el servidor gana la versión con
   `updated_at` más reciente (la última escritura).
2. **Bajar**: filas del servidor con `rev` mayor al último visto. `rev` lo asigna un
   trigger de Postgres, así no dependemos de que los relojes de los PCs coincidan.
3. Se marcan como sincronizadas solo las filas que no cambiaron mientras tanto.

Como los ids son UUID y el inventario/dinero son movimientos (no saldos), dos cajas
vendiendo a la vez no se pisan.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Connection, Table, select, text

from granizapp.core.db import SCHEMA_VERSION, Database, init_schema, make_engine, meta_table, set_meta
from granizapp.core.models import synced_tables

log = logging.getLogger(__name__)

CHUNK = 500
REV_OVERLAP = 1000  # se vuelven a revisar las últimas revisiones por si una transacción tardó en confirmar


@dataclass
class SyncResult:
    pushed: int = 0
    pulled: int = 0
    tables: dict[str, tuple[int, int]] = field(default_factory=dict)
    started: datetime = field(default_factory=datetime.now)
    finished: datetime | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def text(self) -> str:
        if self.error:
            return f"Error: {self.error}"
        return f"Subidos {self.pushed}, descargados {self.pulled}"


def check_connection(url: str) -> str:
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version()")).scalar()
        return str(version).split(",")[0]
    finally:
        engine.dispose()


def _remote_version(conn: Connection) -> int:
    row = conn.execute(select(meta_table.c.value).where(meta_table.c.key == "schema_version")).first()
    return int(row[0]) if row else 0


def _rows(conn: Connection, table: Table, where) -> list[dict]:
    return [dict(r) for r in conn.execute(select(table).where(where)).mappings()]


def _existing(conn: Connection, table: Table, ids: list[str]) -> dict[str, datetime]:
    out = {}
    for i in range(0, len(ids), CHUNK):
        chunk = ids[i:i + CHUNK]
        for rid, ua in conn.execute(select(table.c.id, table.c.updated_at).where(table.c.id.in_(chunk))):
            out[rid] = ua
    return out


def _apply(conn: Connection, table: Table, rows: list[dict], dirty: bool) -> tuple[int, list[str]]:
    """Inserta o actualiza filas si son más nuevas (última escritura gana).

    Devuelve (filas aplicadas, ids rechazados porque el destino tenía una versión más nueva).
    """
    if not rows:
        return 0, []
    existing = _existing(conn, table, [r["id"] for r in rows])
    inserts, updates, rejected = [], [], []
    for r in rows:
        r = dict(r)
        r["dirty"] = dirty
        if r["id"] not in existing:
            inserts.append(r)
        elif existing[r["id"]] is None or (r["updated_at"] and r["updated_at"] > existing[r["id"]]):
            updates.append(r)
        elif r["updated_at"] != existing[r["id"]]:
            rejected.append(r["id"])
    for i in range(0, len(inserts), CHUNK):
        conn.execute(table.insert(), inserts[i:i + CHUNK])
    for r in updates:
        values = {k: v for k, v in r.items() if k != "id"}
        conn.execute(table.update().where(table.c.id == r["id"]).values(**values))
    return len(inserts) + len(updates), rejected


def synchronize(local: Database, remote_url: str, progress=None) -> SyncResult:
    """Sincroniza en ambos sentidos. `progress(texto)` recibe avances para la interfaz."""
    result = SyncResult()
    if not local.is_sqlite:
        result.error = "La sincronización solo aplica cuando se trabaja con la base local (SQLite)."
        return result
    remote = make_engine(remote_url)
    try:
        if progress:
            progress("Preparando el servidor…")
        init_schema(remote)
        tables = synced_tables()
        with remote.connect() as rconn:
            rv = _remote_version(rconn)
            if rv > SCHEMA_VERSION:
                result.error = "El servidor tiene una versión más nueva de la app. Actualice este equipo."
                return result
            server_id = rconn.execute(select(meta_table.c.value).where(meta_table.c.key == "server_id")).scalar()
        if not server_id:
            import uuid

            with remote.begin() as rconn:
                server_id = uuid.uuid4().hex
                set_meta(rconn, "server_id", server_id)
        rev_key = f"sync_rev:{server_id}"
        last_rev = int(local.get_meta(rev_key, "0") or 0)

        # 1. subir
        pushed: dict[str, list[tuple[str, datetime]]] = {}
        rejected: dict[str, list[str]] = {}
        with local.engine.connect() as lconn:
            pending = {t.name: _rows(lconn, t, t.c.dirty.is_(True)) for t in tables}
        with remote.begin() as rconn:
            for t in tables:
                rows = pending[t.name]
                if not rows:
                    continue
                if progress:
                    progress(f"Subiendo {t.name} ({len(rows)})…")
                n, rej = _apply(rconn, t, rows, dirty=False)
                result.pushed += n
                result.tables[t.name] = (n, 0)
                pushed[t.name] = [(r["id"], r["updated_at"]) for r in rows]
                if rej:
                    rejected[t.name] = rej

        # 2. bajar (incluye las filas donde el servidor tenía una versión más nueva)
        max_rev = last_rev
        incoming: dict[str, list[dict]] = {}
        with remote.connect() as rconn:
            since = max(0, last_rev - REV_OVERLAP)
            for t in tables:
                rows = _rows(rconn, t, t.c.rev > since)
                have = {r["id"] for r in rows}
                missing = [rid for rid in rejected.get(t.name, []) if rid not in have]
                for i in range(0, len(missing), CHUNK):
                    rows.extend(_rows(rconn, t, t.c.id.in_(missing[i:i + CHUNK])))
                if rows:
                    incoming[t.name] = rows
                    max_rev = max(max_rev, max(r["rev"] for r in rows))
        with local.engine.begin() as lconn:
            for t in tables:
                rows = incoming.get(t.name, [])
                if rows:
                    if progress:
                        progress(f"Descargando {t.name} ({len(rows)})…")
                    n, _ = _apply(lconn, t, rows, dirty=False)
                    result.pulled += n
                    up, _ = result.tables.get(t.name, (0, 0))
                    result.tables[t.name] = (up, n)
                # 3. marcar como sincronizado lo que se subió y no cambió entretanto
                for rid, ua in pushed.get(t.name, []):
                    lconn.execute(
                        t.update().where(t.c.id == rid, t.c.updated_at == ua).values(dirty=False)
                    )
            set_meta(lconn, rev_key, str(max_rev))
            set_meta(lconn, "last_sync", datetime.now().isoformat(timespec="seconds"))
    except Exception as exc:  # se muestra al usuario; la app sigue funcionando sin conexión
        log.exception("Error de sincronización")
        result.error = _friendly(exc)
    finally:
        remote.dispose()
        result.finished = datetime.now()
    return result


def pending_count(local: Database) -> int:
    total = 0
    with local.engine.connect() as conn:
        for t in synced_tables():
            total += conn.execute(select(text("count(*)")).select_from(t).where(t.c.dirty.is_(True))).scalar() or 0
    return int(total)


def _friendly(exc: Exception) -> str:
    msg = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
    low = msg.lower()
    if "password authentication failed" in low:
        return "Usuario o contraseña de Postgres incorrectos."
    if "could not translate host name" in low or "name or service not known" in low or "getaddrinfo" in low:
        return "No se encontró el servidor. Revise la dirección o la conexión a internet."
    if "timeout" in low or "timed out" in low:
        return "El servidor no respondió (sin internet o servidor apagado)."
    if "connection refused" in low:
        return "El servidor rechazó la conexión (puerto o firewall)."
    if "ssl" in low:
        return "Problema de SSL. Pruebe agregando ?sslmode=require a la URL."
    return msg[:300]
