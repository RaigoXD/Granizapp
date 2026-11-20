"""Contexto compartido por todas las pantallas: base de datos, usuario, equipo y eventos."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from granizapp.config import AppConfig
from granizapp.core.db import Database
from granizapp.core.services.common import Actor


class Topics:
    """Temas de cambio: las pantallas se marcan para refrescar cuando cambia algo que muestran."""

    SALES = "ventas"
    CASH = "caja"
    CUSTOMERS = "clientes"
    CATALOG = "catalogo"
    INVENTORY = "inventario"
    PURCHASES = "compras"
    EXPENSES = "gastos"
    FINANCE = "finanzas"
    STAFF = "personal"
    SETTINGS = "configuracion"
    ALL = "*"


class Bus(QObject):
    changed = Signal(str)
    status = Signal(str)          # mensaje corto para la barra de estado
    navigate = Signal(str)        # pedir ir a un módulo por su clave
    help_requested = Signal(str)  # abrir «Ayuda y tutoriales» en un tema
    help_reset = Signal()         # volver a mostrar las guías rápidas de los módulos


@dataclass
class AppContext:
    config: AppConfig
    db: Database
    actor: Actor
    bus: Bus

    @contextmanager
    def session(self):
        with self.db.session() as s:
            yield s

    def notify(self, *topics: str) -> None:
        for t in topics:
            self.bus.changed.emit(t)

    @property
    def is_admin(self) -> bool:
        return self.actor.is_admin

    @property
    def drawer_account_id(self) -> str | None:
        return self.config.drawer_account_id or None
