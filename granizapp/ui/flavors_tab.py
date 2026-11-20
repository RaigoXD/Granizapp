"""Inventario › Sabores: existencia y ritmo de venta de cada sabor de las bolsas, y qué pedir.

Cada insumo con sabores (p. ej. la mezcla con licor de 6 L) tiene sus sabores; cada sabor tiene
existencia, mínimo y costo propios. Lo vendido sin decir el sabor va a «Sin especificar».
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QHBoxLayout, QSpinBox, QVBoxLayout, QWidget

from granizapp.core.models import Supply, SupplyGroup, Unit
from granizapp.core.services import inventory, purchasing
from granizapp.core.services.settings import get_setting
from granizapp.core.utils import fmt_money, fmt_number
from granizapp.ui.context import AppContext, Topics
from granizapp.ui.dialogs import InfoBanner
from granizapp.ui.widgets.common import button, confirm, info, label, run, toast
from granizapp.ui.widgets.forms import Field, FormDialog
from granizapp.ui.widgets.table import Col, DataTable

PERIODS = [(30, "Ventas de los últimos 30 días"), (14, "Últimos 14 días"), (7, "Últimos 7 días")]
STATUS_COLOR = {"ok": "success", "bajo": "warning", "agotado": "danger", "sin_sabor": "warning"}


def _bags(n: float, group: SupplyGroup | None) -> str:
    pres = (group.presentation_name if group else "") or "bolsa"
    return f"{fmt_number(n, 2)} {pres}{'' if abs(n - 1) < 1e-9 else 's'}"


class FlavorsTab(QWidget):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.groups: list[SupplyGroup] = []
        self.group: SupplyGroup | None = None
        self.stats: list[inventory.FlavorStat] = []
        self.business = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 0)
        bar = QHBoxLayout()
        self.group_cb = QComboBox()
        self.group_cb.setMinimumWidth(300)
        self.group_cb.currentIndexChanged.connect(lambda _i: self.refresh())
        bar.addWidget(self.group_cb)
        self.period_cb = QComboBox()
        for days, text in PERIODS:
            self.period_cb.addItem(text, days)
        self.period_cb.currentIndexChanged.connect(lambda _i: self.refresh())
        bar.addWidget(self.period_cb)
        bar.addWidget(label("Pedir para", "Muted"))
        self.weeks = QSpinBox()
        self.weeks.setRange(1, 8)
        self.weeks.setSuffix(" semanas")
        self.weeks.valueChanged.connect(lambda _v: self.refresh())
        bar.addWidget(self.weeks)
        bar.addStretch(1)
        self.summary = label("", "Muted")
        bar.addWidget(self.summary)
        lay.addLayout(bar)
        self.banner = InfoBanner()
        self.banner.hide()
        lay.addWidget(self.banner)
        self.table = DataTable([
            Col("Sabor", lambda st: st.supply.variant_name, stretch=True, bold=lambda st: st.status != "ok"),
            Col("Código", lambda st: st.supply.variant_code or "", width=70),
            Col("Existencia", lambda st: _bags(st.stock_pres, self.group), width=120,
                color=lambda st: "danger" if st.stock_pres < -0.0001 else None),
            Col("Mínimo", lambda st: _bags(st.min_pres, self.group) if st.min_pres else "", width=95),
            Col("Vasos vendidos", lambda st: st.cups, "qty", width=110),
            Col("Bolsas/semana", lambda st: st.per_week, "number", width=110),
            Col("Alcanza", lambda st: "—" if st.days_left is None else f"{fmt_number(st.days_left, 0)} días", width=90,
                color=lambda st: "danger" if st.days_left is not None and st.days_left < 4 else None),
            Col("Pedir", lambda st: st.suggested or "", "int", width=60, bold=lambda st: st.suggested > 0),
            Col("Costo bolsa", lambda st: st.pres_cost, "money", width=105),
            Col("Estado", lambda st: st.status_label, width=120, color=lambda st: STATUS_COLOR[st.status]),
        ], search=True, placeholder="Buscar sabor…", export_name="sabores",
            footer=lambda rows: f"{len(rows)} sabores")
        self.table.activated.connect(lambda _st: self.edit_flavor())
        lay.addWidget(self.table, 1)
        b1 = QHBoxLayout()
        self.btn_new = button("Nuevo sabor", self.new_flavor, "Primary")
        self.btn_edit = button("Editar sabor", self.edit_flavor)
        b1.addWidget(self.btn_new)
        b1.addWidget(self.btn_edit)
        b1.addWidget(button("Contar sabores", self.count))
        self.btn_reassign = button("Repartir bolsas sin sabor", self.reassign)
        b1.addWidget(self.btn_reassign)
        b1.addStretch(1)
        b1.addWidget(button("Copiar pedido para WhatsApp", self.copy_order))
        self.btn_buy = button("Registrar compra del pedido", self.buy_order)
        b1.addWidget(self.btn_buy)
        lay.addLayout(b1)
        b2 = QHBoxLayout()
        self.btn_group_new = button("Nuevo insumo con sabores", self.new_group)
        self.btn_group_edit = button("Editar insumo con sabores", self.edit_group)
        b2.addWidget(self.btn_group_new)
        b2.addWidget(self.btn_group_edit)
        b2.addStretch(1)
        lay.addLayout(b2)
        lay.addWidget(label(
            "Las recetas gastan el insumo con sabores y en Vender se elige el sabor (cl12 ny, o el número en la "
            "ventana de sabores; F7 lo cambia). «Pedir» cubre las semanas elegidas al ritmo de venta del periodo "
            "y nunca menos que el mínimo. Enter sobre un sabor lo edita.", "Hint", wrap=True))
        with ctx.session() as s:
            self.weeks.blockSignals(True)
            self.weeks.setValue(int(get_setting(s, "flavor_cover_weeks") or 2))
            self.weeks.blockSignals(False)
        admin = ctx.is_admin
        for b in (self.btn_new, self.btn_edit, self.btn_reassign, self.btn_buy, self.btn_group_new, self.btn_group_edit):
            b.setEnabled(admin)
            if not admin:
                b.setToolTip("Solo el administrador")

    # --- datos --------------------------------------------------------------------------------
    def refresh(self):
        cur = self.group_cb.currentData()
        with self.ctx.session() as s:
            self.groups = inventory.list_supply_groups(s)
            self.group = next((g for g in self.groups if g.id == cur), self.groups[0] if self.groups else None)
            self.stats = (inventory.flavor_stats(s, self.group, self.period_cb.currentData() or 30, self.weeks.value())
                          if self.group else [])
            self.business = get_setting(s, "business_name") or ""
            suppliers = purchasing.list_suppliers(s)
        self.supplier_options = [("", "—")] + [(x.id, x.name) for x in suppliers]
        self.group_cb.blockSignals(True)
        self.group_cb.clear()
        for g in self.groups:
            self.group_cb.addItem(g.name, g.id)
        if self.group is not None:
            self.group_cb.setCurrentIndex(max(0, self.group_cb.findData(self.group.id)))
        self.group_cb.blockSignals(False)
        self.table.set_rows(self.stats)
        flavors = [st for st in self.stats if not st.is_default]
        unassigned = next((st for st in self.stats if st.is_default), None)
        total_cups = sum(st.cups for st in self.stats)
        stock = sum(max(0.0, st.stock_pres) for st in flavors)
        self.summary.setText(
            f"{len(flavors)} sabores · {_bags(stock, self.group)} con sabor · {fmt_number(total_cups, 0)} vasos en el periodo"
            if self.group else "No hay insumos con sabores")
        notes = []
        if unassigned is not None and unassigned.stock_pres > 0.0001:
            notes.append(f"Hay <b>{_bags(unassigned.stock_pres, self.group)} sin sabor asignado</b> (vienen de antes de "
                         "manejar sabores o de compras sin sabor). Use «Repartir bolsas sin sabor» o «Contar sabores».")
        elif unassigned is not None and unassigned.stock_pres < -0.0001:
            notes.append(f"Se vendieron <b>{_bags(-unassigned.stock_pres, self.group)} sin decir el sabor</b>, así que "
                         "las existencias de los sabores están por encima de lo real. Se corrige con «Contar sabores» "
                         "(«Sin especificar» queda en 0).")
        if unassigned is not None and total_cups and unassigned.cups:
            pct = unassigned.cups / total_cups * 100
            notes.append(f"{fmt_number(unassigned.cups, 0)} vasos ({fmt_number(pct, 0)} %) se vendieron sin sabor: "
                         "en Vender elija el sabor (número en la ventana de sabores, o F7 sobre la línea).")
        if self.group is not None and not flavors:
            notes.append("Este insumo todavía no tiene sabores: agréguelos con «Nuevo sabor».")
        self.banner.set("<br>".join(notes))
        self.btn_reassign.setVisible(unassigned is not None and unassigned.stock_pres > 0.0001)

    def _notify(self):
        self.ctx.notify(Topics.INVENTORY, Topics.CATALOG)

    # --- sabores ----------------------------------------------------------------------------
    def _flavor_fields(self, creating: bool, is_default: bool = False):
        pres = self.group.presentation_name if self.group else "bolsa"
        fields = []
        if not is_default:
            fields += [
                Field("variant_name", "Sabor", required=True, placeholder="Ej: Maracuyá"),
                Field("variant_code", "Código para vender", placeholder="Ej: MAR",
                      help="Se escribe después del producto en Vender: «cl12 mar». Opcional."),
            ]
        fields += [
            Field("pres_cost", f"Costo de una {pres}", "money", help="Se actualiza solo con cada compra"),
            Field("min_pres", f"Mínimo (en {pres}s)", "number", help="Debajo de esto aparece la alerta «por agotarse»"),
        ]
        if creating:
            fields.append(Field("initial", f"Existencia inicial (en {pres}s)", "number",
                                help="Lo que hay hoy; se puede dejar en 0 y hacer un conteo"))
        fields += [Field("supplier_id", "Proveedor habitual", "choice", options=self.supplier_options)]
        if not is_default:
            fields.append(Field("active", "Activo (aparece en Vender)", "bool", default=True))
        return fields

    def new_flavor(self):
        if self.group is None:
            self.new_group()
            return
        others = [st.pres_cost for st in self.stats if not st.is_default and st.pres_cost]
        data = FormDialog.ask(self, f"Nuevo sabor · {self.group.name}", self._flavor_fields(True),
                              {"pres_cost": int(round(sum(others) / len(others))) if others else 0, "min_pres": 1})
        if data is None:
            return
        gid = self.group.id

        def do():
            with self.ctx.session() as s:
                return inventory.save_variant(s, gid, data, actor=self.ctx.actor).variant_name

        name = run(self, do)
        if name:
            self._notify()
            toast(self, f"Sabor «{name}» creado")

    def edit_flavor(self):
        st = self.table.current()
        if st is None or self.group is None or not self.ctx.is_admin:
            return
        sup = st.supply
        q = self.group.presentation_qty or 1
        values = {"variant_name": sup.variant_name, "variant_code": sup.variant_code or "",
                  "pres_cost": int(round((sup.avg_cost or 0) * q)), "min_pres": (sup.min_stock or 0) / q,
                  "supplier_id": sup.supplier_id or "", "active": sup.active}
        data = FormDialog.ask(self, f"Sabor · {sup.variant_name}", self._flavor_fields(False, st.is_default), values,
                              subtitle="«Sin especificar» recibe lo vendido sin sabor; no se puede renombrar."
                              if st.is_default else "")
        if data is None:
            return
        gid, sid = self.group.id, sup.id

        def do():
            with self.ctx.session() as s:
                inventory.save_variant(s, gid, {**values, **data}, sid, self.ctx.actor)
            return True

        if run(self, do):
            self._notify()

    def count(self):
        """Conteo físico de todos los sabores del grupo (en bolsas)."""
        if self.group is None or not self.stats:
            return
        pres = self.group.presentation_name or "bolsa"
        fields = []
        for i, st in enumerate(self.stats):
            if st.is_default:  # toda bolsa física tiene sabor: lo contado aquí es 0
                fields.append(Field(f"c{i}", st.supply.variant_name, "number", default=0,
                                    help=f"Sistema: {_bags(st.stock_pres, self.group)}. Toda bolsa física tiene "
                                         "sabor: déjelo en 0 (así se corrige lo vendido sin sabor)."))
            else:
                fields.append(Field(f"c{i}", st.supply.variant_name, "number", default=round(st.stock_pres, 2),
                                    help=f"Sistema: {_bags(st.stock_pres, self.group)}"))
        data = FormDialog.ask(self, f"Contar sabores · {self.group.name}", fields, ok_text="Revisar y aplicar",
                              subtitle=f"Cuente todas las {pres}s y escriba cuántas hay de cada sabor "
                                       "(2,5 = dos y media). Solo se registran las que cambian.")
        if data is None:
            return
        q = self.group.presentation_qty or 1
        changes = [(st, data[f"c{i}"] or 0) for i, st in enumerate(self.stats)
                   if abs((data[f"c{i}"] or 0) - st.stock_pres) > 0.004]
        if not changes:
            info(self, "No cambió ningún sabor.", "Conteo")
            return
        net = sum(counted - st.stock_pres for st, counted in changes)
        detail = "\n".join(f"• {st.supply.variant_name}: {fmt_number(st.stock_pres, 2)} → {fmt_number(counted, 2)}"
                           for st, counted in changes)
        verdict = ("sobran" if net > 0 else "faltan") + f" {_bags(abs(net), self.group)} en total"
        if not confirm(self, f"Se registrarán estas diferencias:\n{detail}\n\nNeto: {verdict}. ¿Aplicar el conteo?",
                       "Contar sabores"):
            return
        changes = [(st.supply.id, counted) for st, counted in changes]

        def do():
            value = 0.0
            with self.ctx.session() as s:
                for sid, counted in changes:
                    sup = s.get(Supply, sid)
                    diff = inventory.adjust_to_count(s, sid, max(0.0, counted or 0) * q, self.ctx.actor,
                                                     f"Conteo de sabores: {fmt_number(counted, 2)} {pres}s")
                    value += diff * (sup.avg_cost or 0)
            return value

        value = run(self, do)
        if value is not None:
            self._notify()
            info(self, f"Conteo aplicado a {len(changes)} sabor(es). Diferencia valorizada: {fmt_money(value)} "
                       f"({'sobrante' if value >= 0 else 'faltante / merma'}).", "Conteo de sabores")

    def reassign(self):
        if self.group is None:
            return
        unassigned = next((st for st in self.stats if st.is_default), None)
        flavors = [st for st in self.stats if not st.is_default]
        if unassigned is None or unassigned.stock_pres <= 0 or not flavors:
            return
        pres = self.group.presentation_name or "bolsa"
        fields = [Field(f"r{i}", st.supply.variant_name, "number", help=f"Hoy: {_bags(st.stock_pres, self.group)}")
                  for i, st in enumerate(flavors)]
        data = FormDialog.ask(self, "Repartir bolsas sin sabor", fields, ok_text="Repartir",
                              subtitle=f"Hay {_bags(unassigned.stock_pres, self.group)} sin sabor. Escriba cuántas "
                                       f"{pres}s son de cada sabor. No es merma: solo cambian de sabor.")
        if data is None:
            return
        amounts = {st.supply.id: data[f"r{i}"] or 0 for i, st in enumerate(flavors)}
        gid = self.group.id

        def do():
            with self.ctx.session() as s:
                return inventory.reassign_unspecified(s, gid, amounts, self.ctx.actor)

        moved = run(self, do)
        if moved:
            self._notify()
            toast(self, f"{_bags(moved, self.group)} repartidas entre los sabores")

    # --- pedido -------------------------------------------------------------------------------
    def order_text(self) -> str:
        return inventory.order_text(self.group, self.stats, self.business) if self.group else ""

    def copy_order(self):
        if self.group is None:
            return
        text = self.order_text()
        QApplication.clipboard().setText(text)
        info(self, text + "\n\n(Copiado: péguelo en el chat del proveedor con Ctrl+V)", "Pedido sugerido")

    def buy_order(self):
        if self.group is None:
            return
        lines = [(st.supply.id, st.suggested, int(round(st.suggested * st.pres_cost)))
                 for st in self.stats if st.suggested > 0]
        if not lines:
            info(self, "No hay nada por pedir según las ventas recientes. Puede registrar la compra en Compras.",
                 "Pedido")
            return
        supplier_ids = {st.supply.supplier_id for st in self.stats if st.suggested > 0 and st.supply.supplier_id}
        from granizapp.ui.modules.purchases import PurchaseDialog

        dlg = PurchaseDialog(self, self.ctx, prefill=lines,
                             supplier_id=next(iter(supplier_ids)) if len(supplier_ids) == 1 else None)
        if dlg.exec() == QDialog.Accepted:
            self.ctx.notify(Topics.PURCHASES, Topics.INVENTORY, Topics.FINANCE)
            toast(self, "Compra registrada")

    # --- grupos -------------------------------------------------------------------------------
    def _group_fields(self, creating: bool):
        with self.ctx.session() as s:
            cats = [("", "Sin categoría")] + [(c.id, c.name) for c in inventory.list_supply_categories(s)]
        fields = [
            Field("name", "Nombre", required=True, placeholder="Ej: Base frutal (bolsa 5 L)"),
            Field("category_id", "Categoría", "choice", options=cats),
            Field("unit", "Unidad base", "choice", options=[(u, Unit.LABELS[u]) for u in Unit.CHOICES], default="ml"),
            Field("presentation_name", "Presentación de compra", default="bolsa"),
            Field("presentation_qty", "Contenido de la presentación", "number", default=6000,
                  help="En unidad base: bolsa de 6 L = 6000 ml"),
        ]
        if creating:
            fields.append(Field("pres_cost", "Costo de referencia de una presentación", "money"))
        fields += [
            Field("ask_on_sale", "Preguntar el sabor al vender", "bool", default=True),
            Field("active", "Activo", "bool", default=True),
        ]
        return fields

    def new_group(self):
        data = FormDialog.ask(self, "Nuevo insumo con sabores", self._group_fields(True),
                              subtitle="Después agregue sus sabores y póngalo en la receta de los productos "
                                       "(Productos › Receta) en lugar de un insumo normal.")
        if data is None:
            return

        def do():
            with self.ctx.session() as s:
                return inventory.save_supply_group(s, data, actor=self.ctx.actor).id

        gid = run(self, do)
        if gid:
            self._notify()
            self.group_cb.blockSignals(True)
            self.group_cb.addItem(data["name"], gid)
            self.group_cb.setCurrentIndex(self.group_cb.count() - 1)
            self.group_cb.blockSignals(False)
            self.refresh()

    def edit_group(self):
        g = self.group
        if g is None:
            return
        values = {"name": g.name, "category_id": g.category_id or "", "unit": g.unit,
                  "presentation_name": g.presentation_name, "presentation_qty": g.presentation_qty,
                  "ask_on_sale": g.ask_on_sale, "active": g.active}
        data = FormDialog.ask(self, f"Insumo con sabores · {g.name}", self._group_fields(False), values)
        if data is None:
            return
        gid = g.id

        def do():
            with self.ctx.session() as s:
                inventory.save_supply_group(s, data, gid, self.ctx.actor)
            return True

        if run(self, do):
            self._notify()
