"""Registro de módulos: la barra lateral y los atajos se arman a partir de esta lista.

Para agregar un módulo nuevo: crear `granizapp/ui/modules/<nombre>.py` con una clase
que herede de `Page` y registrarla en `granizapp/ui/modules/__init__.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from granizapp.core.models import Role


@dataclass
class ModuleSpec:
    key: str
    title: str
    section: str
    factory: Callable  # (ctx) -> Page
    shortcut: str = ""
    roles: set[str] = field(default_factory=lambda: {Role.ADMIN, Role.CASHIER})
    description: str = ""

    def allowed(self, role: str) -> bool:
        return role in self.roles


SECTIONS = ["OPERACIÓN", "PRODUCTOS E INVENTARIO", "FINANZAS", "SISTEMA"]
ADMIN_ONLY = {Role.ADMIN}
