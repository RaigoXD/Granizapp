"""Ventas: carrito, cobro (contado, mixto o fiado), cuentas abiertas y anulaciones."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from granizapp.core.models import (
    Customer,
    MoneyKind,
    MovementKind,
    Payment,
    PaymentKind,
    PaymentMethod,
    Product,
    Sale,
    SaleItem,
    SaleItemModifier,
    SaleStatus,
    SupplyGroup,
    local_now,
)
from granizapp.core.services import finance, inventory
from granizapp.core.services.catalog import RecipeBook
from granizapp.core.services.common import Actor, ServiceError, alive, audit, get, require
from granizapp.core.services.settings import get_setting
from granizapp.core.utils import fmt_money

DEFAULT_FLAVOR_NAME = "Sin especificar"


# --- carrito (vive en memoria en la pantalla de caja) ---------------------------------
@dataclass
class CartModifier:
    option_id: str | None
    name: str
    price: int = 0


@dataclass
class CartFlavor:
    """Un sabor elegido para un insumo con sabores (p. ej. Nueva York de la mezcla con licor).

    Cada elección es una parte igual de la línea: una promo x2 con Tijuana y Nueva York
    tiene dos elecciones y gasta media mezcla de cada sabor.
    """

    group_id: str
    supply_id: str
    name: str
    is_default: bool = False  # «Sin especificar»


@dataclass
class CartLine:
    product_id: str | None
    name: str
    unit_price: int
    quantity: float = 1
    modifiers: list[CartModifier] = field(default_factory=list)
    discount: int = 0
    notes: str = ""
    flavors: list[CartFlavor] = field(default_factory=list)

    @property
    def choices(self) -> dict[str, dict[str, float]]:
        """{grupo: {sabor: elecciones}} para la receta (RecipeBook normaliza las proporciones)."""
        out: dict[str, dict[str, float]] = {}
        for f in self.flavors:
            group = out.setdefault(f.group_id, {})
            group[f.supply_id] = group.get(f.supply_id, 0) + 1
        return out

    @property
    def flavor_text(self) -> str:
        """«Tijuana», «2× Tijuana», «Tijuana + Nueva York» (sin mostrar «Sin especificar»)."""
        counts: dict[str, int] = {}
        for f in self.flavors:
            if not f.is_default:
                counts[f.name] = counts.get(f.name, 0) + 1
        return " + ".join(name if n == 1 else f"{n}× {name}" for name, n in counts.items())

    @property
    def modifiers_price(self) -> int:
        return sum(m.price for m in self.modifiers)

    @property
    def total(self) -> int:
        return int(round(self.quantity * (self.unit_price + self.modifiers_price))) - int(self.discount or 0)

    @property
    def description(self) -> str:
        text = self.name
        if self.flavor_text:
            text += f" · {self.flavor_text}"
        if self.modifiers:
            text += " + " + ", ".join(m.name for m in self.modifiers)
        return text

    def same_as(self, other: "CartLine") -> bool:
        return (
            self.product_id == other.product_id
            and self.unit_price == other.unit_price
            and sorted((m.option_id or m.name) for m in self.modifiers)
            == sorted((m.option_id or m.name) for m in other.modifiers)
            and sorted(f.supply_id for f in self.flavors) == sorted(f.supply_id for f in other.flavors)
            and not self.notes and not other.notes and not self.discount and not other.discount
        )


@dataclass
class Cart:
    lines: list[CartLine] = field(default_factory=list)
    discount: int = 0
    label: str = ""
    customer_id: str | None = None
    sale_id: str | None = None  # si viene de una cuenta abierta
    notes: str = ""

    @property
    def subtotal(self) -> int:
        return sum(line.total for line in self.lines)

    @property
    def total(self) -> int:
        return max(0, self.subtotal - int(self.discount or 0))

    @property
    def item_count(self) -> float:
        return sum(line.quantity for line in self.lines)

    def add(self, line: CartLine, merge: bool = True) -> CartLine:
        if merge:
            for existing in self.lines:
                if existing.same_as(line):
                    existing.quantity += line.quantity
                    return existing
        self.lines.append(line)
        return line

    def is_empty(self) -> bool:
        return not self.lines


@dataclass
class PaymentInput:
    method_id: str
    amount: int
    received: int = 0  # efectivo entregado por el cliente


def line_from_product(product: Product, quantity: float = 1) -> CartLine:
    return CartLine(product_id=product.id, name=product.name, unit_price=product.price, quantity=quantity)


# --- consecutivos -----------------------------------------------------------------------
def next_number(session: Session, device_id: str) -> int:
    current = session.scalar(select(func.max(Sale.number)).where(Sale.device_id == device_id))
    return int(current or 0) + 1


def sale_code(sale: Sale) -> str:
    return f"{sale.device_id}-{sale.number:05d}" if sale.device_id else f"{sale.number:05d}"


# --- escritura de la venta ---------------------------------------------------------------
def _write_items(session: Session, sale: Sale, cart: Cart, book: RecipeBook | None) -> tuple[list[tuple[SaleItem, CartLine]], float]:
    for old in session.scalars(alive(SaleItem).where(SaleItem.sale_id == sale.id)):
        old.deleted = True
        for mod in session.scalars(alive(SaleItemModifier).where(SaleItemModifier.sale_item_id == old.id)):
            mod.deleted = True
    written = []
    cost_total = 0.0
    for i, line in enumerate(cart.lines):
        require(line.quantity > 0, f"Cantidad inválida para {line.name}")
        require(line.total >= 0, f"El descuento de «{line.name}» es mayor que su valor")
        unit_cost = 0.0
        mod_costs = []
        if book is not None:
            if line.product_id:
                unit_cost += book.product_cost(line.product_id, line.choices)
            for mod in line.modifiers:
                c = book.option_cost(mod.option_id, line.choices) if mod.option_id else 0.0
                mod_costs.append(c)
                unit_cost += c
        else:
            mod_costs = [0.0] * len(line.modifiers)
        item = SaleItem(
            sale_id=sale.id,
            product_id=line.product_id,
            name=line.description[:160],
            quantity=line.quantity,
            unit_price=line.unit_price,
            modifiers_price=line.modifiers_price,
            discount=int(line.discount or 0),
            total=line.total,
            unit_cost=unit_cost,
            notes=line.notes,
            sort_order=i,
        )
        session.add(item)
        session.flush()
        for mod, cost in zip(line.modifiers, mod_costs):
            session.add(
                SaleItemModifier(
                    sale_item_id=item.id, option_id=mod.option_id, name=mod.name, price_delta=mod.price, unit_cost=cost
                )
            )
        _write_flavors(session, item, line, book)
        cost_total += unit_cost * line.quantity
        written.append((item, line))
    return written, cost_total


def _write_flavors(session: Session, item: SaleItem, line: CartLine, book: RecipeBook | None) -> None:
    """Una fila por sabor elegido, con los vasos que le tocan. Al cobrar, lo que se vendió sin
    sabor queda registrado como «Sin especificar» (para los reportes por sabor)."""
    units = book.group_units(line.product_id) if (book is not None and line.product_id) else {}
    picks = list(line.flavors)
    if book is not None:
        for gid in units:
            default = book.default_of(gid)
            if default and not any(f.group_id == gid for f in picks):
                picks.append(CartFlavor(gid, default, book.supplies[default].variant_name or DEFAULT_FLAVOR_NAME, True))
    per_group = Counter(f.group_id for f in picks)
    for f in picks:
        cups = units.get(f.group_id, 0) * line.quantity / per_group[f.group_id]
        session.add(SaleItemModifier(sale_item_id=item.id, supply_id=f.supply_id, supply_group_id=f.group_id,
                                     name=f.name[:120], price_delta=0, unit_cost=0.0, quantity=cups))


def save_open_tab(session: Session, cart: Cart, actor: Actor, label: str) -> Sale:
    """Guarda (o actualiza) una cuenta abierta: mesa o cliente que sigue pidiendo."""
    require(cart.lines, "La cuenta está vacía")
    label = (label or cart.label or "").strip()
    require(label, "Escriba un nombre para la cuenta (mesa o cliente)")
    if cart.sale_id:
        sale = get(session, Sale, cart.sale_id)
        require(sale.status == SaleStatus.OPEN, "Esa cuenta ya fue cerrada")
    else:
        sale = Sale(
            number=next_number(session, actor.device_id),
            device_id=actor.device_id,
            opened_at=local_now(),
            status=SaleStatus.OPEN,
            user_id=actor.user_id,
        )
        session.add(sale)
        session.flush()
    sale.label = label
    sale.customer_id = cart.customer_id
    sale.notes = cart.notes
    sale.discount = int(cart.discount or 0)
    _write_items(session, sale, cart, None)
    sale.subtotal = cart.subtotal
    sale.total = cart.total
    cart.sale_id = sale.id
    cart.label = label
    return sale


def list_open_tabs(session: Session, device_id: str | None = None) -> list[Sale]:
    stmt = alive(Sale).where(Sale.status == SaleStatus.OPEN).order_by(Sale.opened_at)
    if device_id:
        stmt = stmt.where(Sale.device_id == device_id)
    return list(session.scalars(stmt))


def load_cart(session: Session, sale_id: str) -> Cart:
    sale = get(session, Sale, sale_id)
    cart = Cart(discount=sale.discount, label=sale.label, customer_id=sale.customer_id, sale_id=sale.id, notes=sale.notes)
    items = session.scalars(alive(SaleItem).where(SaleItem.sale_id == sale.id).order_by(SaleItem.sort_order))
    for item in items:
        mods = session.scalars(alive(SaleItemModifier).where(SaleItemModifier.sale_item_id == item.id)).all()
        product = session.get(Product, item.product_id) if item.product_id else None
        base_name = product.name if product is not None else item.name.split(" · ")[0].split(" + ")[0]
        flavors = []
        for m in mods:
            if m.supply_id:
                group = session.get(SupplyGroup, m.supply_group_id) if m.supply_group_id else None
                flavors.append(CartFlavor(m.supply_group_id or "", m.supply_id, m.name,
                                          is_default=group is not None and group.default_supply_id == m.supply_id))
        cart.lines.append(
            CartLine(
                product_id=item.product_id,
                name=base_name,
                unit_price=item.unit_price,
                quantity=item.quantity,
                modifiers=[CartModifier(m.option_id, m.name, m.price_delta) for m in mods if not m.supply_id],
                discount=item.discount,
                notes=item.notes,
                flavors=flavors,
            )
        )
    return cart


def discard_open_tab(session: Session, sale_id: str, actor: Actor, reason: str = "") -> None:
    sale = get(session, Sale, sale_id)
    require(sale.status == SaleStatus.OPEN, "Solo se pueden descartar cuentas abiertas")
    sale.status = SaleStatus.VOID
    sale.void_reason = reason or "Cuenta abierta descartada"
    sale.closed_at = local_now()
    audit(session, actor, "descartar_cuenta", "sale", sale.id, f"{sale.label} {fmt_money(sale.total)}")


def checkout(
    session: Session,
    cart: Cart,
    payments: list[PaymentInput],
    actor: Actor,
    cash_session_id: str | None,
    customer_id: str | None = None,
    allow_over_limit: bool = False,
    at: datetime | None = None,
    origin: str = "pos",
) -> Sale:
    """Cierra la venta: guarda ítems, descuenta inventario y registra los pagos.

    Si lo pagado es menor al total, el saldo queda fiado al cliente indicado.
    """
    require(cart.lines, "No hay productos en la venta")
    total = cart.total
    payments = [p for p in payments if p.amount]
    for p in payments:
        require(p.amount > 0, "Los pagos deben ser positivos")
    paid = sum(p.amount for p in payments)
    require(paid <= total, f"Los pagos ({fmt_money(paid)}) superan el total ({fmt_money(total)})")
    customer_id = customer_id or cart.customer_id
    balance = total - paid
    if balance > 0:
        require(customer_id, "Para dejar saldo pendiente (fiado) seleccione el cliente")
        customer = get(session, Customer, customer_id)
        if customer.credit_limit and not allow_over_limit:
            from granizapp.core.services.customers import customer_balance

            owed = customer_balance(session, customer_id)
            if owed + balance > customer.credit_limit:
                raise ServiceError(
                    f"{customer.name} superaría su cupo de fiado ({fmt_money(customer.credit_limit)}). "
                    f"Debe {fmt_money(owed)}."
                )
    methods = {m.id: m for m in session.scalars(alive(PaymentMethod))}
    for p in payments:
        require(p.method_id in methods, "Medio de pago no válido")

    now = at or local_now()
    if cart.sale_id:
        sale = get(session, Sale, cart.sale_id)
        require(sale.status == SaleStatus.OPEN, "Esta cuenta ya fue cerrada")
    else:
        sale = Sale(number=next_number(session, actor.device_id), device_id=actor.device_id, opened_at=now)
        session.add(sale)
        session.flush()

    book = RecipeBook(session)
    if get_setting(session, "require_flavor"):
        for line in cart.lines:
            for gid in (book.asks_flavor(line.product_id) if line.product_id else []):
                if not any(f.group_id == gid and not f.is_default for f in line.flavors):
                    raise ServiceError(f"Falta el sabor de «{line.name}» ({book.groups[gid].name}). "
                                       "Selecciónelo con F7.")
    written, cost_total = _write_items(session, sale, cart, book)
    sale.closed_at = now
    sale.status = SaleStatus.CLOSED
    sale.label = cart.label
    sale.customer_id = customer_id
    sale.cash_session_id = cash_session_id
    sale.user_id = actor.user_id
    sale.subtotal = cart.subtotal
    sale.discount = int(cart.discount or 0)
    sale.total = total
    sale.paid = paid
    sale.cost_total = cost_total
    sale.is_credit = balance > 0
    sale.notes = cart.notes
    sale.origin = origin

    # inventario
    for item, line in written:
        consumption: dict[str, float] = {}
        if line.product_id:
            consumption = dict(book.expand_product(line.product_id, line.quantity, line.choices))
        for mod in line.modifiers:
            if mod.option_id:
                for sid, q in book.expand_option(mod.option_id, line.quantity, line.choices).items():
                    consumption[sid] = consumption.get(sid, 0.0) + q
        inventory.consume(
            session, consumption, MovementKind.SALE, "venta", sale.id,
            f"Venta {sale_code(sale)}: {line.description}"[:250], actor, now, book.supplies,
        )

    discounts = int(cart.discount or 0) + sum(int(ln.discount or 0) for ln in cart.lines)
    if discounts:
        audit(session, actor, "descuento", "sale", sale.id,
              f"Venta {sale_code(sale)}: descuento {fmt_money(discounts)} sobre {fmt_money(cart.subtotal + int(cart.discount or 0))}")

    # dinero
    for p in payments:
        method = methods[p.method_id]
        pay = Payment(
            at=now,
            kind=PaymentKind.SALE,
            sale_id=sale.id,
            customer_id=customer_id,
            method_id=p.method_id,
            amount=p.amount,
            received=max(p.received, p.amount) if method.is_cash else p.amount,
            cash_session_id=cash_session_id,
            user_id=actor.user_id,
        )
        session.add(pay)
        account_id = finance.payment_account(session, method, cash_session_id)
        if account_id:
            finance.money_movement(
                session, account_id, p.amount, MoneyKind.SALE, f"Venta {sale_code(sale)}",
                actor, "venta", sale.id, cash_session_id=cash_session_id if method.is_cash else None, at=now,
            )
    session.flush()
    return sale


def void_sale(session: Session, sale_id: str, actor: Actor, reason: str) -> Sale:
    sale = get(session, Sale, sale_id)
    require(sale.status != SaleStatus.VOID, "La venta ya está anulada")
    require(reason and reason.strip(), "Escriba el motivo de la anulación")
    if sale.status == SaleStatus.OPEN:
        discard_open_tab(session, sale_id, actor, reason)
        return sale
    inventory.reverse_movements(session, sale.id, MovementKind.VOID, f"Anulación venta {sale_code(sale)}", actor)
    code = sale_code(sale)
    for pay in session.scalars(alive(Payment).where(Payment.sale_id == sale.id, Payment.voided.is_(False))):
        pay.voided = True
        if pay.kind == PaymentKind.ABONO:
            # los abonos tienen su propio asiento: también se devuelven
            finance.reverse_money(session, pay.id, f"Devolución de abono por anulación {code}", actor)
    finance.reverse_money(session, sale.id, f"Anulación venta {code}", actor)
    sale.status = SaleStatus.VOID
    sale.void_reason = reason.strip()
    sale.paid = 0
    audit(session, actor, "anular_venta", "sale", sale.id, f"{sale_code(sale)} {fmt_money(sale.total)}: {reason}")
    return sale


# --- consultas -----------------------------------------------------------------------------
def list_sales(
    session: Session,
    start: datetime | None = None,
    end: datetime | None = None,
    status: str | None = None,
    customer_id: str | None = None,
    include_open: bool = False,
    limit: int = 20000,
) -> list[Sale]:
    stmt = alive(Sale).order_by(Sale.closed_at.desc(), Sale.number.desc())
    if not include_open:
        stmt = stmt.where(Sale.status != SaleStatus.OPEN)
    if start:
        stmt = stmt.where(Sale.closed_at >= start)
    if end:
        stmt = stmt.where(Sale.closed_at < end)
    if status:
        stmt = stmt.where(Sale.status == status)
    if customer_id:
        stmt = stmt.where(Sale.customer_id == customer_id)
    return list(session.scalars(stmt.limit(limit)))


def sale_items(session: Session, sale_id: str) -> list[SaleItem]:
    return list(session.scalars(alive(SaleItem).where(SaleItem.sale_id == sale_id).order_by(SaleItem.sort_order)))


def sale_payments(session: Session, sale_id: str) -> list[Payment]:
    return list(session.scalars(alive(Payment).where(Payment.sale_id == sale_id).order_by(Payment.at)))


def payment_methods(session: Session, include_inactive: bool = False) -> list[PaymentMethod]:
    stmt = alive(PaymentMethod).order_by(PaymentMethod.sort_order, PaymentMethod.name)
    if not include_inactive:
        stmt = stmt.where(PaymentMethod.active.is_(True))
    return list(session.scalars(stmt))


def save_payment_method(session: Session, data: dict, method_id: str | None = None) -> PaymentMethod:
    name = (data.get("name") or "").strip()
    require(name, "El nombre es obligatorio")
    require(data.get("account_id"), "Seleccione la cuenta a la que llega el dinero")
    m = get(session, PaymentMethod, method_id) if method_id else PaymentMethod()
    m.name = name
    m.account_id = data["account_id"]
    m.is_cash = bool(data.get("is_cash", False))
    m.sort_order = int(data.get("sort_order") or 0)
    m.active = bool(data.get("active", True))
    if method_id is None:
        session.add(m)
    session.flush()
    require(payment_methods(session), "Debe quedar al menos un medio de pago activo")
    return m
