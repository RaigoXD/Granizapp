"""Conexión a la base de datos (SQLite local o Postgres) y esquema.

Uso típico desde servicios o pantallas:

    with get_db().session() as s:
        ...  # commit automático al salir, rollback si hay excepción
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Callable, Iterator

from sqlalchemy import Column, Connection, Float, MetaData, String, Table, Text, create_engine, event, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from granizapp.core import models  # noqa: F401  (registra todas las tablas)
from granizapp.core.models.base import Base, Entity, synced_tables, utcnow

log = logging.getLogger(__name__)

SCHEMA_VERSION = 3

meta_md = MetaData()
meta_table = Table(
    "_meta",
    meta_md,
    Column("key", String(64), primary_key=True),
    Column("value", Text, default=""),
)


def _sqlite_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()


def _mark_dirty(session: Session, _ctx, _instances):
    """Todo registro creado o modificado localmente queda pendiente de sincronizar."""
    for obj in list(session.new) + list(session.dirty):
        if isinstance(obj, Entity) and (obj in session.new or session.is_modified(obj)):
            obj.dirty = True
            if obj not in session.new:
                obj.updated_at = utcnow()


def make_engine(url: str, echo: bool = False):
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        engine = create_engine(url, echo=echo, connect_args={"check_same_thread": False, "timeout": 30})
        event.listen(engine, "connect", _sqlite_pragmas)
    else:
        engine = create_engine(
            url,
            echo=echo,
            pool_pre_ping=True,
            pool_recycle=300,
            connect_args={"connect_timeout": 10},
        )
    return engine


class Database:
    def __init__(self, url: str, echo: bool = False):
        self.url = url
        self.is_sqlite = url.startswith("sqlite")
        self.engine = make_engine(url, echo)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        event.listen(self.SessionLocal, "before_flush", _mark_dirty)

    # --- sesiones -----------------------------------------------------------------
    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self.SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # --- esquema ------------------------------------------------------------------
    def init_schema(self) -> bool:
        """Crea/actualiza tablas. Devuelve True si la base estaba vacía (primer uso)."""
        return init_schema(self.engine)

    def get_meta(self, key: str, default: str = "") -> str:
        with self.engine.connect() as conn:
            row = conn.execute(select(meta_table.c.value).where(meta_table.c.key == key)).first()
            return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.engine.begin() as conn:
            set_meta(conn, key, value)

    def dispose(self) -> None:
        self.engine.dispose()


def set_meta(conn: Connection, key: str, value: str) -> None:
    exists = conn.execute(select(meta_table.c.key).where(meta_table.c.key == key)).first()
    if exists:
        conn.execute(meta_table.update().where(meta_table.c.key == key).values(value=value))
    else:
        conn.execute(meta_table.insert().values(key=key, value=value))


def init_schema(engine) -> bool:
    existing = set(inspect(engine).get_table_names())
    fresh = "products" not in existing
    meta_md.create_all(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        row = conn.execute(select(meta_table.c.value).where(meta_table.c.key == "schema_version")).first()
        current = int(row[0]) if row else (SCHEMA_VERSION if fresh else 0)
        for version in range(current + 1, SCHEMA_VERSION + 1):
            log.info("Aplicando migración %s", version)
            MIGRATIONS[version](conn)
        set_meta(conn, "schema_version", str(SCHEMA_VERSION))
        if engine.dialect.name == "postgresql":
            prepare_postgres(conn)
    return fresh


# --- migraciones -------------------------------------------------------------------
# Para agregar un campo nuevo en una versión futura:
#   1. agregarlo al modelo,
#   2. subir SCHEMA_VERSION,
#   3. registrar aquí una función que use add_column(conn, "tabla", Column(...)).


def add_column(conn: Connection, table: str, column: Column) -> None:
    cols = {c["name"] for c in inspect(conn).get_columns(table)}
    if column.name in cols:
        return
    ddl_type = column.type.compile(dialect=conn.dialect)
    default = ""
    if column.server_default is not None:
        arg = column.server_default.arg
        default = f" DEFAULT '{arg}'" if isinstance(arg, str) else f" DEFAULT {arg}"
    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN "{column.name}" {ddl_type}{default}'))


def _migration_1(conn: Connection) -> None:  # esquema inicial: create_all ya lo creó
    pass


def _migration_2(conn: Connection) -> None:  # v1.2: la bitácora guarda desde qué equipo se hizo cada acción
    add_column(conn, "audit_log", Column("device_id", String(8), server_default=""))


def _migration_3(conn: Connection) -> None:
    """v1.3: insumos con variantes (sabores). La tabla `supply_groups` la crea create_all;
    aquí van las columnas nuevas. Los datos (sabores de la v1.2, recetas, ventas anteriores)
    los convierte `seed.migrate_flavors` al arrancar."""
    add_column(conn, "supplies", Column("group_id", String(64)))
    add_column(conn, "supplies", Column("variant_name", String(80), server_default=""))
    add_column(conn, "supplies", Column("variant_code", String(12), server_default=""))
    add_column(conn, "recipe_lines", Column("supply_group_id", String(64)))
    add_column(conn, "sale_item_modifiers", Column("supply_id", String(64)))
    add_column(conn, "sale_item_modifiers", Column("supply_group_id", String(64)))
    add_column(conn, "sale_item_modifiers", Column("quantity", Float, server_default="0"))


MIGRATIONS: dict[int, Callable[[Connection], None]] = {1: _migration_1, 2: _migration_2, 3: _migration_3}


# --- Postgres: número de revisión para sincronizar ------------------------------------
def prepare_postgres(conn: Connection) -> None:
    """Instala en Postgres una secuencia y un trigger que numera cada cambio (`rev`).

    Los equipos que sincronizan descargan "todo lo que tenga rev mayor al último visto",
    sin depender de que los relojes de los PCs coincidan.
    """
    conn.execute(text("CREATE SEQUENCE IF NOT EXISTS granizapp_rev_seq"))
    conn.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION granizapp_set_rev() RETURNS trigger AS $$
            BEGIN
                NEW.rev := nextval('granizapp_rev_seq');
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    for table in synced_tables():
        trigger = f"trg_{table.name}_rev"
        exists = conn.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = :n"), {"n": trigger}
        ).first()
        if not exists:
            conn.execute(
                text(
                    f"CREATE TRIGGER {trigger} BEFORE INSERT OR UPDATE ON {table.name} "
                    f"FOR EACH ROW EXECUTE FUNCTION granizapp_set_rev()"
                )
            )


# --- acceso global -----------------------------------------------------------------
_db: Database | None = None


def set_db(db: Database | None) -> None:
    global _db
    _db = db


def get_db() -> Database:
    if _db is None:
        raise RuntimeError("La base de datos no está inicializada")
    return _db
