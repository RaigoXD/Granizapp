"""Catálogo de productos, modificadores (adiciones) y recetas."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from granizapp.core.models import (
    ModifierGroup,
    ModifierOption,
    Product,
    ProductCategory,
    ProductKind,
    ProductModifierGroup,
    RecipeLine,
    Supply,
    SupplyGroup,
)
from granizapp.core.services.common import Actor, ServiceError, alive, audit, get, require, soft_delete
from granizapp.core.utils import fmt_money, normalize

MAX_RECIPE_DEPTH = 5

# Sabores elegidos en una línea de venta: {grupo_id: {insumo_id: proporción}}.
# Un vaso de Tijuana = {g: {tij: 1}}; una promo x2 Tijuana + Nueva York = {g: {tij: .5, ny: .5}}.
Choices = dict[str, dict[str, float]]


# --- categorías -------------------------------------------------------------------
def list_categories(session: Session, include_inactive: bool = False) -> list[ProductCategory]:
    stmt = alive(ProductCategory).order_by(ProductCategory.sort_order, ProductCategory.name)
    if not include_inactive:
        stmt = stmt.where(ProductCategory.active.is_(True))
    return list(session.scalars(stmt))


def category_paths(categories: list[ProductCategory]) -> dict[str, str]:
    """{id: "Granizados › Con licor"}"""
    by_id = {c.id: c for c in categories}
    out = {}
    for c in categories:
        parts, cur, guard = [], c, 0
        while cur is not None and guard < 10:
            parts.append(cur.name)
            cur = by_id.get(cur.parent_id) if cur.parent_id else None
            guard += 1
        out[c.id] = " › ".join(reversed(parts))
    return out


def root_category_of(categories: list[ProductCategory], cat_id: str | None) -> str | None:
    by_id = {c.id: c for c in categories}
    cur = by_id.get(cat_id)
    guard = 0
    while cur is not None and cur.parent_id and guard < 10:
        cur = by_id.get(cur.parent_id)
        guard += 1
    return cur.id if cur else None


def save_category(session: Session, data: dict, cat_id: str | None = None) -> ProductCategory:
    name = (data.get("name") or "").strip()
    require(name, "El nombre de la categoría es obligatorio")
    cat = get(session, ProductCategory, cat_id) if cat_id else ProductCategory()
    parent_id = data.get("parent_id") or None
    if cat_id:
        _check_no_cycle(session, ProductCategory, cat_id, parent_id)
    cat.name = name
    cat.parent_id = parent_id
    cat.color = data.get("color") or cat.color or "#5B8DEF"
    cat.sort_order = int(data.get("sort_order") or 0)
    cat.active = bool(data.get("active", True))
    if cat_id is None:
        session.add(cat)
    session.flush()
    return cat


def delete_category(session: Session, cat_id: str) -> None:
    cat = get(session, ProductCategory, cat_id)
    in_use = session.scalars(alive(Product).where(Product.category_id == cat_id)).first()
    require(in_use is None, "La categoría tiene productos. Muévalos a otra categoría antes de borrarla.")
    children = session.scalars(alive(ProductCategory).where(ProductCategory.parent_id == cat_id)).first()
    require(children is None, "La categoría tiene subcategorías.")
    soft_delete(session, cat)


# --- productos ----------------------------------------------------------------------
def list_products(
    session: Session, include_inactive: bool = False, category_id: str | None = None
) -> list[Product]:
    stmt = alive(Product).order_by(Product.sort_order, Product.name)
    if not include_inactive:
        stmt = stmt.where(Product.active.is_(True))
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    return list(session.scalars(stmt))


PRODUCT_FIELDS = {
    "name", "code", "category_id", "kind", "price", "size_label", "volume_ml", "is_alcoholic",
    "manual_cost", "track_inventory", "favorite", "active", "sort_order", "available_days", "notes",
}


def save_product(session: Session, data: dict, product_id: str | None = None, actor: Actor | None = None) -> Product:
    name = (data.get("name") or "").strip()
    require(name, "El nombre del producto es obligatorio")
    require(int(data.get("price") or 0) >= 0, "El precio no puede ser negativo")
    code = (data.get("code") or "").strip().upper()
    if code:
        dup = session.scalars(alive(Product).where(Product.code == code, Product.active.is_(True))).first()
        require(dup is None or dup.id == product_id, f"El código {code} ya lo usa '{dup.name if dup else ''}'")
    product = get(session, Product, product_id) if product_id else Product()
    old_price = product.price if product_id else None
    for key in PRODUCT_FIELDS:
        if key in data:
            setattr(product, key, data[key])
    product.name = name
    product.code = code
    product.category_id = data.get("category_id") or None
    product.available_days = data.get("available_days") or "0123456"
    product.price = int(product.price or 0)
    product.manual_cost = int(product.manual_cost or 0)
    product.sort_order = int(product.sort_order or 0)
    product.volume_ml = float(product.volume_ml) if product.volume_ml else None
    product.kind = product.kind or ProductKind.PREPARED
    if product_id is None:
        session.add(product)
    session.flush()
    if product_id is None:
        audit(session, actor, "crear_producto", "product", product.id, f"{product.name}: {fmt_money(product.price)}")
    elif old_price != product.price:
        audit(session, actor, "cambiar_precio", "product", product.id,
              f"{product.name}: {fmt_money(old_price)} → {fmt_money(product.price)}")
    return product


def delete_product(session: Session, product_id: str, actor: Actor | None = None) -> None:
    product = get(session, Product, product_id)
    parents = set()
    for ln in session.scalars(alive(RecipeLine).where(RecipeLine.sub_product_id == product_id)):
        parent = session.get(Product, ln.product_id) if ln.product_id else None
        if parent is not None and not parent.deleted:
            parents.add(parent.name)
    if parents:
        raise ServiceError(f"«{product.name}» hace parte de: {', '.join(sorted(parents))}. "
                           "Quítelo de esas recetas antes de eliminarlo (o desactívelo).")
    soft_delete(session, product)
    for ln in session.scalars(alive(RecipeLine).where(RecipeLine.product_id == product_id)):
        ln.deleted = True  # su receta se va con él
    audit(session, actor, "eliminar_producto", "product", product.id, product.name)


def _check_no_cycle(session: Session, model, cat_id: str | None, parent_id: str | None) -> None:
    """Una categoría no puede quedar dentro de sí misma (ni por intermedio de otras)."""
    seen = set()
    cur = parent_id
    while cur and cur not in seen:
        require(cur != cat_id, "Una categoría no puede quedar dentro de sí misma")
        seen.add(cur)
        parent = session.get(model, cur)
        cur = parent.parent_id if parent is not None else None


def find_product(session: Session, query: str, products: list[Product] | None = None) -> list[Product]:
    """Busca por código exacto primero; luego por palabras en el nombre."""
    products = products if products is not None else list_products(session)
    q = query.strip()
    if not q:
        return products
    exact = [p for p in products if p.code and p.code == q.upper()]
    if exact:
        return exact
    nq = normalize(q)
    words = nq.split()
    out = []
    for p in products:
        hay = normalize(f"{p.name} {p.code} {p.size_label}")
        if all(w in hay for w in words):
            out.append(p)
    out.sort(key=lambda p: (not normalize(p.code).startswith(nq), not normalize(p.name).startswith(nq), p.name))
    return out


def is_available_today(product: Product, weekday: int) -> bool:
    return str(weekday) in (product.available_days or "0123456")


# --- modificadores -----------------------------------------------------------------
def list_groups(session: Session, include_inactive: bool = False) -> list[ModifierGroup]:
    stmt = alive(ModifierGroup).order_by(ModifierGroup.sort_order, ModifierGroup.name)
    if not include_inactive:
        stmt = stmt.where(ModifierGroup.active.is_(True))
    return list(session.scalars(stmt))


def save_group(session: Session, data: dict, group_id: str | None = None) -> ModifierGroup:
    name = (data.get("name") or "").strip()
    require(name, "El nombre del grupo es obligatorio")
    group = get(session, ModifierGroup, group_id) if group_id else ModifierGroup()
    group.name = name
    group.min_select = int(data.get("min_select") or 0)
    group.max_select = int(data.get("max_select") or 0)
    group.ask_on_add = bool(data.get("ask_on_add", False))
    group.sort_order = int(data.get("sort_order") or 0)
    group.active = bool(data.get("active", True))
    if group_id is None:
        session.add(group)
    session.flush()
    return group


def delete_group(session: Session, group_id: str) -> None:
    soft_delete(session, get(session, ModifierGroup, group_id))
    for link in session.scalars(alive(ProductModifierGroup).where(ProductModifierGroup.group_id == group_id)):
        link.deleted = True


def list_options(session: Session, group_id: str | None = None, include_inactive: bool = False) -> list[ModifierOption]:
    stmt = alive(ModifierOption).order_by(ModifierOption.sort_order, ModifierOption.name)
    if group_id:
        stmt = stmt.where(ModifierOption.group_id == group_id)
    if not include_inactive:
        stmt = stmt.where(ModifierOption.active.is_(True))
    return list(session.scalars(stmt))


def save_option(session: Session, data: dict, option_id: str | None = None) -> ModifierOption:
    name = (data.get("name") or "").strip()
    require(name, "El nombre de la opción es obligatorio")
    require(data.get("group_id") or option_id, "Falta el grupo")
    opt = get(session, ModifierOption, option_id) if option_id else ModifierOption(group_id=data["group_id"])
    opt.name = name
    opt.price_delta = int(data.get("price_delta") or 0)
    opt.sort_order = int(data.get("sort_order") or 0)
    opt.active = bool(data.get("active", True))
    if option_id is None:
        session.add(opt)
    session.flush()
    return opt


def delete_option(session: Session, option_id: str) -> None:
    soft_delete(session, get(session, ModifierOption, option_id))


def product_group_ids(session: Session, product_id: str) -> list[str]:
    links = session.scalars(
        alive(ProductModifierGroup)
        .where(ProductModifierGroup.product_id == product_id)
        .order_by(ProductModifierGroup.sort_order)
    )
    return [link.group_id for link in links]


def set_product_groups(session: Session, product_id: str, group_ids: list[str]) -> None:
    current = {
        link.group_id: link
        for link in session.scalars(alive(ProductModifierGroup).where(ProductModifierGroup.product_id == product_id))
    }
    for i, gid in enumerate(group_ids):
        if gid in current:
            current.pop(gid).sort_order = i
        else:
            session.add(ProductModifierGroup(product_id=product_id, group_id=gid, sort_order=i))
    for link in current.values():
        link.deleted = True


def groups_for_product(session: Session, product_id: str) -> list[tuple[ModifierGroup, list[ModifierOption]]]:
    out = []
    groups = {g.id: g for g in list_groups(session)}
    for gid in product_group_ids(session, product_id):
        group = groups.get(gid)
        if group:
            out.append((group, list_options(session, gid)))
    return out


# --- recetas -------------------------------------------------------------------------
def recipe_lines(session: Session, product_id: str | None = None, option_id: str | None = None) -> list[RecipeLine]:
    stmt = alive(RecipeLine)
    if product_id:
        stmt = stmt.where(RecipeLine.product_id == product_id)
    elif option_id:
        stmt = stmt.where(RecipeLine.modifier_option_id == option_id)
    else:
        return []
    return list(session.scalars(stmt.order_by(RecipeLine.created_at)))


def set_recipe(
    session: Session, lines: list[dict], product_id: str | None = None, option_id: str | None = None
) -> None:
    """Reemplaza la receta completa. Cada línea: {supply_id | supply_group_id | sub_product_id, quantity, notes}."""
    require(product_id or option_id, "La receta debe pertenecer a un producto o a una adición")
    for line in lines:
        require(line.get("supply_id") or line.get("supply_group_id") or line.get("sub_product_id"),
                "Cada línea necesita un insumo, un insumo con sabores o un producto")
        require(float(line.get("quantity") or 0) > 0, "Las cantidades de la receta deben ser mayores a cero")
        if product_id and line.get("sub_product_id"):
            require(line["sub_product_id"] != product_id, "Un producto no puede contenerse a sí mismo")
    for old in recipe_lines(session, product_id, option_id):
        old.deleted = True
    for line in lines:
        session.add(
            RecipeLine(
                product_id=product_id,
                modifier_option_id=option_id,
                supply_id=line.get("supply_id") or None,
                supply_group_id=line.get("supply_group_id") or None,
                sub_product_id=line.get("sub_product_id") or None,
                quantity=float(line["quantity"]),
                notes=line.get("notes") or "",
            )
        )
    session.flush()
    if product_id:
        RecipeBook(session).expand_product(product_id)  # valida que no haya ciclos


class RecipeBook:
    """Carga todas las recetas una vez y calcula consumos y costos sin consultas repetidas.

    Las líneas de receta que apuntan a un insumo con sabores (`supply_group_id`) se resuelven
    con `choices` (el sabor elegido al vender). Sin elección van al sabor predeterminado
    («Sin especificar») y se costean con el promedio de los sabores del grupo.
    """

    def __init__(self, session: Session):
        self.supplies: dict[str, Supply] = {s.id: s for s in session.scalars(alive(Supply))}
        self.groups: dict[str, SupplyGroup] = {g.id: g for g in session.scalars(alive(SupplyGroup))}
        # sabores reales activos de cada grupo (sin el predeterminado), en orden alfabético
        self.variants: dict[str, list[Supply]] = defaultdict(list)
        for s in sorted(self.supplies.values(), key=lambda x: normalize(x.variant_name or x.name)):
            group = self.groups.get(s.group_id or "")
            if group is not None and s.active and s.id != group.default_supply_id:
                self.variants[group.id].append(s)
        self.products: dict[str, Product] = {p.id: p for p in session.scalars(alive(Product))}
        self.by_product: dict[str, list[RecipeLine]] = defaultdict(list)
        self.by_option: dict[str, list[RecipeLine]] = defaultdict(list)
        for line in session.scalars(alive(RecipeLine)):
            if line.product_id:
                self.by_product[line.product_id].append(line)
            elif line.modifier_option_id:
                self.by_option[line.modifier_option_id].append(line)

    # --- sabores ------------------------------------------------------------------------
    def default_of(self, group_id: str) -> str | None:
        """Insumo que recibe lo vendido sin sabor («Sin especificar»)."""
        group = self.groups.get(group_id)
        if group is not None and group.default_supply_id in self.supplies:
            return group.default_supply_id
        flavors = self.variants.get(group_id) or []
        return flavors[0].id if flavors else None

    def group_units(self, product_id: str, _depth: int = 0) -> dict[str, float]:
        """{grupo: vasos por unidad vendida}. Granizado CL 12 oz -> {mezcla CL: 1};
        Promo x2 12 oz (2 × CL 12 oz) -> {mezcla CL: 2}."""
        out: dict[str, float] = {}
        if _depth > MAX_RECIPE_DEPTH:
            return out
        for line in self.by_product.get(product_id, []):
            if line.supply_group_id and line.supply_group_id in self.groups:
                out[line.supply_group_id] = out.get(line.supply_group_id, 0) + 1
            elif line.sub_product_id:
                for gid, n in self.group_units(line.sub_product_id, _depth + 1).items():
                    out[gid] = out.get(gid, 0) + n * line.quantity
        return out

    def asks_flavor(self, product_id: str) -> list[str]:
        """Grupos de sabores que se deben preguntar al vender este producto."""
        return [gid for gid in self.group_units(product_id)
                if self.groups[gid].ask_on_sale and self.groups[gid].active and self.variants.get(gid)]

    def group_cost(self, group_id: str) -> float:
        """Costo de referencia por unidad base: promedio de los sabores con costo."""
        priced = [s.avg_cost for s in self.variants.get(group_id, []) if (s.avg_cost or 0) > 0]
        if priced:
            return sum(priced) / len(priced)
        default = self.supplies.get(self.default_of(group_id) or "")
        return float(default.avg_cost or 0) if default is not None else 0.0

    def _shares(self, line: RecipeLine, choices: Choices | None) -> list[tuple[str, float]]:
        """[(insumo, proporción)] que consume una línea de receta."""
        if line.supply_id:
            return [(line.supply_id, 1.0)]
        gid = line.supply_group_id
        if not gid:
            return []
        picked = (choices or {}).get(gid) or {}
        valid = [(sid, share) for sid, share in picked.items() if sid in self.supplies and share > 0]
        total = sum(share for _sid, share in valid)
        if total > 0:
            return [(sid, share / total) for sid, share in valid]
        default = self.default_of(gid)
        return [(default, 1.0)] if default else []

    # --- consumo de inventario -------------------------------------------------------------
    def expand_product(self, product_id: str, qty: float = 1.0, choices: Choices | None = None,
                       _depth: int = 0) -> dict[str, float]:
        if _depth > MAX_RECIPE_DEPTH:
            raise ServiceError("La receta tiene un ciclo (un combo se contiene a sí mismo)")
        out: dict[str, float] = defaultdict(float)
        product = self.products.get(product_id)
        if product is not None and not product.track_inventory and _depth == 0:
            return {}
        for line in self.by_product.get(product_id, []):
            self._add_line(out, line, qty, _depth, choices)
        return dict(out)

    def expand_option(self, option_id: str, qty: float = 1.0, choices: Choices | None = None) -> dict[str, float]:
        out: dict[str, float] = defaultdict(float)
        for line in self.by_option.get(option_id, []):
            self._add_line(out, line, qty, 0, choices)
        return dict(out)

    def _add_line(self, out: dict, line: RecipeLine, qty: float, depth: int, choices: Choices | None) -> None:
        if line.sub_product_id:
            for sid, q in self.expand_product(line.sub_product_id, line.quantity * qty, choices, depth + 1).items():
                out[sid] += q
            return
        for sid, share in self._shares(line, choices):
            out[sid] += line.quantity * qty * share

    # --- costos -------------------------------------------------------------------------------
    def product_cost(self, product_id: str, choices: Choices | None = None, _depth: int = 0) -> float:
        if _depth > MAX_RECIPE_DEPTH:
            return 0.0
        lines = self.by_product.get(product_id, [])
        product = self.products.get(product_id)
        if not lines:
            return float(product.manual_cost or 0) if product else 0.0
        return sum(self.line_cost(line, choices, _depth) for line in lines)

    def option_cost(self, option_id: str, choices: Choices | None = None) -> float:
        return sum(self.line_cost(line, choices) for line in self.by_option.get(option_id, []))

    def line_cost(self, line: RecipeLine, choices: Choices | None = None, _depth: int = 0) -> float:
        if line.sub_product_id:
            return line.quantity * self.product_cost(line.sub_product_id, choices, _depth + 1)
        if line.supply_group_id:
            default = self.default_of(line.supply_group_id)
            unit = 0.0
            for sid, share in self._shares(line, choices):
                # lo que va a «Sin especificar» se costea con el promedio de los sabores
                unit += share * (self.group_cost(line.supply_group_id) if sid == default
                                 else (self.supplies[sid].avg_cost or 0.0))
            return line.quantity * unit
        if line.supply_id:
            supply = self.supplies.get(line.supply_id)
            return line.quantity * (supply.avg_cost if supply else 0.0)
        return 0.0

    def has_recipe(self, product_id: str) -> bool:
        return bool(self.by_product.get(product_id))


def product_kind_label(kind: str) -> str:
    return ProductKind.LABELS.get(kind, kind)


def supplies_by_name(session: Session) -> dict[str, Supply]:
    return {normalize(s.name): s for s in session.scalars(select(Supply).where(Supply.deleted.is_(False)))}
