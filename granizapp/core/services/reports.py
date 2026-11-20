"""Reportes de ventas, rentabilidad y flujo de caja.

Dos formas de ver la ganancia, porque responden preguntas distintas:

* **Estado de resultados (por recetas)**: ventas − costo de lo vendido (según fichas
  técnicas) − mermas − gastos de operación. Dice si el negocio es rentable aunque las
  compras grandes de insumos caigan en otro mes.
* **Resultado de caja**: lo que entró menos todo lo que salió (incluidas compras e
  inversiones). Es la cuenta que se llevaba en el Excel ("Ganancias").
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from granizapp.core.models import (
    Expense,
    ExpenseCategory,
    ExpenseType,
    FinancialEntry,
    MoneyKind,
    MovementKind,
    Payment,
    PaymentKind,
    PaymentMethod,
    Product,
    ProductCategory,
    Purchase,
    PurchaseStatus,
    Sale,
    SaleItem,
    SaleItemModifier,
    SaleStatus,
    StockMovement,
    SupplierPayment,
    SupplyGroup,
)
from granizapp.core.services.catalog import category_paths, list_categories, root_category_of
from granizapp.core.services.common import alive
from granizapp.core.utils import MONTHS, month_bounds, period_range

LOSS_KINDS = {MovementKind.WASTE, MovementKind.COUNT, MovementKind.ADJUST, MovementKind.INTERNAL}


@dataclass
class Period:
    start: date
    end: date  # inclusivo
    label: str = ""

    @property
    def bounds(self) -> tuple[datetime, datetime]:
        return period_range(self.start, self.end)

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def preset_period(key: str, today: date | None = None) -> Period:
    today = today or date.today()
    if key == "hoy":
        return Period(today, today, "Hoy")
    if key == "ayer":
        d = today - timedelta(days=1)
        return Period(d, d, "Ayer")
    if key == "semana":
        start = today - timedelta(days=today.weekday())
        return Period(start, today, "Esta semana")
    if key == "7dias":
        return Period(today - timedelta(days=6), today, "Últimos 7 días")
    if key == "mes":
        return Period(today.replace(day=1), today, "Este mes")
    if key == "mes_anterior":
        last = today.replace(day=1) - timedelta(days=1)
        return Period(last.replace(day=1), last, "Mes anterior")
    if key == "30dias":
        return Period(today - timedelta(days=29), today, "Últimos 30 días")
    if key == "anio":
        return Period(date(today.year, 1, 1), today, "Este año")
    if key == "todo":
        return Period(date(2000, 1, 1), today, "Todo")
    raise ValueError(key)


PRESETS = [
    ("hoy", "Hoy"), ("ayer", "Ayer"), ("semana", "Esta semana"), ("7dias", "Últimos 7 días"),
    ("mes", "Este mes"), ("mes_anterior", "Mes anterior"), ("30dias", "Últimos 30 días"),
    ("anio", "Este año"), ("todo", "Todo"),
]


# --- datos base ------------------------------------------------------------------------
@dataclass
class Dataset:
    """Todo lo del periodo cargado una sola vez; los reportes agregan en memoria."""

    sales: list[Sale]
    items: list[SaleItem]
    modifiers: list[SaleItemModifier]
    payments: list[Payment]
    expenses: list[Expense]
    purchases: list[Purchase]
    supplier_payments: list[SupplierPayment]
    entries: list[FinancialEntry]
    losses: list[StockMovement]
    products: dict[str, Product]
    categories: list[ProductCategory]
    expense_categories: dict[str, ExpenseCategory]
    methods: dict[str, PaymentMethod]
    supply_groups: dict[str, SupplyGroup] = field(default_factory=dict)


def load(session: Session, period: Period) -> Dataset:
    start, end = period.bounds
    sales = list(session.scalars(alive(Sale).where(
        Sale.status == SaleStatus.CLOSED, Sale.closed_at >= start, Sale.closed_at < end)))
    sale_ids = [s.id for s in sales]
    items: list[SaleItem] = []
    mods: list[SaleItemModifier] = []
    for chunk in _chunks(sale_ids, 500):
        items.extend(session.scalars(alive(SaleItem).where(SaleItem.sale_id.in_(chunk))))
    item_ids = [i.id for i in items]
    for chunk in _chunks(item_ids, 500):
        mods.extend(session.scalars(alive(SaleItemModifier).where(SaleItemModifier.sale_item_id.in_(chunk))))
    payments = list(session.scalars(alive(Payment).where(
        Payment.voided.is_(False), Payment.at >= start, Payment.at < end)))
    expenses = list(session.scalars(alive(Expense).where(
        Expense.voided.is_(False), Expense.at >= start, Expense.at < end)))
    purchases = list(session.scalars(alive(Purchase).where(
        Purchase.status != PurchaseStatus.VOID, Purchase.at >= start, Purchase.at < end)))
    sup_pays = list(session.scalars(alive(SupplierPayment).where(
        SupplierPayment.voided.is_(False), SupplierPayment.at >= start, SupplierPayment.at < end)))
    entries = list(session.scalars(alive(FinancialEntry).where(
        FinancialEntry.voided.is_(False), FinancialEntry.at >= start, FinancialEntry.at < end)))
    losses = list(session.scalars(alive(StockMovement).where(
        StockMovement.kind.in_(LOSS_KINDS), StockMovement.at >= start, StockMovement.at < end)))
    return Dataset(
        sales=sales, items=items, modifiers=mods, payments=payments, expenses=expenses, purchases=purchases,
        supplier_payments=sup_pays, entries=entries, losses=losses,
        products={p.id: p for p in session.scalars(alive(Product))},
        categories=list_categories(session, include_inactive=True),
        expense_categories={c.id: c for c in session.scalars(alive(ExpenseCategory))},
        methods={m.id: m for m in session.scalars(alive(PaymentMethod))},
        supply_groups={g.id: g for g in session.scalars(select(SupplyGroup))},
    )


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# --- resumen ------------------------------------------------------------------------------
@dataclass
class Summary:
    sales_total: int = 0
    sales_count: int = 0
    units: float = 0
    cost_of_sales: float = 0
    discounts: int = 0
    credit_generated: int = 0
    abonos: int = 0
    collected_sales: int = 0
    expenses_total: int = 0
    investment_total: int = 0
    purchases_total: int = 0
    other_income: int = 0
    losses_value: float = 0
    by_method: dict[str, int] = field(default_factory=dict)

    @property
    def avg_ticket(self) -> float:
        return self.sales_total / self.sales_count if self.sales_count else 0

    @property
    def gross_profit(self) -> float:
        return self.sales_total - self.cost_of_sales

    @property
    def gross_margin(self) -> float | None:
        return self.gross_profit / self.sales_total if self.sales_total else None


def summary(ds: Dataset) -> Summary:
    s = Summary()
    for sale in ds.sales:
        s.sales_total += sale.total
        s.sales_count += 1
        s.cost_of_sales += sale.cost_total or 0
        s.discounts += sale.discount or 0
    paid_at_sale: dict[str, int] = defaultdict(int)
    for p in ds.payments:
        name = ds.methods[p.method_id].name if p.method_id in ds.methods else "?"
        s.by_method[name] = s.by_method.get(name, 0) + p.amount
        if p.kind == PaymentKind.ABONO:
            s.abonos += p.amount
        else:
            s.collected_sales += p.amount
            if p.sale_id:
                paid_at_sale[p.sale_id] += p.amount
    for sale in ds.sales:
        if sale.is_credit:
            s.credit_generated += max(0, sale.total - paid_at_sale.get(sale.id, 0))
    s.units = sum(i.quantity for i in ds.items)
    for e in ds.expenses:
        cat = ds.expense_categories.get(e.category_id)
        if cat is not None and cat.type == ExpenseType.INVESTMENT:
            s.investment_total += e.amount
        else:
            s.expenses_total += e.amount
    s.purchases_total = sum(p.total for p in ds.purchases)
    s.other_income = sum(e.amount for e in ds.entries if e.kind == MoneyKind.OTHER_INCOME)
    s.losses_value = sum(-m.quantity * (m.unit_cost or 0) for m in ds.losses)
    return s


# --- ventas por producto / categoría --------------------------------------------------------
@dataclass
class ProductRow:
    name: str
    category: str
    quantity: float = 0
    revenue: int = 0
    cost: float = 0

    @property
    def margin(self) -> float:
        return self.revenue - self.cost

    @property
    def margin_pct(self) -> float | None:
        return self.margin / self.revenue if self.revenue else None


def _item_category(ds: Dataset, item: SaleItem, paths: dict[str, str], root: bool) -> str:
    prod = ds.products.get(item.product_id) if item.product_id else None
    if prod is None or not prod.category_id:
        return "Sin categoría"
    if root:
        rid = root_category_of(ds.categories, prod.category_id)
        return paths.get(rid, "Sin categoría")
    return paths.get(prod.category_id, "Sin categoría")


def _discount_factors(ds: Dataset) -> dict[str, float]:
    """Un descuento sobre toda la venta se reparte entre sus productos en proporción al valor."""
    return {s.id: (s.total / s.subtotal if s.subtotal and s.discount else 1.0) for s in ds.sales}


def by_product(ds: Dataset) -> list[ProductRow]:
    paths = category_paths(ds.categories)
    factors = _discount_factors(ds)
    rows: dict[str, ProductRow] = {}
    for item in ds.items:
        prod = ds.products.get(item.product_id) if item.product_id else None
        key = item.product_id or item.name
        name = prod.name if prod else item.name.split(" + ")[0]
        row = rows.get(key)
        if row is None:
            row = rows[key] = ProductRow(name, _item_category(ds, item, paths, False))
        row.quantity += item.quantity
        # el valor del producto sin las adiciones (esas se reportan aparte)
        base = item.total - int(round(item.modifiers_price * item.quantity))
        row.revenue += int(round(base * factors.get(item.sale_id, 1.0)))
        row.cost += (item.unit_cost or 0) * item.quantity
    return sorted(rows.values(), key=lambda r: -r.revenue)


def by_category(ds: Dataset, root: bool = True) -> list[ProductRow]:
    paths = category_paths(ds.categories)
    factors = _discount_factors(ds)
    rows: dict[str, ProductRow] = {}
    for item in ds.items:
        cat = _item_category(ds, item, paths, root)
        row = rows.setdefault(cat, ProductRow(cat, cat))
        row.quantity += item.quantity
        row.revenue += int(round(item.total * factors.get(item.sale_id, 1.0)))
        row.cost += (item.unit_cost or 0) * item.quantity
    return sorted(rows.values(), key=lambda r: -r.revenue)


@dataclass
class ModifierRow:
    name: str
    count: float = 0
    revenue: int = 0
    cost: float = 0


@dataclass
class FlavorRow:
    group: str
    name: str
    cups: float = 0
    revenue: float = 0
    cost: float = 0

    @property
    def margin(self) -> float:
        return self.revenue - self.cost

    @property
    def margin_pct(self) -> float | None:
        return self.margin / self.revenue if self.revenue else None


def by_flavor(ds: Dataset) -> list[FlavorRow]:
    """Vasos, ventas y margen por sabor. Una línea con varios sabores (promo x2) reparte su
    valor según los vasos de cada sabor; los descuentos de toda la venta ya van descontados."""
    items = {i.id: i for i in ds.items}
    factors = _discount_factors(ds)
    flavor_rows = [m for m in ds.modifiers if m.supply_id]
    weight: dict[tuple[str, str], float] = defaultdict(float)
    count: dict[tuple[str, str], int] = defaultdict(int)
    for m in flavor_rows:
        weight[(m.sale_item_id, m.supply_group_id or "")] += m.quantity or 0
        count[(m.sale_item_id, m.supply_group_id or "")] += 1
    rows: dict[tuple[str, str], FlavorRow] = {}
    for m in flavor_rows:
        item = items.get(m.sale_item_id)
        if item is None:
            continue
        key = (m.sale_item_id, m.supply_group_id or "")
        share = (m.quantity or 0) / weight[key] if weight[key] else 1 / count[key]
        group = ds.supply_groups.get(m.supply_group_id or "")
        gname = group.name if group is not None else "Sabores"
        row = rows.setdefault((gname, m.name), FlavorRow(gname, m.name))
        row.cups += (m.quantity or 0) if weight[key] else item.quantity * share
        row.revenue += item.total * factors.get(item.sale_id, 1.0) * share
        row.cost += (item.unit_cost or 0) * item.quantity * share
    return sorted(rows.values(), key=lambda r: (r.group, -r.cups))


def by_modifier(ds: Dataset) -> list[ModifierRow]:
    """Adiciones y escarchados (los sabores van aparte, en `by_flavor`)."""
    qty_by_item = {i.id: i.quantity for i in ds.items}
    rows: dict[str, ModifierRow] = {}
    for m in ds.modifiers:
        if m.supply_id:
            continue
        q = qty_by_item.get(m.sale_item_id, 1)
        row = rows.setdefault(m.name, ModifierRow(m.name))
        row.count += q
        row.revenue += int(round(m.price_delta * q))
        row.cost += (m.unit_cost or 0) * q
    return sorted(rows.values(), key=lambda r: -r.count)


# --- tiempo ---------------------------------------------------------------------------------
def by_day(ds: Dataset, period: Period) -> list[tuple[date, int, int]]:
    """[(día, total vendido, número de ventas)] incluyendo días sin ventas."""
    totals: dict[date, list[int]] = defaultdict(lambda: [0, 0])
    for s in ds.sales:
        d = s.closed_at.date()
        totals[d][0] += s.total
        totals[d][1] += 1
    first = min(totals) if totals and period.label == "Todo" else period.start
    out = []
    d = first
    while d <= period.end:
        t = totals.get(d, [0, 0])
        out.append((d, t[0], t[1]))
        d += timedelta(days=1)
    return out


def by_weekday(ds: Dataset) -> list[tuple[int, int, int, int]]:
    """[(día semana, total, ventas, número de días con ventas)]"""
    totals = defaultdict(lambda: [0, 0, set()])
    for s in ds.sales:
        wd = s.closed_at.weekday()
        totals[wd][0] += s.total
        totals[wd][1] += 1
        totals[wd][2].add(s.closed_at.date())
    return [(wd, totals[wd][0], totals[wd][1], len(totals[wd][2])) for wd in range(7)]


def by_hour(ds: Dataset) -> list[tuple[int, int, int]]:
    """Ventas por hora (solo las registradas en caja; las importadas no tienen hora)."""
    totals = defaultdict(lambda: [0, 0])
    for s in ds.sales:
        if s.origin != "pos":
            continue
        h = s.closed_at.hour
        totals[h][0] += s.total
        totals[h][1] += 1
    return [(h, totals[h][0], totals[h][1]) for h in range(24)]


# --- gastos ---------------------------------------------------------------------------------
@dataclass
class ExpenseGroup:
    name: str
    type: str
    amount: int = 0
    children: dict[str, int] = field(default_factory=dict)


def expenses_by_category(ds: Dataset) -> list[ExpenseGroup]:
    groups: dict[str, ExpenseGroup] = {}
    for e in ds.expenses:
        cat = ds.expense_categories.get(e.category_id)
        parent = ds.expense_categories.get(cat.parent_id) if cat and cat.parent_id else cat
        pname = parent.name if parent else "Sin categoría"
        g = groups.setdefault(pname, ExpenseGroup(pname, parent.type if parent else ExpenseType.OPERATING))
        g.amount += e.amount
        child = cat.name if cat else "Sin categoría"
        g.children[child] = g.children.get(child, 0) + e.amount
    return sorted(groups.values(), key=lambda g: -g.amount)


# --- estado de resultados -------------------------------------------------------------------
@dataclass
class PnLLine:
    label: str
    amount: float
    level: int = 0      # 0 = título/total, 1 = detalle
    bold: bool = False
    is_pct: bool = False
    is_header: bool = False


def income_statement(ds: Dataset) -> list[PnLLine]:
    sm = summary(ds)
    by_type: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in ds.expenses:
        cat = ds.expense_categories.get(e.category_id)
        etype = cat.type if cat else ExpenseType.OPERATING
        parent = ds.expense_categories.get(cat.parent_id) if cat and cat.parent_id else cat
        by_type[etype][parent.name if parent else "Sin categoría"] += e.amount
    lines = [
        PnLLine("Ventas", sm.sales_total, 0, True),
        PnLLine("(−) Costo de lo vendido (según recetas)", -sm.cost_of_sales, 1),
        PnLLine("(−) Mermas, daños y diferencias de inventario", -sm.losses_value, 1),
    ]
    gross = sm.sales_total - sm.cost_of_sales - sm.losses_value
    lines.append(PnLLine("Utilidad bruta", gross, 0, True))
    op_total = 0
    for etype, title in [(ExpenseType.PAYROLL, "Nómina y personal"), (ExpenseType.OPERATING, "Gastos de operación"),
                         (ExpenseType.TAXES, "Impuestos y trámites"), (ExpenseType.FINANCIAL, "Gastos financieros")]:
        groups = by_type.get(etype, {})
        subtotal = sum(groups.values())
        if not subtotal:
            continue
        lines.append(PnLLine(f"(−) {title}", -subtotal, 1))
        op_total += subtotal
    operating = gross - op_total
    lines.append(PnLLine("Utilidad operacional", operating, 0, True))
    if sm.other_income:
        lines.append(PnLLine("(+) Otros ingresos", sm.other_income, 1))
    lines.append(PnLLine("Utilidad del periodo (antes de impuestos de renta)", operating + sm.other_income, 0, True))
    margin = (operating + sm.other_income) / sm.sales_total if sm.sales_total else 0
    lines.append(PnLLine("Margen neto", margin, 1, is_pct=True))
    # informativo
    cost_purchases = sum(by_type.get(ExpenseType.COST, {}).values())
    lines.append(PnLLine("Informativo (no restan arriba):", 0, 0, True, is_header=True))
    lines.append(PnLLine("Compras de insumos registradas en Compras", sm.purchases_total, 1))
    lines.append(PnLLine("Insumos y mercancía registrados como Gasto", cost_purchases, 1))
    lines.append(PnLLine("Inversiones en equipos y mobiliario", sm.investment_total, 1))
    return lines


@dataclass
class CashFlow:
    inflows: list[tuple[str, int]]
    outflows: list[tuple[str, int]]

    @property
    def total_in(self) -> int:
        return sum(v for _, v in self.inflows)

    @property
    def total_out(self) -> int:
        return sum(v for _, v in self.outflows)

    @property
    def net(self) -> int:
        return self.total_in - self.total_out


def cash_flow(ds: Dataset) -> CashFlow:
    sale_pay = sum(p.amount for p in ds.payments if p.kind == PaymentKind.SALE)
    abonos = sum(p.amount for p in ds.payments if p.kind == PaymentKind.ABONO)
    entry_sum = defaultdict(int)
    for e in ds.entries:
        entry_sum[e.kind] += e.amount
    inflows = [("Ventas cobradas", sale_pay), ("Abonos de clientes (fiados)", abonos)]
    for kind in (MoneyKind.OTHER_INCOME, MoneyKind.CAPITAL_IN, MoneyKind.LOAN_IN):
        if entry_sum.get(kind):
            inflows.append((MoneyKind.LABELS[kind], entry_sum[kind]))
    groups = expenses_by_category(ds)
    outflows = [(f"Gastos: {g.name}", g.amount) for g in groups]
    paid_purchases = sum(p.amount for p in ds.supplier_payments)
    if paid_purchases:
        outflows.append(("Pagos a proveedores (compras)", paid_purchases))
    for kind in (MoneyKind.CAPITAL_OUT, MoneyKind.LOAN_PAYMENT):
        if entry_sum.get(kind):
            outflows.append((MoneyKind.LABELS[kind], entry_sum[kind]))
    return CashFlow(inflows, outflows)


# --- comparativo mensual -----------------------------------------------------------------------
@dataclass
class MonthRow:
    year: int
    month: int
    sales: int = 0
    cost: float = 0
    expenses: int = 0       # operación + nómina + impuestos + financieros
    supplies: int = 0       # insumos (gastos tipo costo + compras)
    investment: int = 0
    other_income: int = 0
    sales_count: int = 0

    @property
    def label(self) -> str:
        return f"{MONTHS[self.month - 1].capitalize()} {self.year}"

    @property
    def cash_result(self) -> int:
        """Como en el Excel: ventas − todo lo gastado."""
        return self.sales + self.other_income - self.expenses - self.supplies - self.investment

    @property
    def operating_result(self) -> float:
        return self.sales - self.cost - self.expenses + self.other_income


def monthly(session: Session, year_from: int, month_from: int, year_to: int, month_to: int) -> list[MonthRow]:
    rows = []
    y, m = year_from, month_from
    while (y, m) <= (year_to, month_to):
        start, end = month_bounds(y, m)
        ds = load(session, Period(start, end))
        sm = summary(ds)
        row = MonthRow(y, m, sales=sm.sales_total, cost=sm.cost_of_sales + sm.losses_value,
                       investment=sm.investment_total, other_income=sm.other_income, sales_count=sm.sales_count)
        for e in ds.expenses:
            cat = ds.expense_categories.get(e.category_id)
            etype = cat.type if cat else ExpenseType.OPERATING
            if etype == ExpenseType.COST:
                row.supplies += e.amount
            elif etype != ExpenseType.INVESTMENT:
                row.expenses += e.amount
        row.supplies += sm.purchases_total
        rows.append(row)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return rows


def first_activity(session: Session) -> date | None:
    first = session.scalars(alive(Sale).where(Sale.status == SaleStatus.CLOSED).order_by(Sale.closed_at).limit(1)).first()
    first_exp = session.scalars(alive(Expense).order_by(Expense.at).limit(1)).first()
    dates = [x for x in [first.closed_at if first else None, first_exp.at if first_exp else None] if x]
    return min(dates).date() if dates else None
