"""Importador de Excel con archivos sintéticos en el mismo formato de los de The Spot."""
from datetime import date, datetime

import pytest
from openpyxl import Workbook

from granizapp.core.models import Expense, FinancialEntry, MoneyKind
from granizapp.core.services import excel_import as ei
from granizapp.core.services import reports, sales


def _ventas(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Domingo 28"  # formato viejo: una sola columna de ventas
    ws["C4"], ws["D4"], ws["E4"], ws["F4"] = "Nombre del Producto", "Precio", "Ventas", "Total"
    rows = [("TIJUANA 12oz", 14000, 2), ("CORONA MICHELADA", 10000, 1), ("CLUB ", 6000, None)]
    for i, (n, p, q) in enumerate(rows, 5):
        ws.cell(i, 3, n), ws.cell(i, 4, p), ws.cell(i, 5, q)
    ws.cell(9, 4, "TOTAL")
    ws2 = wb.create_sheet("Lunes 29")  # formato nuevo: efectivo / transferencia
    for c, h in zip("CDEFGH", ["Nombre del Producto", "Precio", "Pagos con efectivo", "Pagos con transferencia",
                               "Total con efectivo", "Total con transferencia"]):
        ws2[f"{c}4"] = h
    rows2 = [("CL 12oz", 14000, 1, 2), ("SL  12oz", 12000, 0, 1), ("CLUB LARGER", 8000, 3, 0), ("GRANIZADOS R", 11000, 1, 0)]
    for i, (n, p, q1, q2) in enumerate(rows2, 5):
        ws2.cell(i, 3, n), ws2.cell(i, 4, p), ws2.cell(i, 5, q1), ws2.cell(i, 6, q2)
    ws2.cell(10, 4, "TOTAL")
    ws2["J5"] = "DEBEN"
    wb.create_sheet("Miercoles 1")["C1"] = "hoja sin tabla"
    wb.save(path)


def _balance(path):
    wb = Workbook()
    g = wb.active
    g.title = "Gastos"
    g.append([])
    g.append(["Gasto", "Costo", "Descripcion", "Fecha"])
    g.append(["Mercado sabores", 1292900, None, datetime(2026, 6, 28)])
    g.append(["Pago Dani", 650000, None, datetime(2026, 6, 29)])
    g.append(["2 bolsas de hielo", 8000, None, datetime(2026, 6, 29)])
    i = wb.create_sheet("Ingresos ")
    i.append([])
    i.append(["Ingresos", "Valor", "Descripcion", "Fecha"])
    i.append(["Total inicial", 2069000, None, datetime(2026, 6, 28)])
    i.append(["ventas 28 junio", 38000, None, datetime(2026, 6, 28)])
    i.append(["Evento ", 350000, None, datetime(2026, 6, 29)])
    i.append(["Ventas para organizar", 1030000, None, datetime(2026, 6, 29)])
    wb.save(path)


def test_import_synthetic_files(db, actor, tmp_path):
    v, b = tmp_path / "ventas.xlsx", tmp_path / "balance.xlsx"
    _ventas(v)
    _balance(b)
    opts = ei.ImportOptions(sales_path=str(v), balance_path=str(b), first_sheet_date=date(2026, 6, 28))
    with db.session() as s:
        rep = ei.run_import(s, opts, actor)
    assert [d.day for d in rep.days] == [date(2026, 6, 28), date(2026, 6, 29)]
    assert any("Miercoles 1" in w for w in rep.warnings)
    assert rep.sales_created == 3  # domingo efectivo, lunes efectivo y transferencia
    assert rep.sales_total == 38000 + (14000 + 24000 + 11000) + (28000 + 12000)
    assert rep.legacy_products == ["Granizados R (11000)"]
    assert rep.expenses_created == 3 and rep.expenses_total == 1292900 + 650000 + 8000
    assert any("Total inicial" in e for e in rep.entries_created)
    assert any("Ventas para organizar" in x for x in rep.skipped_income_rows)
    with db.session() as s:
        cats = {e.description: e.category_id for e in s.query(Expense).all()}
        assert cats["Mercado sabores"] == "seed-exp-ins-mezclas"
        assert cats["Pago Dani"] == "seed-exp-nomina-sueldos"
        assert cats["2 bolsas de hielo"] == "seed-exp-ins-hielo"
        kinds = {e.kind for e in s.query(FinancialEntry).all()}
        assert kinds == {MoneyKind.CAPITAL_IN, MoneyKind.OTHER_INCOME}
        ds = reports.load(s, reports.preset_period("todo"))
        assert reports.by_modifier(ds) == []  # el sabor ya no es una adición
        flavors = {r.name: r.cups for r in reports.by_flavor(ds)}
        assert flavors["Tijuana"] == 2  # TIJUANA 12oz -> Granizado CL 12 oz con sabor Tijuana
        names = {r.name for r in reports.by_product(ds)}
        assert {"Granizado CL 12 oz", "Club Colombia", "Granizado SL 12 oz"} <= names
        assert all(x.origin == "importado" for x in sales.list_sales(s))
    # reimportar reemplaza lo anterior (no duplica)
    with db.session() as s:
        rep2 = ei.run_import(s, opts, actor)
    assert rep2.removed_previous > 0
    with db.session() as s:
        assert len(sales.list_sales(s)) == 3


@pytest.mark.parametrize("name,price,expected", [
    ("TIJUANA 9oz", 8000, ("seed-p-cl9", "seed-su-cl-tijuana")),
    ("NUEVA YORK 12oz", 14000, ("seed-p-cl12", "seed-su-cl-ny")),
    ("BUBALU 12oz", 12000, ("seed-p-sl12", "seed-su-sl-bubalu")),
    ("CL 16 OZ", 18000, ("seed-p-cl16", None)),
    ("SL  12oz", 12000, ("seed-p-sl12", None)),
    ("CL 9oz ESPECIAL", 10000, ("seed-p-cle9", None)),
    ("QUIPITOS 16 OZ", 18000, ("seed-p-quip16", None)),
    ("PROMO x2 16oz", 28000, ("seed-p-promo2x16", None)),
    ("SODAS", 12000, ("seed-p-soda-sab", None)),
    ("SODAS 12K", 10000, ("seed-p-soda", None)),
    ("PROMO (LUN - JUE)", 17000, ("seed-p-promo17", None)),
    ("ALPINITO / P. COLADA", 18000, ("seed-p-alpinito", None)),
    ("agua", 1500, ("seed-p-agua", None)),
    ("PROMO (FINAL MUNDIAL)", 20000, (None, None)),
])
def test_legacy_mapping(name, price, expected):
    assert ei.map_legacy(name, price) == expected
