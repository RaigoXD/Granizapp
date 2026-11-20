"""Inventario: insumos, existencias (kardex), conteos físicos y mermas."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from granizapp.core.models import (
    MovementKind,
    Sale,
    SaleItem,
    SaleItemModifier,
    SaleStatus,
    StockMovement,
    Supply,
    SupplyCategory,
    SupplyGroup,
    Unit,
    local_now,
)
from granizapp.core.services.common import Actor, ServiceError, alive, audit, get, require, soft_delete
from granizapp.core.utils import fmt_number, normalize

DEFAULT_VARIANT = "Sin especificar"


# --- categorías de insumo -------------------------------------------------------------
def list_supply_categories(session: Session) -> list[SupplyCategory]:
    return list(session.scalars(alive(SupplyCategory).order_by(SupplyCategory.sort_order, SupplyCategory.name)))


def save_supply_category(session: Session, data: dict, cat_id: str | None = None) -> SupplyCategory:
    name = (data.get("name") or "").strip()
    require(name, "El nombre es obligatorio")
    cat = get(session, SupplyCategory, cat_id) if cat_id else SupplyCategory()
    cat.name = name
    cat.sort_order = int(data.get("sort_order") or 0)
    cat.active = bool(data.get("active", True))
    if cat_id is None:
        session.add(cat)
    session.flush()
    return cat


def delete_supply_category(session: Session, cat_id: str) -> None:
    used = session.scalars(alive(Supply).where(Supply.category_id == cat_id)).first()
    require(used is None, "La categoría tiene insumos asignados")
    soft_delete(session, get(session, SupplyCategory, cat_id))


# --- insumos ----------------------------------------------------------------------------
def list_supplies(session: Session, include_inactive: bool = False) -> list[Supply]:
    stmt = alive(Supply).order_by(Supply.name)
    if not include_inactive:
        stmt = stmt.where(Supply.active.is_(True))
    return list(session.scalars(stmt))


def save_supply(session: Session, data: dict, supply_id: str | None = None, actor: Actor | None = None) -> Supply:
    name = (data.get("name") or "").strip()
    require(name, "El nombre del insumo es obligatorio")
    unit = data.get("unit") or Unit.UNIT
    require(unit in Unit.CHOICES, "Unidad no válida")
    pres_qty = float(data.get("presentation_qty") or 1)
    require(pres_qty > 0, "El contenido de la presentación debe ser mayor a cero")
    supply = get(session, Supply, supply_id) if supply_id else Supply()
    group_id = data.get("group_id") if "group_id" in data else supply.group_id
    if group_id:  # sabor de un insumo con sabores: unidad y presentación son las del grupo
        group = get(session, SupplyGroup, group_id)
        variant = (data.get("variant_name") or supply.variant_name or name).strip()
        code = (data.get("variant_code") if "variant_code" in data else supply.variant_code) or ""
        code = code.strip().upper()
        for other in list_variants(session, group_id, include_inactive=True):
            if other.id == supply.id:
                continue
            require(normalize(other.variant_name) != normalize(variant), f"Ya existe el sabor «{other.variant_name}»")
            require(not code or (other.variant_code or "").upper() != code,
                    f"El código {code} ya lo usa «{other.variant_name}»")
        supply.group_id = group.id
        supply.variant_name = variant
        supply.variant_code = code
        name = variant_display_name(group, variant)
        unit = group.unit
        pres_qty = group.presentation_qty
        data = {**data, "presentation_name": group.presentation_name,
                "category_id": data.get("category_id") or group.category_id}
    supply.name = name
    supply.category_id = data.get("category_id") or None
    supply.unit = unit
    supply.presentation_name = (data.get("presentation_name") or "unidad").strip()
    supply.presentation_qty = pres_qty
    supply.min_stock = float(data.get("min_stock") or 0)
    supply.supplier_id = data.get("supplier_id") or None
    supply.active = bool(data.get("active", True))
    supply.notes = data.get("notes") or ""
    if "avg_cost" in data and data["avg_cost"] is not None:
        supply.avg_cost = float(data["avg_cost"])
        if not supply.last_cost:
            supply.last_cost = supply.avg_cost
    if supply_id is None:
        supply.avg_cost = float(data.get("avg_cost") or 0)
        supply.last_cost = supply.avg_cost
        session.add(supply)
    session.flush()
    initial = float(data.get("initial_stock") or 0)
    if supply_id is None and initial:
        add_movement(session, supply.id, initial, MovementKind.INITIAL, supply.avg_cost, note="Inventario inicial", actor=actor)
    return supply


def delete_supply(session: Session, supply_id: str, actor: Actor | None = None) -> None:
    from granizapp.core.models import ModifierOption, Product, RecipeLine

    supply = get(session, Supply, supply_id)
    if supply.group_id:
        group = session.get(SupplyGroup, supply.group_id)
        require(group is None or group.deleted or group.default_supply_id != supply.id,
                f"«{DEFAULT_VARIANT}» recibe lo vendido sin sabor y no se puede eliminar.")
    lines = session.scalars(alive(RecipeLine).where(RecipeLine.supply_id == supply_id)).all()
    if lines:
        names = set()
        for ln in lines:
            owner = session.get(Product, ln.product_id) if ln.product_id else session.get(ModifierOption, ln.modifier_option_id)
            if owner is not None and not owner.deleted:
                names.add(owner.name)
        if names:
            raise ServiceError(f"«{supply.name}» está en la receta de: {', '.join(sorted(names)[:6])}"
                               f"{'…' if len(names) > 6 else ''}. Cámbielo en esas recetas antes de eliminarlo (o desactívelo).")
    soft_delete(session, supply)
    audit(session, actor, "eliminar_insumo", "supply", supply.id, supply.name)


# --- existencias -----------------------------------------------------------------------
def stock_map(session: Session, at: datetime | None = None) -> dict[str, float]:
    stmt = (
        select(StockMovement.supply_id, func.sum(StockMovement.quantity))
        .where(StockMovement.deleted.is_(False))
        .group_by(StockMovement.supply_id)
    )
    if at is not None:
        stmt = stmt.where(StockMovement.at < at)
    return {sid: float(q or 0) for sid, q in session.execute(stmt)}


def stock_of(session: Session, supply_id: str) -> float:
    q = session.scalar(
        select(func.sum(StockMovement.quantity)).where(
            StockMovement.supply_id == supply_id, StockMovement.deleted.is_(False)
        )
    )
    return float(q or 0)


@dataclass
class StockRow:
    supply: Supply
    category: str
    stock: float
    presentations: float
    value: float
    status: str  # ok | bajo | agotado | sin_sabor

    @property
    def status_label(self) -> str:
        return {"ok": "OK", "bajo": "Bajo", "agotado": "Agotado", "sin_sabor": "Sin sabor"}[self.status]


def unassigned_ids(session: Session) -> set[str]:
    """Insumos «Sin especificar» de los insumos con sabores."""
    return {g.default_supply_id for g in session.scalars(alive(SupplyGroup)) if g.default_supply_id}


def stock_levels(session: Session, include_inactive: bool = False) -> list[StockRow]:
    stocks = stock_map(session)
    cats = {c.id: c.name for c in list_supply_categories(session)}
    unassigned = unassigned_ids(session)
    rows = []
    for s in list_supplies(session, include_inactive):
        qty = stocks.get(s.id, 0.0)
        if s.id in unassigned:  # lo vendido o comprado sin sabor: aviso, no alerta de compra
            status = "sin_sabor" if abs(qty) > 0.0001 else "ok"
        elif qty <= 0.0001:
            status = "agotado"
        elif s.min_stock and qty <= s.min_stock:
            status = "bajo"
        else:
            status = "ok"
        rows.append(
            StockRow(
                supply=s,
                category=cats.get(s.category_id, "Sin categoría"),
                stock=qty,
                presentations=qty / s.presentation_qty if s.presentation_qty else qty,
                value=max(qty, 0) * (s.avg_cost or 0),
                status=status,
            )
        )
    return rows


def low_stock(session: Session) -> list[StockRow]:
    return [r for r in stock_levels(session) if r.status != "ok" and (r.supply.min_stock or 0) > 0]


def inventory_value(session: Session, at: datetime | None = None) -> float:
    stocks = stock_map(session, at)
    return sum(max(stocks.get(s.id, 0.0), 0) * (s.avg_cost or 0) for s in list_supplies(session, True))


# --- movimientos ------------------------------------------------------------------------
def add_movement(
    session: Session,
    supply_id: str,
    quantity: float,
    kind: str,
    unit_cost: float | None = None,
    ref_type: str = "",
    ref_id: str | None = None,
    note: str = "",
    actor: Actor | None = None,
    at: datetime | None = None,
) -> StockMovement:
    if unit_cost is None:
        supply = session.get(Supply, supply_id)
        unit_cost = supply.avg_cost if supply else 0.0
    mov = StockMovement(
        supply_id=supply_id,
        quantity=float(quantity),
        kind=kind,
        unit_cost=float(unit_cost or 0),
        ref_type=ref_type,
        ref_id=ref_id,
        note=note[:250],
        user_id=actor.user_id if actor else None,
        at=at or local_now(),
    )
    session.add(mov)
    return mov


def consume(
    session: Session,
    consumption: dict[str, float],
    kind: str,
    ref_type: str,
    ref_id: str,
    note: str = "",
    actor: Actor | None = None,
    at: datetime | None = None,
    supplies: dict[str, Supply] | None = None,
) -> None:
    """Descuenta insumos (cantidades positivas = salida)."""
    for supply_id, qty in consumption.items():
        if abs(qty) < 1e-9:
            continue
        cost = supplies[supply_id].avg_cost if supplies and supply_id in supplies else None
        add_movement(session, supply_id, -qty, kind, cost, ref_type, ref_id, note, actor, at)


def reverse_movements(session: Session, ref_id: str, kind: str, note: str, actor: Actor | None = None) -> int:
    """Crea movimientos contrarios a los de una referencia (anulación de venta o compra)."""
    originals = session.scalars(
        alive(StockMovement).where(StockMovement.ref_id == ref_id, StockMovement.kind != MovementKind.VOID)
    ).all()
    for mov in originals:
        add_movement(session, mov.supply_id, -mov.quantity, kind, mov.unit_cost, mov.ref_type, ref_id, note, actor)
    return len(originals)


def receive(session: Session, supply: Supply, quantity: float, unit_cost: float, ref_type: str, ref_id: str,
            note: str = "", actor: Actor | None = None, at: datetime | None = None) -> None:
    """Entrada por compra: actualiza el costo promedio ponderado y el último costo."""
    require(quantity > 0, "La cantidad recibida debe ser mayor a cero")
    before = max(stock_of(session, supply.id), 0.0)
    if before + quantity > 0:
        supply.avg_cost = (before * (supply.avg_cost or 0) + quantity * unit_cost) / (before + quantity)
    supply.last_cost = unit_cost
    add_movement(session, supply.id, quantity, MovementKind.PURCHASE, unit_cost, ref_type, ref_id, note, actor, at)


def adjust_to_count(session: Session, supply_id: str, counted: float, actor: Actor, note: str = "") -> float:
    """Conteo físico: registra la diferencia contra el sistema. Devuelve la diferencia."""
    require(counted >= 0, "El conteo no puede ser negativo")
    current = stock_of(session, supply_id)
    diff = counted - current
    if abs(diff) > 1e-6:
        add_movement(session, supply_id, diff, MovementKind.COUNT, None, "conteo", None,
                     note or f"Conteo físico: {counted:g} (sistema {current:g})", actor)
        audit(session, actor, "conteo_inventario", "supply", supply_id, f"sistema={current:g} contado={counted:g}")
    return diff


def register_adjustment(session: Session, supply_id: str, quantity: float, kind: str, actor: Actor, note: str) -> None:
    require(kind in (MovementKind.ADJUST, MovementKind.WASTE, MovementKind.INTERNAL, MovementKind.INITIAL,
                     MovementKind.RETURN), "Tipo de ajuste no válido")
    require(abs(quantity) > 0, "La cantidad debe ser distinta de cero")
    if kind in (MovementKind.WASTE, MovementKind.INTERNAL, MovementKind.RETURN):
        quantity = -abs(quantity)
    add_movement(session, supply_id, quantity, kind, None, kind, None, note, actor)
    audit(session, actor, f"inventario_{kind}", "supply", supply_id, f"{quantity:g} {note}")


def list_movements(
    session: Session,
    supply_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    kind: str | None = None,
    limit: int = 5000,
) -> list[StockMovement]:
    stmt = alive(StockMovement).order_by(StockMovement.at.desc(), StockMovement.created_at.desc())
    if supply_id:
        stmt = stmt.where(StockMovement.supply_id == supply_id)
    if start:
        stmt = stmt.where(StockMovement.at >= start)
    if end:
        stmt = stmt.where(StockMovement.at < end)
    if kind:
        stmt = stmt.where(StockMovement.kind == kind)
    return list(session.scalars(stmt.limit(limit)))


def presentation_text(supply: Supply, qty: float) -> str:
    """"3,5 bolsas (21.000 ml)"."""
    from granizapp.core.utils import fmt_number

    base = f"{fmt_number(qty, 2)} {supply.unit}"
    if supply.presentation_qty and supply.presentation_qty != 1:
        pres = qty / supply.presentation_qty
        return f"{fmt_number(pres, 2)} {supply.presentation_name} ({base})"
    return base


def ensure_supply(session: Session, supply_id: str) -> Supply:
    supply = session.get(Supply, supply_id)
    if supply is None or supply.deleted:
        raise ServiceError("Insumo no encontrado")
    return supply


# --- insumos con sabores (variantes) -------------------------------------------------------
def variant_display_name(group: SupplyGroup, variant_name: str) -> str:
    return f"{group.name} · {variant_name}"


def list_supply_groups(session: Session, include_inactive: bool = False) -> list[SupplyGroup]:
    stmt = alive(SupplyGroup).order_by(SupplyGroup.sort_order, SupplyGroup.name)
    if not include_inactive:
        stmt = stmt.where(SupplyGroup.active.is_(True))
    return list(session.scalars(stmt))


def list_variants(session: Session, group_id: str, include_inactive: bool = False) -> list[Supply]:
    """Sabores de un grupo en orden alfabético, con «Sin especificar» de último."""
    stmt = alive(Supply).where(Supply.group_id == group_id)
    if not include_inactive:
        stmt = stmt.where(Supply.active.is_(True))
    group = session.get(SupplyGroup, group_id)
    default = group.default_supply_id if group is not None else None
    rows = list(session.scalars(stmt))
    rows.sort(key=lambda s: (s.id == default, normalize(s.variant_name or s.name)))
    return rows


def save_supply_group(session: Session, data: dict, group_id: str | None = None,
                      actor: Actor | None = None) -> SupplyGroup:
    """Crea o edita un insumo con sabores. Al crearlo se crea su sabor «Sin especificar»."""
    name = (data.get("name") or "").strip()
    require(name, "Escriba el nombre (ej. Mezcla con licor (bolsa 6 L))")
    unit = data.get("unit") or Unit.ML
    require(unit in Unit.CHOICES, "Unidad no válida")
    pres_qty = float(data.get("presentation_qty") or 0)
    require(pres_qty > 0, "El contenido de la presentación debe ser mayor a cero (ej. 6000 ml)")
    group = get(session, SupplyGroup, group_id) if group_id else SupplyGroup()
    group.name = name
    group.category_id = data.get("category_id") or None
    group.unit = unit
    group.presentation_name = (data.get("presentation_name") or "bolsa").strip()
    group.presentation_qty = pres_qty
    group.ask_on_sale = bool(data.get("ask_on_sale", True))
    group.active = bool(data.get("active", True))
    group.notes = data.get("notes") or ""
    if group_id is None:
        session.add(group)
        session.flush()
        cost = float(data.get("pres_cost") or 0) / pres_qty
        default = Supply(name=variant_display_name(group, DEFAULT_VARIANT), category_id=group.category_id, unit=unit,
                         presentation_name=group.presentation_name, presentation_qty=pres_qty, group_id=group.id,
                         variant_name=DEFAULT_VARIANT, avg_cost=cost, last_cost=cost)
        session.add(default)
        session.flush()
        group.default_supply_id = default.id
        audit(session, actor, "crear_grupo_sabores", "supply_group", group.id, group.name)
    else:
        for member in list_variants(session, group.id, include_inactive=True):
            member.name = variant_display_name(group, member.variant_name or DEFAULT_VARIANT)
            member.unit = unit
            member.presentation_name = group.presentation_name
            member.presentation_qty = pres_qty
    session.flush()
    return group


def delete_supply_group(session: Session, group_id: str, actor: Actor | None = None) -> None:
    from granizapp.core.models import RecipeLine

    group = get(session, SupplyGroup, group_id)
    used = session.scalars(alive(RecipeLine).where(RecipeLine.supply_group_id == group_id)).first()
    require(used is None, f"«{group.name}» está en recetas de productos. Cámbielas antes de eliminarlo.")
    stocks = stock_map(session)
    members = list_variants(session, group_id, include_inactive=True)
    for member in members:
        require(abs(stocks.get(member.id, 0.0)) < 1e-6,
                f"El sabor «{member.variant_name}» todavía tiene existencias: ajústelas a cero primero.")
    for member in members:
        soft_delete(session, member)
    soft_delete(session, group)
    audit(session, actor, "eliminar_grupo_sabores", "supply_group", group.id, group.name)


def save_variant(session: Session, group_id: str, data: dict, supply_id: str | None = None,
                 actor: Actor | None = None) -> Supply:
    """Crea o edita un sabor. data: variant_name, variant_code, min_pres (bolsas), pres_cost (costo de
    una bolsa), initial (bolsas, solo al crear), supplier_id, active, notes."""
    group = get(session, SupplyGroup, group_id)
    q = group.presentation_qty or 1
    payload = {
        "group_id": group_id,
        "name": data.get("variant_name") or "",
        "variant_name": (data.get("variant_name") or "").strip(),
        "variant_code": data.get("variant_code") or "",
        "min_stock": float(data.get("min_pres") or 0) * q,
        "supplier_id": data.get("supplier_id"),
        "active": data.get("active", True),
        "notes": data.get("notes") or "",
    }
    if supply_id is not None:
        current = get(session, Supply, supply_id)
        require(current.group_id == group_id, "Ese sabor es de otro grupo")
        if current.id == group.default_supply_id:  # el predeterminado no se renombra ni se desactiva
            payload.update(variant_name=DEFAULT_VARIANT, name=DEFAULT_VARIANT, variant_code="", active=True)
    require(payload["variant_name"], "Escriba el nombre del sabor")
    if data.get("pres_cost") is not None:
        payload["avg_cost"] = float(data["pres_cost"]) / q
    if supply_id is None:
        payload["initial_stock"] = float(data.get("initial") or 0) * q
    supply = save_supply(session, payload, supply_id, actor)
    if supply_id is None:
        audit(session, actor, "crear_sabor", "supply", supply.id, supply.name)
    return supply


@dataclass
class FlavorStat:
    supply: Supply
    stock_pres: float        # existencia en bolsas
    min_pres: float
    sold_pres: float         # bolsas gastadas en ventas del periodo
    cups: float              # vasos vendidos en el periodo
    per_week: float          # bolsas por semana
    days_left: float | None  # días que alcanza la existencia al ritmo actual (None = sin ventas)
    suggested: int           # bolsas a pedir
    pres_cost: float         # costo de una bolsa
    is_default: bool

    @property
    def status(self) -> str:
        if self.is_default:
            return "sin_sabor" if abs(self.stock_pres) > 0.0001 else "ok"
        if self.stock_pres <= 0.0001:
            return "agotado"
        if self.min_pres and self.stock_pres <= self.min_pres:
            return "bajo"
        return "ok"

    @property
    def status_label(self) -> str:
        if self.status == "sin_sabor":
            return "Repartir en sabores" if self.stock_pres > 0 else "Vendido sin sabor"
        return {"ok": "OK", "bajo": "Bajo", "agotado": "Agotado"}[self.status]


def flavor_stats(session: Session, group: SupplyGroup, days: int = 30, cover_weeks: float = 2) -> list[FlavorStat]:
    """Existencia, ritmo de venta y pedido sugerido de cada sabor de un grupo.

    Pedido sugerido = lo necesario para cubrir `cover_weeks` semanas al ritmo de los últimos
    `days` días (y como mínimo el mínimo configurado), menos lo que hay.
    """
    members = list_variants(session, group.id)
    if not members:
        return []
    ids = [m.id for m in members]
    start = local_now() - timedelta(days=days)
    sold = {
        sid: float(q or 0) for sid, q in session.execute(
            select(StockMovement.supply_id, func.sum(StockMovement.quantity)).where(
                StockMovement.deleted.is_(False), StockMovement.ref_type == "venta",
                StockMovement.at >= start, StockMovement.supply_id.in_(ids)).group_by(StockMovement.supply_id))
    }
    cups = {
        sid: float(q or 0) for sid, q in session.execute(
            select(SaleItemModifier.supply_id, func.sum(SaleItemModifier.quantity))
            .join(SaleItem, SaleItem.id == SaleItemModifier.sale_item_id)
            .join(Sale, Sale.id == SaleItem.sale_id)
            .where(SaleItemModifier.deleted.is_(False), SaleItem.deleted.is_(False), Sale.deleted.is_(False),
                   Sale.status == SaleStatus.CLOSED, Sale.closed_at >= start, SaleItemModifier.supply_id.in_(ids))
            .group_by(SaleItemModifier.supply_id))
    }
    stocks = stock_map(session)
    pq = group.presentation_qty or 1
    out = []
    for m in members:
        stock_pres = stocks.get(m.id, 0.0) / pq
        sold_pres = max(0.0, -sold.get(m.id, 0.0)) / pq
        per_day = sold_pres / days if days else 0.0
        is_default = m.id == group.default_supply_id
        min_pres = (m.min_stock or 0) / pq
        days_left = max(0.0, stock_pres) / per_day if per_day > 0 and not is_default else None
        target = max(cover_weeks * per_day * 7, min_pres)
        suggested = 0 if is_default else int(math.ceil(max(0.0, target - max(stock_pres, 0.0)) - 1e-9))
        if not is_default and min_pres and stock_pres <= min_pres + 1e-9:
            suggested = max(suggested, 1)  # en el mínimo o debajo (alerta «Bajo»): siempre pedir algo
        out.append(FlavorStat(m, stock_pres, min_pres, sold_pres, cups.get(m.id, 0.0), per_day * 7, days_left,
                              suggested, (m.avg_cost or 0) * pq, is_default))
    return out


def reassign_unspecified(session: Session, group_id: str, amounts: dict[str, float], actor: Actor) -> float:
    """Pasa bolsas de «Sin especificar» a sabores (p. ej. la existencia que venía de antes de
    manejar sabores). No es merma: sale de uno y entra al otro al mismo costo.
    `amounts` = {sabor: bolsas}. Devuelve las bolsas reasignadas."""
    group = get(session, SupplyGroup, group_id)
    default = get(session, Supply, group.default_supply_id)
    pq = group.presentation_qty or 1
    available = stock_of(session, default.id) / pq
    total = sum(v for v in amounts.values() if v > 0)
    require(total > 0, "Escriba cuántas bolsas pasan a cada sabor")
    require(total <= available + 1e-6,
            f"Solo hay {fmt_number(available, 2)} {group.presentation_name} sin sabor; escribió {fmt_number(total, 2)}")
    cost = default.avg_cost or 0
    for sid, bags in amounts.items():
        if bags <= 0:
            continue
        target = get(session, Supply, sid)
        require(target.group_id == group_id and target.id != default.id, "Sabor no válido")
        qty = bags * pq
        add_movement(session, default.id, -qty, MovementKind.ADJUST, cost, "reasignar", None,
                     f"Reasignado a {target.variant_name}", actor)
        add_movement(session, target.id, qty, MovementKind.ADJUST, cost, "reasignar", None,
                     f"Viene de «{DEFAULT_VARIANT}»", actor)
    audit(session, actor, "reasignar_sabores", "supply_group", group.id,
          ", ".join(f"{fmt_number(v, 2)} {session.get(Supply, k).variant_name}" for k, v in amounts.items() if v > 0))
    return total


def order_text(group: SupplyGroup, stats: list[FlavorStat], business: str = "") -> str:
    """Pedido sugerido listo para pegar en WhatsApp al proveedor."""
    pres = group.presentation_name or "unidad"

    def plural(n: float) -> str:
        return pres if n == 1 else pres + ("es" if pres[-1:] in "lnrd" else "s")

    head = f"Pedido{' ' + business if business else ''} ({local_now():%d/%m/%Y}) · {group.name}"
    lines = [f"• {s.suggested} {plural(s.suggested)} {s.supply.variant_name}" for s in stats if s.suggested > 0]
    if not lines:
        return head + "\nNada por pedir según las ventas recientes."
    total = sum(s.suggested for s in stats)
    return "\n".join([head, *lines, f"Total: {fmt_number(total)} {plural(total)}"])
