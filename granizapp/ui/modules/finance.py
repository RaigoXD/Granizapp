"""Cuentas de dinero (Caja, Nequi, banco…), libro por cuenta, transferencias y capital."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QSplitter, QTabWidget, QVBoxLayout, QWidget

from granizapp.core.models import AccountKind, MoneyKind
from granizapp.core.services import finance
from granizapp.core.utils import fmt_money
from granizapp.ui.context import AppContext, Topics
from granizapp.ui.widgets.common import (
    KpiCard,
    Page,
    PeriodSelector,
    button,
    confirm,
    label,
    page_header,
    run,
)
from granizapp.ui.widgets.crud import column_values
from granizapp.ui.widgets.forms import Field, FormDialog
from granizapp.ui.widgets.table import Col, DataTable


class FinancePage(Page):
    topics = {Topics.FINANCE, Topics.CASH, Topics.SALES, Topics.EXPENSES, Topics.PURCHASES, Topics.CUSTOMERS}

    def __init__(self, ctx: AppContext):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.addWidget(page_header("Cuentas y capital", "Dónde está la plata: caja, caja fuerte, Nequi, banco"))
        kpis = QHBoxLayout()
        self.k_total = KpiCard("Total disponible")
        self.k_cash = KpiCard("Efectivo")
        self.k_digital = KpiCard("Bancos y billeteras")
        for k in (self.k_total, self.k_cash, self.k_digital):
            kpis.addWidget(k)
        root.addLayout(kpis)
        tabs = QTabWidget()
        root.addWidget(tabs, 1)
        w = QWidget()
        wl = QVBoxLayout(w)
        wl.setContentsMargins(0, 8, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(button("Transferir entre cuentas", self.transfer, "Primary"))
        bar.addWidget(button("Aporte de capital", lambda: self.entry(MoneyKind.CAPITAL_IN)))
        bar.addWidget(button("Retiro de socio", lambda: self.entry(MoneyKind.CAPITAL_OUT)))
        bar.addWidget(button("Otro ingreso", lambda: self.entry(MoneyKind.OTHER_INCOME)))
        bar.addWidget(button("Préstamo", lambda: self.entry(MoneyKind.LOAN_IN)))
        bar.addWidget(button("Ajustar saldo real", self.adjust))
        bar.addStretch(1)
        bar.addWidget(button("Nueva cuenta", self.new_account))
        bar.addWidget(button("Editar cuenta", self.edit_account))
        wl.addLayout(bar)
        split = QSplitter(Qt.Horizontal)
        self.accounts = DataTable([
            Col("Cuenta", lambda a: a.name + ("  (cajón)" if a.is_drawer else ""), stretch=True, bold=lambda a: True),
            Col("Tipo", lambda a: AccountKind.LABELS.get(a.kind, a.kind), width=130),
            Col("Saldo", lambda a: self.balances.get(a.id, 0), "money", width=130,
                color=lambda a: "danger" if self.balances.get(a.id, 0) < 0 else None),
        ])
        self.accounts.selection_changed.connect(lambda _a: self._load_ledger())
        self.accounts.activated.connect(lambda _a: self.edit_account())
        split.addWidget(self.accounts)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        self.l_title = label("", "SectionTitle")
        rl.addWidget(self.l_title)
        self.period = PeriodSelector("mes")
        self.period.changed.connect(lambda _p: self._load_ledger())
        rl.addWidget(self.period)
        self.ledger = DataTable([
            Col("Fecha", lambda r: r.movement.at, "datetime", width=140),
            Col("Tipo", lambda r: MoneyKind.LABELS.get(r.movement.kind, r.movement.kind), width=140),
            Col("Detalle", lambda r: r.movement.description, stretch=True),
            Col("Valor", lambda r: r.movement.amount, "money", width=110,
                color=lambda r: "success" if r.movement.amount > 0 else "danger"),
            Col("Saldo", lambda r: r.balance, "money", width=120, bold=lambda r: True),
        ], search=True, export_name="libro_cuenta")
        self.ledger.view.setSortingEnabled(False)
        rl.addWidget(self.ledger, 1)
        split.addWidget(right)
        split.setSizes([420, 740])
        wl.addWidget(split, 1)
        wl.addWidget(label("Los saldos salen de los movimientos registrados en la app (ventas, abonos, gastos, compras, "
                           "transferencias). Use «Ajustar saldo real» para cuadrar con el extracto o con lo contado.",
                           "Hint", wrap=True))
        tabs.addTab(w, "Cuentas")
        e = QWidget()
        el = QVBoxLayout(e)
        el.setContentsMargins(0, 8, 0, 0)
        self.entries = DataTable([
            Col("Fecha", lambda x: x.at, "date", width=95),
            Col("Tipo", lambda x: MoneyKind.LABELS.get(x.kind, x.kind), width=150),
            Col("Descripción", lambda x: x.description, stretch=True),
            Col("Cuenta", lambda x: self.acc_names.get(x.account_id, ""), width=170),
            Col("Valor", lambda x: x.amount, "money", width=110),
            Col("Origen", lambda x: "Excel" if x.origin == "importado" else "", width=60),
        ], search=True, export_name="aportes_retiros_otros")
        el.addWidget(self.entries, 1)
        eb = QHBoxLayout()
        eb.addStretch(1)
        eb.addWidget(button("Anular movimiento", self.void_entry, "Danger"))
        el.addLayout(eb)
        tabs.addTab(e, "Aportes, retiros y otros ingresos")

    def refresh(self):
        with self.ctx.session() as s:
            accs = finance.list_accounts(s, include_inactive=True)
            self.balances = finance.account_balances(s)
            entries = finance.list_financial_entries(s)
        self.acc_names = {a.id: a.name for a in accs}
        active = [a for a in accs if a.active]
        cash_total = sum(self.balances.get(a.id, 0) for a in active if a.kind == AccountKind.CASH)
        digital = sum(self.balances.get(a.id, 0) for a in active if a.kind != AccountKind.CASH)
        self.k_total.set(fmt_money(cash_total + digital))
        self.k_cash.set(fmt_money(cash_total))
        self.k_digital.set(fmt_money(digital))
        self.accounts.set_rows(accs)
        if self.accounts.current() is None:
            self.accounts.select_first()
        self.entries.set_rows(entries)
        self._load_ledger()

    def _load_ledger(self):
        a = self.accounts.current()
        if a is None:
            self.ledger.set_rows([])
            return
        start, end = self.period.period().bounds
        with self.ctx.session() as s:
            rows = finance.ledger(s, a.id, start, end)
        self.l_title.setText(f"{a.name} · saldo {fmt_money(self.balances.get(a.id, 0))}")
        self.ledger.set_rows(list(reversed(rows)))

    def _acc_options(self):
        return [(a.id, a.name) for a in self.accounts.rows() if a.active]

    def transfer(self):
        cur = self.accounts.current()
        data = FormDialog.ask(self, "Transferir entre cuentas", [
            Field("from_id", "Desde", "choice", options=self._acc_options(), default=cur.id if cur else None),
            Field("to_id", "Hacia", "choice", options=self._acc_options(), default="seed-acc-banco"),
            Field("amount", "Valor", "money", required=True),
            Field("description", "Detalle", placeholder="Ej: consignación del efectivo, paso de Nequi al banco"),
        ])
        if not data:
            return

        def do():
            with self.ctx.session() as s:
                finance.transfer(s, data["from_id"], data["to_id"], data["amount"], data["description"], self.ctx.actor)
            return True

        if run(self, do):
            self.ctx.notify(Topics.FINANCE, Topics.CASH)

    def entry(self, kind: str):
        helps = {
            MoneyKind.CAPITAL_IN: "Plata que pone el dueño/socio. No es venta ni ingreso del negocio.",
            MoneyKind.CAPITAL_OUT: "Plata que saca el dueño/socio para él. No es gasto del negocio.",
            MoneyKind.OTHER_INCOME: "Ingresos que no son ventas del día: eventos, alquiler de espacio, etc.",
            MoneyKind.LOAN_IN: "Préstamo recibido (queda como deuda; los pagos se registran como gasto financiero).",
        }
        cur = self.accounts.current()
        data = FormDialog.ask(self, MoneyKind.LABELS[kind], [
            Field("amount", "Valor", "money", required=True),
            Field("account_id", "Cuenta", "choice", options=self._acc_options(),
                  default=cur.id if cur else "seed-acc-fuerte"),
            Field("description", "Descripción", required=True),
            Field("at", "Fecha", "datetime"),
        ], subtitle=helps.get(kind, ""))
        if not data:
            return
        data["kind"] = kind

        def do():
            with self.ctx.session() as s:
                finance.record_financial_entry(s, data, self.ctx.actor)
            return True

        if run(self, do):
            self.ctx.notify(Topics.FINANCE, Topics.CASH)

    def adjust(self):
        a = self.accounts.current()
        if a is None:
            return
        data = FormDialog.ask(self, f"Ajustar saldo de {a.name}", [
            Field("real", "Saldo real", "money", default=self.balances.get(a.id, 0), required=True),
            Field("note", "Motivo", default="Cuadre con extracto / conteo"),
        ], subtitle=f"Saldo según la app: {fmt_money(self.balances.get(a.id, 0))}. Se registra la diferencia.")
        if not data:
            return

        def do():
            with self.ctx.session() as s:
                return finance.adjust_balance(s, a.id, data["real"], self.ctx.actor, data["note"])

        if run(self, do) is not None:
            self.ctx.notify(Topics.FINANCE, Topics.CASH)

    def _account_fields(self):
        return [
            Field("name", "Nombre", required=True, placeholder="Ej: Nequi, Bancolombia ahorros, Caja 2"),
            Field("kind", "Tipo", "choice", options=list(AccountKind.LABELS.items())),
            Field("is_drawer", "Es el cajón de una caja registradora", "bool",
                  help="Solo para el efectivo del mostrador. Si tiene dos cajas, cree un cajón para cada una."),
            Field("opening_balance", "Saldo inicial", "money", help="Lo que había al empezar a usar la app"),
            Field("sort_order", "Orden", "int"),
            Field("active", "Activa", "bool", default=True),
            Field("notes", "Notas"),
        ]

    def new_account(self):
        data = FormDialog.ask(self, "Nueva cuenta", self._account_fields())
        if data and run(self, self._save_account, data, None):
            self.ctx.notify(Topics.FINANCE)

    def edit_account(self):
        a = self.accounts.current()
        if a is None:
            return
        data = FormDialog.ask(self, "Editar cuenta", self._account_fields(), column_values(a))
        if data and run(self, self._save_account, data, a.id):
            self.ctx.notify(Topics.FINANCE)

    def _save_account(self, data, aid):
        with self.ctx.session() as s:
            finance.save_account(s, data, aid)
        return True

    def void_entry(self):
        x = self.entries.current()
        if x is None or not confirm(self, f"¿Anular «{x.description}» por {fmt_money(x.amount)}?", danger=True,
                                    yes="Anular"):
            return

        def do():
            with self.ctx.session() as s:
                finance.void_financial_entry(s, x.id, self.ctx.actor)
            return True

        if run(self, do):
            self.ctx.notify(Topics.FINANCE, Topics.CASH)
