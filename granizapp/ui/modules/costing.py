"""Costeo: costo por vaso, margen, rendimiento por bolsa y calculadora de calibración."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from granizapp.core.services import catalog, costing, inventory
from granizapp.core.utils import fmt_money, fmt_number, fmt_pct
from granizapp.ui.context import AppContext, Topics
from granizapp.ui.recipe_dialog import RecipeDialog
from granizapp.ui.widgets.common import KpiCard, Page, button, card, confirm, label, page_header, run
from granizapp.ui.widgets.forms import NumberEdit
from granizapp.ui.widgets.table import Col, DataTable


class CostingPage(Page):
    topics = {Topics.CATALOG, Topics.INVENTORY, Topics.PURCHASES}

    def __init__(self, ctx: AppContext):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.addWidget(page_header("Costeo y rendimiento",
                                   "Cuánto cuesta cada vaso, cuánto deja y cuántos vasos rinde cada bolsa"))
        kpis = QHBoxLayout()
        self.k_avg = KpiCard("Margen promedio")
        self.k_low = KpiCard("Productos con margen bajo (< 60 %)")
        self.k_norecipe = KpiCard("Productos sin receta")
        for k in (self.k_avg, self.k_low, self.k_norecipe):
            kpis.addWidget(k)
        root.addLayout(kpis)
        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # costo por producto
        w = QWidget()
        wl = QVBoxLayout(w)
        wl.setContentsMargins(0, 8, 0, 0)
        self.table = DataTable([
            Col("Producto", lambda c: c.product.name, stretch=True),
            Col("Precio", lambda c: c.price, "money", width=95),
            Col("Costo", lambda c: c.cost, "money", width=95),
            Col("Ganancia por unidad", lambda c: c.margin, "money", width=140, bold=lambda c: True),
            Col("Margen", lambda c: c.margin_pct, "pct", width=80,
                color=lambda c: None if c.margin_pct is None else (
                    "danger" if c.margin_pct < 0.4 else "warning" if c.margin_pct < 0.6 else "success")),
            Col("Costo / precio", lambda c: c.cost_pct, "pct", width=110),
            Col("Receta", lambda c: "Sí" if c.has_recipe else "Falta", width=70,
                color=lambda c: None if c.has_recipe else "warning"),
        ], search=True, placeholder="Buscar producto…", export_name="costeo_productos")
        self.table.activated.connect(self.open_recipe)
        self.table.selection_changed.connect(self._show_breakdown)
        wl.addWidget(self.table, 2)
        self.breakdown = DataTable([
            Col("Insumo", lambda l: l.name, stretch=True),
            Col("Cantidad", lambda l: l.quantity, "qty", width=90),
            Col("Unidad", lambda l: l.unit, width=60),
            Col("Costo unitario", lambda l: l.unit_cost, "number", width=110),
            Col("Costo", lambda l: l.cost, "money", width=95),
            Col("% del costo", lambda l: l.cost / self._cur_cost if self._cur_cost else None, "pct", width=90),
        ])
        self._cur_cost = 0
        f, fl = card(title="Desglose del costo (Enter sobre un producto para editar su receta)")
        fl.addWidget(self.breakdown)
        wl.addWidget(f, 1)
        tabs.addTab(w, "Costo por producto")

        # rendimiento
        y = QWidget()
        yl = QVBoxLayout(y)
        yl.setContentsMargins(0, 8, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(label("Insumo:"))
        self.supply = QComboBox()
        self.supply.setMinimumWidth(320)
        self.supply.currentIndexChanged.connect(lambda _i: self._load_yields())
        bar.addWidget(self.supply)
        bar.addStretch(1)
        yl.addLayout(bar)
        self.yield_info = label("", "Muted", wrap=True)
        yl.addWidget(self.yield_info)
        self.yields = DataTable([
            Col("Producto", lambda r: r.product.name, stretch=True),
            Col("Gasta por unidad", lambda r: f"{fmt_number(r.per_unit, 1)} {self._unit}", width=140),
            Col("Unidades por presentación", lambda r: r.units_per_presentation, "qty", width=180, bold=lambda r: True),
            Col("Costo de este insumo por unidad", lambda r: r.cost_per_unit, "money", width=210),
            Col("Precio", lambda r: r.product.price, "money", width=90),
        ], export_name="rendimiento")
        yl.addWidget(self.yields, 1)
        calc_frame, cl = card(title="Calculadora de rendimiento")
        row = QHBoxLayout()
        form1 = QFormLayout()
        self.c_ml = NumberEdit(6000)
        self.c_oz = QDoubleSpinBox()
        self.c_oz.setRange(1, 64)
        self.c_oz.setValue(12)
        self.c_fill = QSpinBox()
        self.c_fill.setRange(50, 120)
        self.c_fill.setValue(90)
        self.c_fill.setSuffix(" %")
        for wdg in (self.c_oz, self.c_fill):
            wdg.valueChanged.connect(lambda _v: self._calc())
        self.c_ml.value_changed.connect(lambda _v: self._calc())
        self.c_out = label("", "SectionTitle")
        form1.addRow("Volumen de la bolsa (ml)", self.c_ml)
        form1.addRow("Tamaño del vaso (oz)", self.c_oz)
        form1.addRow("Llenado del vaso", self.c_fill)
        form1.addRow("Vasos teóricos", self.c_out)
        row.addLayout(form1)
        form2 = QFormLayout()
        self.r_cups = QDoubleSpinBox()
        self.r_cups.setRange(0.1, 1000)
        self.r_cups.setValue(18)
        self.r_cups.setDecimals(1)
        self.r_cups.valueChanged.connect(lambda _v: self._calc())
        self.r_out = label("", "SectionTitle")
        self.r_product = QComboBox()
        form2.addRow("Rendimiento real: 1 bolsa dio", self.r_cups)
        form2.addRow("Equivale a por vaso", self.r_out)
        form2.addRow("Aplicar a la receta de", self.r_product)
        apply = button("Aplicar cantidad a la receta", self.apply_yield, "Primary")
        form2.addRow("", apply)
        row.addLayout(form2)
        cl.addLayout(row)
        cl.addWidget(label("Tip: el día que se termine una bolsa, cuente cuántos vasos salieron y aplíquelo aquí. "
                           "Así el costo por vaso y el inventario quedan exactos.", "Hint", wrap=True))
        yl.addWidget(calc_frame)
        tabs.addTab(y, "Rendimiento por bolsa")

        # adiciones
        a = QWidget()
        al = QVBoxLayout(a)
        al.setContentsMargins(0, 8, 0, 0)
        self.options = DataTable([
            Col("Adición", lambda o: o.name, stretch=True),
            Col("Cobro extra", lambda o: o.price, "money", width=110),
            Col("Costo", lambda o: o.cost, "money", width=95),
            Col("Ganancia", lambda o: o.price - o.cost, "money", width=95,
                color=lambda o: "danger" if o.price - o.cost < 0 else None),
        ], export_name="costeo_adiciones")
        al.addWidget(self.options)
        al.addWidget(label("Las opciones sin cobro extra (ej. escarchado incluido) aparecen con ganancia negativa: "
                           "es lo que cuesta regalarlas.", "Hint", wrap=True))
        tabs.addTab(a, "Adiciones")

    def refresh(self):
        with self.ctx.session() as s:
            rows = costing.costing_table(s)
            opts = costing.options_costing(s)
            supplies = inventory.list_supplies(s)
            products = catalog.list_products(s)
        self.table.set_rows(rows)
        self.options.set_rows(opts)
        with_recipe = [r for r in rows if r.has_recipe and r.price]
        avg = sum(r.margin_pct for r in with_recipe) / len(with_recipe) if with_recipe else None
        self.k_avg.set(fmt_pct(avg) if avg is not None else "—")
        low = [r for r in with_recipe if r.margin_pct < 0.6]
        self.k_low.set(str(len(low)), ", ".join(r.product.name for r in low[:3]), "warning" if low else None)
        missing = [r for r in rows if not r.has_recipe and r.product.kind != "servicio"]
        self.k_norecipe.set(str(len(missing)), ", ".join(r.product.name for r in missing[:3]),
                            "warning" if missing else None)
        cur = self.supply.currentData()
        self.supply.blockSignals(True)
        self.supply.clear()
        multi = [x for x in supplies if (x.presentation_qty or 1) > 1]
        for x in multi:
            self.supply.addItem(x.name, x.id)
        idx = self.supply.findData(cur or "seed-su-mezcla-cl")
        self.supply.setCurrentIndex(max(0, idx))
        self.supply.blockSignals(False)
        self.r_product.clear()
        for p in products:
            self.r_product.addItem(p.name, p.id)
        self._load_yields()
        self._calc()
        if self.table.current() is None:
            self.table.select_first()

    def _show_breakdown(self, pc):
        if pc is None:
            self.breakdown.set_rows([])
            return
        self._cur_cost = pc.cost
        self.breakdown.set_rows(pc.lines)

    def _load_yields(self):
        sid = self.supply.currentData()
        if not sid:
            self.yields.set_rows([])
            return
        with self.ctx.session() as s:
            sup = inventory.ensure_supply(s, sid)
            rows = costing.yields_for_supply(s, sup)
        self._unit = sup.unit
        self._supply = sup
        self.yield_info.setText(
            f"1 {sup.presentation_name} = {fmt_number(sup.presentation_qty)} {sup.unit} · costo promedio "
            f"{fmt_money((sup.avg_cost or 0) * sup.presentation_qty)} por {sup.presentation_name} "
            f"({fmt_number(sup.avg_cost or 0, 2)} $/{sup.unit})")
        self.c_ml.setValue(sup.presentation_qty)
        self.yields.set_rows(rows)
        for r in rows:
            idx = self.r_product.findData(r.product.id)
            if idx >= 0:
                self.r_product.setCurrentIndex(idx)
                break

    def _calc(self):
        cups = costing.cups_from_volume(self.c_ml.value(), self.c_oz.value(), self.c_fill.value() / 100)
        self.c_out.setText(f"{fmt_number(cups, 1)} vasos")
        per = costing.quantity_from_yield(self.c_ml.value(), self.r_cups.value())
        self.r_out.setText(f"{fmt_number(per, 1)} {getattr(self, '_unit', 'ml')}")

    def open_recipe(self, pc):
        if RecipeDialog(self, self.ctx, product_id=pc.product.id, title=pc.product.name,
                        price=pc.product.price).exec() == QDialog.Accepted:
            self.ctx.notify(Topics.CATALOG)

    def apply_yield(self):
        sup = getattr(self, "_supply", None)
        pid = self.r_product.currentData()
        if sup is None or not pid:
            return
        per = costing.quantity_from_yield(sup.presentation_qty, self.r_cups.value())
        name = self.r_product.currentText()
        if not confirm(self, f"¿Poner {fmt_number(per, 1)} {sup.unit} de «{sup.name}» en la receta de «{name}»?"):
            return

        def do():
            with self.ctx.session() as s:
                lines = catalog.recipe_lines(s, pid)
                data = [{"supply_id": ln.supply_id, "sub_product_id": ln.sub_product_id, "quantity": ln.quantity,
                         "notes": ln.notes} for ln in lines]
                found = False
                for d in data:
                    if d["supply_id"] == sup.id:
                        d["quantity"] = per
                        found = True
                if not found:
                    data.append({"supply_id": sup.id, "quantity": per})
                catalog.set_recipe(s, data, pid)
            return True

        if run(self, do):
            self.ctx.notify(Topics.CATALOG)
