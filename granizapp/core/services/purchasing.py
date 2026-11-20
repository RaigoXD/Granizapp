"""Proveedores, compras de insumos (entran al inventario) y cuentas por pagar."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from granizapp.core.models import (
    MoneyKind,
    MovementKind,
    Purchase,
    PurchaseItem,
    PurchaseStatus,
    Supplier,
    SupplierPayment,
    Supply,
    local_now,
)
from granizapp.core.services import finance, inventory
from granizapp.core.services.common import Actor, alive, audit, get, require, soft_delete
from granizapp.core.utils import fmt_money


# --- proveedores -------------------------------------------------------------------------
def list_suppliers(session: Session, include_inactive: bool = False) -> list[Supplier]:
    stmt = alive(Supplier).order_by(Supplier.name)
    if not include_inactive:
        stmt = stmt.where(Supplier.active.is_(True))
    return list(session.scalars(stmt))


SUPPLIER_FIELDS = ["name", "nit", "contact_name", "phone", "email", "city", "address", "supplies_text",
                   "payment_terms", "notes"]


def save_supplier(session: Session, data: dict, supplier_id: str | None = None) -> Supplier:
    name = (data.get("name") or "").strip()
    require(name, "El nombre del proveedor es obligatorio")
    sup = get(session, Supplier, supplier_id) if supplier_id else Supplier()
    for key in SUPPLIER_FIELDS:
        setattr(sup, key, (data.get(key) or "").strip() if isinstance(data.get(key), str) else (data.get(key) or ""))
    sup.name = name
    sup.payment_terms = sup.payment_terms or "Contado"
    sup.active = bool(data.get("active", True))
    if supplier_id is None:
        session.add(sup)
    session.flush()
    return sup


def delete_supplier(session: Session, supplier_id: str) -> None:
    owed = sum(p.balance for p in payables(session) if p.supplier_id == supplier_id)
    require(owed == 0, f"Hay {fmt_money(owed)} pendientes con este proveedor")
    soft_delete(session, get(session, Supplier, supplier_id))


# --- compras -----------------------------------------------------------------------------
@dataclass
class PurchaseLineInput:
    supply_id: str
    presentations: float       # cuántas bolsas / paquetes / pacas
    line_total: int            # lo que costaron en total
    presentation_qty: float | None = None  # contenido de cada una (por defecto el del insumo)
    description: str = ""


def create_purchase(
    session: Session,
    actor: Actor,
    lines: list[PurchaseLineInput],
    supplier_id: str | None = None,
    at: datetime | None = None,
    invoice_number: str = "",
    shipping: int = 0,
    prorate_shipping: bool = True,
    pay_amount: int = 0,
    pay_account_id: str | None = None,
    due_date: date | None = None,
    notes: str = "",
) -> Purchase:
    require(lines, "Agregue al menos un insumo a la compra")
    for line in lines:
        require(line.presentations > 0, "Las cantidades deben ser mayores a cero")
        require(line.line_total >= 0, "Los valores no pueden ser negativos")
    subtotal = sum(int(line.line_total) for line in lines)
    total = subtotal + int(shipping or 0)
    require(0 <= pay_amount <= total, "El pago no puede superar el total de la compra")
    if pay_amount:
        require(pay_account_id, "Indique de qué cuenta sale el pago")
    at = at or local_now()
    purchase = Purchase(
        supplier_id=supplier_id or None,
        at=at,
        invoice_number=invoice_number,
        subtotal=subtotal,
        shipping=int(shipping or 0),
        total=total,
        paid=0,
        due_date=due_date,
        user_id=actor.user_id,
        notes=notes,
    )
    session.add(purchase)
    session.flush()
    for line in lines:
        supply = get(session, Supply, line.supply_id)
        pres_qty = float(line.presentation_qty or supply.presentation_qty or 1)
        base_qty = line.presentations * pres_qty
        landed = float(line.line_total)
        if prorate_shipping and shipping and subtotal:
            landed += shipping * (line.line_total / subtotal)
        unit_cost = landed / base_qty if base_qty else 0.0
        session.add(
            PurchaseItem(
                purchase_id=purchase.id,
                supply_id=supply.id,
                description=line.description or supply.name,
                presentations=line.presentations,
                presentation_qty=pres_qty,
                base_qty=base_qty,
                line_total=int(line.line_total),
                unit_cost=unit_cost,
            )
        )
        if supplier_id and not supply.supplier_id:
            supply.supplier_id = supplier_id
        session.flush()
        inventory.receive(session, supply, base_qty, unit_cost, "compra", purchase.id,
                          f"Compra {invoice_number or ''}".strip(), actor, at)
    if pay_amount:
        pay_purchase(session, purchase.id, pay_amount, pay_account_id, actor, at=at)
    audit(session, actor, "compra", "purchase", purchase.id, f"{fmt_money(total)}")
    return purchase


def pay_purchase(
    session: Session, purchase_id: str, amount: int, account_id: str, actor: Actor,
    at: datetime | None = None, note: str = "",
) -> SupplierPayment:
    purchase = get(session, Purchase, purchase_id)
    require(purchase.status != PurchaseStatus.VOID, "La compra está anulada")
    require(0 < amount <= purchase.balance, f"El pago debe estar entre $ 1 y {fmt_money(purchase.balance)}")
    at = at or local_now()
    supplier = session.get(Supplier, purchase.supplier_id) if purchase.supplier_id else None
    pay = SupplierPayment(
        supplier_id=purchase.supplier_id,
        purchase_id=purchase.id,
        at=at,
        amount=amount,
        account_id=account_id,
        user_id=actor.user_id,
        note=note,
    )
    session.add(pay)
    session.flush()
    mov = finance.money_movement(
        session, account_id, -amount, MoneyKind.SUPPLIER_PAYMENT,
        f"Pago a {supplier.name if supplier else 'proveedor'}" + (f" (fact. {purchase.invoice_number})" if purchase.invoice_number else ""),
        actor, "pago_proveedor", pay.id, at=at,
    )
    pay.cash_session_id = mov.cash_session_id
    purchase.paid += amount
    return pay


def void_purchase(session: Session, purchase_id: str, actor: Actor, reason: str) -> None:
    purchase = get(session, Purchase, purchase_id)
    require(purchase.status != PurchaseStatus.VOID, "La compra ya está anulada")
    require(reason and reason.strip(), "Escriba el motivo")
    inventory.reverse_movements(session, purchase.id, MovementKind.VOID, f"Anulación compra: {reason}", actor)
    for pay in session.scalars(alive(SupplierPayment).where(SupplierPayment.purchase_id == purchase.id,
                                                            SupplierPayment.voided.is_(False))):
        pay.voided = True
        finance.reverse_money(session, pay.id, f"Anulación pago compra: {reason}", actor)
    purchase.status = PurchaseStatus.VOID
    purchase.paid = 0
    audit(session, actor, "anular_compra", "purchase", purchase.id, reason)


def list_purchases(session: Session, start: datetime | None = None, end: datetime | None = None,
                   supplier_id: str | None = None, include_void: bool = False) -> list[Purchase]:
    stmt = alive(Purchase).order_by(Purchase.at.desc())
    if start:
        stmt = stmt.where(Purchase.at >= start)
    if end:
        stmt = stmt.where(Purchase.at < end)
    if supplier_id:
        stmt = stmt.where(Purchase.supplier_id == supplier_id)
    if not include_void:
        stmt = stmt.where(Purchase.status != PurchaseStatus.VOID)
    return list(session.scalars(stmt))


def purchase_items(session: Session, purchase_id: str) -> list[PurchaseItem]:
    return list(session.scalars(alive(PurchaseItem).where(PurchaseItem.purchase_id == purchase_id)))


def purchase_payments(session: Session, purchase_id: str) -> list[SupplierPayment]:
    return list(session.scalars(alive(SupplierPayment).where(SupplierPayment.purchase_id == purchase_id)
                                .order_by(SupplierPayment.at)))


def payables(session: Session) -> list[Purchase]:
    rows = session.scalars(
        alive(Purchase).where(Purchase.status != PurchaseStatus.VOID, Purchase.total > Purchase.paid)
        .order_by(Purchase.due_date, Purchase.at)
    )
    return list(rows)


def total_payable(session: Session) -> int:
    return sum(p.balance for p in payables(session))


def supplier_payments_between(session: Session, start: datetime, end: datetime) -> list[SupplierPayment]:
    return list(session.scalars(
        alive(SupplierPayment).where(SupplierPayment.voided.is_(False), SupplierPayment.at >= start,
                                     SupplierPayment.at < end)
    ))
