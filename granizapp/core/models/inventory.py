"""Inventario de insumos.

Cada insumo se maneja en una unidad base (ml, g o und) y tiene una presentación de
compra (bolsa de 6.000 ml, paquete de 50 vasos, paca de 24 cervezas). La existencia
es la suma de los movimientos (kardex), así varias cajas pueden sincronizar sin
pisarse el saldo.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from granizapp.core.models.base import Entity, fk, local_now


class Unit:
    ML = "ml"
    G = "g"
    UNIT = "und"

    LABELS = {ML: "mililitros (ml)", G: "gramos (g)", UNIT: "unidades (und)"}
    CHOICES = [ML, G, UNIT]


class MovementKind:
    INITIAL = "inicial"
    PURCHASE = "compra"
    SALE = "venta"
    VOID = "anulacion"
    ADJUST = "ajuste"
    COUNT = "conteo"
    WASTE = "merma"
    INTERNAL = "consumo_interno"
    RETURN = "devolucion"

    LABELS = {
        INITIAL: "Inventario inicial",
        PURCHASE: "Compra",
        SALE: "Venta",
        VOID: "Anulación de venta",
        ADJUST: "Ajuste",
        COUNT: "Conteo físico",
        WASTE: "Merma / daño",
        INTERNAL: "Consumo interno",
        RETURN: "Devolución a proveedor",
    }


class SupplyCategory(Entity):
    __tablename__ = "supply_categories"

    name: Mapped[str] = mapped_column(String(80))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class SupplyGroup(Entity):
    """Insumo con variantes: una bolsa de mezcla que viene en varios sabores.

    Las recetas consumen el grupo ("320 ml de Mezcla con licor") y al vender se elige el sabor,
    que es un `Supply` miembro del grupo con su propia existencia, costo y mínimo. El miembro
    `default_supply_id` ("Sin especificar") recibe lo vendido sin decir sabor.
    """

    __tablename__ = "supply_groups"

    name: Mapped[str] = mapped_column(String(120))
    category_id: Mapped[Optional[str]] = fk("supply_categories.id")
    unit: Mapped[str] = mapped_column(String(5), default=Unit.ML)
    presentation_name: Mapped[str] = mapped_column(String(40), default="bolsa")
    presentation_qty: Mapped[float] = mapped_column(Float, default=1)
    # sin llave foránea a propósito: evita el ciclo supplies <-> supply_groups al crear tablas
    default_supply_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ask_on_sale: Mapped[bool] = mapped_column(Boolean, default=True)  # preguntar el sabor al vender
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class Supply(Entity):
    __tablename__ = "supplies"

    name: Mapped[str] = mapped_column(String(120))
    category_id: Mapped[Optional[str]] = fk("supply_categories.id")
    unit: Mapped[str] = mapped_column(String(5), default=Unit.UNIT)
    presentation_name: Mapped[str] = mapped_column(String(40), default="unidad")
    presentation_qty: Mapped[float] = mapped_column(Float, default=1)
    # Variante de un grupo (sabor): grupo al que pertenece, nombre y código corto para vender
    group_id: Mapped[Optional[str]] = fk("supply_groups.id")
    variant_name: Mapped[str] = mapped_column(String(80), default="", server_default="")
    variant_code: Mapped[str] = mapped_column(String(12), default="", server_default="")
    # Costos por unidad base (pesos por ml / g / und)
    avg_cost: Mapped[float] = mapped_column(Float, default=0)
    last_cost: Mapped[float] = mapped_column(Float, default=0)
    min_stock: Mapped[float] = mapped_column(Float, default=0)  # en unidad base
    supplier_id: Mapped[Optional[str]] = fk("suppliers.id")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    category: Mapped[Optional[SupplyCategory]] = relationship()
    group: Mapped[Optional[SupplyGroup]] = relationship()

    @property
    def is_variant(self) -> bool:
        return bool(self.group_id)


class StockMovement(Entity):
    __tablename__ = "stock_movements"

    supply_id: Mapped[str] = fk("supplies.id", nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime, default=local_now, index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    quantity: Mapped[float] = mapped_column(Float)  # con signo, en unidad base
    unit_cost: Mapped[float] = mapped_column(Float, default=0)
    ref_type: Mapped[str] = mapped_column(String(30), default="")
    ref_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    note: Mapped[str] = mapped_column(String(250), default="")
    user_id: Mapped[Optional[str]] = fk("users.id")

    supply: Mapped[Supply] = relationship()
