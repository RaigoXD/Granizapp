"""Reportes: ventas, rentabilidad, estado de resultados, flujo de caja y comparativo mensual."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QGridLayout, QHBoxLayout, QSplitter, QTabWidget, QVBoxLayout, QWidget

from granizapp.core.export import Sheet, export_xlsx
from granizapp.core.models import ExpenseType
from granizapp.core.services import reports
from granizapp.core.services.settings import get_setting
from granizapp.core.utils import WEEKDAYS, fmt_money, fmt_number, fmt_pct
from granizapp.ui.context import AppContext, Topics
from granizapp.ui.widgets.charts import BarChart, HBars
from granizapp.ui.widgets.common import KpiCard, Page, PeriodSelector, button, card, label, page_header, toast
from granizapp.ui.widgets.table import Col, DataTable


class ReportsPage(Page):
    topics = {Topics.SALES, Topics.EXPENSES, Topics.PURCHASES, Topics.FINANCE, Topics.INVENTORY, Topics.ALL}

    def __init__(self, ctx: AppContext):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.addWidget(page_header("Reportes", "Cómo va el negocio",
                                   [button("Exportar todo a Excel", self.export_all, "Primary")]))
        self.period = PeriodSelector("mes")
        self.period.changed.connect(lambda _p: self.safe_refresh())
        root.addWidget(self.period)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        # resumen
        w = QWidget()
        wl = QVBoxLayout(w)
        wl.setContentsMargins(0, 8, 0, 0)
        g = QGridLayout()
        self.k = {}
        specs = [("sales", "Ventas"), ("count", "Número de ventas"), ("ticket", "Ticket promedio"),
                 ("gross", "Utilidad bruta (recetas)"), ("margin", "Margen bruto"), ("credit", "Fiado en el periodo"),
                 ("abonos", "Abonos recibidos"), ("expenses", "Gastos (sin inversión)"), ("cash", "Resultado de caja")]
        for i, (key, title) in enumerate(specs):
            self.k[key] = KpiCard(title)
            g.addWidget(self.k[key], i // 5, i % 5)
        wl.addLayout(g)
        row = QHBoxLayout()
        f1, l1 = card(title="Ventas por día")
        self.chart_day = BarChart(height=240)
        l1.addWidget(self.chart_day)
        row.addWidget(f1, 3)
        f2, l2 = card(title="Cobrado por medio de pago")
        self.chart_methods = HBars()
        l2.addWidget(self.chart_methods)
        l2.addStretch(1)
        row.addWidget(f2, 2)
        wl.addLayout(row, 1)
        self.tabs.addTab(w, "Resumen")

        # productos
        self.products = DataTable([
            Col("Producto", lambda r: r.name, stretch=True),
            Col("Categoría", lambda r: r.category, width=220),
            Col("Cantidad", lambda r: r.quantity, "qty", width=85),
            Col("Ventas", lambda r: r.revenue, "money", width=115, bold=lambda r: True),
            Col("Costo", lambda r: r.cost, "money", width=105),
            Col("Ganancia", lambda r: r.margin, "money", width=110),
            Col("Margen", lambda r: r.margin_pct, "pct", width=75),
            Col("% de ventas", lambda r: r.revenue / self.total_sales if self.total_sales else None, "pct", width=90),
        ], search=True, export_name="ventas_por_producto",
            footer=lambda rows: f"{len(rows)} productos · {fmt_money(sum(r.revenue for r in rows))}")
        self.tabs.addTab(self._wrap(self.products, "Las adiciones se muestran aparte; aquí va el valor del producto."),
                         "Productos")

        # categorías
        c = QWidget()
        cl = QHBoxLayout(c)
        cl.setContentsMargins(0, 8, 0, 0)
        self.categories = DataTable([
            Col("Categoría", lambda r: r.name, stretch=True),
            Col("Cantidad", lambda r: r.quantity, "qty", width=85),
            Col("Ventas", lambda r: r.revenue, "money", width=115),
            Col("Ganancia", lambda r: r.margin, "money", width=110),
            Col("Margen", lambda r: r.margin_pct, "pct", width=75),
        ], export_name="ventas_por_categoria")
        cl.addWidget(self.categories, 3)
        f3, l3 = card(title="Participación")
        self.chart_cat = HBars()
        l3.addWidget(self.chart_cat)
        l3.addStretch(1)
        cl.addWidget(f3, 2)
        self.tabs.addTab(c, "Categorías")

        # sabores (de las bolsas)
        self.flavors = DataTable([
            Col("Insumo", lambda r: r.group, width=260),
            Col("Sabor", lambda r: r.name, stretch=True, bold=lambda r: r.name != "Sin especificar",
                color=lambda r: "muted" if r.name == "Sin especificar" else None),
            Col("Vasos", lambda r: r.cups, "qty", width=80),
            Col("Ventas", lambda r: r.revenue, "money", width=110),
            Col("Costo", lambda r: r.cost, "money", width=100),
            Col("Ganancia", lambda r: r.margin, "money", width=105),
            Col("Margen", lambda r: r.margin_pct, "pct", width=75),
        ], search=True, export_name="sabores",
            footer=lambda rows: f"{fmt_number(sum(r.cups for r in rows), 0)} vasos")
        self.tabs.addTab(self._wrap(self.flavors, "Vasos por sabor. Una promo con dos sabores reparte su valor entre ellos. "
                                                  "«Sin especificar» = vendidos sin elegir el sabor."), "Sabores")

        # adiciones
        self.mods = DataTable([
            Col("Adición / escarchado", lambda r: r.name, stretch=True),
            Col("Veces", lambda r: r.count, "qty", width=80),
            Col("Cobrado", lambda r: r.revenue, "money", width=110),
            Col("Costo", lambda r: r.cost, "money", width=100),
        ], export_name="adiciones")
        self.tabs.addTab(self._wrap(self.mods, "Adiciones más pedidas (bolitas, gomitas, escarchado…)."), "Adiciones")

        # horas y días
        h = QWidget()
        hl = QVBoxLayout(h)
        hl.setContentsMargins(0, 8, 0, 0)
        f4, l4 = card(title="Ventas por hora (registradas en caja)")
        self.chart_hour = BarChart(height=220)
        l4.addWidget(self.chart_hour)
        hl.addWidget(f4)
        self.weekdays = DataTable([
            Col("Día", lambda r: WEEKDAYS[r[0]].capitalize(), stretch=True),
            Col("Ventas", lambda r: r[1], "money", width=120),
            Col("N.º ventas", lambda r: r[2], "int", width=90),
            Col("Días con ventas", lambda r: r[3], "int", width=120),
            Col("Promedio por día", lambda r: r[1] / r[3] if r[3] else 0, "money", width=140, bold=lambda r: True),
        ], export_name="ventas_por_dia_semana")
        self.weekdays.view.setSortingEnabled(False)
        hl.addWidget(self.weekdays, 1)
        self.tabs.addTab(h, "Horas y días")

        # estado de resultados
        self.pnl = DataTable([
            Col("Concepto", lambda l: ("      " * l.level) + l.label, stretch=True, bold=lambda l: l.bold),
            Col("Valor", lambda l: None if l.is_header else (fmt_pct(l.amount) if l.is_pct else fmt_money(l.amount)), width=160,
                bold=lambda l: l.bold, color=lambda l: "danger" if not l.is_pct and not l.is_header and l.amount < 0 and l.bold else None),
        ], export_name="estado_de_resultados")
        self.pnl.view.setSortingEnabled(False)
        self.tabs.addTab(self._wrap(self.pnl, "Ventas menos el costo de lo vendido según las recetas y menos los gastos de "
                                              "operación. Las compras de insumos no restan aquí (ya están en el costo de lo "
                                              "vendido); ver Flujo de caja para la plata que realmente salió."),
                         "Estado de resultados")

        # flujo de caja
        fc = QWidget()
        fl = QHBoxLayout(fc)
        fl.setContentsMargins(0, 8, 0, 0)
        self.inflows = DataTable([Col("Entradas", lambda r: r[0], stretch=True),
                                  Col("Valor", lambda r: r[1], "money", width=130, color=lambda r: "success")],
                                 export_name="entradas", footer=lambda rows: f"Total entradas: {fmt_money(sum(r[1] for r in rows))}")
        self.outflows = DataTable([Col("Salidas", lambda r: r[0], stretch=True),
                                   Col("Valor", lambda r: r[1], "money", width=130, color=lambda r: "danger")],
                                  export_name="salidas", footer=lambda rows: f"Total salidas: {fmt_money(sum(r[1] for r in rows))}")
        fl.addWidget(self.inflows)
        fl.addWidget(self.outflows)
        fcw = QWidget()
        fcl = QVBoxLayout(fcw)
        fcl.setContentsMargins(0, 0, 0, 0)
        fcl.addWidget(fc, 1)
        self.net_lbl = label("", "SectionTitle")
        fcl.addWidget(self.net_lbl)
        self.tabs.addTab(fcw, "Flujo de caja")

        # gastos
        self.expenses = DataTable([
            Col("Categoría", lambda r: r[0], stretch=True, bold=lambda r: r[2]),
            Col("Tipo", lambda r: ExpenseType.LABELS.get(r[3], "") if r[2] else "", width=200),
            Col("Valor", lambda r: r[1], "money", width=130, bold=lambda r: r[2]),
        ], export_name="gastos_por_categoria")
        self.expenses.view.setSortingEnabled(False)
        self.tabs.addTab(self._wrap(self.expenses), "Gastos por categoría")

        # comparativo mensual
        m = QWidget()
        ml = QVBoxLayout(m)
        ml.setContentsMargins(0, 8, 0, 0)
        ml.addWidget(label("Mes a mes desde el inicio (no depende del periodo elegido arriba).", "Hint"))
        self.monthly = DataTable([
            Col("Mes", lambda r: r.label, width=150, bold=lambda r: True),
            Col("Ventas", lambda r: r.sales, "money", width=120),
            Col("N.º ventas", lambda r: r.sales_count, "int", width=85),
            Col("Costo recetas", lambda r: r.cost, "money", width=120),
            Col("Insumos comprados", lambda r: r.supplies, "money", width=135),
            Col("Gastos operación y nómina", lambda r: r.expenses, "money", width=170),
            Col("Inversiones", lambda r: r.investment, "money", width=110),
            Col("Otros ingresos", lambda r: r.other_income, "money", width=110),
            Col("Utilidad operacional", lambda r: r.operating_result, "money", width=145,
                color=lambda r: "success" if r.operating_result >= 0 else "danger"),
            Col("Resultado de caja", lambda r: r.cash_result, "money", width=135, bold=lambda r: True,
                color=lambda r: "success" if r.cash_result >= 0 else "danger"),
        ], export_name="comparativo_mensual")
        self.monthly.view.setSortingEnabled(False)
        ml.addWidget(self.monthly, 1)
        f5, l5 = card(title="Ventas por mes")
        self.chart_month = BarChart(height=200)
        l5.addWidget(self.chart_month)
        ml.addWidget(f5)
        self.tabs.addTab(m, "Comparativo mensual")

    @staticmethod
    def _wrap(widget, hint: str = "") -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        if hint:
            lay.addWidget(label(hint, "Hint", wrap=True))
        lay.addWidget(widget, 1)
        return w

    def refresh(self):
        p = self.period.period()
        with self.ctx.session() as s:
            ds = reports.load(s, p)
            first = reports.first_activity(s) or date.today()
            today = date.today()
            months = reports.monthly(s, first.year, first.month, today.year, today.month)
            self.business = get_setting(s, "business_name")
        self.ds, self.p = ds, p
        sm = reports.summary(ds)
        self.total_sales = sm.sales_total
        cash_result = sm.sales_total + sm.other_income - sm.expenses_total - sm.investment_total - sm.purchases_total
        self.k["sales"].set(fmt_money(sm.sales_total), color="primary")
        self.k["count"].set(str(sm.sales_count), f"{sm.units:.0f} productos")
        self.k["ticket"].set(fmt_money(sm.avg_ticket) if sm.sales_count else "—")
        self.k["gross"].set(fmt_money(sm.gross_profit), f"Costo de lo vendido {fmt_money(sm.cost_of_sales)}")
        self.k["margin"].set(fmt_pct(sm.gross_margin) if sm.gross_margin is not None else "—")
        self.k["credit"].set(fmt_money(sm.credit_generated))
        self.k["abonos"].set(fmt_money(sm.abonos))
        self.k["expenses"].set(fmt_money(sm.expenses_total), f"Inversiones aparte: {fmt_money(sm.investment_total)}")
        self.k["cash"].set(fmt_money(cash_result), "Ventas − gastos − compras − inversiones",
                           "success" if cash_result >= 0 else "danger")
        days = reports.by_day(ds, p) if p.days <= 400 else []
        self.chart_day.set_data([(d.strftime("%d/%m"), v) for d, v, _n in days])
        self.chart_methods.set_data(sorted(sm.by_method.items(), key=lambda kv: -kv[1]))
        self.products.set_rows(reports.by_product(ds))
        cats = reports.by_category(ds)
        self.categories.set_rows(cats)
        self.chart_cat.set_data([(r.name, r.revenue) for r in cats])
        self.flavors.set_rows(reports.by_flavor(ds))
        self.mods.set_rows(reports.by_modifier(ds))
        hours = reports.by_hour(ds)
        active_hours = [h for h in hours if h[1]] or hours[10:24]
        lo, hi = (min(h[0] for h in active_hours), max(h[0] for h in active_hours)) if active_hours else (10, 23)
        self.chart_hour.set_data([(f"{h:02d}h", v) for h, v, _n in hours if lo <= h <= hi])
        self.weekdays.set_rows(reports.by_weekday(ds))
        self.pnl.set_rows(reports.income_statement(ds))
        cf = reports.cash_flow(ds)
        self.inflows.set_rows(cf.inflows)
        self.outflows.set_rows(cf.outflows)
        self.net_lbl.setText(f"Flujo neto del periodo: {fmt_money(cf.net)}")
        rows = []
        for gp in reports.expenses_by_category(ds):
            rows.append((gp.name, gp.amount, True, gp.type))
            for child, amount in sorted(gp.children.items(), key=lambda kv: -kv[1]):
                if child != gp.name:
                    rows.append(("      " + child, amount, False, gp.type))
        self.expenses.set_rows(rows)
        self.months = months
        self.monthly.set_rows(months)
        self.chart_month.set_data([(m.label[:3] + " " + str(m.year)[2:], m.sales) for m in months])

    def export_all(self):
        path, _ = QFileDialog.getSaveFileName(self, "Exportar reportes", f"reportes_{self.p.start}_{self.p.end}.xlsx",
                                              "Excel (*.xlsx)")
        if not path:
            return
        ds = self.ds
        sm = reports.summary(ds)
        sub = f"Periodo: {self.p.start:%d/%m/%Y} a {self.p.end:%d/%m/%Y}"
        sheets = [
            Sheet("Resumen", ["Indicador", "Valor"], [
                ["Ventas", sm.sales_total], ["Número de ventas", sm.sales_count], ["Ticket promedio", sm.avg_ticket],
                ["Costo de lo vendido (recetas)", sm.cost_of_sales], ["Utilidad bruta", sm.gross_profit],
                ["Fiado en el periodo", sm.credit_generated], ["Abonos recibidos", sm.abonos],
                ["Gastos (sin inversión)", sm.expenses_total], ["Inversiones", sm.investment_total],
                ["Compras registradas", sm.purchases_total], ["Otros ingresos", sm.other_income],
            ] + [[f"Cobrado: {k}", v] for k, v in sm.by_method.items()], ["text", "money"], sub),
            Sheet("Productos", ["Producto", "Categoría", "Cantidad", "Ventas", "Costo", "Ganancia", "Margen"],
                  [[r.name, r.category, r.quantity, r.revenue, r.cost, r.margin, r.margin_pct] for r in reports.by_product(ds)],
                  ["text", "text", "qty", "money", "money", "money", "pct"], sub),
            Sheet("Categorías", ["Categoría", "Cantidad", "Ventas", "Ganancia", "Margen"],
                  [[r.name, r.quantity, r.revenue, r.margin, r.margin_pct] for r in reports.by_category(ds)],
                  ["text", "qty", "money", "money", "pct"], sub),
            Sheet("Sabores", ["Insumo", "Sabor", "Vasos", "Ventas", "Costo", "Ganancia", "Margen"],
                  [[r.group, r.name, r.cups, r.revenue, r.cost, r.margin, r.margin_pct] for r in reports.by_flavor(ds)],
                  ["text", "text", "qty", "money", "money", "money", "pct"], sub),
            Sheet("Adiciones", ["Opción", "Veces", "Cobrado", "Costo"],
                  [[r.name, r.count, r.revenue, r.cost] for r in reports.by_modifier(ds)],
                  ["text", "qty", "money", "money"], sub),
            Sheet("Estado de resultados", ["Concepto", "Valor"],
                  [[("    " * ln.level) + ln.label, None if ln.is_header else ln.amount] for ln in reports.income_statement(ds)],
                  ["text", "money"], sub),
            Sheet("Flujo de caja", ["Concepto", "Entradas", "Salidas"],
                  [[n, v, None] for n, v in reports.cash_flow(ds).inflows] + [[n, None, v] for n, v in reports.cash_flow(ds).outflows],
                  ["text", "money", "money"], sub),
            Sheet("Ventas por día", ["Día", "Ventas", "N.º ventas"],
                  [[d, v, n] for d, v, n in reports.by_day(ds, self.p)], ["date", "money", "int"], sub),
            Sheet("Comparativo mensual", ["Mes", "Ventas", "Costo recetas", "Insumos", "Gastos", "Inversiones",
                                          "Otros ingresos", "Utilidad operacional", "Resultado de caja"],
                  [[m.label, m.sales, m.cost, m.supplies, m.expenses, m.investment, m.other_income, m.operating_result,
                    m.cash_result] for m in self.months], ["text"] + ["money"] * 8),
        ]
        export_xlsx(path, sheets, self.business)
        toast(self, f"Reportes exportados: {path}")
