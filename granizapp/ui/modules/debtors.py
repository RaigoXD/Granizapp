"""Deudores (fiados), abonos, estado de cuenta y directorio de clientes."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from granizapp.core.models import Customer, PaymentMethod
from granizapp.core.services import cash, customers, sales
from granizapp.core.services.settings import get_setting
from granizapp.core.utils import day_range, fmt_date, fmt_money
from granizapp.ui.context import AppContext, Topics
from granizapp.ui.dialogs import ensure_cash_open
from granizapp.ui.widgets.common import KpiCard, Page, ask_text, button, card, confirm, label, page_header, run, shortcut, show_error, toast
from granizapp.ui.widgets.crud import CrudPanel, column_values
from granizapp.ui.widgets.forms import Field, MoneyEdit
from granizapp.ui.widgets.table import Col, DataTable


class AbonoDialog(QDialog):
    def __init__(self, parent, ctx: AppContext, customer: Customer, balance: int):
        super().__init__(parent)
        self.ctx = ctx
        self.customer = customer
        self.setWindowTitle(f"Abono de {customer.name}")
        self.setMinimumWidth(440)
        with ctx.session() as s:
            self.methods: list[PaymentMethod] = sales.payment_methods(s)
        lay = QVBoxLayout(self)
        lay.addWidget(label(f"Abono de {customer.name}", "SectionTitle"))
        lay.addWidget(label(f"Debe {fmt_money(balance)}. El abono se aplica a las deudas más antiguas primero.", "Muted"))
        form = QFormLayout()
        self.amount = MoneyEdit(balance, big=True)
        self.method = QComboBox()
        for m in self.methods:
            self.method.addItem(m.name, m.id)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Opcional")
        form.addRow("Valor del abono", self.amount)
        form.addRow("Medio de pago", self.method)
        form.addRow("Nota", self.note)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Registrar abono")
        bb.button(QDialogButtonBox.Ok).setObjectName("Primary")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.amount.returnPressed.connect(self.accept)
        self.amount.setFocus()

    def accept(self):
        method = self.methods[self.method.currentIndex()]
        cs_id = None
        with self.ctx.session() as s:
            cs = cash.current_session(s, self.ctx.actor.device_id)
            cs_id = cs.id if cs else None
        if method.is_cash and cs_id is None:
            cs_id = ensure_cash_open(self, self.ctx)
            if cs_id is None:
                return
        try:
            with self.ctx.session() as s:
                customers.register_abono(s, self.customer.id, self.amount.value(), method.id, self.ctx.actor, cs_id,
                                         self.note.text().strip())
            super().accept()
        except Exception as exc:
            show_error(self, exc)


class DebtorsPage(Page):
    topics = {Topics.SALES, Topics.CUSTOMERS, Topics.CASH}

    def __init__(self, ctx: AppContext):
        super().__init__(ctx)
        self.selected_id: str | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.addWidget(page_header("Deudores y clientes", "Fiados pendientes, abonos y estado de cuenta"))
        kpis = QHBoxLayout()
        self.k_total = KpiCard("Total por cobrar")
        self.k_count = KpiCard("Clientes que deben")
        self.k_today = KpiCard("Fiado hoy")
        self.k_abonos = KpiCard("Abonos hoy")
        for k in (self.k_total, self.k_count, self.k_today, self.k_abonos):
            kpis.addWidget(k)
        root.addLayout(kpis)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        # deudores
        w = QWidget()
        wl = QVBoxLayout(w)
        wl.setContentsMargins(0, 8, 0, 0)
        split = QSplitter(Qt.Horizontal)
        self.debtors = DataTable([
            Col("Cliente", lambda d: d.customer.name, stretch=True, bold=lambda d: True),
            Col("Teléfono", lambda d: d.customer.phone, width=110),
            Col("Debe", lambda d: d.balance, "money", width=110, color=lambda d: "danger"),
            Col("Cuentas", lambda d: d.open_sales, "int", width=70),
            Col("Desde", lambda d: d.oldest, "date", width=95),
            Col("Días", lambda d: d.days_overdue, "int", width=55,
                color=lambda d: "danger" if d.days_overdue > 15 else ("warning" if d.days_overdue > 7 else None)),
        ], search=True, placeholder="Buscar deudor…", export_name="deudores",
            footer=lambda rows: f"{len(rows)} deudores · {fmt_money(sum(r.balance for r in rows))}")
        self.debtors.selection_changed.connect(self._select)
        self.debtors.activated.connect(lambda _d: self.abono())
        split.addWidget(self.debtors)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        self.st_title = label("Seleccione un deudor", "SectionTitle")
        rl.addWidget(self.st_title)
        btns = QHBoxLayout()
        btns.addWidget(button("Registrar abono", self.abono, "Primary", "Enter"))
        btns.addWidget(button("Mensaje de cobro", self.copy_message, tip="Copia un mensaje para WhatsApp"))
        btns.addWidget(button("Exportar estado de cuenta", self.export_statement))
        btns.addStretch(1)
        rl.addLayout(btns)
        self.statement = DataTable([
            Col("Fecha", lambda r: r.at, "datetime", width=140),
            Col("Movimiento", lambda r: r.kind, width=110),
            Col("Detalle", lambda r: r.description, stretch=True),
            Col("Cargo", lambda r: r.charge or None, "money", width=95),
            Col("Abono", lambda r: r.payment or None, "money", width=95, color=lambda r: "success"),
            Col("Saldo", lambda r: r.balance, "money", width=100, bold=lambda r: True),
        ], export_name="estado_de_cuenta")
        self.statement.view.setSortingEnabled(False)
        self.statement.activated.connect(self._statement_action)
        rl.addWidget(self.statement, 1)
        rl.addWidget(label("Enter sobre un abono permite anularlo.", "Hint"))
        split.addWidget(right)
        split.setSizes([560, 560])
        wl.addWidget(split)
        self.tabs.addTab(w, "Deudores")

        # fiados y abonos del día
        d = QWidget()
        dl = QVBoxLayout(d)
        bar = QHBoxLayout()
        bar.addWidget(label("Día:"))
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("dd/MM/yyyy")
        self.day.dateChanged.connect(lambda _d: self._load_day())
        bar.addWidget(self.day)
        bar.addStretch(1)
        dl.addLayout(bar)
        split2 = QSplitter(Qt.Horizontal)
        self.day_credit = DataTable([
            Col("Hora", lambda s: s.closed_at, "time", width=85),
            Col("Cliente", lambda s: self.names.get(s.customer_id, ""), stretch=True),
            Col("Venta", lambda s: sales.sale_code(s), width=95),
            Col("Total", lambda s: s.total, "money", width=95),
            Col("Pagó", lambda s: s.paid, "money", width=95),
            Col("Saldo", lambda s: s.balance, "money", width=95, color=lambda s: "danger" if s.balance else "success"),
        ], export_name="fiados_del_dia",
            footer=lambda rows: f"{len(rows)} fiados · saldo {fmt_money(sum(r.balance for r in rows))}")
        f1, l1 = card(title="Fiados del día")
        l1.addWidget(self.day_credit)
        split2.addWidget(f1)
        self.day_abonos = DataTable([
            Col("Hora", lambda p: p.at, "time", width=85),
            Col("Cliente", lambda p: self.names.get(p.customer_id, ""), stretch=True),
            Col("Medio", lambda p: self.method_names.get(p.method_id, ""), width=120),
            Col("Valor", lambda p: p.amount, "money", width=100, color=lambda p: "success"),
        ], export_name="abonos_del_dia", footer=lambda rows: f"Abonos: {fmt_money(sum(r.amount for r in rows))}")
        f2, l2 = card(title="Abonos recibidos")
        l2.addWidget(self.day_abonos)
        split2.addWidget(f2)
        dl.addWidget(split2, 1)
        self.tabs.addTab(d, "Fiados y abonos por día")

        # clientes
        self.balances: dict[str, int] = {}
        self.clients = CrudPanel(
            ctx, "Cliente",
            [
                Col("Nombre", lambda c: c.name, stretch=True),
                Col("Teléfono", lambda c: c.phone, width=120),
                Col("Documento", lambda c: c.document, width=110),
                Col("Cupo de fiado", lambda c: c.credit_limit or None, "money", width=110),
                Col("Debe", lambda c: self.balances.get(c.id, 0) or None, "money", width=100,
                    color=lambda c: "danger"),
                Col("Activo", lambda c: c.active, "bool", width=60),
                Col("Notas", lambda c: c.notes, width=200),
            ],
            load=lambda s: customers.list_customers(s, include_inactive=True),
            fields=lambda s: [
                Field("name", "Nombre", required=True),
                Field("phone", "Teléfono / WhatsApp"),
                Field("document", "Cédula / NIT"),
                Field("credit_limit", "Cupo máximo de fiado", "money", help="0 = sin límite"),
                Field("active", "Activo", "bool", default=True),
                Field("notes", "Notas", "multiline"),
            ],
            save=lambda s, data, cid: customers.save_customer(s, data, cid),
            delete=lambda s, cid: customers.delete_customer(s, cid),
            to_values=column_values,
            topics=(Topics.CUSTOMERS,),
        )
        self.tabs.addTab(self.clients, "Clientes")
        shortcut(self, "Ctrl+A", self.abono)

    # --- datos --------------------------------------------------------------------------
    def refresh(self):
        today = date.today()
        start, end = day_range(today)
        with self.ctx.session() as s:
            rows = customers.debtors(s)
            self.balances = customers.balances(s)
            self.names = {c.id: c.name for c in customers.list_customers(s, True)}
            self.method_names = {m.id: m.name for m in sales.payment_methods(s, True)}
            fiado_hoy = sum(x.balance for x in customers.credit_sales_on(s, today))
            abonos_hoy = sum(p.amount for p in customers.abonos_between(s, start, end))
            self.business = get_setting(s, "business_name")
        self.debtors.set_rows(rows)
        self.k_total.set(fmt_money(sum(d.balance for d in rows)), color="danger" if rows else None)
        self.k_count.set(str(len(rows)))
        self.k_today.set(fmt_money(fiado_hoy))
        self.k_abonos.set(fmt_money(abonos_hoy), color="success" if abonos_hoy else None)
        if self.debtors.current() is None and rows:
            self.debtors.select_first()
        self._select(self.debtors.current())
        self.clients.refresh()
        self._load_day()

    def _load_day(self):
        q = self.day.date()
        d = date(q.year(), q.month(), q.day())
        start, end = day_range(d)
        with self.ctx.session() as s:
            credit = customers.credit_sales_on(s, d)
            abonos = customers.abonos_between(s, start, end)
        self.day_credit.set_rows(credit)
        self.day_abonos.set_rows(abonos)

    def _select(self, debtor):
        if debtor is None:
            self.selected_id = None
            self.st_title.setText("No hay deudores pendientes" if not self.debtors.rows() else "Seleccione un deudor")
            self.statement.set_rows([])
            return
        self.selected_id = debtor.customer.id
        with self.ctx.session() as s:
            lines = customers.statement(s, debtor.customer.id)
        self.st_title.setText(f"{debtor.customer.name} · debe {fmt_money(debtor.balance)}")
        self.statement.set_rows(lines)
        self.statement.select_row(len(lines) - 1)

    def _current_debtor(self):
        return self.debtors.current()

    def abono(self):
        d = self._current_debtor()
        if d is None:
            return
        dlg = AbonoDialog(self, self.ctx, d.customer, d.balance)
        if dlg.exec() == QDialog.Accepted:
            self.ctx.notify(Topics.CUSTOMERS, Topics.CASH, Topics.FINANCE, Topics.SALES)
            toast(self, f"Abono registrado para {d.customer.name}")

    def _statement_action(self, line):
        if line.kind != "Abono" or not line.ref_id:
            return
        if not confirm(self, f"¿Anular el abono de {fmt_money(line.payment)} del {fmt_date(line.at)}?",
                       danger=True, yes="Anular abono"):
            return
        reason = ask_text(self, "Anular abono", "Motivo:")
        if not reason:
            return

        def do():
            with self.ctx.session() as s:
                customers.void_abono(s, line.ref_id, self.ctx.actor, reason)
            return True

        if run(self, do):
            self.ctx.notify(Topics.CUSTOMERS, Topics.CASH, Topics.FINANCE)

    def copy_message(self):
        d = self._current_debtor()
        if d is None:
            return
        msg = (f"Hola {d.customer.name.split()[0]}, te saluda {self.business}. "
               f"Tu saldo pendiente es de {fmt_money(d.balance)} (desde el {fmt_date(d.oldest)}). "
               "Puedes pagar en efectivo o por transferencia/Nequi. ¡Gracias!")
        QGuiApplication.clipboard().setText(msg)
        toast(self, "Mensaje copiado: péguelo en WhatsApp")

    def export_statement(self):
        d = self._current_debtor()
        if d is None:
            return
        from granizapp.core.export import Sheet, export_xlsx

        path, _ = QFileDialog.getSaveFileName(self, "Estado de cuenta", f"estado_cuenta_{d.customer.name}.xlsx",
                                              "Excel (*.xlsx)")
        if not path:
            return
        rows = [[r.at, r.kind, r.description, r.charge or None, r.payment or None, r.balance]
                for r in self.statement.rows()]
        export_xlsx(path, [Sheet(f"Estado de cuenta {d.customer.name}",
                                 ["Fecha", "Movimiento", "Detalle", "Cargo", "Abono", "Saldo"], rows,
                                 ["datetime", "text", "text", "money", "money", "money"],
                                 subtitle=f"Saldo: {fmt_money(d.balance)}")], self.business)
        toast(self, f"Exportado: {path}")
