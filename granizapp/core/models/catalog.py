"""Catálogo: lo que se vende.

Categorías jerárquicas (Granizados > Con licor), productos con tamaño/volumen,
grupos de modificadores (adiciones, escarchado, sabor) y recetas (fichas técnicas)
que dicen cuánto insumo gasta cada producto o cada adición.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from granizapp.core.models.base import Entity, fk


class ProductKind:
    PREPARED = "preparado"   # granizados, micheladas, sodas: se descuentan insumos por receta
    RESALE = "reventa"       # cerveza, agua: 1 a 1 con un insumo
    COMBO = "combo"          # promos: receta compuesta por otros productos
    EXTRA = "adicion"        # adiciones vendidas como línea propia
    SERVICE = "servicio"     # eventos, domicilios: sin inventario

    LABELS = {
        PREPARED: "Preparado",
        RESALE: "Reventa",
        COMBO: "Combo / Promo",
        EXTRA: "Adición",
        SERVICE: "Servicio",
    }


class ProductCategory(Entity):
    __tablename__ = "product_categories"

    name: Mapped[str] = mapped_column(String(80))
    parent_id: Mapped[Optional[str]] = fk("product_categories.id")
    color: Mapped[str] = mapped_column(String(9), default="#5B8DEF")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    parent: Mapped[Optional["ProductCategory"]] = relationship(remote_side="ProductCategory.id")


class Product(Entity):
    __tablename__ = "products"

    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(20), default="", index=True)  # código rápido: "CL12"
    category_id: Mapped[Optional[str]] = fk("product_categories.id")
    kind: Mapped[str] = mapped_column(String(20), default=ProductKind.PREPARED)
    price: Mapped[int] = mapped_column(Integer, default=0)
    size_label: Mapped[str] = mapped_column(String(20), default="")  # "12 oz"
    volume_ml: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_alcoholic: Mapped[bool] = mapped_column(Boolean, default=False)
    # Costo manual: solo se usa cuando el producto no tiene receta
    manual_cost: Mapped[int] = mapped_column(Integer, default=0)
    track_inventory: Mapped[bool] = mapped_column(Boolean, default=True)
    favorite: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # Días en que se puede vender (0=lunes ... 6=domingo). "0123" = promo de lunes a jueves
    available_days: Mapped[str] = mapped_column(String(7), default="0123456")
    notes: Mapped[str] = mapped_column(Text, default="")

    category: Mapped[Optional[ProductCategory]] = relationship()


class ModifierGroup(Entity):
    """Grupo de opciones que se agregan a un producto: Adiciones, Escarchado... (los sabores de las bolsas son insumos con sabores)."""

    __tablename__ = "modifier_groups"

    name: Mapped[str] = mapped_column(String(80))
    min_select: Mapped[int] = mapped_column(Integer, default=0)
    max_select: Mapped[int] = mapped_column(Integer, default=0)  # 0 = sin límite
    # Abrir la ventana de opciones automáticamente al agregar el producto en caja
    ask_on_add: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ModifierOption(Entity):
    __tablename__ = "modifier_options"

    group_id: Mapped[str] = fk("modifier_groups.id", nullable=False)
    name: Mapped[str] = mapped_column(String(80))
    price_delta: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    group: Mapped[ModifierGroup] = relationship()


class ProductModifierGroup(Entity):
    """Qué grupos de modificadores aplican a cada producto."""

    __tablename__ = "product_modifier_groups"

    product_id: Mapped[str] = fk("products.id", nullable=False)
    group_id: Mapped[str] = fk("modifier_groups.id", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class RecipeLine(Entity):
    """Ficha técnica: una línea de consumo.

    Pertenece a un producto o a una opción de modificador. Consume un insumo
    (`supply_id`, cantidad en la unidad base del insumo: ml, g, und), un insumo con
    variantes (`supply_group_id`: el sabor se elige al vender) o, para combos, otro
    producto (`sub_product_id`, cantidad = número de unidades).
    """

    __tablename__ = "recipe_lines"

    product_id: Mapped[Optional[str]] = fk("products.id")
    modifier_option_id: Mapped[Optional[str]] = fk("modifier_options.id")
    supply_id: Mapped[Optional[str]] = fk("supplies.id")
    supply_group_id: Mapped[Optional[str]] = fk("supply_groups.id")
    sub_product_id: Mapped[Optional[str]] = fk("products.id")
    quantity: Mapped[float] = mapped_column(Float, default=0)
    notes: Mapped[str] = mapped_column(String(200), default="")
