"""Usuarios y PIN de acceso.

Si ningún usuario tiene PIN, la aplicación abre directamente como administrador
(ideal mientras se configura). En cuanto exista un PIN, se pide ingreso.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from granizapp.core.models import Role, User
from granizapp.core.services.common import Actor, ServiceError, alive, audit, get, require
from granizapp.core.utils import normalize

_ITERATIONS = 120_000


def hash_pin(pin: str) -> str:
    salt = secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), _ITERATIONS).hex()
    return f"{salt}${digest}"


def check_pin(pin: str, stored: str) -> bool:
    if not stored:
        return pin == ""
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), _ITERATIONS).hex()
    return hmac.compare_digest(candidate, digest)


def list_users(session: Session, include_inactive: bool = False) -> list[User]:
    stmt = alive(User).order_by(User.name)
    if not include_inactive:
        stmt = stmt.where(User.active.is_(True))
    return list(session.scalars(stmt))


def login_required(session: Session) -> bool:
    return any(u.pin_hash for u in list_users(session))


def save_user(session: Session, data: dict, user_id: str | None = None, actor: Actor | None = None) -> User:
    name = (data.get("name") or "").strip()
    require(name, "El nombre del usuario es obligatorio")
    username = normalize(data.get("username") or name).replace(" ", ".")
    dup = session.scalars(alive(User).where(User.username == username)).first()
    require(dup is None or dup.id == user_id, f"Ya existe el usuario '{username}'")
    user = get(session, User, user_id) if user_id else User()
    user.name = name
    user.username = username
    user.role = data.get("role") or Role.CASHIER
    user.active = bool(data.get("active", True))
    user.employee_id = data.get("employee_id") or None
    pin = data.get("pin")
    if pin is not None and pin != "":
        require(pin.isdigit() and 4 <= len(pin) <= 8, "El PIN debe tener de 4 a 8 números")
        if user.role != Role.ADMIN:
            _require_admins_with_pin(session, exclude_id=user_id)
        user.pin_hash = hash_pin(pin)
    if user_id is None:
        session.add(user)
    session.flush()
    if user.role != Role.ADMIN or not user.active:
        _ensure_admin_left(session)
    if user.role == Role.ADMIN and not user.pin_hash and user.active:
        _require_no_other_pins(session, user)
    changes = [Role.LABELS.get(user.role, user.role), "activo" if user.active else "inactivo"]
    if pin:
        changes.append("PIN nuevo")
    audit(session, actor, "crear_usuario" if user_id is None else "editar_usuario", "user", user.id,
          f"{user.name} ({user.username}): " + ", ".join(changes))
    return user


def clear_pin(session: Session, user_id: str, actor: Actor | None = None) -> None:
    user = get(session, User, user_id)
    if user.role == Role.ADMIN and user.active:
        _require_no_other_pins(session, user)
    user.pin_hash = ""
    audit(session, actor, "quitar_pin", "user", user.id, user.name)


def _ensure_admin_left(session: Session) -> None:
    admins = session.scalars(alive(User).where(User.role == Role.ADMIN, User.active.is_(True))).all()
    if not admins:
        raise ServiceError("Debe quedar al menos un administrador activo")


def _require_admins_with_pin(session: Session, exclude_id: str | None) -> None:
    """Si un cajero tiene PIN, todos los administradores deben tenerlo: si no, cualquiera
    podría entrar como administrador con el PIN vacío."""
    missing = [u.name for u in list_users(session) if u.role == Role.ADMIN and not u.pin_hash and u.id != exclude_id]
    if missing:
        raise ServiceError("Antes de ponerle PIN a un cajero, el administrador debe tener su propio PIN "
                           f"(sin PIN: {', '.join(missing)}).")


def _require_no_other_pins(session: Session, admin: User) -> None:
    others = [u.name for u in list_users(session) if u.pin_hash and u.id != admin.id]
    if others:
        raise ServiceError(f"Mientras otros usuarios tengan PIN ({', '.join(others)}), el administrador "
                           "también debe tener uno.")


def authenticate(session: Session, user_id: str, pin: str, device_id: str) -> Actor:
    user = get(session, User, user_id)
    require(user.active, "El usuario está inactivo")
    actor = Actor(user_id=user.id, device_id=device_id, user_name=user.name, role=user.role)
    if not check_pin(pin, user.pin_hash):
        audit(session, actor, "ingreso_fallido", "user", user.id, f"PIN incorrecto para {user.name}")
        session.flush()
        session.commit()  # el intento fallido queda registrado aunque la operación «falle»
        raise ServiceError("PIN incorrecto")
    audit(session, actor, "ingreso", "user", user.id, user.name)
    return actor


def default_actor(session: Session, device_id: str) -> Actor:
    """Actor cuando no se exige ingreso: el primer administrador."""
    admin = session.scalars(
        select(User).where(User.deleted.is_(False), User.role == Role.ADMIN, User.active.is_(True)).order_by(User.created_at)
    ).first()
    if admin is None:
        return Actor(user_id=None, device_id=device_id, user_name="Administrador", role=Role.ADMIN)
    return Actor(user_id=admin.id, device_id=device_id, user_name=admin.name, role=admin.role)
