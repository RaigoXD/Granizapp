"""Directorio de proveedores con su historial de compras y saldo."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from granizapp.core.models import PurchaseStatus
from granizapp.core.services import purchasing
from granizapp.core.utils import fmt_money
from granizapp.ui.context import AppContext, Topics
from granizapp.ui.widgets.common import Page, label, page_header
from granizapp.ui.widgets.crud import CrudPanel, column_values
from granizapp.ui.widgets.forms import Field
from granizapp.ui.widgets.table import Col, DataTable


class SuppliersPage(Page):
    topics = {Topics.PURCHASES}

    def __init__(self, ctx: AppContext):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.addWidget(page_header("Proveedores", "Mezclas, perlas, vasos, cervezas, envíos…"))
        self.balances: dict[str, int] = {}
        self.totals: dict[str, int] = {}
        split = QSplitter(Qt.Horizontal)
        self.panel = CrudPanel(
            ctx, "Proveedor",
            [Col("Proveedor", lambda s: s.name, stretch=True, bold=lambda s: True),
             Col("Qué le compramos", lambda s: s.supplies_text, width=200),
             Col("Teléfono", lambda s: s.phone, width=110),
             Col("Ciudad", lambda s: s.city, width=100),
             Col("Comprado", lambda s: self.totals.get(s.id, 0) or None, "money", width=110),
             Col("Le debemos", lambda s: self.balances.get(s.id, 0) or None, "money", width=110, color=lambda s: "danger")],
            load=lambda s: purchasing.list_suppliers(s, include_inactive=True),
            fields=lambda s: [
                Field("name", "Nombre / razón social", required=True),
                Field("nit", "NIT / cédula"),
                Field("contact_name", "Contacto"),
                Field("phone", "Teléfono / WhatsApp"),
                Field("email", "Correo"),
                Field("city", "Ciudad"),
                Field("address", "Dirección"),
                Field("supplies_text", "Qué le compramos", placeholder="Ej: bolsas de mezcla 6 L, perlas explosivas"),
                Field("payment_terms", "Condiciones de pago", placeholder="Contado, 15 días, 30 días…"),
                Field("active", "Activo", "bool", default=True),
                Field("notes", "Notas", "multiline"),
            ],
            save=lambda s, d, sid: purchasing.save_supplier(s, d, sid),
            delete=lambda s, sid: purchasing.delete_supplier(s, sid),
            to_values=column_values,
            topics=(Topics.PURCHASES,),
        )
        self.panel.table.selection_changed.connect(self._show)
        split.addWidget(self.panel)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        self.title = label("Historial de compras", "SectionTitle")
        rl.addWidget(self.title)
        self.history = DataTable([
            Col("Fecha", lambda p: p.at, "date", width=95),
            Col("Factura", lambda p: p.invoice_number, width=100),
            Col("Total", lambda p: p.total, "money", width=110),
            Col("Saldo", lambda p: p.balance or None, "money", width=100, color=lambda p: "danger"),
            Col("Estado", lambda p: "Anulada" if p.status == PurchaseStatus.VOID else "", stretch=True),
        ], export_name="compras_proveedor")
        rl.addWidget(self.history, 1)
        split.addWidget(right)
        split.setSizes([700, 420])
        root.addWidget(split, 1)

    def refresh(self):
        with self.ctx.session() as s:
            purchases = purchasing.list_purchases(s)
        self.purchases = purchases
        self.balances, self.totals = {}, {}
        for p in purchases:
            if p.supplier_id:
                self.totals[p.supplier_id] = self.totals.get(p.supplier_id, 0) + p.total
                self.balances[p.supplier_id] = self.balances.get(p.supplier_id, 0) + p.balance
        self.panel.refresh()
        self._show(self.panel.table.current())

    def _show(self, sup):
        if sup is None:
            self.history.set_rows([])
            return
        rows = [p for p in self.purchases if p.supplier_id == sup.id]
        self.title.setText(f"Compras a {sup.name} · total {fmt_money(sum(p.total for p in rows))}")
        self.history.set_rows(rows)
