"""Personal y usuarios del sistema."""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import Boolean, Date, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from granizapp.core.models.base import Entity, fk


class PayType:
    BIWEEKLY = "quincenal"
    WEEKLY = "semanal"
    DAILY = "por_turno"
    HOURLY = "por_hora"
    MONTHLY = "mensual"

    LABELS = {
        MONTHLY: "Mensual",
        BIWEEKLY: "Quincenal",
        WEEKLY: "Semanal",
        DAILY: "Por turno / día",
        HOURLY: "Por hora",
    }


class Employee(Entity):
    __tablename__ = "employees"

    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(60), default="Bartender")
    phone: Mapped[str] = mapped_column(String(40), default="")
    document: Mapped[str] = mapped_column(String(40), default="")
    pay_type: Mapped[str] = mapped_column(String(12), default=PayType.BIWEEKLY)
    base_pay: Mapped[int] = mapped_column(Integer, default=0)      # valor por periodo
    hourly_rate: Mapped[int] = mapped_column(Integer, default=0)   # hora extra / por hora
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class Role:
    ADMIN = "admin"
    CASHIER = "cajero"

    LABELS = {ADMIN: "Administrador", CASHIER: "Cajero / bartender"}


class User(Entity):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(80))
    username: Mapped[str] = mapped_column(String(40), index=True)
    pin_hash: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(10), default=Role.CASHIER)
    employee_id: Mapped[Optional[str]] = fk("employees.id")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Setting(Entity):
    """Parámetros del negocio (se sincronizan). El id es la propia clave."""

    __tablename__ = "settings"

    value: Mapped[str] = mapped_column(Text, default="")


class AuditLog(Entity):
    """Bitácora de acciones sensibles: anulaciones, ajustes, cierres de caja, cambios de precio,
    usuarios, ingresos... (`created_at` está en UTC; se muestra en hora local)."""

    __tablename__ = "audit_log"

    user_id: Mapped[Optional[str]] = fk("users.id")
    action: Mapped[str] = mapped_column(String(40), index=True)
    entity: Mapped[str] = mapped_column(String(40), default="")
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    device_id: Mapped[str] = mapped_column(String(8), default="", server_default="")  # desde qué equipo
