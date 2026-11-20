"""Importa el historial desde los Excel que se llevaban antes del sistema.

* "Lista de Ventas": una hoja por día ("Sabado 11") con cantidades vendidas en efectivo
  y por transferencia. Cada hoja se convierte en hasta dos ventas del día (una por medio
  de pago). Los productos viejos se reconocen: "TIJUANA 12oz" -> Granizado CL 12 oz con
  sabor Tijuana, "CLUB LARGER" -> Club Colombia, etc.
* "Dashboard Balance": hoja Gastos (cada fila es un gasto, se clasifica por palabras
  clave) e Ingresos (las filas "ventas ..." solo sirven para conciliar; "Total inicial"
  y "Evento" se pueden traer como aporte de capital y otro ingreso).

Lo importado queda marcado (origin = "importado"): no mueve inventario ni saldos de
cuentas, y puede borrarse para volver a importar.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time

from sqlalchemy.orm import Session

from granizapp.core.models import (
    Expense,
    FinancialEntry,
    MoneyKind,
    Payment,
    PaymentKind,
    Product,
    ProductKind,
    Sale,
    SaleItem,
    SaleItemModifier,
    SaleStatus,
    new_id,
)
from granizapp.core.services import finance, staff
from granizapp.core.services.catalog import RecipeBook
from granizapp.core.services.common import Actor, alive, audit
from granizapp.core.utils import normalize

IMPORT_DEVICE = "IMP"
WEEKDAY_NAMES = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
CASH_METHOD = "seed-pm-efectivo"
TRANSFER_METHOD = "seed-pm-transferencia"

# sabores del Excel -> sabor (insumo con sabores) de la app
FLAVORS_CL = {
    "tijuana": "seed-su-cl-tijuana",
    "nueva york": "seed-su-cl-ny",
    "san andres": "seed-su-cl-sanandres",
    "habana": "seed-su-cl-habana",
    "ibiza": "seed-su-cl-ibiza",
}
FLAVORS_SL = {"bubalu": "seed-su-sl-bubalu", "chicle": "seed-su-sl-chicle"}
SIZED = {
    "cl": {"9": "seed-p-cl9", "12": "seed-p-cl12", "16": "seed-p-cl16"},
    "sl": {"9": "seed-p-sl9", "12": "seed-p-sl12", "16": "seed-p-sl16"},
    "quipitos": {"8": "seed-p-quip8", "12": "seed-p-quip12", "16": "seed-p-quip16"},
    "promo x2": {"12": "seed-p-promo2x12", "16": "seed-p-promo2x16"},
}
DIRECT = {
    "corona": "seed-p-corona",
    "corona michelada": "seed-p-corona-m",
    "club": "seed-p-club",
    "club larger": "seed-p-club",
    "club lager": "seed-p-club",
    "club michelada": "seed-p-club-m",
    "budweiser": "seed-p-bud",
    "budweiser michelada": "seed-p-bud-m",
    "soda normal": "seed-p-soda",
    "soda saborizada": "seed-p-soda-sab",
    "adiciones": "seed-p-adicion",
    "agua": "seed-p-agua",
    "alpinito": "seed-p-alpinito",
    "alpinito / p. colada": "seed-p-alpinito",
    "cremoso": "seed-p-cremoso",
    "especial de 15k": "seed-p-esp15",
    "promo": "seed-p-promo17",
    "promo 17k": "seed-p-promo17",
    "promo (mar - jue)": "seed-p-promo17",
    "promo (lun - jue)": "seed-p-promo17",
}


@dataclass
class ImportOptions:
    sales_path: str | None = None
    balance_path: str | None = None
    first_sheet_date: date = date(2026, 6, 28)
    import_sales: bool = True
    import_expenses: bool = True
    initial_total_as_capital: bool = True
    events_as_other_income: bool = True
    unorganized_as_other_income: bool = False
    replace_previous: bool = True


@dataclass
class DaySheet:
    sheet: str
    day: date
    lines: list[tuple[str, float, float, float]]  # (nombre, precio, cant. efectivo, cant. transferencia)
    weekday_ok: bool = True

    @property
    def cash_total(self) -> int:
        return int(round(sum(p * c for _, p, c, _ in self.lines)))

    @property
    def transfer_total(self) -> int:
        return int(round(sum(p * t for _, p, _, t in self.lines)))


@dataclass
class ImportReport:
    days: list[DaySheet] = field(default_factory=list)
    sales_created: int = 0
    items_created: int = 0
    sales_total: int = 0
    expenses_created: int = 0
    expenses_total: int = 0
    entries_created: list[str] = field(default_factory=list)
    skipped_income_rows: list[str] = field(default_factory=list)
    legacy_products: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    expense_by_category: dict[str, int] = field(default_factory=dict)
    reconciliation: list[tuple[str, int, int]] = field(default_factory=list)  # (mes, excel ingresos, hojas diarias)
    removed_previous: int = 0

    def text(self) -> str:
        lines = [
            f"Días importados: {len(self.days)}",
            f"Ventas creadas: {self.sales_created} ({self.items_created} líneas) por $ {self.sales_total:,.0f}".replace(",", "."),
            f"Gastos creados: {self.expenses_created} por $ {self.expenses_total:,.0f}".replace(",", "."),
        ]
        if self.entries_created:
            lines.append("Otros movimientos: " + "; ".join(self.entries_created))
        if self.legacy_products:
            lines.append("Productos históricos creados: " + ", ".join(self.legacy_products))
        if self.skipped_income_rows:
            lines.append("Filas de Ingresos no importadas: " + "; ".join(self.skipped_income_rows))
        for w in self.warnings:
            lines.append("Aviso: " + w)
        return "\n".join(lines)


# --- lectura -------------------------------------------------------------------------------
def _num(v) -> float:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return 0.0


def read_daily_sheets(path: str, first_date: date) -> tuple[list[DaySheet], list[str]]:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    out: list[DaySheet] = []
    warnings: list[str] = []
    year, month = first_date.year, first_date.month
    prev_day = None
    try:
        for ws in wb.worksheets:
            title = ws.title
            m = re.match(r"([a-z]+)\s+(\d+)", normalize(title))
            if not m:
                warnings.append(f"Hoja '{title}' ignorada: el nombre no tiene día")
                continue
            weekday_name, day_num = m.group(1), int(m.group(2))
            if prev_day is not None and day_num < prev_day:
                month += 1
                if month > 12:
                    year, month = year + 1, 1
            prev_day = day_num
            try:
                day = date(year, month, day_num)
            except ValueError:
                warnings.append(f"Hoja '{title}': fecha inválida")
                continue
            rows = [list(r) for r in ws.iter_rows(min_row=1, max_row=60, max_col=16, values_only=True)]
            sheet = _parse_day(rows)
            if sheet is None:
                warnings.append(f"Hoja '{title}' ignorada: no se encontró la tabla de productos")
                continue
            ok = WEEKDAY_NAMES[day.weekday()] == weekday_name
            if not ok:
                warnings.append(f"Hoja '{title}': el día de la semana no coincide con {day.isoformat()}")
            out.append(DaySheet(title.strip(), day, sheet, ok))
    finally:
        wb.close()
    return out, warnings


def _parse_day(rows: list[list]) -> list[tuple[str, float, float, float]] | None:
    hdr = None
    for r, row in enumerate(rows[:12]):
        for c, v in enumerate(row):
            if isinstance(v, str) and normalize(v) == "nombre del producto":
                hdr = (r, c)
                break
        if hdr:
            break
    if hdr is None:
        return None
    r0, c0 = hdr
    header = rows[r0]
    single = isinstance(header[c0 + 2], str) and normalize(header[c0 + 2]) == "ventas"
    lines = []
    for row in rows[r0 + 1:]:
        if len(row) <= c0 + 3:
            continue
        name, price = row[c0], row[c0 + 1]
        if isinstance(price, str) and normalize(price) == "total":
            break
        if not isinstance(name, str) or not name.strip() or not _num(price):
            continue
        cash = _num(row[c0 + 2])
        transfer = 0.0 if single else _num(row[c0 + 3])
        if cash or transfer:
            lines.append((name.strip(), _num(price), cash, transfer))
    return lines


def read_balance(path: str) -> tuple[list[tuple[str, str, int, date]], list[tuple[str, int, date]]]:
    """Devuelve (gastos [(gasto, descripción, valor, fecha)], ingresos [(concepto, valor, fecha)])."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    expenses, incomes = [], []
    try:
        for ws in wb.worksheets:
            name = normalize(ws.title)
            rows = [list(r) for r in ws.iter_rows(min_row=1, max_row=5000, max_col=6, values_only=True)]
            if name.startswith("gasto"):
                for row in rows:
                    if len(row) < 4 or not isinstance(row[0], str):
                        continue
                    if normalize(row[0]) == "gasto":
                        continue
                    value, when = _num(row[1]), row[3]
                    if value and isinstance(when, (datetime, date)):
                        expenses.append((row[0].strip(), (row[2] or "").strip() if isinstance(row[2], str) else "",
                                         int(round(value)), when.date() if isinstance(when, datetime) else when))
            elif name.startswith("ingreso"):
                for row in rows:
                    if len(row) < 4 or not isinstance(row[0], str) or normalize(row[0]) == "ingresos":
                        continue
                    value, when = _num(row[1]), row[3]
                    if value and isinstance(when, (datetime, date)):
                        incomes.append((row[0].strip(), int(round(value)),
                                        when.date() if isinstance(when, datetime) else when))
    finally:
        wb.close()
    return expenses, incomes


# --- mapeo de productos ------------------------------------------------------------------------
def map_legacy(name: str, price: float) -> tuple[str | None, str | None]:
    n = normalize(name)
    n = re.sub(r"\s+", " ", n)
    special = "especial" in n
    m = re.match(r"^(.*?)\s*(\d+)\s*oz\b", n)
    if m:
        base, size = m.group(1).strip(), m.group(2)
        if base in FLAVORS_CL and size in ("9", "12"):
            return SIZED["cl"][size], FLAVORS_CL[base]
        if base in FLAVORS_SL and size in ("9", "12"):
            return SIZED["sl"][size], FLAVORS_SL[base]
        if base == "cl" and special and size in ("9", "12"):
            return {"9": "seed-p-cle9", "12": "seed-p-cle12"}[size], None
        if base in SIZED and size in SIZED[base]:
            return SIZED[base][size], None
    if n.startswith("sodas"):
        return ("seed-p-soda-sab" if price >= 12000 else "seed-p-soda"), None
    if n in DIRECT:
        return DIRECT[n], None
    return None, None


def _legacy_product(session: Session, name: str, price: float, cache: dict, report: ImportReport) -> str:
    key = (normalize(name), int(price))
    if key in cache:
        return cache[key]
    pid = "imp-" + re.sub(r"[^a-z0-9]+", "-", normalize(name)).strip("-") + f"-{int(price)}"
    if session.get(Product, pid) is None:
        category = "seed-pc-promos" if "promo" in normalize(name) else "seed-pc-historicos"
        session.add(Product(id=pid, name=name.title(), code="", category_id=category, kind=ProductKind.PREPARED,
                            price=int(price), active=False, favorite=False, track_inventory=False,
                            notes="Creado al importar el Excel"))
        report.legacy_products.append(f"{name.title()} ({int(price)})")
    cache[key] = pid
    return pid


# --- importación ---------------------------------------------------------------------------------
def remove_previous_import(session: Session) -> int:
    n = 0
    for model in (Sale, Expense, FinancialEntry):
        for row in session.scalars(alive(model).where(model.origin == "importado")):
            row.deleted = True
            n += 1
            if model is Sale:
                for item in session.scalars(alive(SaleItem).where(SaleItem.sale_id == row.id)):
                    item.deleted = True
                    for mod in session.scalars(alive(SaleItemModifier).where(SaleItemModifier.sale_item_id == item.id)):
                        mod.deleted = True
                for pay in session.scalars(alive(Payment).where(Payment.sale_id == row.id)):
                    pay.deleted = True
    return n


def run_import(session: Session, opts: ImportOptions, actor: Actor) -> ImportReport:
    report = ImportReport()
    if opts.replace_previous:
        report.removed_previous = remove_previous_import(session)
        session.flush()
    days: list[DaySheet] = []
    if opts.sales_path:
        days, warns = read_daily_sheets(opts.sales_path, opts.first_sheet_date)
        report.days = days
        report.warnings.extend(warns)
    if opts.import_sales and days:
        _import_sales(session, days, report, actor)
    expenses, incomes = ([], [])
    if opts.balance_path:
        expenses, incomes = read_balance(opts.balance_path)
    if opts.import_expenses and expenses:
        _import_expenses(session, expenses, report, actor)
    if incomes:
        _import_incomes(session, incomes, opts, report, actor)
        report.reconciliation = _reconcile(days, incomes)
    audit(session, actor, "importar_excel", "", "", report.text()[:2000])
    return report


def _import_sales(session: Session, days: list[DaySheet], report: ImportReport, actor: Actor) -> None:
    book = RecipeBook(session)
    cache: dict = {}
    number = 0
    existing = session.scalars(alive(Sale).where(Sale.device_id == IMPORT_DEVICE).order_by(Sale.number.desc())).first()
    if existing:
        number = existing.number
    units_of: dict[str, dict[str, float]] = {}
    for day in days:
        for method_id, use_cash, label, hour in ((CASH_METHOD, True, "efectivo", 12),
                                                 (TRANSFER_METHOD, False, "transferencia", 13)):
            lines = [(n, p, cash if use_cash else transfer) for n, p, cash, transfer in day.lines]
            lines = [line for line in lines if line[2]]
            if not lines:
                continue
            number += 1
            when = datetime.combine(day.day, time(hour, 0))
            sale = Sale(id=new_id(), number=number, device_id=IMPORT_DEVICE, opened_at=when, closed_at=when,
                        status=SaleStatus.CLOSED, label=f"Ventas del día ({label}) – hoja {day.sheet}",
                        origin="importado", user_id=actor.user_id)
            session.add(sale)
            total = 0
            cost = 0.0
            for order, (name, price, qty) in enumerate(lines):
                pid, flavor_id = map_legacy(name, price)
                if pid is None or session.get(Product, pid) is None:
                    pid = _legacy_product(session, name, price, cache, report)
                    flavor_id = None
                flavor = book.supplies.get(flavor_id) if flavor_id else None
                choices = {flavor.group_id: {flavor.id: 1.0}} if flavor is not None and flavor.group_id else None
                product = session.get(Product, pid)
                unit_cost = book.product_cost(pid, choices) if pid in book.products else 0.0
                line_total = int(round(price * qty))
                display = product.name + (f" · {flavor.variant_name}" if flavor is not None else "")
                item = SaleItem(id=new_id(), sale_id=sale.id, product_id=pid, name=display, quantity=qty,
                                unit_price=int(price), total=line_total, unit_cost=unit_cost, sort_order=order)
                session.add(item)
                if pid not in units_of:
                    units_of[pid] = book.group_units(pid)
                for gid, units in units_of[pid].items():  # sabor de la línea (o «Sin especificar»)
                    sid = flavor.id if flavor is not None and flavor.group_id == gid else book.default_of(gid)
                    if sid:
                        session.add(SaleItemModifier(sale_item_id=item.id, supply_id=sid, supply_group_id=gid,
                                                     name=book.supplies[sid].variant_name or "Sin especificar",
                                                     price_delta=0, quantity=units * qty))
                total += line_total
                cost += unit_cost * qty
                report.items_created += 1
            sale.subtotal = sale.total = sale.paid = total
            sale.cost_total = cost
            session.add(Payment(at=when, kind=PaymentKind.SALE, sale_id=sale.id, method_id=method_id, amount=total,
                                received=total, user_id=actor.user_id, note="Importado de Excel"))
            report.sales_created += 1
            report.sales_total += total
    session.flush()


def _import_expenses(session: Session, rows, report: ImportReport, actor: Actor) -> None:
    cats = finance.list_expense_categories(session)
    names = {c.id: c.name for c in cats}
    employee_cache: dict[str, str] = {}
    for gasto, desc, amount, when in rows:
        text = f"{gasto} {desc}"
        cat = finance.classify_expense(cats, text)
        cat_id = cat.id if cat else "seed-exp-otros"
        employee_id = None
        if cat_id.startswith("seed-exp-nomina"):
            n = normalize(text)
            for nick, canonical in (("danny", "Dani"), ("dani", "Dani")):
                if nick in n:
                    employee_id = employee_cache.get(canonical) or _employee(session, canonical)
                    employee_cache[canonical] = employee_id
                    break
        description = gasto if not desc or normalize(desc) == normalize(gasto) else f"{gasto} – {desc}"
        session.add(Expense(at=datetime.combine(when, time(12, 0)), category_id=cat_id, description=description[:250],
                            amount=amount, employee_id=employee_id, origin="importado", user_id=actor.user_id))
        report.expenses_created += 1
        report.expenses_total += amount
        report.expense_by_category[names.get(cat_id, cat_id)] = report.expense_by_category.get(names.get(cat_id, cat_id), 0) + amount
    session.flush()


def _employee(session: Session, name: str) -> str:
    for emp in staff.list_employees(session, True):
        if normalize(emp.name) == normalize(name):
            return emp.id
    return staff.save_employee(session, {"name": name, "role": "Bartender", "notes": "Creado al importar el Excel"}).id


def _import_incomes(session: Session, rows, opts: ImportOptions, report: ImportReport, actor: Actor) -> None:
    for concept, amount, when in rows:
        n = normalize(concept)
        at = datetime.combine(when, time(12, 0))
        kind = None
        if n.startswith("total inicial"):
            kind = MoneyKind.CAPITAL_IN if opts.initial_total_as_capital else None
        elif n.startswith("ventas para organizar"):
            kind = MoneyKind.OTHER_INCOME if opts.unorganized_as_other_income else None
        elif n.startswith("venta"):
            continue  # ya está en el detalle diario
        elif opts.events_as_other_income:
            kind = MoneyKind.OTHER_INCOME
        if kind is None:
            report.skipped_income_rows.append(f"{concept} ({amount:,})".replace(",", "."))
            continue
        session.add(FinancialEntry(at=at, kind=kind, description=f"{concept} (Excel)", amount=amount,
                                   account_id="seed-acc-fuerte", origin="importado", user_id=actor.user_id))
        report.entries_created.append(f"{MoneyKind.LABELS[kind]}: {concept} {amount:,}".replace(",", "."))
    session.flush()


def _reconcile(days: list[DaySheet], incomes) -> list[tuple[str, int, int]]:
    from granizapp.core.utils import month_label

    excel = defaultdict(int)
    for concept, amount, when in incomes:
        if normalize(concept).startswith("venta") and not normalize(concept).startswith("ventas para organizar"):
            excel[(when.year, when.month)] += amount
    sheets = defaultdict(int)
    for d in days:
        sheets[(d.day.year, d.day.month)] += d.cash_total + d.transfer_total
    keys = sorted(set(excel) | set(sheets))
    return [(month_label(y, m), excel.get((y, m), 0), sheets.get((y, m), 0)) for y, m in keys]
