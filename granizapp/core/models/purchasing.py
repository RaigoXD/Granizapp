"""Proveedores, compras de insumos y cuentas por pagar."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from granizapp.core.models.base import Entity, fk, local_now


class Supplier(Entity):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(120))
    nit: Mapped[str] = mapped_column(String(30), default="")
    contact_name: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    city: Mapped[str] = mapped_column(String(80), default="")
    address: Mapped[str] = mapped_column(String(200), default="")
    supplies_text: Mapped[str] = mapped_column(String(250), default="")  # qué le compramos
    payment_terms: Mapped[str] = mapped_column(String(80), default="Contado")
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PurchaseStatus:
    RECEIVED = "recibida"
    VOID = "anulada"


class Purchase(Entity):
    __tablename__ = "purchases"

    supplier_id: Mapped[Optional[str]] = fk("suppliers.id")
    at: Mapped[datetime] = mapped_column(DateTime, default=local_now, index=True)
    invoice_number: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(12), default=PurchaseStatus.RECEIVED)
    subtotal: Mapped[int] = mapped_column(Integer, default=0)
    shipping: Mapped[int] = mapped_column(Integer, default=0)  # envío / flete
    total: Mapped[int] = mapped_column(Integer, default=0)
    paid: Mapped[int] = mapped_column(Integer, default=0)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    user_id: Mapped[Optional[str]] = fk("users.id")
    notes: Mapped[str] = mapped_column(Text, default="")

    supplier: Mapped[Optional[Supplier]] = relationship()

    @property
    def balance(self) -> int:
        return max(0, (self.total or 0) - (self.paid or 0))


class PurchaseItem(Entity):
    __tablename__ = "purchase_items"

    purchase_id: Mapped[str] = fk("purchases.id", nullable=False)
    supply_id: Mapped[str] = fk("supplies.id", nullable=False)
    description: Mapped[str] = mapped_column(String(160), default="")
    presentations: Mapped[float] = mapped_column(Float, default=1)     # cuántas bolsas / paquetes
    presentation_qty: Mapped[float] = mapped_column(Float, default=1)  # contenido de cada una
    base_qty: Mapped[float] = mapped_column(Float, default=0)          # total en unidad base
    line_total: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost: Mapped[float] = mapped_column(Float, default=0)          # por unidad base, con envío


class SupplierPayment(Entity):
    __tablename__ = "supplier_payments"

    supplier_id: Mapped[Optional[str]] = fk("suppliers.id")
    purchase_id: Mapped[Optional[str]] = fk("purchases.id")
    at: Mapped[datetime] = mapped_column(DateTime, default=local_now, index=True)
    amount: Mapped[int] = mapped_column(Integer, default=0)
    account_id: Mapped[str] = fk("accounts.id", nullable=False)
    cash_session_id: Mapped[Optional[str]] = fk("cash_sessions.id")
    user_id: Mapped[Optional[str]] = fk("users.id")
    voided: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(200), default="")
