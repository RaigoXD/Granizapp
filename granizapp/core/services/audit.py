"""Auditoría: consulta de la bitácora que escriben los demás servicios (`common.audit`).

Cada registro dice quién (usuario), desde qué equipo, cuándo (hora local al mostrar) y qué
hizo, sobre qué registro (venta, producto, caja…) y con qué detalle.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from granizapp.core.models import (
    Account,
    AuditLog,
    CashSession,
    CashSessionStatus,
    Customer,
    Expense,
    FinancialEntry,
    Product,
    Purchase,
    Sale,
    Supplier,
    Supply,
    User,
)
from granizapp.core.services.common import alive
from granizapp.core.utils import local_to_utc, matches

# acción -> (etiqueta, grupo)
ACTIONS: dict[str, tuple[str, str]] = {
    "abrir_caja": ("Abrir caja", "Caja"),
    "cerrar_caja": ("Cerrar caja (arqueo)", "Caja"),
    "caja_in": ("Ingreso de efectivo a la caja", "Caja"),
    "caja_out": ("Retiro de efectivo de la caja", "Caja"),
    "descuento": ("Descuento en una venta", "Ventas"),
    "anular_venta": ("Anular venta", "Ventas"),
    "descartar_cuenta": ("Descartar cuenta abierta", "Ventas"),
    "abono": ("Abono de cliente", "Cartera"),
    "anular_abono": ("Anular abono", "Cartera"),
    "compra": ("Compra de insumos", "Compras"),
    "anular_compra": ("Anular compra", "Compras"),
    "editar_gasto": ("Editar gasto", "Gastos"),
    "anular_gasto": ("Anular gasto", "Gastos"),
    "transferencia": ("Transferencia entre cuentas", "Dinero"),
    "ajuste_saldo": ("Ajuste de saldo de una cuenta", "Dinero"),
    "aporte": ("Aporte de capital", "Dinero"),
    "retiro": ("Retiro de socio", "Dinero"),
    "otro_ingreso": ("Otro ingreso", "Dinero"),
    "prestamo": ("Préstamo recibido", "Dinero"),
    "pago_prestamo": ("Pago de préstamo", "Dinero"),
    "anular_movimiento": ("Anular aporte/retiro/ingreso", "Dinero"),
    "conteo_inventario": ("Conteo físico de inventario", "Inventario"),
    "inventario_merma": ("Merma / daño", "Inventario"),
    "inventario_ajuste": ("Ajuste manual de inventario", "Inventario"),
    "inventario_consumo_interno": ("Consumo interno", "Inventario"),
    "inventario_inicial": ("Inventario inicial", "Inventario"),
    "inventario_devolucion": ("Devolución a proveedor", "Inventario"),
    "eliminar_insumo": ("Eliminar insumo", "Inventario"),
    "crear_sabor": ("Crear sabor", "Inventario"),
    "crear_grupo_sabores": ("Crear insumo con sabores", "Inventario"),
    "eliminar_grupo_sabores": ("Eliminar insumo con sabores", "Inventario"),
    "reasignar_sabores": ("Repartir bolsas sin sabor", "Inventario"),
    "crear_producto": ("Crear producto", "Productos"),
    "cambiar_precio": ("Cambio de precio", "Productos"),
    "eliminar_producto": ("Eliminar producto", "Productos"),
    "ingreso": ("Ingreso a la aplicación", "Usuarios"),
    "ingreso_fallido": ("Intento de ingreso con PIN incorrecto", "Usuarios"),
    "crear_usuario": ("Crear usuario", "Usuarios"),
    "editar_usuario": ("Editar usuario", "Usuarios"),
    "quitar_pin": ("Quitar PIN", "Usuarios"),
    "restablecer_pin": ("Restablecer PIN de administradores", "Usuarios"),
    "configurar_negocio": ("Configuración del negocio", "Sistema"),
    "importar_excel": ("Importación de Excel", "Sistema"),
}
GROUPS = ["Caja", "Ventas", "Cartera", "Compras", "Gastos", "Dinero", "Inventario", "Productos", "Usuarios", "Sistema"]
SENSITIVE = {"anular_venta", "anular_abono", "anular_compra", "anular_gasto", "anular_movimiento", "descuento",
             "ajuste_saldo", "conteo_inventario", "inventario_merma", "inventario_ajuste", "cambiar_precio",
             "ingreso_fallido", "quitar_pin", "restablecer_pin"}


def action_label(action: str) -> str:
    if action in ACTIONS:
        return ACTIONS[action][0]
    return action.replace("_", " ").capitalize()


def action_group(action: str) -> str:
    return ACTIONS.get(action, ("", "Otros"))[1]


def list_entries(
    session: Session,
    start: datetime | None = None,
    end: datetime | None = None,
    user_id: str | None = None,
    group: str | None = None,
    action: str | None = None,
    query: str = "",
    limit: int = 5000,
) -> list[AuditLog]:
    stmt = alive(AuditLog).order_by(AuditLog.created_at.desc())
    if start is not None:
        stmt = stmt.where(AuditLog.created_at >= local_to_utc(start))
    if end is not None:
        stmt = stmt.where(AuditLog.created_at < local_to_utc(end))
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    rows = list(session.scalars(stmt.limit(limit)))
    if group:
        rows = [r for r in rows if action_group(r.action) == group]
    if query:
        rows = [r for r in rows if matches(query, action_label(r.action), r.detail, r.entity_id)]
    return rows


def entity_labels(session: Session, entries: list[AuditLog]) -> dict[tuple[str, str], str]:
    """Nombre legible del registro al que se refiere cada entrada (venta 640E-00012, Raigo…)."""
    from granizapp.core.services.sales import sale_code

    wanted: dict[str, set[str]] = {}
    for e in entries:
        if e.entity and e.entity_id:
            wanted.setdefault(e.entity, set()).add(e.entity_id)
    out: dict[tuple[str, str], str] = {}
    resolvers = {
        "sale": (Sale, lambda s: f"Venta {sale_code(s)}"),
        "product": (Product, lambda p: p.name),
        "supply": (Supply, lambda x: x.name),
        "customer": (Customer, lambda c: c.name),
        "user": (User, lambda u: u.name),
        "account": (Account, lambda a: a.name),
        "cash_session": (CashSession, lambda c: f"Caja #{c.number} ({c.device_id})"),
        "purchase": (Purchase, lambda p: f"Compra {p.invoice_number or p.at:%d/%m/%y}"),
        "expense": (Expense, lambda x: x.description),
        "financial_entry": (FinancialEntry, lambda x: x.description),
        "supplier": (Supplier, lambda x: x.name),
    }
    for entity, ids in wanted.items():
        if entity not in resolvers:
            continue
        model, label = resolvers[entity]
        for row in session.scalars(select(model).where(model.id.in_(list(ids)))):
            out[(entity, row.id)] = label(row)
    return out


@dataclass
class AuditSummary:
    total: int = 0
    voids: int = 0
    discounts: int = 0
    price_changes: int = 0
    inventory_adjustments: int = 0
    failed_logins: int = 0
    cash_differences: int = 0            # cierres con sobrante o faltante
    cash_difference_total: int = 0       # suma de esas diferencias (negativo = faltó)
    by_user: dict[str, int] = field(default_factory=dict)


def summarize(session: Session, entries: list[AuditLog], start: datetime | None, end: datetime | None) -> AuditSummary:
    s = AuditSummary(total=len(entries))
    for e in entries:
        if e.action.startswith("anular") or e.action == "descartar_cuenta":
            s.voids += 1
        elif e.action == "descuento":
            s.discounts += 1
        elif e.action == "cambiar_precio":
            s.price_changes += 1
        elif e.action in ("conteo_inventario", "inventario_merma", "inventario_ajuste"):
            s.inventory_adjustments += 1
        elif e.action == "ingreso_fallido":
            s.failed_logins += 1
        s.by_user[e.user_id or ""] = s.by_user.get(e.user_id or "", 0) + 1
    stmt = alive(CashSession).where(CashSession.status == CashSessionStatus.CLOSED, CashSession.difference != 0)
    if start is not None:
        stmt = stmt.where(CashSession.closed_at >= start)
    if end is not None:
        stmt = stmt.where(CashSession.closed_at < end)
    for cs in session.scalars(stmt):
        s.cash_differences += 1
        s.cash_difference_total += cs.difference or 0
    return s
