"""Finanzas: cuentas de dinero, libro de movimientos, gastos, caja y capital.

`AccountMovement` es el libro único de dinero: cada venta cobrada, abono, gasto, pago a
proveedor, transferencia o aporte escribe aquí una fila con signo. El saldo de cada
cuenta (Caja, Nequi, Bancolombia...) y el flujo de caja salen de esta tabla.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from granizapp.core.models.base import Entity, fk, local_now


class AccountKind:
    CASH = "efectivo"
    BANK = "banco"
    WALLET = "billetera"

    LABELS = {CASH: "Efectivo", BANK: "Cuenta bancaria", WALLET: "Billetera digital"}


class MoneyKind:
    SALE = "venta"
    ABONO = "abono"
    EXPENSE = "gasto"
    SUPPLIER_PAYMENT = "pago_proveedor"
    TRANSFER = "transferencia"
    CAPITAL_IN = "aporte"
    CAPITAL_OUT = "retiro"
    OTHER_INCOME = "otro_ingreso"
    LOAN_IN = "prestamo"
    LOAN_PAYMENT = "pago_prestamo"
    ADJUST = "ajuste"
    VOID = "anulacion"

    LABELS = {
        SALE: "Venta",
        ABONO: "Abono de cliente",
        EXPENSE: "Gasto",
        SUPPLIER_PAYMENT: "Pago a proveedor",
        TRANSFER: "Transferencia",
        CAPITAL_IN: "Aporte de capital",
        CAPITAL_OUT: "Retiro de socio",
        OTHER_INCOME: "Otro ingreso",
        LOAN_IN: "Préstamo recibido",
        LOAN_PAYMENT: "Pago de préstamo",
        ADJUST: "Ajuste / descuadre",
        VOID: "Anulación",
    }


class ExpenseType:
    """Clasificación contable de las categorías de gasto (para el estado de resultados)."""

    COST = "costo"            # insumos y mercancía comprados como gasto
    OPERATING = "operativo"   # arriendo, servicios, transporte, aseo, publicidad...
    PAYROLL = "nomina"        # sueldos, horas extra, adelantos
    INVESTMENT = "inversion"  # máquinas, muebles, equipos (activos)
    FINANCIAL = "financiero"  # comisiones, intereses
    TAXES = "impuestos"

    LABELS = {
        COST: "Costo de insumos / mercancía",
        OPERATING: "Gasto operativo",
        PAYROLL: "Nómina y personal",
        INVESTMENT: "Inversión (activos)",
        FINANCIAL: "Gasto financiero",
        TAXES: "Impuestos y trámites",
    }


class Account(Entity):
    __tablename__ = "accounts"

    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(12), default=AccountKind.CASH)
    is_drawer: Mapped[bool] = mapped_column(Boolean, default=False)  # el cajón de la caja registradora
    opening_balance: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(String(200), default="")


class AccountMovement(Entity):
    __tablename__ = "account_movements"

    account_id: Mapped[str] = fk("accounts.id", nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime, default=local_now, index=True)
    amount: Mapped[int] = mapped_column(Integer)  # + entra, - sale
    kind: Mapped[str] = mapped_column(String(20), index=True)
    description: Mapped[str] = mapped_column(String(250), default="")
    ref_type: Mapped[str] = mapped_column(String(30), default="")
    ref_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    cash_session_id: Mapped[Optional[str]] = fk("cash_sessions.id")
    user_id: Mapped[Optional[str]] = fk("users.id")
    voided: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    account: Mapped[Account] = relationship()


class ExpenseCategory(Entity):
    __tablename__ = "expense_categories"

    name: Mapped[str] = mapped_column(String(80))
    parent_id: Mapped[Optional[str]] = fk("expense_categories.id")
    type: Mapped[str] = mapped_column(String(12), default=ExpenseType.OPERATING)
    keywords: Mapped[str] = mapped_column(String(250), default="")  # para clasificar importaciones
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    parent: Mapped[Optional["ExpenseCategory"]] = relationship(remote_side="ExpenseCategory.id")


class Expense(Entity):
    __tablename__ = "expenses"

    at: Mapped[datetime] = mapped_column(DateTime, default=local_now, index=True)
    category_id: Mapped[Optional[str]] = fk("expense_categories.id")
    description: Mapped[str] = mapped_column(String(250))
    amount: Mapped[int] = mapped_column(Integer, default=0)
    account_id: Mapped[Optional[str]] = fk("accounts.id")
    supplier_id: Mapped[Optional[str]] = fk("suppliers.id")
    employee_id: Mapped[Optional[str]] = fk("employees.id")
    cash_session_id: Mapped[Optional[str]] = fk("cash_sessions.id")
    user_id: Mapped[Optional[str]] = fk("users.id")
    receipt: Mapped[str] = mapped_column(String(60), default="")  # número de factura / soporte
    notes: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(12), default="manual")
    voided: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    category: Mapped[Optional[ExpenseCategory]] = relationship()


class FinancialEntry(Entity):
    """Ingresos que no son ventas y movimientos de capital."""

    __tablename__ = "financial_entries"

    at: Mapped[datetime] = mapped_column(DateTime, default=local_now, index=True)
    kind: Mapped[str] = mapped_column(String(20))  # MoneyKind: aporte, retiro, otro_ingreso, prestamo...
    description: Mapped[str] = mapped_column(String(250))
    amount: Mapped[int] = mapped_column(Integer, default=0)  # siempre positivo
    account_id: Mapped[str] = fk("accounts.id", nullable=False)
    cash_session_id: Mapped[Optional[str]] = fk("cash_sessions.id")
    user_id: Mapped[Optional[str]] = fk("users.id")
    origin: Mapped[str] = mapped_column(String(12), default="manual")
    voided: Mapped[bool] = mapped_column(Boolean, default=False)


class CashSessionStatus:
    OPEN = "abierta"
    CLOSED = "cerrada"


class CashSession(Entity):
    """Turno de caja: apertura con base, movimientos y arqueo al cierre."""

    __tablename__ = "cash_sessions"

    device_id: Mapped[str] = mapped_column(String(8), default="", index=True)
    number: Mapped[int] = mapped_column(Integer, default=0)
    account_id: Mapped[str] = fk("accounts.id", nullable=False)  # cuenta del cajón
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=local_now, index=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    opened_by: Mapped[Optional[str]] = fk("users.id")
    closed_by: Mapped[Optional[str]] = fk("users.id")
    status: Mapped[str] = mapped_column(String(10), default=CashSessionStatus.OPEN, index=True)
    opening_amount: Mapped[int] = mapped_column(Integer, default=0)
    expected_cash: Mapped[int] = mapped_column(Integer, default=0)
    counted_cash: Mapped[int] = mapped_column(Integer, default=0)
    difference: Mapped[int] = mapped_column(Integer, default=0)
    withdrawn: Mapped[int] = mapped_column(Integer, default=0)  # lo que se sacó al cerrar
    withdraw_account_id: Mapped[Optional[str]] = fk("accounts.id")
    denominations: Mapped[str] = mapped_column(Text, default="")  # JSON {billete: cantidad}
    notes: Mapped[str] = mapped_column(Text, default="")
