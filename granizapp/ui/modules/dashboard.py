"""Resumen: cómo va el día y el mes, y qué requiere atención."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from granizapp.core.services import cash, costing, customers, inventory, purchasing, reports
from granizapp.core.utils import WEEKDAYS_SHORT, fmt_long_date, fmt_money, fmt_pct
from granizapp.ui import theme
from granizapp.ui.context import AppContext, Topics
from granizapp.ui.widgets.charts import BarChart, HBars
from granizapp.ui.widgets.common import KpiCard, Page, button, card, label, page_header


def _dot(color: str) -> str:
    return f"<span style='color:{theme.color(color)}; font-size:14pt'>●</span> "


class DashboardPage(Page):
    topics = {Topics.ALL, Topics.SALES, Topics.EXPENSES, Topics.CASH, Topics.INVENTORY, Topics.PURCHASES,
              Topics.CUSTOMERS, Topics.CATALOG}

    def __init__(self, ctx: AppContext):
        super().__init__(ctx)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("Page")
        scroll.setWidget(body)
        outer.addWidget(scroll)
        root = QVBoxLayout(body)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)
        self.header = page_header("Resumen", fmt_long_date(date.today()),
                                  [button("Ir a vender", lambda: ctx.bus.navigate.emit("pos")),
                                   button("Reportes", lambda: ctx.bus.navigate.emit("reports"))])
        root.addWidget(self.header)
        root.addWidget(label("HOY", "Overline"))
        g1 = QGridLayout()
        self.k_today = KpiCard("Ventas de hoy")
        self.k_count = KpiCard("Número de ventas")
        self.k_ticket = KpiCard("Ticket promedio")
        self.k_cash = KpiCard("Caja")
        self.k_recv = KpiCard("Por cobrar (fiados)")
        self.k_exp_today = KpiCard("Gastos de hoy")
        for i, k in enumerate((self.k_today, self.k_count, self.k_ticket, self.k_cash, self.k_recv, self.k_exp_today)):
            g1.addWidget(k, 0, i)
        root.addLayout(g1)
        root.addWidget(label("ESTE MES", "Overline"))
        g2 = QGridLayout()
        self.k_month = KpiCard("Ventas del mes")
        self.k_gross = KpiCard("Utilidad bruta (recetas)")
        self.k_mexp = KpiCard("Gastos del mes")
        self.k_result = KpiCard("Resultado de caja")
        self.k_payable = KpiCard("Cuentas por pagar")
        for i, k in enumerate((self.k_month, self.k_gross, self.k_mexp, self.k_result, self.k_payable)):
            g2.addWidget(k, 0, i)
        root.addLayout(g2)
        row = QHBoxLayout()
        f1, l1 = card(title="Ventas de los últimos 30 días")
        self.chart_days = BarChart(height=230)
        l1.addWidget(self.chart_days)
        row.addWidget(f1, 3)
        f2, l2 = card(title="Promedio por día de la semana (últimos 60 días)")
        self.chart_week = BarChart(height=230)
        l2.addWidget(self.chart_week)
        row.addWidget(f2, 2)
        root.addLayout(row)
        row2 = QHBoxLayout()
        f3, l3 = card(title="Más vendidos del mes")
        self.top = HBars(max_rows=10)
        l3.addWidget(self.top)
        l3.addStretch(1)
        row2.addWidget(f3, 3)
        f4, l4 = card(title="Atención")
        self.alerts = label("", wrap=True)
        self.alerts.setTextFormat(Qt.RichText)
        l4.addWidget(self.alerts)
        l4.addStretch(1)
        row2.addWidget(f4, 2)
        root.addLayout(row2)
        root.addStretch(1)

    def refresh(self):
        today = date.today()
        with self.ctx.session() as s:
            ds_today = reports.load(s, reports.Period(today, today))
            ds_yday = reports.load(s, reports.Period(today - timedelta(days=1), today - timedelta(days=1)))
            month = reports.preset_period("mes")
            ds_month = reports.load(s, month)
            last30 = reports.Period(today - timedelta(days=29), today)
            ds_30 = reports.load(s, last30)
            ds_60 = reports.load(s, reports.Period(today - timedelta(days=59), today))
            cs = cash.current_session(s, self.ctx.actor.device_id)
            sm = cash.summary(s, cs) if cs else None
            debtors = customers.debtors(s)
            low = inventory.low_stock(s)
            payables = purchasing.payables(s)
            no_recipe = [c for c in costing.costing_table(s) if not c.has_recipe and c.product.kind != "servicio"]
        t, y, m = reports.summary(ds_today), reports.summary(ds_yday), reports.summary(ds_month)
        delta = ""
        if y.sales_total:
            change = (t.sales_total - y.sales_total) / y.sales_total
            delta = f"{'+' if change >= 0 else ''}{fmt_pct(change)} vs ayer ({fmt_money(y.sales_total)})"
        self.k_today.set(fmt_money(t.sales_total), delta, "primary")
        self.k_count.set(str(t.sales_count), f"{t.units:.0f} productos")
        self.k_ticket.set(fmt_money(t.avg_ticket) if t.sales_count else "—")
        if sm:
            self.k_cash.set(fmt_money(sm.expected), f"Caja #{cs.number} abierta · efectivo esperado")
        else:
            self.k_cash.set("Cerrada", "Abra la caja para vender", "warning")
        self.k_recv.set(fmt_money(sum(d.balance for d in debtors)), f"{len(debtors)} clientes",
                        "danger" if debtors else None)
        self.k_exp_today.set(fmt_money(t.expenses_total + t.investment_total))
        self.k_month.set(fmt_money(m.sales_total), f"{m.sales_count} ventas · ticket {fmt_money(m.avg_ticket)}")
        self.k_gross.set(fmt_money(m.gross_profit), f"Margen {fmt_pct(m.gross_margin)}" if m.gross_margin is not None else "")
        self.k_mexp.set(fmt_money(m.expenses_total + m.investment_total + m.purchases_total),
                        "Incluye insumos, nómina e inversiones")
        cash_result = m.sales_total + m.other_income - m.expenses_total - m.investment_total - m.purchases_total
        self.k_result.set(fmt_money(cash_result), "Ventas − todo lo gastado (como el Excel)",
                          "success" if cash_result >= 0 else "danger")
        self.k_payable.set(fmt_money(sum(p.balance for p in payables)), f"{len(payables)} facturas",
                           "warning" if payables else None)
        days = reports.by_day(ds_30, last30)
        self.chart_days.set_data([(d.strftime("%d/%m"), v) for d, v, _n in days], highlight=len(days) - 1)
        week = reports.by_weekday(ds_60)
        self.chart_week.set_data([(WEEKDAYS_SHORT[wd], total / ndays if ndays else 0) for wd, total, _c, ndays in week])
        self.top.set_data([(r.name, r.revenue, f"({r.quantity:.0f})") for r in reports.by_product(ds_month)[:10]])
        alerts = []
        if not cs:
            alerts.append(_dot("warning") + "La caja de este equipo está cerrada.")
        elif cs and datetime.now() - cs.opened_at > timedelta(hours=16):
            alerts.append(_dot("warning") + f"La caja lleva abierta desde {cs.opened_at:%d/%m %I:%M %p}: recuerde cerrarla con arqueo.")
        if low and all(r.stock <= 0 for r in low) and len(low) >= 8:
            alerts.append(_dot("primary") + "El inventario está en cero: haga el <b>conteo inicial</b> en "
                          "Inventario › Conteo físico (o registre las compras) para empezar a controlarlo.")
            low = []
        for r in low[:6]:
            alerts.append(_dot("danger") + f"Insumo {'agotado' if r.status == 'agotado' else 'por agotarse'}: <b>{r.supply.name}</b> "
                          f"({inventory.presentation_text(r.supply, r.stock)})")
        old = [d for d in debtors if d.days_overdue > 15]
        if old:
            alerts.append(_dot("warning") + f"{len(old)} cliente(s) deben hace más de 15 días: "
                          + ", ".join(f"{d.customer.name} ({fmt_money(d.balance)})" for d in old[:4]))
        overdue = [p for p in payables if p.due_date and p.due_date < today]
        if overdue:
            alerts.append(_dot("warning") + f"{len(overdue)} factura(s) de proveedor vencida(s) por {fmt_money(sum(p.balance for p in overdue))}")
        if no_recipe:
            alerts.append(_dot("primary") + "Sin receta (costo desconocido): " + ", ".join(c.product.name for c in no_recipe[:5]))
        self.alerts.setText("<br><br>".join(alerts) if alerts else _dot("success") + "Todo en orden.")
