"""Ventas, pagos y clientes (incluye los fiados / deudores)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from granizapp.core.models.base import Entity, fk, local_now


class SaleStatus:
    OPEN = "abierta"      # cuenta abierta / mesa: aún se le pueden agregar cosas
    CLOSED = "cerrada"    # cobrada (total o parcialmente: el saldo queda como fiado)
    VOID = "anulada"

    LABELS = {OPEN: "Abierta", CLOSED: "Cerrada", VOID: "Anulada"}


class PaymentKind:
    SALE = "venta"     # pago al momento de la venta
    ABONO = "abono"    # pago posterior de un fiado

    LABELS = {SALE: "Venta", ABONO: "Abono"}


class Customer(Entity):
    __tablename__ = "customers"

    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(40), default="")
    document: Mapped[str] = mapped_column(String(40), default="")
    credit_limit: Mapped[int] = mapped_column(Integer, default=0)  # 0 = sin límite
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PaymentMethod(Entity):
    __tablename__ = "payment_methods"

    name: Mapped[str] = mapped_column(String(60))
    account_id: Mapped[Optional[str]] = fk("accounts.id")
    is_cash: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Sale(Entity):
    __tablename__ = "sales"

    number: Mapped[int] = mapped_column(Integer, default=0, index=True)
    device_id: Mapped[str] = mapped_column(String(8), default="")
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=local_now)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(12), default=SaleStatus.OPEN, index=True)
    label: Mapped[str] = mapped_column(String(80), default="")  # nombre de la cuenta abierta / mesa
    customer_id: Mapped[Optional[str]] = fk("customers.id")
    cash_session_id: Mapped[Optional[str]] = fk("cash_sessions.id")
    user_id: Mapped[Optional[str]] = fk("users.id")
    subtotal: Mapped[int] = mapped_column(Integer, default=0)
    discount: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    paid: Mapped[int] = mapped_column(Integer, default=0)
    cost_total: Mapped[float] = mapped_column(Float, default=0)
    is_credit: Mapped[bool] = mapped_column(Boolean, default=False)  # se dejó saldo fiado
    origin: Mapped[str] = mapped_column(String(12), default="pos")  # pos | importado
    notes: Mapped[str] = mapped_column(Text, default="")
    void_reason: Mapped[str] = mapped_column(String(250), default="")

    customer: Mapped[Optional[Customer]] = relationship()

    @property
    def balance(self) -> int:
        return max(0, (self.total or 0) - (self.paid or 0))


class SaleItem(Entity):
    __tablename__ = "sale_items"

    sale_id: Mapped[str] = fk("sales.id", nullable=False)
    product_id: Mapped[Optional[str]] = fk("products.id")
    name: Mapped[str] = mapped_column(String(160))
    quantity: Mapped[float] = mapped_column(Float, default=1)
    unit_price: Mapped[int] = mapped_column(Integer, default=0)      # precio base del producto
    modifiers_price: Mapped[int] = mapped_column(Integer, default=0)  # suma de adiciones por unidad
    discount: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost: Mapped[float] = mapped_column(Float, default=0)        # costo por unidad (con adiciones)
    notes: Mapped[str] = mapped_column(String(200), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class SaleItemModifier(Entity):
    """Una adición (option_id) o un sabor elegido (supply_id + supply_group_id) de una línea.

    Sabores: una fila por cada elección; en una promo x2 con Tijuana y Nueva York hay dos
    filas. `quantity` = vasos de la línea servidos con ese sabor (para reportes por sabor).
    """

    __tablename__ = "sale_item_modifiers"

    sale_item_id: Mapped[str] = fk("sale_items.id", nullable=False)
    option_id: Mapped[Optional[str]] = fk("modifier_options.id")
    supply_id: Mapped[Optional[str]] = fk("supplies.id")
    supply_group_id: Mapped[Optional[str]] = fk("supply_groups.id")
    name: Mapped[str] = mapped_column(String(120))
    price_delta: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost: Mapped[float] = mapped_column(Float, default=0)
    quantity: Mapped[float] = mapped_column(Float, default=0, server_default="0")


class Payment(Entity):
    __tablename__ = "payments"

    at: Mapped[datetime] = mapped_column(DateTime, default=local_now, index=True)
    kind: Mapped[str] = mapped_column(String(10), default=PaymentKind.SALE, index=True)
    sale_id: Mapped[Optional[str]] = fk("sales.id")
    customer_id: Mapped[Optional[str]] = fk("customers.id")
    method_id: Mapped[str] = fk("payment_methods.id", nullable=False)
    amount: Mapped[int] = mapped_column(Integer, default=0)
    received: Mapped[int] = mapped_column(Integer, default=0)  # efectivo entregado (para el cambio)
    group_id: Mapped[str] = mapped_column(String(64), default="", index=True)  # un abono repartido
    cash_session_id: Mapped[Optional[str]] = fk("cash_sessions.id")
    user_id: Mapped[Optional[str]] = fk("users.id")
    voided: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(200), default="")

    method: Mapped[PaymentMethod] = relationship()
