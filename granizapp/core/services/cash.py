"""Caja: apertura con base, resumen del turno, retiros y arqueo de cierre."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from granizapp.core.models import (
    Account,
    AccountMovement,
    CashSession,
    CashSessionStatus,
    MoneyKind,
    Payment,
    PaymentKind,
    PaymentMethod,
    Sale,
    SaleStatus,
    local_now,
)
from granizapp.core.services import finance
from granizapp.core.services.common import Actor, ServiceError, alive, audit, get, require
from granizapp.core.utils import fmt_money

# Billetes y monedas en circulación en Colombia
DENOMINATIONS = [100000, 50000, 20000, 10000, 5000, 2000, 1000, 500, 200, 100, 50]


def current_session(session: Session, device_id: str) -> CashSession | None:
    return session.scalars(
        alive(CashSession)
        .where(CashSession.device_id == device_id, CashSession.status == CashSessionStatus.OPEN)
        .order_by(CashSession.opened_at.desc())
    ).first()


def last_closed(session: Session, device_id: str) -> CashSession | None:
    return session.scalars(
        alive(CashSession)
        .where(CashSession.device_id == device_id, CashSession.status == CashSessionStatus.CLOSED)
        .order_by(CashSession.closed_at.desc())
    ).first()


def device_drawer(session: Session, account_id: str | None = None):
    """Cajón de este equipo: el configurado en el equipo o, si no, el primero marcado como caja."""
    if account_id:
        acc = session.get(Account, account_id)
        if acc is not None and not acc.deleted and acc.active and acc.is_drawer:
            return acc
    return finance.drawer_account(session)


def suggested_base(session: Session, device_id: str, account_id: str | None = None) -> int:
    """La base sugerida es lo que quedó en el cajón al último cierre."""
    drawer = device_drawer(session, account_id)
    if drawer is None:
        return 0
    return finance.account_balances(session).get(drawer.id, 0)


def open_session(
    session: Session, actor: Actor, opening_amount: int, notes: str = "", account_id: str | None = None
) -> CashSession:
    require(current_session(session, actor.device_id) is None, "Ya hay una caja abierta en este equipo")
    require(opening_amount >= 0, "La base no puede ser negativa")
    drawer = device_drawer(session, account_id)
    require(drawer is not None, "No hay una cuenta configurada como caja registradora")
    other = finance.open_session_for_account(session, drawer.id)
    require(
        other is None,
        f"El cajón '{drawer.name}' ya está abierto en otro equipo. Cada caja necesita su propia cuenta de "
        "cajón (Configuración > Este equipo).",
    )
    number = (session.scalar(select(func.max(CashSession.number)).where(CashSession.device_id == actor.device_id)) or 0) + 1
    cs = CashSession(
        device_id=actor.device_id,
        number=number,
        account_id=drawer.id,
        opened_at=local_now(),
        opened_by=actor.user_id,
        opening_amount=int(opening_amount),
        notes=notes,
    )
    session.add(cs)
    session.flush()
    book = finance.account_balances(session).get(drawer.id, 0)
    diff = int(opening_amount) - book
    if diff:
        finance.money_movement(
            session, drawer.id, diff, MoneyKind.ADJUST,
            f"Diferencia en la base al abrir (sistema {fmt_money(book)}, contado {fmt_money(opening_amount)})",
            actor, "cash_open", cs.id, cash_session_id=cs.id,
        )
    audit(session, actor, "abrir_caja", "cash_session", cs.id, f"base {fmt_money(opening_amount)}")
    return cs


@dataclass
class MethodTotal:
    method_id: str
    name: str
    is_cash: bool
    sales: int = 0
    abonos: int = 0

    @property
    def total(self) -> int:
        return self.sales + self.abonos


@dataclass
class SessionSummary:
    session: CashSession
    opening: int = 0
    cash_sales: int = 0
    cash_abonos: int = 0
    cash_expenses: int = 0          # gastos y pagos a proveedor en efectivo de la caja
    cash_in: int = 0                # ingresos/aportes/transferencias hacia la caja
    cash_out: int = 0               # retiros/transferencias desde la caja
    voids: int = 0                  # devoluciones de dinero por anulaciones
    adjustments: int = 0
    expected: int = 0
    sales_count: int = 0
    sales_total: int = 0
    credit_total: int = 0           # lo que quedó fiado en el turno
    void_count: int = 0
    by_method: list[MethodTotal] = field(default_factory=list)

    @property
    def non_cash_total(self) -> int:
        return sum(m.total for m in self.by_method if not m.is_cash)

    @property
    def collected_total(self) -> int:
        return sum(m.total for m in self.by_method)


def summary(session: Session, cs: CashSession) -> SessionSummary:
    s = SessionSummary(session=cs, opening=cs.opening_amount)
    movs = session.scalars(
        alive(AccountMovement).where(
            AccountMovement.cash_session_id == cs.id, AccountMovement.account_id == cs.account_id
        )
    ).all()
    for m in movs:
        if m.ref_type == "cash_open":
            continue  # la base ya incluye la diferencia de apertura
        if m.ref_type == "cash_close":
            continue  # el descuadre del cierre no forma parte de lo esperado
        if m.kind == MoneyKind.SALE:
            s.cash_sales += m.amount
        elif m.kind == MoneyKind.ABONO:
            s.cash_abonos += m.amount
        elif m.kind in (MoneyKind.EXPENSE, MoneyKind.SUPPLIER_PAYMENT):
            s.cash_expenses += -m.amount
        elif m.kind == MoneyKind.VOID:
            s.voids += m.amount
        elif m.kind == MoneyKind.ADJUST:
            s.adjustments += m.amount
        elif m.amount >= 0:
            s.cash_in += m.amount
        else:
            s.cash_out += -m.amount
    s.expected = s.opening + s.cash_sales + s.cash_abonos - s.cash_expenses + s.cash_in - s.cash_out + s.voids + s.adjustments

    methods = {m.id: m for m in session.scalars(alive(PaymentMethod).order_by(PaymentMethod.sort_order))}
    totals: dict[str, MethodTotal] = {
        mid: MethodTotal(mid, m.name, m.is_cash) for mid, m in methods.items() if m.active
    }
    pays = session.scalars(
        alive(Payment).where(Payment.cash_session_id == cs.id, Payment.voided.is_(False))
    ).all()
    for p in pays:
        m = methods.get(p.method_id)
        t = totals.setdefault(p.method_id, MethodTotal(p.method_id, m.name if m else "?", bool(m and m.is_cash)))
        if p.kind == PaymentKind.ABONO:
            t.abonos += p.amount
        else:
            t.sales += p.amount
    s.by_method = list(totals.values())

    sales = session.scalars(alive(Sale).where(Sale.cash_session_id == cs.id, Sale.status != SaleStatus.OPEN)).all()
    for sale in sales:
        if sale.status == SaleStatus.VOID:
            s.void_count += 1
            continue
        s.sales_count += 1
        s.sales_total += sale.total
        if sale.is_credit:
            s.credit_total += max(0, sale.total - _paid_at_sale(session, sale))
    return s


def _paid_at_sale(session: Session, sale: Sale) -> int:
    v = session.scalar(
        select(func.sum(Payment.amount)).where(
            Payment.sale_id == sale.id,
            Payment.kind == PaymentKind.SALE,
            Payment.voided.is_(False),
            Payment.deleted.is_(False),
        )
    )
    return int(v or 0)


def cash_in_out(
    session: Session, cs: CashSession, amount: int, direction: str, description: str, actor: Actor,
    other_account_id: str | None = None, as_capital: bool = False,
) -> None:
    """Retiro (direction="out") o ingreso ("in") de efectivo en la caja.

    Con `other_account_id` es una transferencia (p. ej. a la caja fuerte o al banco);
    con `as_capital` es un retiro/aporte del socio.
    """
    require(cs.status == CashSessionStatus.OPEN, "La caja está cerrada")
    require(amount > 0, "El valor debe ser mayor a cero")
    if other_account_id:
        if direction == "out":
            finance.transfer(session, cs.account_id, other_account_id, amount, description, actor)
        else:
            finance.transfer(session, other_account_id, cs.account_id, amount, description, actor)
    else:
        if as_capital:
            kind = MoneyKind.CAPITAL_OUT if direction == "out" else MoneyKind.CAPITAL_IN
            finance.record_financial_entry(
                session, {"kind": kind, "amount": amount, "account_id": cs.account_id, "description": description}, actor
            )
        else:
            sign = -1 if direction == "out" else 1
            finance.money_movement(
                session, cs.account_id, sign * amount, MoneyKind.ADJUST, description or "Movimiento de caja",
                actor, "cash_manual", cs.id, cash_session_id=cs.id,
            )
    audit(session, actor, f"caja_{direction}", "cash_session", cs.id, f"{fmt_money(amount)} {description}")


def close_session(
    session: Session,
    cs_id: str,
    counted: int,
    actor: Actor,
    denominations: dict[int, int] | None = None,
    withdraw_amount: int = 0,
    withdraw_account_id: str | None = None,
    notes: str = "",
) -> SessionSummary:
    cs = get(session, CashSession, cs_id)
    require(cs.status == CashSessionStatus.OPEN, "La caja ya está cerrada")
    require(counted >= 0, "El efectivo contado no puede ser negativo")
    open_tabs = session.scalars(
        alive(Sale).where(Sale.status == SaleStatus.OPEN, Sale.device_id == cs.device_id)
    ).all()
    sm = summary(session, cs)
    diff = int(counted) - sm.expected
    if diff:
        label = "Sobrante" if diff > 0 else "Faltante"
        finance.money_movement(
            session, cs.account_id, diff, MoneyKind.ADJUST, f"{label} en arqueo de caja #{cs.number}",
            actor, "cash_close", cs.id, cash_session_id=cs.id,
        )
    if withdraw_amount:
        require(0 < withdraw_amount <= counted, "El retiro no puede superar el efectivo contado")
        require(withdraw_account_id, "Indique a qué cuenta va el dinero retirado")
        require(withdraw_account_id != cs.account_id, "El retiro debe ir a una cuenta distinta a la caja")
    cs.expected_cash = sm.expected
    cs.counted_cash = int(counted)
    cs.difference = diff
    cs.withdrawn = int(withdraw_amount or 0)
    cs.withdraw_account_id = withdraw_account_id
    cs.denominations = json.dumps({str(k): v for k, v in (denominations or {}).items() if v})
    cs.notes = "\n".join(x for x in [cs.notes, notes] if x)
    cs.closed_at = local_now()
    cs.closed_by = actor.user_id
    cs.status = CashSessionStatus.CLOSED
    session.flush()
    if withdraw_amount:
        # Con el turno ya cerrado, el retiro no altera el arqueo: solo deja en el cajón la base de mañana
        finance.transfer(session, cs.account_id, withdraw_account_id, withdraw_amount,
                         f"Retiro al cierre de caja #{cs.number}", actor)
    audit(
        session, actor, "cerrar_caja", "cash_session", cs.id,
        f"esperado {fmt_money(sm.expected)} contado {fmt_money(counted)} diferencia {fmt_money(diff)}"
        + (f"; {len(open_tabs)} cuentas abiertas pendientes" if open_tabs else ""),
    )
    return sm


def list_sessions(session: Session, device_id: str | None = None, limit: int = 200) -> list[CashSession]:
    stmt = alive(CashSession).order_by(CashSession.opened_at.desc()).limit(limit)
    if device_id:
        stmt = stmt.where(CashSession.device_id == device_id)
    return list(session.scalars(stmt))


def require_open(session: Session, actor: Actor) -> CashSession:
    cs = current_session(session, actor.device_id)
    if cs is None:
        raise ServiceError("La caja está cerrada. Abra la caja con la base para empezar a vender.")
    return cs
