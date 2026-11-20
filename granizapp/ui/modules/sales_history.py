"""Historial de ventas: búsqueda por periodo, detalle, pagos y anulación."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QSplitter, QVBoxLayout, QWidget

from granizapp.core.models import SaleStatus
from granizapp.core.services import customers, sales
from granizapp.core.utils import fmt_datetime, fmt_money
from granizapp.ui.context import AppContext, Topics
from granizapp.ui.widgets.common import (
    KpiCard,
    Page,
    PeriodSelector,
    ask_text,
    button,
    confirm,
    label,
    page_header,
    run,
)
from granizapp.ui.widgets.table import Col, DataTable


class SalesHistoryPage(Page):
    topics = {Topics.SALES, Topics.CUSTOMERS}

    def __init__(self, ctx: AppContext):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.addWidget(page_header("Historial de ventas", "Todas las ventas cerradas, fiadas y anuladas"))
        bar = QHBoxLayout()
        self.period = PeriodSelector("hoy")
        self.period.changed.connect(lambda _p: self.safe_refresh())
        bar.addWidget(self.period)
        self.status = QComboBox()
        for value, text in [("", "Todas"), ("pagadas", "Pagadas"), ("fiadas", "Con saldo (fiadas)"),
                            (SaleStatus.VOID, "Anuladas"), (SaleStatus.OPEN, "Cuentas abiertas")]:
            self.status.addItem(text, value)
        self.status.currentIndexChanged.connect(lambda _i: self.safe_refresh())
        bar.addWidget(self.status)
        bar.addStretch(1)
        root.addLayout(bar)
        kpis = QHBoxLayout()
        self.k_total = KpiCard("Vendido")
        self.k_count = KpiCard("Ventas")
        self.k_ticket = KpiCard("Ticket promedio")
        self.k_credit = KpiCard("Saldo pendiente")
        for k in (self.k_total, self.k_count, self.k_ticket, self.k_credit):
            kpis.addWidget(k)
        root.addLayout(kpis)
        split = QSplitter(Qt.Horizontal)
        self.table = DataTable([
            Col("Venta", lambda s: sales.sale_code(s), width=92),
            Col("Fecha", lambda s: s.closed_at or s.opened_at, "datetime", width=150),
            Col("Cliente / cuenta", lambda s: self.names.get(s.customer_id, "") or s.label, stretch=True),
            Col("Total", lambda s: s.total, "money", width=100, bold=lambda s: True),
            Col("Saldo", lambda s: s.balance if s.status == SaleStatus.CLOSED else None, "money", width=95,
                color=lambda s: "danger" if s.balance and s.status == SaleStatus.CLOSED else None),
            Col("Estado", self._status_text, width=95,
                color=lambda s: "danger" if s.status == SaleStatus.VOID else (
                    "warning" if s.status == SaleStatus.OPEN else None)),
        ], search=True, placeholder="Buscar por número, cliente o cuenta…", export_name="ventas",
            footer=lambda rows: f"{len(rows)} ventas")
        self.table.selection_changed.connect(self._show)
        split.addWidget(self.table)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        self.title = label("Seleccione una venta", "SectionTitle")
        rl.addWidget(self.title)
        self.meta = label("", "Muted", wrap=True)
        rl.addWidget(self.meta)
        self.items = DataTable([
            Col("Cant.", lambda i: i.quantity, "qty", width=52),
            Col("Producto", lambda i: i.name + (f" · {i.notes}" if i.notes else ""), stretch=True,
                tooltip=lambda i: f"Precio unitario {fmt_money(i.unit_price + i.modifiers_price)}"),
            Col("Total", lambda i: i.total, "money", width=95),
            Col("Costo", lambda i: i.unit_cost * i.quantity, "money", width=92, color=lambda i: "muted"),
        ])
        rl.addWidget(self.items, 2)
        self.pays = DataTable([
            Col("Fecha", lambda p: p.at, "datetime", width=150),
            Col("Medio", lambda p: ("Abono · " if p.kind == "abono" else "") + self.methods.get(p.method_id, "")
                + (" (anulado)" if p.voided else ""), stretch=True,
                color=lambda p: "danger" if p.voided else None),
            Col("Valor", lambda p: p.amount, "money", width=95),
        ])
        rl.addWidget(label("Pagos", "SectionTitle"))
        rl.addWidget(self.pays, 1)
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.void_btn = button("Anular venta…", self.void, "Danger")
        self.void_btn.setEnabled(False)
        actions.addWidget(self.void_btn)
        rl.addLayout(actions)
        split.addWidget(right)
        split.setSizes([720, 440])
        root.addWidget(split, 1)

    def _status_text(self, s) -> str:
        if s.status == SaleStatus.VOID:
            return "Anulada"
        if s.status == SaleStatus.OPEN:
            return "Abierta"
        base = "Fiada" if s.balance else "Pagada"
        return base + (" (Excel)" if s.origin == "importado" else "")

    def refresh(self):
        p = self.period.period()
        start, end = p.bounds
        mode = self.status.currentData()
        with self.ctx.session() as s:
            if mode == SaleStatus.OPEN:
                rows = sales.list_open_tabs(s)
            else:
                rows = sales.list_sales(s, start, end, status=SaleStatus.VOID if mode == SaleStatus.VOID else None)
            self.names = {c.id: c.name for c in customers.list_customers(s, True)}
            self.methods = {m.id: m.name for m in sales.payment_methods(s, True)}
        if mode == "pagadas":
            rows = [r for r in rows if r.status == SaleStatus.CLOSED and not r.balance]
        elif mode == "fiadas":
            rows = [r for r in rows if r.status == SaleStatus.CLOSED and r.balance]
        valid = [r for r in rows if r.status == SaleStatus.CLOSED]
        total = sum(r.total for r in valid)
        self.k_total.set(fmt_money(total))
        self.k_count.set(str(len(valid)))
        self.k_ticket.set(fmt_money(total / len(valid)) if valid else "—")
        self.k_credit.set(fmt_money(sum(r.balance for r in valid)))
        self.table.set_rows(rows)
        if self.table.current() is None:
            self.table.select_first()
        self._show(self.table.current())

    def _show(self, sale):
        if sale is None:
            self.title.setText("Seleccione una venta")
            self.meta.setText("")
            self.items.set_rows([])
            self.pays.set_rows([])
            self.void_btn.setEnabled(False)
            return
        with self.ctx.session() as s:
            items = sales.sale_items(s, sale.id)
            pays = sales.sale_payments(s, sale.id)
        self.title.setText(f"Venta {sales.sale_code(sale)} · {fmt_money(sale.total)}")
        parts = [fmt_datetime(sale.closed_at or sale.opened_at), self._status_text(sale)]
        if sale.customer_id:
            parts.append(f"Cliente: {self.names.get(sale.customer_id, '')}")
        if sale.label:
            parts.append(sale.label)
        if sale.discount:
            parts.append(f"Descuento {fmt_money(sale.discount)}")
        if sale.cost_total:
            parts.append(f"Costo {fmt_money(sale.cost_total)} · margen {fmt_money(sale.total - sale.cost_total)}")
        if sale.void_reason:
            parts.append(f"Motivo anulación: {sale.void_reason}")
        if sale.notes:
            parts.append(f"Nota: {sale.notes}")
        self.meta.setText(" · ".join(parts))
        self.items.set_rows(items)
        self.pays.set_rows(pays)
        self.void_btn.setEnabled(sale.status != SaleStatus.VOID and sale.origin == "pos" and self.ctx.is_admin)

    def void(self):
        sale = self.table.current()
        if sale is None:
            return
        if not confirm(self, f"¿Anular la venta {sales.sale_code(sale)} por {fmt_money(sale.total)}?\n"
                             "Se devuelve el inventario y se reversa el dinero recibido.", danger=True,
                       yes="Anular venta"):
            return
        reason = ask_text(self, "Anular venta", "Motivo de la anulación:")
        if not reason:
            return

        def do():
            with self.ctx.session() as s:
                sales.void_sale(s, sale.id, self.ctx.actor, reason)
            return True

        if run(self, do):
            self.ctx.notify(Topics.SALES, Topics.CASH, Topics.INVENTORY, Topics.CUSTOMERS, Topics.FINANCE)
