"""Clientes y cartera: deudores, fiados del día, abonos y estado de cuenta."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from granizapp.core.models import (
    Customer,
    MoneyKind,
    Payment,
    PaymentKind,
    PaymentMethod,
    Sale,
    SaleStatus,
    local_now,
    new_id,
)
from granizapp.core.services import finance
from granizapp.core.services.common import Actor, alive, audit, get, require, soft_delete
from granizapp.core.utils import day_range, fmt_money, normalize


def list_customers(session: Session, include_inactive: bool = False) -> list[Customer]:
    stmt = alive(Customer).order_by(Customer.name)
    if not include_inactive:
        stmt = stmt.where(Customer.active.is_(True))
    return list(session.scalars(stmt))


def find_customer_by_name(session: Session, name: str) -> Customer | None:
    target = normalize(name)
    for c in list_customers(session, True):
        if normalize(c.name) == target:
            return c
    return None


def save_customer(session: Session, data: dict, customer_id: str | None = None) -> Customer:
    name = (data.get("name") or "").strip()
    require(name, "El nombre del cliente es obligatorio")
    dup = find_customer_by_name(session, name)
    require(dup is None or dup.id == customer_id, f"Ya existe un cliente llamado '{dup.name if dup else ''}'")
    c = get(session, Customer, customer_id) if customer_id else Customer()
    c.name = name
    c.phone = (data.get("phone") or "").strip()
    c.document = (data.get("document") or "").strip()
    c.credit_limit = int(data.get("credit_limit") or 0)
    c.notes = data.get("notes") or ""
    c.active = bool(data.get("active", True))
    if customer_id is None:
        session.add(c)
    session.flush()
    return c


def delete_customer(session: Session, customer_id: str) -> None:
    owed = customer_balance(session, customer_id)
    require(owed == 0, f"El cliente debe {fmt_money(owed)}; no se puede borrar")
    soft_delete(session, get(session, Customer, customer_id))


# --- saldos ----------------------------------------------------------------------------
def _open_credit_sales(session: Session, customer_id: str | None = None):
    stmt = alive(Sale).where(
        Sale.status == SaleStatus.CLOSED, Sale.customer_id.is_not(None), Sale.total > Sale.paid
    )
    if customer_id:
        stmt = stmt.where(Sale.customer_id == customer_id)
    return stmt.order_by(Sale.closed_at, Sale.number)


def customer_balance(session: Session, customer_id: str) -> int:
    v = session.scalar(
        select(func.sum(Sale.total - Sale.paid)).where(
            Sale.deleted.is_(False),
            Sale.status == SaleStatus.CLOSED,
            Sale.customer_id == customer_id,
            Sale.total > Sale.paid,
        )
    )
    return int(v or 0)


def balances(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(Sale.customer_id, func.sum(Sale.total - Sale.paid))
        .where(
            Sale.deleted.is_(False),
            Sale.status == SaleStatus.CLOSED,
            Sale.customer_id.is_not(None),
            Sale.total > Sale.paid,
        )
        .group_by(Sale.customer_id)
    )
    return {cid: int(v or 0) for cid, v in rows}


@dataclass
class Debtor:
    customer: Customer
    balance: int
    open_sales: int
    oldest: datetime | None
    last: datetime | None

    @property
    def days_overdue(self) -> int:
        if not self.oldest:
            return 0
        return (local_now().date() - self.oldest.date()).days


def debtors(session: Session) -> list[Debtor]:
    customers = {c.id: c for c in list_customers(session, True)}
    agg: dict[str, Debtor] = {}
    for sale in session.scalars(_open_credit_sales(session)):
        cust = customers.get(sale.customer_id)
        if cust is None:
            continue
        d = agg.get(cust.id)
        if d is None:
            d = agg[cust.id] = Debtor(cust, 0, 0, sale.closed_at, sale.closed_at)
        d.balance += sale.total - sale.paid
        d.open_sales += 1
        if sale.closed_at and (d.oldest is None or sale.closed_at < d.oldest):
            d.oldest = sale.closed_at
        if sale.closed_at and (d.last is None or sale.closed_at > d.last):
            d.last = sale.closed_at
    return sorted(agg.values(), key=lambda d: -d.balance)


def total_receivable(session: Session) -> int:
    return sum(balances(session).values())


def credit_sales_on(session: Session, day: date) -> list[Sale]:
    """Fiados del día: ventas de ese día que quedaron con saldo."""
    start, end = day_range(day)
    stmt = alive(Sale).where(
        Sale.status == SaleStatus.CLOSED, Sale.is_credit.is_(True), Sale.closed_at >= start, Sale.closed_at < end
    )
    return list(session.scalars(stmt.order_by(Sale.closed_at)))


def abonos_between(session: Session, start: datetime, end: datetime) -> list[Payment]:
    return list(
        session.scalars(
            alive(Payment)
            .where(Payment.kind == PaymentKind.ABONO, Payment.voided.is_(False), Payment.at >= start, Payment.at < end)
            .order_by(Payment.at)
        )
    )


# --- abonos ----------------------------------------------------------------------------
def register_abono(
    session: Session,
    customer_id: str,
    amount: int,
    method_id: str,
    actor: Actor,
    cash_session_id: str | None,
    note: str = "",
    sale_ids: list[str] | None = None,
) -> list[Payment]:
    """Aplica un pago a las deudas del cliente, de la más antigua a la más reciente
    (o solo a las ventas indicadas)."""
    require(amount > 0, "El abono debe ser mayor a cero")
    customer = get(session, Customer, customer_id)
    method = get(session, PaymentMethod, method_id)
    open_sales = list(session.scalars(_open_credit_sales(session, customer_id)))
    if sale_ids:
        open_sales = [s for s in open_sales if s.id in set(sale_ids)]
    owed = sum(s.total - s.paid for s in open_sales)
    require(owed > 0, f"{customer.name} no tiene saldo pendiente")
    require(amount <= owed, f"El abono ({fmt_money(amount)}) supera la deuda ({fmt_money(owed)})")
    group = new_id()
    now = local_now()
    remaining = amount
    created = []
    for sale in open_sales:
        if remaining <= 0:
            break
        part = min(remaining, sale.total - sale.paid)
        pay = Payment(
            at=now,
            kind=PaymentKind.ABONO,
            sale_id=sale.id,
            customer_id=customer_id,
            method_id=method_id,
            amount=part,
            received=part,
            group_id=group,
            cash_session_id=cash_session_id,
            user_id=actor.user_id,
            note=note,
        )
        session.add(pay)
        session.flush()
        sale.paid += part
        remaining -= part
        account_id = finance.payment_account(session, method, cash_session_id)
        if account_id:
            finance.money_movement(
                session, account_id, part, MoneyKind.ABONO, f"Abono de {customer.name}", actor, "abono", pay.id,
                cash_session_id=cash_session_id if method.is_cash else None, at=now,
            )
        created.append(pay)
    audit(session, actor, "abono", "customer", customer_id, f"{fmt_money(amount)} por {method.name}")
    return created


def void_abono(session: Session, group_id: str, actor: Actor, reason: str = "") -> None:
    pays = session.scalars(alive(Payment).where(Payment.group_id == group_id, Payment.voided.is_(False))).all()
    require(pays, "No se encontró el abono")
    for pay in pays:
        pay.voided = True
        sale = session.get(Sale, pay.sale_id) if pay.sale_id else None
        if sale is not None and sale.status != SaleStatus.VOID:
            sale.paid = max(0, sale.paid - pay.amount)
        finance.reverse_money(session, pay.id, f"Anulación de abono {reason}".strip(), actor)
    audit(session, actor, "anular_abono", "payment", group_id, reason)


# --- estado de cuenta -------------------------------------------------------------------
@dataclass
class StatementLine:
    at: datetime
    kind: str          # "Fiado" | "Abono" | "Pago en la venta"
    description: str
    charge: int
    payment: int
    balance: int = 0
    ref_id: str = ""


def statement(session: Session, customer_id: str, item_names: bool = True) -> list[StatementLine]:
    from granizapp.core.services.sales import sale_code, sale_items

    lines: list[StatementLine] = []
    sales = session.scalars(
        alive(Sale).where(Sale.customer_id == customer_id, Sale.status == SaleStatus.CLOSED).order_by(Sale.closed_at)
    ).all()
    sale_ids = {s.id for s in sales}
    for s in sales:
        desc = f"Venta {sale_code(s)}"
        if item_names:
            names = ", ".join(
                f"{int(i.quantity) if float(i.quantity).is_integer() else i.quantity}× {i.name}"
                for i in sale_items(session, s.id)
            )
            desc = f"{desc}: {names}"
        lines.append(StatementLine(s.closed_at, "Compra", desc, s.total, 0, ref_id=s.id))
    if sale_ids:
        pays = session.scalars(
            alive(Payment).where(Payment.sale_id.in_(sale_ids), Payment.voided.is_(False)).order_by(Payment.at)
        ).all()
        methods = {m.id: m.name for m in session.scalars(alive(PaymentMethod))}
        grouped: dict[str, StatementLine] = {}
        for p in pays:
            key = p.group_id or p.id
            label = "Abono" if p.kind == PaymentKind.ABONO else "Pago en la venta"
            if key in grouped:
                grouped[key].payment += p.amount
            else:
                grouped[key] = StatementLine(p.at, label, f"{label} ({methods.get(p.method_id, '')})", 0, p.amount,
                                             ref_id=p.group_id or "")
        lines.extend(grouped.values())
    lines.sort(key=lambda line: (line.at or datetime.min, 0 if line.charge else 1))
    bal = 0
    for line in lines:
        bal += line.charge - line.payment
        line.balance = bal
    return lines


def quick_customer(session: Session, name: str, phone: str = "") -> Customer:
    existing = find_customer_by_name(session, name)
    if existing:
        return existing
    return save_customer(session, {"name": name, "phone": phone})
