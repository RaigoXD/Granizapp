"""Editor de recetas (ficha técnica) para productos y adiciones."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QTableWidget,
    QVBoxLayout,
)

from granizapp.core.models import Product, Supply
from granizapp.core.services import catalog, costing, inventory
from granizapp.core.utils import fmt_money, fmt_number, fmt_pct
from granizapp.ui.context import AppContext
from granizapp.ui.widgets.common import button, label, show_error
from granizapp.ui.widgets.forms import NumberEdit


class RecipeDialog(QDialog):
    def __init__(self, parent, ctx: AppContext, product_id: str | None = None, option_id: str | None = None,
                 title: str = "", price: int = 0):
        super().__init__(parent)
        self.ctx = ctx
        self.product_id = product_id
        self.option_id = option_id
        self.price = price
        self.setWindowTitle(f"Receta · {title}")
        self.resize(820, 520)
        with ctx.session() as s:
            self.groups = inventory.list_supply_groups(s)
            unassigned = inventory.unassigned_ids(s)  # «Sin especificar» se usa solo a través del grupo
            self.supplies: list[Supply] = [x for x in inventory.list_supplies(s) if x.id not in unassigned]
            self.products: list[Product] = [p for p in catalog.list_products(s, True) if p.id != product_id]
            self.book = catalog.RecipeBook(s)
            lines = catalog.recipe_lines(s, product_id, option_id)
        self.sup_by_id = {s.id: s for s in self.supplies}
        self.grp_by_id = {g.id: g for g in self.groups}
        lay = QVBoxLayout(self)
        lay.addWidget(label(f"Receta de «{title}»", "SectionTitle"))
        lay.addWidget(label(
            "Cantidades por UNA unidad vendida, en la unidad del insumo (ml, g o und). Se descuentan del inventario "
            "en cada venta y dan el costo por vaso. Las bolsas con sabores se eligen como «… · sabor al vender»: "
            "el sabor se pregunta en Vender. Para combos/promos agregue productos (p. ej. 2 × Granizado CL 12 oz).",
            "Muted", wrap=True))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Insumo o producto", "Cantidad", "Unidad", "Costo unitario", "Costo"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for i, w in enumerate([0, 110, 70, 110, 100]):
            if w:
                self.table.setColumnWidth(i, w)
        self.table.verticalHeader().setDefaultSectionSize(36)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(button("Agregar línea", self.add_line, "", "Ctrl+N"))
        QShortcut(QKeySequence("Ctrl+N"), self, activated=lambda: self.add_line())
        row.addWidget(button("Quitar línea", self.remove_line))
        row.addWidget(button("Calibrar: «1 bolsa rinde N vasos»…", self.calibrate,
                             tip="Calcula la cantidad por vaso a partir del rendimiento real de una presentación"))
        row.addStretch(1)
        lay.addLayout(row)
        self.totals = label("", "SectionTitle")
        lay.addWidget(self.totals)
        self.yield_lbl = label("", "Muted", wrap=True)
        lay.addWidget(self.yield_lbl)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Guardar receta")
        bb.button(QDialogButtonBox.Save).setObjectName("Primary")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for line in lines:
            if line.supply_group_id:
                ref = f"g:{line.supply_group_id}"
            elif line.supply_id:
                ref = f"s:{line.supply_id}"
            else:
                ref = f"p:{line.sub_product_id}"
            self.add_line(ref, line.quantity)
        self._recalc()

    def _combo(self, ref: str | None) -> QComboBox:
        cb = QComboBox()
        cb.setEditable(True)
        cb.setInsertPolicy(QComboBox.NoInsert)
        cb.addItem("— elegir —", "")
        for g in self.groups:
            cb.addItem(f"{g.name} · sabor al vender  [{g.unit}]", f"g:{g.id}")
        for s in self.supplies:
            cb.addItem(f"{s.name}  [{s.unit}]", f"s:{s.id}")
        if self.product_id:
            for p in self.products:
                cb.addItem(f"Producto: {p.name}", f"p:{p.id}")
        comp = cb.completer()
        comp.setFilterMode(Qt.MatchContains)
        comp.setCompletionMode(QCompleter.PopupCompletion)
        idx = cb.findData(ref or "")
        cb.setCurrentIndex(max(0, idx))
        cb.currentIndexChanged.connect(lambda _i: self._recalc())
        return cb

    def add_line(self, ref: str | None = None, qty: float = 0):
        r = self.table.rowCount()
        self.table.insertRow(r)
        cb = self._combo(ref if isinstance(ref, str) else None)
        self.table.setCellWidget(r, 0, cb)
        q = NumberEdit(qty, decimals=3)
        q.value_changed.connect(lambda _v: self._recalc())
        self.table.setCellWidget(r, 1, q)
        for c in (2, 3, 4):
            lb = QLabel()
            lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter if c > 2 else Qt.AlignCenter)
            self.table.setCellWidget(r, c, lb)
        if not ref:
            cb.setFocus()
        self._recalc()

    def remove_line(self):
        r = self.table.currentRow()
        if r < 0:
            r = self.table.rowCount() - 1
        if r >= 0:
            self.table.removeRow(r)
            self._recalc()

    def _lines(self) -> list[tuple[str, float]]:
        out = []
        for r in range(self.table.rowCount()):
            ref = self.table.cellWidget(r, 0).currentData()
            qty = self.table.cellWidget(r, 1).value()
            out.append((ref or "", qty))
        return out

    def _presentation(self, ref: str):
        """(nombre, presentación, contenido, unidad) del insumo o insumo con sabores de la línea."""
        if ref.startswith("s:") and ref[2:] in self.sup_by_id:
            s = self.sup_by_id[ref[2:]]
            return s.name, s.presentation_name, s.presentation_qty, s.unit
        if ref.startswith("g:") and ref[2:] in self.grp_by_id:
            g = self.grp_by_id[ref[2:]]
            return g.name, g.presentation_name, g.presentation_qty, g.unit
        return None

    def _unit_cost(self, ref: str) -> tuple[str, float]:
        if ref.startswith("g:"):
            g = self.grp_by_id.get(ref[2:])
            return (g.unit, self.book.group_cost(g.id)) if g else ("", 0)
        if ref.startswith("s:"):
            s = self.sup_by_id.get(ref[2:])
            return (s.unit, s.avg_cost or 0) if s else ("", 0)
        if ref.startswith("p:"):
            return "und", self.book.product_cost(ref[2:])
        return "", 0

    def _recalc(self):
        total = 0.0
        yields = []
        for r, (ref, qty) in enumerate(self._lines()):
            unit, uc = self._unit_cost(ref)
            cost = uc * qty
            total += cost
            self.table.cellWidget(r, 2).setText(unit)
            self.table.cellWidget(r, 3).setText(fmt_money(uc) if uc >= 10 or not uc else f"$ {fmt_number(uc, 2)}")
            self.table.cellWidget(r, 4).setText(fmt_money(cost))
            pres = self._presentation(ref) if qty else None
            if pres and pres[2] and pres[2] > qty:
                yields.append(f"1 {pres[1]} de {pres[0]} rinde {fmt_number(pres[2] / qty, 1)} unidades")
        text = f"Costo: {fmt_money(total)}"
        if self.price:
            margin = self.price - total
            text += f"   ·   Precio: {fmt_money(self.price)}   ·   Margen: {fmt_money(margin)} ({fmt_pct(margin / self.price)})"
            text += f"   ·   Costo/precio: {fmt_pct(total / self.price)}"
        self.totals.setText(text)
        self.yield_lbl.setText("  ·  ".join(yields))

    def calibrate(self):
        r = self.table.currentRow()
        lines = self._lines()
        candidates = [i for i, (ref, _q) in enumerate(lines) if self._presentation(ref)]
        if r not in candidates:
            r = next((i for i in candidates if (self._presentation(lines[i][0])[2] or 1) > 1), None)
        if r is None:
            show_error(self, "Agregue primero el insumo (p. ej. la bolsa de mezcla) y selecciónelo.")
            return
        name, pres_name, pres_qty, unit = self._presentation(lines[r][0])
        n, ok = QInputDialog.getDouble(
            self, "Calibrar con rendimiento real",
            f"¿Cuántas unidades de este producto salen de 1 {pres_name} de «{name}» "
            f"({fmt_number(pres_qty)} {unit})?", 18, 0.1, 100000, 1)
        if ok and n > 0:
            self.table.cellWidget(r, 1).setValue(costing.quantity_from_yield(pres_qty, n))
            self._recalc()

    def save(self):
        data = []
        for ref, qty in self._lines():
            if not ref and not qty:
                continue
            if not ref:
                show_error(self, "Hay una línea sin insumo")
                return
            line = {"quantity": qty}
            if ref.startswith("g:"):
                line["supply_group_id"] = ref[2:]
            elif ref.startswith("s:"):
                line["supply_id"] = ref[2:]
            else:
                line["sub_product_id"] = ref[2:]
            data.append(line)
        try:
            with self.ctx.session() as s:
                catalog.set_recipe(s, data, self.product_id, self.option_id)
            self.accept()
        except Exception as exc:
            show_error(self, exc)
