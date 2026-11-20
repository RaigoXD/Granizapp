"""Personal: empleados y pagos de nómina (se registran como gastos de nómina)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from granizapp.core.models import Employee, Expense, PayType
from granizapp.core.services import finance
from granizapp.core.services.common import Actor, alive, get, require, soft_delete

# Conceptos de pago -> id fijo de la subcategoría de gasto (creada en los datos semilla)
PAY_CONCEPTS = {
    "sueldo": ("Sueldo / turno", "seed-exp-nomina-sueldos"),
    "extra": ("Horas extra", "seed-exp-nomina-extras"),
    "adelanto": ("Adelanto", "seed-exp-nomina-adelantos"),
    "bono": ("Bonificación / propina", "seed-exp-nomina-bonos"),
    "seguridad": ("Seguridad social / prestaciones", "seed-exp-nomina-seguridad"),
}


def list_employees(session: Session, include_inactive: bool = False) -> list[Employee]:
    stmt = alive(Employee).order_by(Employee.name)
    if not include_inactive:
        stmt = stmt.where(Employee.active.is_(True))
    return list(session.scalars(stmt))


def save_employee(session: Session, data: dict, employee_id: str | None = None) -> Employee:
    name = (data.get("name") or "").strip()
    require(name, "El nombre es obligatorio")
    emp = get(session, Employee, employee_id) if employee_id else Employee()
    emp.name = name
    emp.role = (data.get("role") or "Bartender").strip()
    emp.phone = (data.get("phone") or "").strip()
    emp.document = (data.get("document") or "").strip()
    emp.pay_type = data.get("pay_type") or PayType.BIWEEKLY
    emp.base_pay = int(data.get("base_pay") or 0)
    emp.hourly_rate = int(data.get("hourly_rate") or 0)
    emp.start_date = data.get("start_date")
    emp.active = bool(data.get("active", True))
    emp.notes = data.get("notes") or ""
    if employee_id is None:
        session.add(emp)
    session.flush()
    return emp


def delete_employee(session: Session, employee_id: str) -> None:
    soft_delete(session, get(session, Employee, employee_id))


def pay_employee(
    session: Session,
    employee_id: str,
    amount: int,
    concept: str,
    account_id: str | None,
    actor: Actor,
    at: datetime | None = None,
    notes: str = "",
) -> Expense:
    emp = get(session, Employee, employee_id)
    require(concept in PAY_CONCEPTS, "Concepto de pago no válido")
    label, category_id = PAY_CONCEPTS[concept]
    return finance.record_expense(
        session,
        {
            "at": at,
            "category_id": category_id,
            "description": f"{label} - {emp.name}",
            "amount": amount,
            "account_id": account_id,
            "employee_id": emp.id,
            "notes": notes,
        },
        actor,
    )


def employee_payments(session: Session, employee_id: str | None = None, start: datetime | None = None,
                      end: datetime | None = None) -> list[Expense]:
    stmt = alive(Expense).where(Expense.employee_id.is_not(None), Expense.voided.is_(False)).order_by(Expense.at.desc())
    if employee_id:
        stmt = stmt.where(Expense.employee_id == employee_id)
    if start:
        stmt = stmt.where(Expense.at >= start)
    if end:
        stmt = stmt.where(Expense.at < end)
    return list(session.scalars(stmt))
