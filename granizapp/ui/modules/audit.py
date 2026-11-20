"""Auditoría: quién hizo qué, cuándo y desde qué equipo."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QVBoxLayout

from granizapp.core.models import Role
from granizapp.core.services import audit as audit_svc
from granizapp.core.services import auth
from granizapp.core.utils import fmt_datetime, fmt_money, utc_to_local
from granizapp.ui.context import AppContext, Topics
from granizapp.ui.widgets.common import KpiCard, Page, PeriodSelector, info, label, page_header
from granizapp.ui.widgets.table import Col, DataTable


class AuditPage(Page):
    topics = {Topics.ALL, Topics.SALES, Topics.CASH, Topics.CUSTOMERS, Topics.CATALOG, Topics.INVENTORY,
              Topics.PURCHASES, Topics.EXPENSES, Topics.FINANCE, Topics.SETTINGS}

    def __init__(self, ctx: AppContext):
        super().__init__(ctx)
        self.labels: dict[tuple[str, str], str] = {}
        self.user_names: dict[str, str] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.addWidget(page_header("Auditoría", "Bitácora de acciones sensibles: quién, cuándo, desde qué equipo y qué"))
        bar = QHBoxLayout()
        self.period = PeriodSelector("7dias")
        self.period.changed.connect(lambda _p: self.safe_refresh())
        bar.addWidget(self.period)
        self.user = QComboBox()
        self.user.currentIndexChanged.connect(lambda _i: self.safe_refresh())
        bar.addWidget(self.user)
        self.group = QComboBox()
        self.group.addItem("Todos los tipos", "")
        for g in audit_svc.GROUPS:
            self.group.addItem(g, g)
        self.group.currentIndexChanged.connect(lambda _i: self.safe_refresh())
        bar.addWidget(self.group)
        bar.addStretch(1)
        root.addLayout(bar)
        kpis = QHBoxLayout()
        self.k_total = KpiCard("Acciones registradas")
        self.k_voids = KpiCard("Anulaciones")
        self.k_disc = KpiCard("Descuentos en ventas")
        self.k_cash = KpiCard("Cierres con diferencia")
        self.k_inv = KpiCard("Ajustes de inventario")
        self.k_login = KpiCard("PIN incorrecto")
        for k in (self.k_total, self.k_voids, self.k_disc, self.k_cash, self.k_inv, self.k_login):
            kpis.addWidget(k)
        root.addLayout(kpis)
        self.table = DataTable([
            Col("Fecha y hora", lambda e: utc_to_local(e.created_at), "datetime", width=140),
            Col("Usuario", lambda e: self.user_names.get(e.user_id or "", "Sistema"), width=130),
            Col("Equipo", lambda e: e.device_id or "", width=70),
            Col("Acción", lambda e: audit_svc.action_label(e.action), width=230,
                bold=lambda e: e.action in audit_svc.SENSITIVE,
                color=lambda e: "danger" if e.action in ("ingreso_fallido", "restablecer_pin") else (
                    "warning" if e.action in audit_svc.SENSITIVE else None)),
            Col("Sobre", lambda e: self.labels.get((e.entity, e.entity_id), ""), width=190),
            Col("Detalle", lambda e: e.detail, stretch=True, tooltip=lambda e: e.detail),
        ], search=True, placeholder="Buscar en la bitácora (venta, cliente, producto, motivo…)…",
            export_name="auditoria", footer=lambda rows: f"{len(rows)} registros")
        self.table.activated.connect(self.show_entry)
        root.addWidget(self.table, 1)
        root.addWidget(label("La bitácora no se puede editar ni borrar desde la aplicación. Enter sobre una fila "
                             "muestra el detalle completo.", "Hint"))

    def refresh(self):
        start, end = self.period.period().bounds
        cur_user = self.user.currentData()
        with self.ctx.session() as s:
            users = auth.list_users(s, include_inactive=True)
            self.user_names = {u.id: u.name + ("" if u.active else " (inactivo)") for u in users}
            entries = audit_svc.list_entries(s, start, end, user_id=cur_user or None,
                                             group=self.group.currentData() or None)
            self.labels = audit_svc.entity_labels(s, entries)
            sm = audit_svc.summarize(s, entries, start, end)
        self.user.blockSignals(True)
        self.user.clear()
        self.user.addItem("Todos los usuarios", "")
        for u in users:
            self.user.addItem(self.user_names[u.id] + (" · admin" if u.role == Role.ADMIN else ""), u.id)
        self.user.setCurrentIndex(max(0, self.user.findData(cur_user or "")))
        self.user.blockSignals(False)
        self.table.set_rows(entries)
        self.k_total.set(str(sm.total))
        self.k_voids.set(str(sm.voids), color="warning" if sm.voids else None)
        self.k_disc.set(str(sm.discounts))
        self.k_cash.set(str(sm.cash_differences), fmt_money(sm.cash_difference_total) if sm.cash_differences else "",
                        "danger" if sm.cash_difference_total < 0 else ("warning" if sm.cash_differences else None))
        self.k_inv.set(str(sm.inventory_adjustments))
        self.k_login.set(str(sm.failed_logins), color="danger" if sm.failed_logins else None)

    def show_entry(self, e):
        info(self, "\n".join([
            f"Fecha: {fmt_datetime(utc_to_local(e.created_at))}",
            f"Usuario: {self.user_names.get(e.user_id or '', 'Sistema')} · equipo {e.device_id or '—'}",
            f"Acción: {audit_svc.action_label(e.action)}",
            f"Sobre: {self.labels.get((e.entity, e.entity_id), e.entity or '—')}",
            "", e.detail or "(sin detalle)",
        ]), "Registro de auditoría")
