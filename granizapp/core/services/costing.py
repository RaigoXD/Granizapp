"""Costeo: cuánto cuesta cada vaso, qué margen deja y cuántos vasos rinde cada presentación.

Ejemplo: si el Granizado CL 12 oz gasta 320 ml de la bolsa de 6.000 ml, una bolsa rinde
18,75 vasos; si la bolsa cuesta $ 57.500, la mezcla de cada vaso cuesta $ 3.067.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from granizapp.core.models import Product, Supply
from granizapp.core.services.catalog import RecipeBook, list_options, list_products

OZ_ML = 29.5735


def oz_to_ml(oz: float) -> float:
    return oz * OZ_ML


@dataclass
class CostLine:
    name: str
    unit: str
    quantity: float
    unit_cost: float
    cost: float
    is_product: bool = False
    is_group: bool = False  # insumo con sabores: costo promedio de sus sabores


@dataclass
class ProductCosting:
    product: Product
    lines: list[CostLine] = field(default_factory=list)
    cost: float = 0.0
    has_recipe: bool = False

    @property
    def price(self) -> int:
        return self.product.price or 0

    @property
    def margin(self) -> float:
        return self.price - self.cost

    @property
    def margin_pct(self) -> float | None:
        return self.margin / self.price if self.price else None

    @property
    def cost_pct(self) -> float | None:
        return self.cost / self.price if self.price else None


def product_costing(book: RecipeBook, product: Product) -> ProductCosting:
    pc = ProductCosting(product=product, has_recipe=book.has_recipe(product.id))
    for line in book.by_product.get(product.id, []):
        if line.supply_group_id:
            g = book.groups.get(line.supply_group_id)
            if g is None:
                continue
            unit_cost = book.group_cost(g.id)
            pc.lines.append(CostLine(f"{g.name} (promedio de sabores)", g.unit, line.quantity, unit_cost,
                                     unit_cost * line.quantity, is_group=True))
        elif line.supply_id:
            s = book.supplies.get(line.supply_id)
            if s is None:
                continue
            cost = line.quantity * (s.avg_cost or 0)
            pc.lines.append(CostLine(s.name, s.unit, line.quantity, s.avg_cost or 0, cost))
        elif line.sub_product_id:
            sub = book.products.get(line.sub_product_id)
            unit_cost = book.product_cost(line.sub_product_id)
            pc.lines.append(CostLine(sub.name if sub else "?", "und", line.quantity, unit_cost,
                                     unit_cost * line.quantity, True))
    pc.cost = book.product_cost(product.id)
    return pc


def costing_table(session: Session, include_inactive: bool = False) -> list[ProductCosting]:
    book = RecipeBook(session)
    return [product_costing(book, p) for p in list_products(session, include_inactive)]


@dataclass
class OptionCosting:
    name: str
    group_id: str
    price: int
    cost: float


def options_costing(session: Session) -> list[OptionCosting]:
    book = RecipeBook(session)
    return [OptionCosting(o.name, o.group_id, o.price_delta, book.option_cost(o.id)) for o in list_options(session)]


@dataclass
class YieldRow:
    product: Product
    per_unit: float          # cantidad del insumo por vaso
    units_per_presentation: float
    cost_per_unit: float     # costo de ese insumo por vaso


def yields_for_supply(session: Session, supply: Supply) -> list[YieldRow]:
    """Para un insumo (p. ej. la bolsa de 6 L), cuántos vasos de cada producto rinde.
    Si es un sabor, cuenta los productos que usan su grupo como si se vendieran con ese sabor."""
    book = RecipeBook(session)
    choices = {supply.group_id: {supply.id: 1.0}} if supply.group_id else None
    rows = []
    for product in list_products(session):
        consumption = book.expand_product(product.id, 1.0, choices) if product.track_inventory else {}
        qty = consumption.get(supply.id)
        if not qty:
            continue
        rows.append(
            YieldRow(
                product=product,
                per_unit=qty,
                units_per_presentation=(supply.presentation_qty or 1) / qty,
                cost_per_unit=qty * (supply.avg_cost or 0),
            )
        )
    rows.sort(key=lambda r: r.per_unit)
    return rows


def quantity_from_yield(presentation_qty: float, units: float) -> float:
    """Calibración: "1 bolsa de 6.000 ml me rindió 18 vasos" -> 333,3 ml por vaso."""
    if units <= 0:
        return 0.0
    return presentation_qty / units


def cups_from_volume(total_ml: float, cup_oz: float, fill_pct: float = 0.9) -> float:
    """Estimación teórica: vasos que salen de un volumen según la onza del vaso y el llenado."""
    per_cup = oz_to_ml(cup_oz) * fill_pct
    return total_ml / per_cup if per_cup else 0.0
