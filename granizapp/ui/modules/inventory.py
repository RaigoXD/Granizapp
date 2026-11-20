"""Inventario de insumos: existencias, conteo físico, mermas, kardex y catálogo de insumos."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from granizapp.core.models import MovementKind, Unit
from granizapp.core.services import inventory, purchasing
from granizapp.core.utils import fmt_money, fmt_number
from granizapp.ui.context import AppContext, Topics
from granizapp.ui.flavors_tab import FlavorsTab
from granizapp.ui.widgets.common import (
    KpiCard,
    Page,
    PeriodSelector,
    button,
    confirm,
    info,
    label,
    page_header,
    run,
)
from granizapp.ui.widgets.crud import CrudPanel
from granizapp.ui.widgets.forms import Field, FormDialog, NumberEdit
from granizapp.ui.widgets.table import Col, DataTable


def _pres(s) -> str:
    return f"{s.presentation_name} ({fmt_number(s.presentation_qty, 2)} {s.unit})" if s.presentation_qty != 1 else s.unit


class InventoryPage(Page):
    topics = {Topics.INVENTORY, Topics.SALES, Topics.PURCHASES, Topics.CATALOG}

    def __init__(self, ctx: AppContext):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.addWidget(page_header("Inventario", "Insumos: bolsas de mezcla, perlas, sales, vasos, cervezas…"))
        kpis = QHBoxLayout()
        self.k_value = KpiCard("Valor del inventario")
        self.k_low = KpiCard("Por agotarse")
        self.k_out = KpiCard("Agotados / negativos")
        self.k_items = KpiCard("Insumos activos")
        for k in (self.k_value, self.k_low, self.k_out, self.k_items):
            kpis.addWidget(k)
        root.addLayout(kpis)
        self.unassigned: set[str] = set()
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        # existencias
        w = QWidget()
        wl = QVBoxLayout(w)
        wl.setContentsMargins(0, 8, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(button("Merma / daño", lambda: self.adjust(MovementKind.WASTE)))
        bar.addWidget(button("Entrada o ajuste manual", lambda: self.adjust(MovementKind.ADJUST)))
        bar.addWidget(button("Contar este insumo", self.count_one))
        bar.addWidget(button("Ver kardex", self.show_kardex))
        bar.addStretch(1)
        self.only_alerts = QCheckBox("Solo alertas")
        self.only_alerts.toggled.connect(lambda _c: self._fill_stock())
        bar.addWidget(self.only_alerts)
        wl.addLayout(bar)
        self.stock = DataTable([
            Col("Insumo", lambda r: r.supply.name, stretch=True, bold=lambda r: r.status != "ok"),
            Col("Categoría", lambda r: r.category, width=190),
            Col("Existencia", lambda r: inventory.presentation_text(r.supply, r.stock), width=220),
            Col("Mínimo", lambda r: inventory.presentation_text(r.supply, r.supply.min_stock) if r.supply.min_stock else "", width=170),
            Col("Costo x presentación", lambda r: (r.supply.avg_cost or 0) * (r.supply.presentation_qty or 1), "money", width=140),
            Col("Valor", lambda r: r.value, "money", width=100),
            Col("Estado", lambda r: r.status_label, width=80,
                color=lambda r: {"ok": "success", "bajo": "warning", "agotado": "danger", "sin_sabor": "warning"}[r.status]),
        ], search=True, placeholder="Buscar insumo…", export_name="existencias",
            footer=lambda rows: f"{len(rows)} insumos · valor {fmt_money(sum(r.value for r in rows))}")
        self.stock.activated.connect(lambda _r: self.show_kardex())
        wl.addWidget(self.stock, 1)
        wl.addWidget(label("Las ventas descuentan insumos según la receta de cada producto. Las compras los suman. "
                           "El conteo físico corrige la diferencia (y la registra como merma o sobrante).", "Hint", wrap=True))
        self.tabs.addTab(w, "Existencias")

        # sabores de las bolsas (insumos con sabores)
        self.flavors = FlavorsTab(ctx)
        self.tabs.addTab(self.flavors, "Sabores")

        # conteo físico
        c = QWidget()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(0, 8, 0, 0)
        cl.addWidget(label("Escriba lo que contó en la columna «Contado» (en la presentación indicada; acepta "
                           "decimales, ej. 2,5 bolsas). Deje vacío lo que no contó. Las bolsas de mezcla se cuentan "
                           "mejor por sabor en la pestaña Sabores («Contar sabores»).", "Muted", wrap=True))
        self.count_table = QTableWidget(0, 5)
        self.count_table.setHorizontalHeaderLabels(["Insumo", "Presentación", "Sistema", "Contado", "Diferencia"])
        self.count_table.verticalHeader().setVisible(False)
        self.count_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for i, wd in enumerate([0, 200, 110, 110, 110]):
            if wd:
                self.count_table.setColumnWidth(i, wd)
        self.count_table.verticalHeader().setDefaultSectionSize(34)
        cl.addWidget(self.count_table, 1)
        cb = QHBoxLayout()
        cb.addStretch(1)
        cb.addWidget(button("Aplicar conteo", self.apply_count, "Primary"))
        cl.addLayout(cb)
        self.tabs.addTab(c, "Conteo físico")

        # kardex
        k = QWidget()
        kl = QVBoxLayout(k)
        kl.setContentsMargins(0, 8, 0, 0)
        kb = QHBoxLayout()
        self.k_period = PeriodSelector("7dias")
        self.k_period.changed.connect(lambda _p: self._load_kardex())
        kb.addWidget(self.k_period)
        self.k_supply = QComboBox()
        self.k_supply.currentIndexChanged.connect(lambda _i: self._load_kardex())
        kb.addWidget(self.k_supply)
        self.k_kind = QComboBox()
        self.k_kind.addItem("Todos los movimientos", "")
        for key, text in MovementKind.LABELS.items():
            self.k_kind.addItem(text, key)
        self.k_kind.currentIndexChanged.connect(lambda _i: self._load_kardex())
        kb.addWidget(self.k_kind)
        kb.addStretch(1)
        kl.addLayout(kb)
        self.kardex = DataTable([
            Col("Fecha", lambda m: m.at, "datetime", width=150),
            Col("Insumo", lambda m: self.sup_names.get(m.supply_id, ""), width=230),
            Col("Movimiento", lambda m: MovementKind.LABELS.get(m.kind, m.kind), width=150),
            Col("Cantidad", lambda m: m.quantity, "qty", width=100, color=lambda m: "success" if m.quantity > 0 else "danger"),
            Col("Unidad", lambda m: self.sup_units.get(m.supply_id, ""), width=60),
            Col("Costo unit.", lambda m: m.unit_cost, "number", width=90),
            Col("Valor", lambda m: m.quantity * (m.unit_cost or 0), "money", width=100),
            Col("Detalle", lambda m: m.note, stretch=True),
        ], search=True, export_name="kardex", footer=lambda rows: f"{len(rows)} movimientos")
        kl.addWidget(self.kardex, 1)
        self.kardex_tab = k
        self.tabs.addTab(k, "Kardex (movimientos)")

        # insumos (catálogo)
        self.supplies_panel = CrudPanel(
            ctx, "Insumo",
            [Col("Insumo", lambda s: s.name, stretch=True),
             Col("Categoría", lambda s: self.cat_names.get(s.category_id, ""), width=190),
             Col("Unidad", lambda s: s.unit, width=55),
             Col("Presentación", _pres, width=190),
             Col("Costo x presentación", lambda s: (s.avg_cost or 0) * (s.presentation_qty or 1), "money", width=140),
             Col("Último costo", lambda s: (s.last_cost or 0) * (s.presentation_qty or 1), "money", width=110),
             Col("Proveedor", lambda s: self.sup_suppliers.get(s.supplier_id, ""), width=150),
             Col("Activo", lambda s: s.active, "bool", width=55)],
            load=lambda s: inventory.list_supplies(s, include_inactive=True),
            fields=self._supply_fields,
            save=self._save_supply,
            delete=lambda s, sid: inventory.delete_supply(s, sid, self.ctx.actor),
            to_values=self._supply_values,
            topics=(Topics.INVENTORY, Topics.CATALOG),
            admin_only=True,
        )
        self.tabs.addTab(self.supplies_panel, "Insumos")
        self.cats_panel = CrudPanel(
            ctx, "Categoría de insumo",
            [Col("Categoría", lambda c: c.name, stretch=True), Col("Orden", lambda c: c.sort_order, "int", width=60)],
            load=inventory.list_supply_categories,
            fields=lambda s: [Field("name", "Nombre", required=True), Field("sort_order", "Orden", "int")],
            save=lambda s, d, cid: inventory.save_supply_category(s, d, cid),
            delete=lambda s, cid: inventory.delete_supply_category(s, cid),
            topics=(Topics.INVENTORY,), admin_only=True,
        )
        self.tabs.addTab(self.cats_panel, "Categorías de insumo")

    # --- datos ------------------------------------------------------------------------------------
    def refresh(self):
        with self.ctx.session() as s:
            self.rows = inventory.stock_levels(s)
            self.unassigned = inventory.unassigned_ids(s)
            cats = inventory.list_supply_categories(s)
            supplies = inventory.list_supplies(s, include_inactive=True)
            suppliers = purchasing.list_suppliers(s, include_inactive=True)
        self.cat_names = {c.id: c.name for c in cats}
        self.sup_names = {x.id: x.name for x in supplies}
        self.sup_units = {x.id: x.unit for x in supplies}
        self.sup_suppliers = {x.id: x.name for x in suppliers}
        self.supplier_options = [("", "—")] + [(x.id, x.name) for x in suppliers if x.active]
        self.cat_options = [("", "Sin categoría")] + [(c.id, c.name) for c in cats]
        low = [r for r in self.rows if r.status == "bajo"]
        out = [r for r in self.rows if r.status == "agotado" and (r.supply.min_stock or r.stock < 0)]
        # «Sin especificar» de los sabores no es una alerta de compra (se ve en la pestaña Sabores)
        self.k_value.set(fmt_money(sum(r.value for r in self.rows)))
        self.k_low.set(str(len(low)), ", ".join(r.supply.name for r in low[:3]), "warning" if low else None)
        self.k_out.set(str(len(out)), ", ".join(r.supply.name for r in out[:3]), "danger" if out else None)
        self.k_items.set(str(len(self.rows)))
        self._fill_stock()
        self._fill_count()
        cur = self.k_supply.currentData()
        self.k_supply.blockSignals(True)
        self.k_supply.clear()
        self.k_supply.addItem("Todos los insumos", "")
        for x in supplies:
            self.k_supply.addItem(x.name, x.id)
        self.k_supply.setCurrentIndex(max(0, self.k_supply.findData(cur or "")))
        self.k_supply.blockSignals(False)
        self._load_kardex()
        self.flavors.refresh()
        self.supplies_panel.refresh()
        self.cats_panel.refresh()

    def _fill_stock(self):
        rows = self.rows
        if self.only_alerts.isChecked():
            rows = [r for r in rows if r.status != "ok"]
        self.stock.set_rows(rows)

    def _typed_counts(self) -> dict[str, str]:
        """Lo que el usuario ya escribió en «Contado» (para no perderlo si la pantalla se refresca)."""
        typed = {}
        for i in range(self.count_table.rowCount()):
            edit = self.count_table.cellWidget(i, 3)
            if edit is not None and edit.text().strip():
                typed[self.count_table.item(i, 0).data(Qt.UserRole)] = edit.text()
        return typed

    def _fill_count(self):
        typed = self._typed_counts()
        self.count_table.setRowCount(0)
        for r in self.rows:
            if r.supply.id in self.unassigned:  # «Sin especificar» se corrige al contar en Sabores
                continue
            i = self.count_table.rowCount()
            self.count_table.insertRow(i)
            it = QTableWidgetItem(r.supply.name)
            it.setData(Qt.UserRole, r.supply.id)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.count_table.setItem(i, 0, it)
            pres = r.supply.presentation_name if r.supply.presentation_qty != 1 else r.supply.unit
            p = QTableWidgetItem(f"{pres}" + (f" ({fmt_number(r.supply.presentation_qty)} {r.supply.unit})"
                                              if r.supply.presentation_qty != 1 else ""))
            p.setFlags(p.flags() & ~Qt.ItemIsEditable)
            self.count_table.setItem(i, 1, p)
            sys_qty = QTableWidgetItem(fmt_number(r.presentations, 2))
            sys_qty.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            sys_qty.setFlags(sys_qty.flags() & ~Qt.ItemIsEditable)
            self.count_table.setItem(i, 2, sys_qty)
            edit = NumberEdit(0, decimals=2)
            edit.setText(typed.get(r.supply.id, ""))
            diff = QLabel()
            diff.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            show_diff = lambda _t=None, e=edit, d=diff, cur=r.presentations: d.setText(  # noqa: E731
                fmt_number(e.value() - cur, 2) if e.text().strip() else "")
            edit.textEdited.connect(show_diff)
            if edit.text():
                show_diff()
            self.count_table.setCellWidget(i, 3, edit)
            self.count_table.setCellWidget(i, 4, diff)

    def _load_kardex(self):
        p = self.k_period.period()
        start, end = p.bounds
        with self.ctx.session() as s:
            rows = inventory.list_movements(s, self.k_supply.currentData() or None, start, end,
                                            self.k_kind.currentData() or None)
        self.kardex.set_rows(rows)

    # --- acciones ------------------------------------------------------------------------------------
    def adjust(self, kind: str):
        r = self.stock.current()
        options = [(x.supply.id, x.supply.name) for x in self.rows]
        title = "Registrar merma / daño" if kind == MovementKind.WASTE else "Entrada o ajuste manual"
        help_txt = ("Lo que se botó, se dañó o se regaló. Se descuenta del inventario."
                    if kind == MovementKind.WASTE else "Positivo suma al inventario, negativo resta. En la unidad base.")
        data = FormDialog.ask(self, title, [
            Field("supply_id", "Insumo", "choice", options=options, default=r.supply.id if r else None),
            Field("quantity", "Cantidad (unidad base: ml, g o und)", "number", required=True, help=help_txt),
            Field("note", "Motivo", required=True),
        ])
        if data is None:
            return

        def do():
            with self.ctx.session() as s:
                inventory.register_adjustment(s, data["supply_id"], data["quantity"], kind, self.ctx.actor, data["note"])
            return True

        if run(self, do):
            self.ctx.notify(Topics.INVENTORY)

    def count_one(self):
        r = self.stock.current()
        if r is None:
            return
        s = r.supply
        data = FormDialog.ask(self, f"Conteo de {s.name}", [
            Field("counted", f"Contado (en {s.presentation_name if s.presentation_qty != 1 else s.unit})", "number",
                  default=round(r.presentations, 2), help=f"Sistema: {inventory.presentation_text(s, r.stock)}"),
            Field("note", "Nota"),
        ])
        if data is None:
            return

        def do():
            with self.ctx.session() as ses:
                return inventory.adjust_to_count(ses, s.id, data["counted"] * (s.presentation_qty or 1), self.ctx.actor,
                                                 data["note"])

        diff = run(self, do)
        if diff is not None:
            self.ctx.notify(Topics.INVENTORY)

    def apply_count(self):
        entries = []
        for i in range(self.count_table.rowCount()):
            edit = self.count_table.cellWidget(i, 3)
            if edit.text().strip():
                sid = self.count_table.item(i, 0).data(Qt.UserRole)
                entries.append((sid, edit.value()))
        if not entries:
            info(self, "No escribió ningún conteo.", "Conteo físico")
            return
        if not confirm(self, f"¿Aplicar el conteo de {len(entries)} insumo(s)? Las diferencias quedan registradas."):
            return
        rows = {r.supply.id: r for r in self.rows}

        def do():
            total = 0.0
            with self.ctx.session() as s:
                for sid, counted in entries:
                    sup = rows[sid].supply
                    diff = inventory.adjust_to_count(s, sid, counted * (sup.presentation_qty or 1), self.ctx.actor)
                    total += diff * (sup.avg_cost or 0)
            return total

        value = run(self, do)
        if value is not None:
            self.ctx.notify(Topics.INVENTORY)
            info(self, f"Conteo aplicado. Diferencia valorizada: {fmt_money(value)} "
                       f"({'sobrante' if value >= 0 else 'faltante / merma'}).", "Conteo físico")

    def show_kardex(self):
        r = self.stock.current()
        if r is not None:
            self.k_supply.setCurrentIndex(max(0, self.k_supply.findData(r.supply.id)))
        self.tabs.setCurrentWidget(self.kardex_tab)

    # --- formulario de insumo ------------------------------------------------------------------------
    def _supply_fields(self, s):
        return [
            Field("name", "Nombre", required=True, placeholder="Ej: Mezcla granizado con licor (bolsa 6 L)"),
            Field("category_id", "Categoría", "choice", options=self.cat_options),
            Field("unit", "Unidad base", "choice", options=[(u, Unit.LABELS[u]) for u in Unit.CHOICES],
                  help="Unidad en la que se escriben las recetas: ml para líquidos, g para polvos/perlas, und para vasos"),
            Field("presentation_name", "Presentación de compra", placeholder="bolsa, tarro, paquete x50, paca x24"),
            Field("presentation_qty", "Contenido de la presentación", "number", default=1,
                  help="En unidad base. Ej: bolsa de 6 L = 6000 ml; paquete de 50 vasos = 50"),
            Field("pres_cost", "Costo de una presentación", "money",
                  help="Se actualiza solo con cada compra (costo promedio)"),
            Field("min_pres", "Mínimo (en presentaciones)", "number", help="Para la alerta de 'por agotarse'"),
            Field("initial", "Existencia inicial (en presentaciones)", "number", help="Solo al crear"),
            Field("supplier_id", "Proveedor habitual", "choice", options=self.supplier_options),
            Field("active", "Activo", "bool", default=True),
            Field("notes", "Notas", "multiline"),
        ]

    def _supply_values(self, s):
        q = s.presentation_qty or 1
        return {
            "name": s.name, "category_id": s.category_id or "", "unit": s.unit, "presentation_name": s.presentation_name,
            "presentation_qty": q, "pres_cost": int(round((s.avg_cost or 0) * q)),
            "min_pres": (s.min_stock or 0) / q, "supplier_id": s.supplier_id or "", "active": s.active, "notes": s.notes,
        }

    def _save_supply(self, s, data, sid):
        q = data.get("presentation_qty") or 1
        payload = dict(data)
        payload["avg_cost"] = (data.get("pres_cost") or 0) / q
        payload["min_stock"] = (data.get("min_pres") or 0) * q
        payload["initial_stock"] = (data.get("initial") or 0) * q
        return inventory.save_supply(s, payload, sid, self.ctx.actor)
