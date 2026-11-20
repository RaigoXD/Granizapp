"""Tesorería y gastos: cuentas, libro de movimientos, gastos, capital y transferencias."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from granizapp.core.models import (
    Account,
    AccountKind,
    AccountMovement,
    CashSession,
    CashSessionStatus,
    Expense,
    ExpenseCategory,
    ExpenseType,
    FinancialEntry,
    MoneyKind,
    local_now,
    new_id,
)
from granizapp.core.services.common import Actor, alive, audit, get, require, soft_delete
from granizapp.core.utils import fmt_money, normalize


# --- cuentas -------------------------------------------------------------------------
def list_accounts(session: Session, include_inactive: bool = False) -> list[Account]:
    stmt = alive(Account).order_by(Account.sort_order, Account.name)
    if not include_inactive:
        stmt = stmt.where(Account.active.is_(True))
    return list(session.scalars(stmt))


def save_account(session: Session, data: dict, account_id: str | None = None) -> Account:
    name = (data.get("name") or "").strip()
    require(name, "El nombre de la cuenta es obligatorio")
    acc = get(session, Account, account_id) if account_id else Account()
    acc.name = name
    acc.kind = data.get("kind") or AccountKind.CASH
    acc.is_drawer = bool(data.get("is_drawer", False))
    acc.opening_balance = int(data.get("opening_balance") or 0)
    acc.sort_order = int(data.get("sort_order") or 0)
    acc.active = bool(data.get("active", True))
    acc.notes = data.get("notes") or ""
    if account_id is None:
        session.add(acc)
    session.flush()
    return acc


def delete_account(session: Session, account_id: str) -> None:
    acc = get(session, Account, account_id)
    require(not acc.is_drawer, "No se puede borrar la cuenta de la caja registradora")
    balance = account_balances(session).get(account_id, 0)
    require(balance == 0, f"La cuenta tiene saldo ({fmt_money(balance)}). Transfiéralo antes de borrarla.")
    soft_delete(session, acc)


def drawer_account(session: Session) -> Account | None:
    return session.scalars(
        alive(Account).where(Account.is_drawer.is_(True), Account.active.is_(True)).order_by(Account.sort_order)
    ).first()


def account_balances(session: Session, until: datetime | None = None) -> dict[str, int]:
    stmt = (
        select(AccountMovement.account_id, func.sum(AccountMovement.amount))
        .where(AccountMovement.deleted.is_(False))
        .group_by(AccountMovement.account_id)
    )
    if until is not None:
        stmt = stmt.where(AccountMovement.at < until)
    sums = {aid: int(v or 0) for aid, v in session.execute(stmt)}
    return {a.id: (a.opening_balance or 0) + sums.get(a.id, 0) for a in list_accounts(session, True)}


def payment_account(session: Session, method, cash_session_id: str | None) -> str | None:
    """Cuenta a la que llega un pago: el efectivo entra al cajón del turno abierto de este
    equipo (cada caja tiene el suyo); los demás medios, a la cuenta configurada."""
    if method.is_cash and cash_session_id:
        cs = session.get(CashSession, cash_session_id)
        if cs is not None:
            return cs.account_id
    return method.account_id


def open_session_for_account(session: Session, account_id: str) -> CashSession | None:
    return session.scalars(
        alive(CashSession).where(CashSession.account_id == account_id, CashSession.status == CashSessionStatus.OPEN)
    ).first()


def money_movement(
    session: Session,
    account_id: str,
    amount: int,
    kind: str,
    description: str,
    actor: Actor | None = None,
    ref_type: str = "",
    ref_id: str | None = None,
    cash_session_id: str | None = None,
    at: datetime | None = None,
) -> AccountMovement:
    """Registra dinero que entra (+) o sale (-) de una cuenta.

    Si la cuenta es el cajón y no se indicó turno, se asocia al turno abierto de esa caja
    para que el arqueo cuadre.
    """
    acc = get(session, Account, account_id)
    if acc.is_drawer and cash_session_id is None:
        open_cs = open_session_for_account(session, account_id)
        cash_session_id = open_cs.id if open_cs else None
    if not acc.is_drawer:
        cash_session_id = None
    mov = AccountMovement(
        account_id=account_id,
        amount=int(amount),
        kind=kind,
        description=description[:250],
        ref_type=ref_type,
        ref_id=ref_id,
        cash_session_id=cash_session_id,
        user_id=actor.user_id if actor else None,
        at=at or local_now(),
    )
    session.add(mov)
    return mov


def reverse_money(session: Session, ref_id: str, description: str, actor: Actor | None = None) -> None:
    """Deja en cero el efecto neto de una referencia en cada cuenta (anulaciones y correcciones).

    Se calcula sobre el neto, así una segunda corrección no revierte dos veces lo mismo.
    """
    movements = session.scalars(alive(AccountMovement).where(AccountMovement.ref_id == ref_id)).all()
    net: dict[str, int] = {}
    ref_types: dict[str, str] = {}
    for mov in movements:
        net[mov.account_id] = net.get(mov.account_id, 0) + mov.amount
        ref_types[mov.account_id] = mov.ref_type
    for account_id, amount in net.items():
        if amount:
            money_movement(session, account_id, -amount, MoneyKind.VOID, description, actor, ref_types[account_id], ref_id)


@dataclass
class LedgerRow:
    movement: AccountMovement
    balance: int


def ledger(session: Session, account_id: str, start: datetime | None = None, end: datetime | None = None) -> list[LedgerRow]:
    acc = get(session, Account, account_id)
    stmt = alive(AccountMovement).where(AccountMovement.account_id == account_id).order_by(
        AccountMovement.at, AccountMovement.created_at
    )
    balance = acc.opening_balance or 0
    if start is not None:
        prev = session.scalar(
            select(func.sum(AccountMovement.amount)).where(
                AccountMovement.account_id == account_id,
                AccountMovement.deleted.is_(False),
                AccountMovement.at < start,
            )
        )
        balance += int(prev or 0)
        stmt = stmt.where(AccountMovement.at >= start)
    if end is not None:
        stmt = stmt.where(AccountMovement.at < end)
    rows = []
    for mov in session.scalars(stmt):
        balance += mov.amount
        rows.append(LedgerRow(mov, balance))
    return rows


def transfer(
    session: Session, from_id: str, to_id: str, amount: int, description: str, actor: Actor, at: datetime | None = None
) -> None:
    require(from_id != to_id, "Las cuentas de origen y destino deben ser distintas")
    require(amount > 0, "El valor debe ser mayor a cero")
    src = get(session, Account, from_id)
    dst = get(session, Account, to_id)
    desc = description or f"Transferencia {src.name} → {dst.name}"
    ref = "trf-" + new_id()
    money_movement(session, from_id, -amount, MoneyKind.TRANSFER, desc, actor, "transferencia", ref, at=at)
    money_movement(session, to_id, amount, MoneyKind.TRANSFER, desc, actor, "transferencia", ref, at=at)
    audit(session, actor, "transferencia", "account", from_id, f"{fmt_money(amount)} a {dst.name}")


def adjust_balance(session: Session, account_id: str, real_balance: int, actor: Actor, note: str = "") -> int:
    current = account_balances(session).get(account_id, 0)
    diff = int(real_balance) - current
    if diff:
        money_movement(session, account_id, diff, MoneyKind.ADJUST, note or "Ajuste de saldo", actor, "ajuste")
        audit(session, actor, "ajuste_saldo", "account", account_id, f"{current} -> {real_balance}")
    return diff


# --- categorías de gasto ------------------------------------------------------------
def list_expense_categories(session: Session, include_inactive: bool = False) -> list[ExpenseCategory]:
    stmt = alive(ExpenseCategory).order_by(ExpenseCategory.sort_order, ExpenseCategory.name)
    if not include_inactive:
        stmt = stmt.where(ExpenseCategory.active.is_(True))
    return list(session.scalars(stmt))


def expense_category_paths(categories: list[ExpenseCategory]) -> dict[str, str]:
    by_id = {c.id: c for c in categories}
    out = {}
    for c in categories:
        parent = by_id.get(c.parent_id) if c.parent_id else None
        out[c.id] = f"{parent.name} › {c.name}" if parent else c.name
    return out


def save_expense_category(session: Session, data: dict, cat_id: str | None = None) -> ExpenseCategory:
    name = (data.get("name") or "").strip()
    require(name, "El nombre es obligatorio")
    cat = get(session, ExpenseCategory, cat_id) if cat_id else ExpenseCategory()
    cat.name = name
    cat.parent_id = data.get("parent_id") or None
    if cat_id:
        from granizapp.core.services.catalog import _check_no_cycle

        _check_no_cycle(session, ExpenseCategory, cat_id, cat.parent_id)
    if cat.parent_id:
        parent = get(session, ExpenseCategory, cat.parent_id)
        cat.type = data.get("type") or parent.type
    else:
        cat.type = data.get("type") or ExpenseType.OPERATING
    cat.keywords = data.get("keywords") or ""
    cat.sort_order = int(data.get("sort_order") or 0)
    cat.active = bool(data.get("active", True))
    if cat_id is None:
        session.add(cat)
    session.flush()
    return cat


def delete_expense_category(session: Session, cat_id: str) -> None:
    used = session.scalars(alive(Expense).where(Expense.category_id == cat_id, Expense.voided.is_(False))).first()
    require(used is None, "La categoría tiene gastos registrados; desactívela en vez de borrarla.")
    soft_delete(session, get(session, ExpenseCategory, cat_id))


def classify_expense(categories: list[ExpenseCategory], text: str) -> ExpenseCategory | None:
    """Sugiere una categoría según palabras clave (se usa al importar y al escribir).

    Gana la palabra clave que aparece primero en la descripción (suele ser lo que se
    compró: "Hielo x2 bolsas" -> Hielo); si empatan, la más larga (más específica).
    """
    import re

    t = normalize(text)
    best, best_score = None, None
    for cat in categories:
        for kw in (cat.keywords or "").split(","):
            kw = normalize(kw)
            if not kw:
                continue
            m = re.search(r"\b" + re.escape(kw), t)
            if m is None:
                continue
            score = (m.start(), -len(kw))
            if best_score is None or score < best_score:
                best, best_score = cat, score
    return best


# --- gastos -------------------------------------------------------------------------
def record_expense(session: Session, data: dict, actor: Actor) -> Expense:
    amount = int(data.get("amount") or 0)
    require(amount > 0, "El valor del gasto debe ser mayor a cero")
    description = (data.get("description") or "").strip()
    require(description, "Escriba una descripción del gasto")
    require(data.get("category_id"), "Seleccione la categoría del gasto")
    at = data.get("at") or local_now()
    exp = Expense(
        at=at,
        category_id=data["category_id"],
        description=description,
        amount=amount,
        account_id=data.get("account_id") or None,
        supplier_id=data.get("supplier_id") or None,
        employee_id=data.get("employee_id") or None,
        receipt=data.get("receipt") or "",
        notes=data.get("notes") or "",
        origin=data.get("origin") or "manual",
        user_id=actor.user_id,
    )
    session.add(exp)
    session.flush()
    if exp.account_id:
        mov = money_movement(session, exp.account_id, -amount, MoneyKind.EXPENSE, description, actor, "gasto", exp.id, at=at)
        exp.cash_session_id = mov.cash_session_id
    return exp


def update_expense(session: Session, expense_id: str, data: dict, actor: Actor) -> Expense:
    """Editar un gasto = anular el asiento anterior y registrar el nuevo (queda rastro)."""
    exp = get(session, Expense, expense_id)
    require(not exp.voided, "El gasto está anulado")
    if exp.account_id:
        reverse_money(session, exp.id, f"Corrección de gasto: {exp.description}", actor)
    exp.at = data.get("at") or exp.at
    exp.category_id = data.get("category_id") or exp.category_id
    exp.description = (data.get("description") or exp.description).strip()
    exp.amount = int(data.get("amount") or exp.amount)
    exp.account_id = data.get("account_id") or None
    exp.supplier_id = data.get("supplier_id") or None
    exp.employee_id = data.get("employee_id") or None
    exp.receipt = data.get("receipt") or ""
    exp.notes = data.get("notes") or ""
    if exp.account_id:
        money_movement(session, exp.account_id, -exp.amount, MoneyKind.EXPENSE, exp.description, actor, "gasto", exp.id, at=exp.at)
    audit(session, actor, "editar_gasto", "expense", exp.id, exp.description)
    return exp


def void_expense(session: Session, expense_id: str, actor: Actor, reason: str = "") -> None:
    exp = get(session, Expense, expense_id)
    require(not exp.voided, "El gasto ya está anulado")
    exp.voided = True
    if exp.account_id:
        reverse_money(session, exp.id, f"Anulación de gasto: {exp.description}", actor)
    audit(session, actor, "anular_gasto", "expense", exp.id, reason or exp.description)


def list_expenses(
    session: Session,
    start: datetime | None = None,
    end: datetime | None = None,
    category_ids: set[str] | None = None,
    include_voided: bool = False,
) -> list[Expense]:
    stmt = alive(Expense).order_by(Expense.at.desc(), Expense.created_at.desc())
    if start:
        stmt = stmt.where(Expense.at >= start)
    if end:
        stmt = stmt.where(Expense.at < end)
    if not include_voided:
        stmt = stmt.where(Expense.voided.is_(False))
    rows = list(session.scalars(stmt))
    if category_ids:
        rows = [e for e in rows if e.category_id in category_ids]
    return rows


# --- capital y otros ingresos ---------------------------------------------------------
INFLOW_KINDS = {MoneyKind.CAPITAL_IN, MoneyKind.OTHER_INCOME, MoneyKind.LOAN_IN}
OUTFLOW_KINDS = {MoneyKind.CAPITAL_OUT, MoneyKind.LOAN_PAYMENT}


def record_financial_entry(session: Session, data: dict, actor: Actor) -> FinancialEntry:
    kind = data.get("kind")
    require(kind in INFLOW_KINDS | OUTFLOW_KINDS, "Tipo de movimiento no válido")
    amount = int(data.get("amount") or 0)
    require(amount > 0, "El valor debe ser mayor a cero")
    require(data.get("account_id"), "Seleccione la cuenta")
    description = (data.get("description") or MoneyKind.LABELS[kind]).strip()
    at = data.get("at") or local_now()
    entry = FinancialEntry(
        at=at,
        kind=kind,
        description=description,
        amount=amount,
        account_id=data["account_id"],
        origin=data.get("origin") or "manual",
        user_id=actor.user_id,
    )
    session.add(entry)
    session.flush()
    if data.get("origin") != "importado":
        sign = 1 if kind in INFLOW_KINDS else -1
        mov = money_movement(session, entry.account_id, sign * amount, kind, description, actor, "financiero", entry.id, at=at)
        entry.cash_session_id = mov.cash_session_id
    audit(session, actor, kind, "financial_entry", entry.id, f"{fmt_money(amount)} {description}")
    return entry


def void_financial_entry(session: Session, entry_id: str, actor: Actor) -> None:
    entry = get(session, FinancialEntry, entry_id)
    require(not entry.voided, "El movimiento ya está anulado")
    entry.voided = True
    reverse_money(session, entry.id, f"Anulación: {entry.description}", actor)
    audit(session, actor, "anular_movimiento", "financial_entry", entry.id, entry.description)


def list_financial_entries(session: Session, start: datetime | None = None, end: datetime | None = None) -> list[FinancialEntry]:
    stmt = alive(FinancialEntry).where(FinancialEntry.voided.is_(False)).order_by(FinancialEntry.at.desc())
    if start:
        stmt = stmt.where(FinancialEntry.at >= start)
    if end:
        stmt = stmt.where(FinancialEntry.at < end)
    return list(session.scalars(stmt))
