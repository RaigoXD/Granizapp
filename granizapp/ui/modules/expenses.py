"""Gastos del negocio clasificados por categoría contable."""
from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QSplitter, QTabWidget, QVBoxLayout, QWidget

from granizapp.core.models import ExpenseType
from granizapp.core.services import finance, purchasing, staff
from granizapp.core.utils import fmt_money
from granizapp.ui.context import AppContext, Topics
from granizapp.ui.dialogs import default_pay_account
from granizapp.ui.widgets.charts import HBars
from granizapp.ui.widgets.common import (
    KpiCard,
    Page,
    PeriodSelector,
    ask_text,
    button,
    card,
    confirm,
    label,
    page_header,
    run,
    shortcut,
    show_error,
)
from granizapp.ui.widgets.crud import CrudPanel, column_values
from granizapp.ui.widgets.forms import Field, FormDialog
from granizapp.ui.widgets.table import Col, DataTable


class ExpensesPage(Page):
    topics = {Topics.EXPENSES, Topics.FINANCE, Topics.STAFF}

    def __init__(self, ctx: AppContext):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.addWidget(page_header("Gastos", "Todo lo que sale: insumos, nómina, servicios, arriendo, envíos…",
                                   [button("Nuevo gasto", self.new_expense, "Primary", "Ctrl+N")]))
        tabs = QTabWidget()
        root.addWidget(tabs, 1)
        w = QWidget()
        wl = QVBoxLayout(w)
        wl.setContentsMargins(0, 8, 0, 0)
        bar = QHBoxLayout()
        self.period = PeriodSelector("mes")
        self.period.changed.connect(lambda _p: self.safe_refresh())
        bar.addWidget(self.period)
        self.cat_filter = QComboBox()
        self.cat_filter.currentIndexChanged.connect(lambda _i: self._apply_filter())
        bar.addWidget(self.cat_filter)
        bar.addStretch(1)
        wl.addLayout(bar)
        kpis = QHBoxLayout()
        self.k_total = KpiCard("Total gastos")
        self.k_cost = KpiCard("Insumos y mercancía")
        self.k_payroll = KpiCard("Nómina")
        self.k_oper = KpiCard("Operación")
        self.k_inv = KpiCard("Inversión (equipos)")
        for k in (self.k_total, self.k_cost, self.k_payroll, self.k_oper, self.k_inv):
            kpis.addWidget(k)
        wl.addLayout(kpis)
        split = QSplitter(Qt.Horizontal)
        self.table = DataTable([
            Col("Fecha", lambda e: e.at, "date", width=95),
            Col("Categoría", lambda e: self.paths.get(e.category_id, "Sin categoría"), width=230),
            Col("Descripción", lambda e: e.description, stretch=True),
            Col("Valor", lambda e: e.amount, "money", width=110, bold=lambda e: True),
            Col("Pagado desde", lambda e: self.acc_names.get(e.account_id, "—"), width=150),
            Col("Origen", lambda e: "Excel" if e.origin == "importado" else "", width=60),
        ], search=True, placeholder="Buscar gasto…", export_name="gastos",
            footer=lambda rows: f"{len(rows)} gastos · {fmt_money(sum(r.amount for r in rows))}")
        self.table.activated.connect(lambda _e: self.edit_expense())
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.table, 1)
        ab = QHBoxLayout()
        ab.addWidget(button("Editar", self.edit_expense, "", "Enter"))
        ab.addWidget(button("Anular", self.void_expense, "Danger"))
        ab.addStretch(1)
        ll.addLayout(ab)
        split.addWidget(left)
        frame, fl = card(title="Por categoría")
        self.chart = HBars(max_rows=14)
        fl.addWidget(self.chart)
        fl.addStretch(1)
        split.addWidget(frame)
        split.setSizes([760, 380])
        wl.addWidget(split, 1)
        tabs.addTab(w, "Gastos")
        self.cats_panel = CrudPanel(
            ctx, "Categoría de gasto",
            [Col("Categoría", lambda c: self.paths.get(c.id, c.name), stretch=True),
             Col("Tipo contable", lambda c: ExpenseType.LABELS.get(c.type, c.type), width=200),
             Col("Palabras clave (para clasificar)", lambda c: c.keywords, width=320),
             Col("Activa", lambda c: c.active, "bool", width=60)],
            load=lambda s: finance.list_expense_categories(s, include_inactive=True),
            fields=lambda s: [
                Field("name", "Nombre", required=True),
                Field("parent_id", "Dentro de", "choice",
                      options=[("", "— Categoría principal —")] + [
                          (c.id, c.name) for c in finance.list_expense_categories(s) if not c.parent_id]),
                Field("type", "Tipo contable", "choice", options=list(ExpenseType.LABELS.items()),
                      help="Define en qué renglón del estado de resultados aparece"),
                Field("keywords", "Palabras clave", help="Separadas por coma. Sirven para clasificar al importar."),
                Field("sort_order", "Orden", "int"),
                Field("active", "Activa", "bool", default=True),
            ],
            save=lambda s, d, cid: finance.save_expense_category(s, d, cid),
            delete=lambda s, cid: finance.delete_expense_category(s, cid),
            to_values=column_values,
            topics=(Topics.EXPENSES,),
        )
        tabs.addTab(self.cats_panel, "Categorías de gasto")
        shortcut(w, "Ctrl+N", self.new_expense)

    def refresh(self):
        start, end = self.period.period().bounds
        with self.ctx.session() as s:
            cats = finance.list_expense_categories(s, include_inactive=True)
            self.cat_by_id = {c.id: c for c in cats}
            self.paths = finance.expense_category_paths(cats)
            self.acc_names = {a.id: a.name for a in finance.list_accounts(s, True)}
            self.rows = finance.list_expenses(s, start, end)
        cur = self.cat_filter.currentData()
        self.cat_filter.blockSignals(True)
        self.cat_filter.clear()
        self.cat_filter.addItem("Todas las categorías", "")
        for c in sorted(cats, key=lambda c: self.paths[c.id]):
            self.cat_filter.addItem(self.paths[c.id], c.id)
        self.cat_filter.setCurrentIndex(max(0, self.cat_filter.findData(cur or "")))
        self.cat_filter.blockSignals(False)
        self._apply_filter()
        self.cats_panel.refresh()

    def _type_of(self, e) -> str:
        c = self.cat_by_id.get(e.category_id)
        return c.type if c else ExpenseType.OPERATING

    def _apply_filter(self):
        cid = self.cat_filter.currentData()
        rows = self.rows
        if cid:
            rows = [e for e in rows if e.category_id == cid or self.cat_by_id.get(e.category_id) is not None
                    and self.cat_by_id[e.category_id].parent_id == cid]
        self.table.set_rows(rows)
        by_type = defaultdict(int)
        by_parent = defaultdict(int)
        for e in rows:
            by_type[self._type_of(e)] += e.amount
            c = self.cat_by_id.get(e.category_id)
            parent = self.cat_by_id.get(c.parent_id) if c and c.parent_id else c
            by_parent[parent.name if parent else "Sin categoría"] += e.amount
        self.k_total.set(fmt_money(sum(e.amount for e in rows)))
        self.k_cost.set(fmt_money(by_type[ExpenseType.COST]))
        self.k_payroll.set(fmt_money(by_type[ExpenseType.PAYROLL]))
        self.k_oper.set(fmt_money(by_type[ExpenseType.OPERATING] + by_type[ExpenseType.TAXES] + by_type[ExpenseType.FINANCIAL]))
        self.k_inv.set(fmt_money(by_type[ExpenseType.INVESTMENT]))
        self.chart.set_data(sorted(by_parent.items(), key=lambda kv: -kv[1]))

    def _fields(self, s, values=None):
        cats = finance.list_expense_categories(s)
        paths = finance.expense_category_paths(cats)
        accounts = [("", "— No mover dinero de ninguna cuenta —")] + [(a.id, a.name) for a in finance.list_accounts(s)]
        suppliers = [("", "—")] + [(x.id, x.name) for x in purchasing.list_suppliers(s)]
        employees = [("", "—")] + [(x.id, x.name) for x in staff.list_employees(s)]
        return [
            Field("at", "Fecha", "datetime"),
            Field("description", "Descripción", required=True, placeholder="Ej: Pago energía, mercado de sabores"),
            Field("amount", "Valor", "money", required=True),
            Field("category_id", "Categoría", "choice",
                  options=[("", "— Clasificar automáticamente por la descripción —")]
                  + sorted(((c.id, paths[c.id]) for c in cats), key=lambda x: x[1]),
                  help="Automático usa las palabras clave de cada categoría (ej: «hielo» → Hielo)"),
            Field("account_id", "Pagado desde", "choice", options=accounts,
                  default=default_pay_account(self.ctx, s)),
            Field("supplier_id", "Proveedor", "choice", options=suppliers),
            Field("employee_id", "Empleado (si es nómina)", "choice", options=employees),
            Field("receipt", "Factura / soporte"),
            Field("notes", "Notas", "multiline"),
        ]

    def new_expense(self):
        with self.ctx.session() as s:
            fields = self._fields(s)
        values = {}
        while True:
            data = FormDialog.ask(self, "Nuevo gasto", fields, values)
            if data is None:
                return
            try:
                with self.ctx.session() as s:
                    if not data.get("category_id"):
                        guess = finance.classify_expense(finance.list_expense_categories(s), data["description"])
                        data["category_id"] = guess.id if guess else "seed-exp-otros"
                    finance.record_expense(s, data, self.ctx.actor)
                break
            except Exception as exc:
                show_error(self, exc)
                values = data
        self.ctx.notify(Topics.EXPENSES, Topics.FINANCE, Topics.CASH)

    def edit_expense(self):
        e = self.table.current()
        if e is None:
            return
        with self.ctx.session() as s:
            fields = self._fields(s)
        values = column_values(e)
        values["account_id"] = e.account_id or ""
        data = FormDialog.ask(self, "Editar gasto", fields, values)
        if data is None:
            return

        def do():
            with self.ctx.session() as s:
                finance.update_expense(s, e.id, data, self.ctx.actor)
            return True

        if run(self, do):
            self.ctx.notify(Topics.EXPENSES, Topics.FINANCE, Topics.CASH)

    def void_expense(self):
        e = self.table.current()
        if e is None:
            return
        if not confirm(self, f"¿Anular el gasto «{e.description}» por {fmt_money(e.amount)}?"
                             + ("\nEl dinero vuelve a la cuenta de donde salió." if e.account_id else ""),
                       danger=True, yes="Anular"):
            return
        reason = ask_text(self, "Anular gasto", "Motivo:", required=False) or ""

        def do():
            with self.ctx.session() as s:
                finance.void_expense(s, e.id, self.ctx.actor, reason)
            return True

        if run(self, do):
            self.ctx.notify(Topics.EXPENSES, Topics.FINANCE, Topics.CASH)
