"""Personal: empleados y pagos (sueldo, horas extra, adelantos, bonificaciones)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from granizapp.core.models import PayType
from granizapp.core.services import finance, staff
from granizapp.core.utils import fmt_money
from granizapp.ui.context import AppContext, Topics
from granizapp.ui.dialogs import default_pay_account
from granizapp.ui.widgets.common import Page, PeriodSelector, button, label, page_header, run
from granizapp.ui.widgets.crud import CrudPanel, column_values
from granizapp.ui.widgets.forms import Field, FormDialog
from granizapp.ui.widgets.table import Col, DataTable


class StaffPage(Page):
    topics = {Topics.STAFF, Topics.EXPENSES}

    def __init__(self, ctx: AppContext):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.addWidget(page_header("Personal y nómina", "Los pagos quedan como gastos de nómina"))
        self.paid: dict[str, int] = {}
        split = QSplitter(Qt.Horizontal)
        self.panel = CrudPanel(
            ctx, "Empleado",
            [Col("Nombre", lambda e: e.name, stretch=True, bold=lambda e: True),
             Col("Cargo", lambda e: e.role, width=110),
             Col("Pago", lambda e: f"{PayType.LABELS.get(e.pay_type, e.pay_type)} {fmt_money(e.base_pay)}"
                 if e.base_pay else PayType.LABELS.get(e.pay_type, ""), width=170),
             Col("Pagado en el periodo", lambda e: self.paid.get(e.id, 0) or None, "money", width=150),
             Col("Activo", lambda e: e.active, "bool", width=60)],
            load=lambda s: staff.list_employees(s, include_inactive=True),
            fields=lambda s: [
                Field("name", "Nombre", required=True),
                Field("role", "Cargo", default="Bartender"),
                Field("phone", "Teléfono"),
                Field("document", "Cédula"),
                Field("pay_type", "Forma de pago", "choice", options=list(PayType.LABELS.items())),
                Field("base_pay", "Valor por periodo", "money"),
                Field("hourly_rate", "Valor hora extra", "money"),
                Field("start_date", "Fecha de ingreso", "date"),
                Field("active", "Activo", "bool", default=True),
                Field("notes", "Notas", "multiline"),
            ],
            save=lambda s, d, eid: staff.save_employee(s, d, eid),
            delete=lambda s, eid: staff.delete_employee(s, eid),
            to_values=column_values,
            topics=(Topics.STAFF,),
            extra_buttons=[button("Registrar pago", self.pay, "Primary")],
        )
        self.panel.table.selection_changed.connect(lambda _e: self._load_payments())
        split.addWidget(self.panel)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        self.period = PeriodSelector("mes")
        self.period.changed.connect(lambda _p: self.safe_refresh())
        rl.addWidget(self.period)
        self.title = label("Pagos", "SectionTitle")
        rl.addWidget(self.title)
        self.payments = DataTable([
            Col("Fecha", lambda e: e.at, "date", width=95),
            Col("Concepto", lambda e: e.description, stretch=True),
            Col("Valor", lambda e: e.amount, "money", width=110),
            Col("Pagado desde", lambda e: self.acc_names.get(e.account_id, "—"), width=150),
        ], export_name="pagos_nomina", footer=lambda rows: f"Total: {fmt_money(sum(r.amount for r in rows))}")
        rl.addWidget(self.payments, 1)
        split.addWidget(right)
        split.setSizes([620, 520])
        root.addWidget(split, 1)

    def refresh(self):
        start, end = self.period.period().bounds
        with self.ctx.session() as s:
            pays = staff.employee_payments(s, None, start, end)
            self.acc_names = {a.id: a.name for a in finance.list_accounts(s, True)}
        self.period_pays = pays
        self.paid = {}
        for p in pays:
            self.paid[p.employee_id] = self.paid.get(p.employee_id, 0) + p.amount
        self.panel.refresh()
        self._load_payments()

    def _load_payments(self):
        e = self.panel.table.current()
        rows = [p for p in self.period_pays if e is None or p.employee_id == e.id]
        self.title.setText(f"Pagos a {e.name}" if e else "Pagos del periodo")
        self.payments.set_rows(rows)

    def pay(self):
        e = self.panel.table.current()
        if e is None:
            return
        with self.ctx.session() as s:
            accounts = [("", "— No mover dinero —")] + [(a.id, a.name) for a in finance.list_accounts(s)]
            default = default_pay_account(self.ctx, s)
        data = FormDialog.ask(self, f"Pago a {e.name}", [
            Field("concept", "Concepto", "choice", options=[(k, v[0]) for k, v in staff.PAY_CONCEPTS.items()]),
            Field("amount", "Valor", "money", default=e.base_pay, required=True),
            Field("account_id", "Pagado desde", "choice", options=accounts, default=default),
            Field("at", "Fecha", "datetime"),
            Field("notes", "Notas", placeholder="Ej: quincena del 1 al 15, 2 horas extra"),
        ])
        if not data:
            return

        def do():
            with self.ctx.session() as s:
                staff.pay_employee(s, e.id, data["amount"], data["concept"], data["account_id"] or None,
                                   self.ctx.actor, data["at"], data["notes"])
            return True

        if run(self, do):
            self.ctx.notify(Topics.STAFF, Topics.EXPENSES, Topics.FINANCE, Topics.CASH)
