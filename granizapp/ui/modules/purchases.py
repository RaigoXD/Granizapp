"""Compras de insumos a proveedores y cuentas por pagar."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSplitter,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from granizapp.core.models import Purchase, PurchaseStatus
from granizapp.core.services import finance, inventory, purchasing
from granizapp.core.utils import fmt_date, fmt_money, fmt_number
from granizapp.ui.context import AppContext, Topics
from granizapp.ui.dialogs import default_pay_account
from granizapp.ui.widgets.common import (
    shortcut,
    KpiCard,
    Page,
    PeriodSelector,
    ask_text,
    button,
    confirm,
    label,
    page_header,
    run,
    show_error,
)
from granizapp.ui.widgets.forms import Field, FormDialog, MoneyEdit, NumberEdit, date_edit, from_qdate, from_qdatetime, to_qdatetime
from granizapp.ui.widgets.table import Col, DataTable


class PurchaseDialog(QDialog):
    """Nueva compra. `prefill` = [(insumo, cantidad, valor total)] (p. ej. el pedido sugerido de sabores)."""

    def __init__(self, parent, ctx: AppContext, prefill: list[tuple[str, float, int]] | None = None,
                 supplier_id: str | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Nueva compra de insumos")
        self.resize(900, 640)
        with ctx.session() as s:
            # «Sin especificar» no se compra: las bolsas siempre llegan con sabor
            unassigned = {g.default_supply_id for g in inventory.list_supply_groups(s, include_inactive=True)}
            self.supplies = [x for x in inventory.list_supplies(s) if x.id not in unassigned]
            self.suppliers = purchasing.list_suppliers(s)
            self.accounts = finance.list_accounts(s)
            self.default_account = default_pay_account(ctx, s)
        self.sup_by_id = {x.id: x for x in self.supplies}
        lay = QVBoxLayout(self)
        lay.addWidget(label("Nueva compra de insumos", "SectionTitle"))
        head = QFormLayout()
        self.supplier = QComboBox()
        self.supplier.addItem("— Sin proveedor —", "")
        for x in self.suppliers:
            self.supplier.addItem(x.name, x.id)
        self.supplier.setEditable(True)
        self.supplier.setInsertPolicy(QComboBox.NoInsert)
        self.supplier.completer().setFilterMode(Qt.MatchContains)
        self.supplier.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.at = QDateTimeEdit(to_qdatetime(None))
        self.at.setCalendarPopup(True)
        self.at.setDisplayFormat("dd/MM/yyyy hh:mm AP")
        self.invoice = QLineEdit()
        self.invoice.setPlaceholderText("Número de factura o remisión (opcional)")
        row = QHBoxLayout()
        row.addWidget(self.supplier, 2)
        row.addWidget(button("+ Proveedor", self.new_supplier))
        head.addRow("Proveedor", row)
        head.addRow("Fecha", self.at)
        head.addRow("Factura", self.invoice)
        lay.addLayout(head)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Insumo", "Cantidad", "Presentación", "Valor total", "Costo por presentación"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for i, w in enumerate([0, 90, 170, 130, 160]):
            if w:
                self.table.setColumnWidth(i, w)
        self.table.verticalHeader().setDefaultSectionSize(36)
        lay.addWidget(self.table, 1)
        lb = QHBoxLayout()
        lb.addWidget(button("Agregar insumo", self.add_line))
        lb.addWidget(button("Quitar línea", self.remove_line))
        lb.addStretch(1)
        lay.addLayout(lb)
        foot = QFormLayout()
        self.shipping = MoneyEdit(0)
        self.shipping.value_changed.connect(lambda _v: self._recalc())
        self.prorate = QCheckBox("Repartir el envío en el costo de los insumos (recomendado)")
        self.prorate.setChecked(True)
        self.total_lbl = label("", "SectionTitle")
        self.paid = MoneyEdit(0)
        self.paid_touched = False
        self.paid.textEdited.connect(lambda _t: setattr(self, "paid_touched", True))
        self.paid.value_changed.connect(lambda _v: self._recalc())
        self.account = QComboBox()
        for a in self.accounts:
            self.account.addItem(a.name, a.id)
        self.account.setCurrentIndex(max(0, self.account.findData(self.default_account or "")))
        self.due = date_edit()
        self.balance_lbl = label("", "Muted")
        self.notes = QLineEdit()
        foot.addRow("Envío / flete", self.shipping)
        foot.addRow("", self.prorate)
        foot.addRow("TOTAL", self.total_lbl)
        foot.addRow("Pagado ahora", self.paid)
        foot.addRow("Pagado desde", self.account)
        foot.addRow("Saldo a crédito", self.balance_lbl)
        foot.addRow("Vence", self.due)
        foot.addRow("Notas", self.notes)
        lay.addLayout(foot)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Registrar compra")
        bb.button(QDialogButtonBox.Save).setObjectName("Primary")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        if supplier_id:
            self.supplier.setCurrentIndex(max(0, self.supplier.findData(supplier_id)))
        for sid, qty, total in prefill or []:
            self.add_line(supply_id=sid, qty=qty, total=total)
        if not prefill:
            self.add_line()

    def new_supplier(self):
        data = FormDialog.ask(self, "Nuevo proveedor", [Field("name", "Nombre", required=True), Field("phone", "Teléfono"),
                                                       Field("city", "Ciudad")])
        if not data:
            return
        try:
            with self.ctx.session() as s:
                sup = purchasing.save_supplier(s, data)
                sid, name = sup.id, sup.name
            self.supplier.addItem(name, sid)
            self.supplier.setCurrentIndex(self.supplier.count() - 1)
            self.ctx.notify(Topics.PURCHASES)
        except Exception as exc:
            show_error(self, exc)

    def add_line(self, *_, supply_id: str | None = None, qty: float = 1, total: int = 0):
        r = self.table.rowCount()
        self.table.insertRow(r)
        cb = QComboBox()
        cb.setEditable(True)
        cb.setInsertPolicy(QComboBox.NoInsert)
        cb.addItem("— elegir insumo —", "")
        for x in self.supplies:
            cb.addItem(x.name, x.id)
        cb.completer().setFilterMode(Qt.MatchContains)
        cb.completer().setCompletionMode(QCompleter.PopupCompletion)
        if supply_id:
            cb.setCurrentIndex(max(0, cb.findData(supply_id)))
        cb.currentIndexChanged.connect(lambda _i: self._recalc())
        qty_edit = NumberEdit(qty)
        qty_edit.value_changed.connect(lambda _v: self._recalc())
        total_edit = MoneyEdit(total)
        total_edit.value_changed.connect(lambda _v: self._recalc())
        pres = QLabel()
        unit = QLabel()
        unit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setCellWidget(r, 0, cb)
        self.table.setCellWidget(r, 1, qty_edit)
        self.table.setCellWidget(r, 2, pres)
        self.table.setCellWidget(r, 3, total_edit)
        self.table.setCellWidget(r, 4, unit)
        cb.setFocus()
        self._recalc()

    def remove_line(self):
        r = self.table.currentRow()
        if r < 0:
            r = self.table.rowCount() - 1
        if r >= 0:
            self.table.removeRow(r)
            self._recalc()

    def _lines(self):
        out = []
        for r in range(self.table.rowCount()):
            sid = self.table.cellWidget(r, 0).currentData()
            qty = self.table.cellWidget(r, 1).value()
            total = self.table.cellWidget(r, 3).value()
            out.append((r, sid, qty, total))
        return out

    def _recalc(self):
        subtotal = 0
        for r, sid, qty, total in self._lines():
            s = self.sup_by_id.get(sid)
            self.table.cellWidget(r, 2).setText(
                f"{s.presentation_name} ({fmt_number(s.presentation_qty)} {s.unit})" if s else "")
            self.table.cellWidget(r, 4).setText(fmt_money(total / qty) if qty and total else "")
            subtotal += total
        total = subtotal + self.shipping.value()
        self.total_lbl.setText(fmt_money(total))
        if not self.paid_touched:
            self.paid.blockSignals(True)
            self.paid.setValue(total)
            self.paid.blockSignals(False)
        balance = max(0, total - self.paid.value())
        self.balance_lbl.setText(fmt_money(balance) if balance else "— (de contado)")
        self.due.setEnabled(balance > 0)

    def save(self):
        lines = []
        for _r, sid, qty, total in self._lines():
            if not sid and not total:
                continue
            if not sid:
                show_error(self, "Hay una línea sin insumo")
                return
            lines.append(purchasing.PurchaseLineInput(sid, qty, total))
        total = sum(ln.line_total for ln in lines) + self.shipping.value()
        paid = min(self.paid.value(), total)
        try:
            with self.ctx.session() as s:
                purchasing.create_purchase(
                    s, self.ctx.actor, lines, supplier_id=self.supplier.currentData() or None,
                    at=from_qdatetime(self.at.dateTime()), invoice_number=self.invoice.text().strip(),
                    shipping=self.shipping.value(), prorate_shipping=self.prorate.isChecked(),
                    pay_amount=paid, pay_account_id=self.account.currentData() if paid else None,
                    due_date=from_qdate(self.due.date()) if paid < total else None, notes=self.notes.text().strip())
            self.accept()
        except Exception as exc:
            show_error(self, exc)


class PurchasesPage(Page):
    topics = {Topics.PURCHASES, Topics.INVENTORY, Topics.FINANCE}

    def __init__(self, ctx: AppContext):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.addWidget(page_header("Compras", "Lo que se compra entra al inventario y actualiza el costo de las recetas",
                                   [button("Nueva compra", self.new_purchase, "Primary", "Ctrl+N")]))
        kpis = QHBoxLayout()
        self.k_period = KpiCard("Compras del periodo")
        self.k_payable = KpiCard("Cuentas por pagar")
        self.k_overdue = KpiCard("Vencidas")
        for k in (self.k_period, self.k_payable, self.k_overdue):
            kpis.addWidget(k)
        root.addLayout(kpis)
        tabs = QTabWidget()
        root.addWidget(tabs, 1)
        w = QWidget()
        wl = QVBoxLayout(w)
        wl.setContentsMargins(0, 8, 0, 0)
        self.period = PeriodSelector("mes")
        self.period.changed.connect(lambda _p: self.safe_refresh())
        wl.addWidget(self.period)
        split = QSplitter(Qt.Horizontal)
        self.table = DataTable([
            Col("Fecha", lambda p: p.at, "date", width=95),
            Col("Proveedor", lambda p: self.sup_names.get(p.supplier_id, "—"), stretch=True),
            Col("Factura", lambda p: p.invoice_number, width=100),
            Col("Total", lambda p: p.total, "money", width=110, bold=lambda p: True),
            Col("Pagado", lambda p: p.paid, "money", width=110),
            Col("Saldo", lambda p: p.balance or None, "money", width=100, color=lambda p: "danger"),
        ], search=True, export_name="compras", footer=lambda rows: f"{len(rows)} compras · {fmt_money(sum(r.total for r in rows))}")
        self.table.selection_changed.connect(self._show)
        split.addWidget(self.table)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        self.d_title = label("", "SectionTitle")
        rl.addWidget(self.d_title)
        self.items = DataTable([
            Col("Insumo", lambda i: self.supply_names.get(i.supply_id, i.description), stretch=True),
            Col("Cant.", lambda i: i.presentations, "qty", width=60),
            Col("Valor", lambda i: i.line_total, "money", width=100),
            Col("Costo por unidad base", lambda i: i.unit_cost, "number", width=150),
        ])
        rl.addWidget(self.items, 1)
        self.pays = DataTable([
            Col("Fecha", lambda p: p.at, "date", width=95),
            Col("Cuenta", lambda p: self.acc_names.get(p.account_id, ""), stretch=True),
            Col("Valor", lambda p: p.amount, "money", width=100),
            Col("", lambda p: "Anulado" if p.voided else "", width=70, color=lambda p: "danger"),
        ])
        rl.addWidget(label("Pagos", "SectionTitle"))
        rl.addWidget(self.pays)
        ab = QHBoxLayout()
        ab.addWidget(button("Registrar pago", self.pay))
        ab.addStretch(1)
        ab.addWidget(button("Anular compra", self.void, "Danger"))
        rl.addLayout(ab)
        split.addWidget(right)
        split.setSizes([600, 500])
        wl.addWidget(split, 1)
        tabs.addTab(w, "Compras")
        p = QWidget()
        pl = QVBoxLayout(p)
        pl.setContentsMargins(0, 8, 0, 0)
        self.payables = DataTable([
            Col("Proveedor", lambda x: self.sup_names.get(x.supplier_id, "—"), stretch=True),
            Col("Fecha", lambda x: x.at, "date", width=95),
            Col("Factura", lambda x: x.invoice_number, width=100),
            Col("Vence", lambda x: x.due_date, "date", width=95,
                color=lambda x: "danger" if x.due_date and x.due_date < datetime.now().date() else None),
            Col("Total", lambda x: x.total, "money", width=100),
            Col("Saldo", lambda x: x.balance, "money", width=110, bold=lambda x: True),
        ], search=True, export_name="cuentas_por_pagar",
            footer=lambda rows: f"Total por pagar: {fmt_money(sum(r.balance for r in rows))}")
        self.payables.activated.connect(lambda x: self.pay(x))
        pl.addWidget(self.payables, 1)
        pl.addWidget(label("Enter sobre una cuenta para registrar el pago.", "Hint"))
        tabs.addTab(p, "Cuentas por pagar")
        shortcut(self, "Ctrl+N", self.new_purchase)

    def refresh(self):
        start, end = self.period.period().bounds
        with self.ctx.session() as s:
            rows = purchasing.list_purchases(s, start, end, include_void=True)
            pay = purchasing.payables(s)
            self.sup_names = {x.id: x.name for x in purchasing.list_suppliers(s, True)}
            self.supply_names = {x.id: x.name for x in inventory.list_supplies(s, True)}
            self.acc_names = {a.id: a.name for a in finance.list_accounts(s, True)}
        valid = [r for r in rows if r.status != PurchaseStatus.VOID]
        self.k_period.set(fmt_money(sum(r.total for r in valid)), f"{len(valid)} compras")
        self.k_payable.set(fmt_money(sum(p.balance for p in pay)), color="danger" if pay else None)
        overdue = [p for p in pay if p.due_date and p.due_date < datetime.now().date()]
        self.k_overdue.set(str(len(overdue)), fmt_money(sum(p.balance for p in overdue)) if overdue else "",
                           "danger" if overdue else None)
        self.table.set_rows(rows)
        self.payables.set_rows(pay)
        if self.table.current() is None:
            self.table.select_first()
        self._show(self.table.current())

    def _show(self, p: Purchase | None):
        if p is None:
            self.d_title.setText("")
            self.items.set_rows([])
            self.pays.set_rows([])
            return
        with self.ctx.session() as s:
            self.items.set_rows(purchasing.purchase_items(s, p.id))
            self.pays.set_rows(purchasing.purchase_payments(s, p.id))
        status = " · ANULADA" if p.status == PurchaseStatus.VOID else ""
        self.d_title.setText(f"{self.sup_names.get(p.supplier_id, 'Compra')} · {fmt_date(p.at)} · "
                             f"{fmt_money(p.total)}" + (f" (envío {fmt_money(p.shipping)})" if p.shipping else "") + status)

    def new_purchase(self):
        if PurchaseDialog(self, self.ctx).exec() == QDialog.Accepted:
            self.ctx.notify(Topics.PURCHASES, Topics.INVENTORY, Topics.FINANCE, Topics.CASH, Topics.CATALOG)

    def pay(self, purchase=None):
        p = purchase if isinstance(purchase, Purchase) else self.table.current()
        if p is None or not p.balance:
            return
        with self.ctx.session() as s:
            accounts = [(a.id, a.name) for a in finance.list_accounts(s)]
            default = default_pay_account(self.ctx, s)
        data = FormDialog.ask(self, "Pago a proveedor", [
            Field("amount", "Valor", "money", default=p.balance, required=True),
            Field("account_id", "Pagado desde", "choice", options=accounts, default=default),
            Field("note", "Nota"),
        ], subtitle=f"Saldo pendiente: {fmt_money(p.balance)}")
        if not data:
            return

        def do():
            with self.ctx.session() as s:
                purchasing.pay_purchase(s, p.id, data["amount"], data["account_id"], self.ctx.actor, note=data["note"])
            return True

        if run(self, do):
            self.ctx.notify(Topics.PURCHASES, Topics.FINANCE, Topics.CASH)

    def void(self):
        p = self.table.current()
        if p is None or p.status == PurchaseStatus.VOID:
            return
        if not confirm(self, f"¿Anular la compra de {fmt_money(p.total)}? Se retira del inventario lo que entró "
                             "y se reversan los pagos.", danger=True, yes="Anular"):
            return
        reason = ask_text(self, "Anular compra", "Motivo:")
        if not reason:
            return

        def do():
            with self.ctx.session() as s:
                purchasing.void_purchase(s, p.id, self.ctx.actor, reason)
            return True

        if run(self, do):
            self.ctx.notify(Topics.PURCHASES, Topics.INVENTORY, Topics.FINANCE, Topics.CASH)
