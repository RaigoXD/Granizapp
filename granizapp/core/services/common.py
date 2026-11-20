"""Piezas compartidas por todos los servicios."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Type, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from granizapp.core.models import AuditLog, Entity

T = TypeVar("T", bound=Entity)


class ServiceError(Exception):
    """Error de negocio con un mensaje apto para mostrar al usuario."""


@dataclass
class Actor:
    """Quién hace la operación y desde qué equipo."""

    user_id: str | None = None
    device_id: str = ""
    user_name: str = ""
    role: str = "admin"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


SYSTEM = Actor(user_id=None, device_id="", user_name="Sistema", role="admin")


def alive(model: Type[T]) -> Select:
    """SELECT de registros no borrados."""
    return select(model).where(model.deleted.is_(False))


def get(session: Session, model: Type[T], obj_id: str | None) -> T:
    if not obj_id:
        raise ServiceError(f"{model.__name__}: falta el identificador")
    obj = session.get(model, obj_id)
    if obj is None or obj.deleted:
        raise ServiceError(f"No se encontró el registro ({model.__name__})")
    return obj


def soft_delete(session: Session, obj: Entity) -> None:
    obj.deleted = True
    if hasattr(obj, "active"):
        obj.active = False


def update_fields(obj: Entity, data: dict, allowed: set[str]) -> None:
    for key, value in data.items():
        if key in allowed:
            setattr(obj, key, value)


def audit(session: Session, actor: Actor | None, action: str, entity: str = "", entity_id: str = "",
          detail: str = "") -> None:
    """Deja rastro en la bitácora (módulo Auditoría). `actor` None = acción del sistema."""
    actor = actor or SYSTEM
    session.add(
        AuditLog(user_id=actor.user_id, action=action, entity=entity, entity_id=entity_id or "",
                 detail=(detail or "")[:2000], device_id=actor.device_id or "")
    )


def require(condition, message: str) -> None:
    if not condition:
        raise ServiceError(message)
