"""Base declarativa común a todos los modelos.

Cada tabla de negocio hereda de `Entity`, que aporta lo necesario para sincronizar
entre varios equipos y un servidor Postgres:

* `id` texto (UUID hex) en vez de autoincremental: dos cajas pueden crear registros sin
  chocar. Los datos semilla usan ids fijos ("seed-...") para que no se dupliquen.
* `updated_at` en UTC para resolver conflictos (gana la última escritura).
* `deleted` (borrado lógico): nada se borra físicamente, así el borrado también se sincroniza.
* `dirty`: marca local de "pendiente de subir".
* `rev`: número de revisión que asigna el servidor Postgres (trigger) para las descargas.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_now() -> datetime:
    """Hora de negocio (la del PC, Colombia). Se guarda sin zona horaria."""
    return datetime.now().replace(microsecond=0)


def fk(target: str, nullable: bool = True, index: bool = True):
    """Llave foránea diferible: permite sincronizar tablas en cualquier orden dentro
    de una transacción (Postgres) sin violar restricciones a mitad de camino."""
    return mapped_column(
        String(64),
        ForeignKey(target, deferrable=True, initially="DEFERRED"),
        nullable=nullable,
        index=index,
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class Entity(Base):
    __abstract__ = True
    # Tablas que no deben sincronizarse pueden poner esto en False
    __sync__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, index=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    dirty: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    rev: Mapped[int] = mapped_column(BigInteger, default=0, index=True)

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        label = getattr(self, "name", None) or getattr(self, "number", None) or self.id
        return f"<{type(self).__name__} {label}>"


def synced_tables():
    """Tablas a sincronizar, en orden de dependencias."""
    names = {
        m.local_table.name
        for m in Base.registry.mappers
        if issubclass(m.class_, Entity) and getattr(m.class_, "__sync__", True)
    }
    return [t for t in Base.metadata.sorted_tables if t.name in names]
