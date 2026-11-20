"""Caja: turno abierto, gastos de caja, retiros, cierre con arqueo e historial de cierres."""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from granizapp.core.models import AccountMovement, CashSession, MoneyKind
from granizapp.core.services import cash, finance
from granizapp.core.services.common import alive
from granizapp.core.services.settings import get_setting
from granizapp.core.utils import fmt_datetime, fmt_money
from granizapp.ui.context import AppContext, Topics
from granizapp.ui.dialogs import OpenCashDialog
from granizapp.ui.widgets.common import (
    repolish,
    KpiCard,
    Page,
    button,
    card,
    confirm,
    info,
    label,
    page_header,
    run,
    shortcut,
    show_error,
)
from granizapp.ui.widgets.forms import Field, FormDialog, MoneyEdit
from granizapp.ui.widgets.table import Col, DataTable


class CloseCashDialog(QDialog):
    def __init__(self, parent, ctx: AppContext, cs: CashSession, sm: cash.SessionSummary):
        super().__init__(parent)
        self.ctx = ctx
        self.cs = cs
        self.sm = sm
        self.setWindowTitle(f"Cerrar caja #{cs.number}")
        self.setMinimumWidth(640)
        with ctx.session() as s:
            self.base_default = int(get_setting(s, "default_cash_base") or 0)
            self.accounts = [(a.id, a.name) for a in finance.list_accounts(s) if a.id != cs.account_id]
        lay = QVBoxLayout(self)
        lay.addWidget(label(f"Arqueo y cierre de caja #{cs.number}", "SectionTitle"))
        lay.addWidget(label("Cuente los billetes y monedas (o escriba el total contado). "
                            "El sistema compara contra lo que debería haber.", "Muted", wrap=True))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        self.spins: dict[int, QSpinBox] = {}
        for i, d in enumerate(cash.DENOMINATIONS):
            sp = QSpinBox()
            sp.setRange(0, 10000)
            sp.setMaximumWidth(80)
            sp.valueChanged.connect(self._from_denoms)
            self.spins[d] = sp
            r, c = i % 6, (i // 6) * 2
            grid.addWidget(QLabel(("Billete " if d >= 2000 else "Moneda ") + fmt_money(d)), r, c, Qt.AlignRight)
            grid.addWidget(sp, r, c + 1)
        lay.addLayout(grid)
        form = QFormLayout()
        self.counted = MoneyEdit(0, big=True)
        self.counted.value_changed.connect(self._update)
        form.addRow("Efectivo contado", self.counted)
        self.expected_lbl = label(fmt_money(sm.expected), "SectionTitle")
        form.addRow("Debería haber", self.expected_lbl)
        self.diff_lbl = label("", "SectionTitle")
        form.addRow("Diferencia", self.diff_lbl)
        lay.addLayout(form)
        box = QFormLayout()
        self.keep = MoneyEdit(self.base_default)
        self.keep.value_changed.connect(self._update)
        self.target = QComboBox()
        for aid, name in self.accounts:
            self.target.addItem(name, aid)
        idx = self.target.findData("seed-acc-fuerte")
        if idx >= 0:
            self.target.setCurrentIndex(idx)
        self.withdraw_lbl = label("", "Money")
        box.addRow("Dejar de base para el próximo turno", self.keep)
        box.addRow("Retirar del cajón", self.withdraw_lbl)
        box.addRow("Llevar el retiro a", self.target)
        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(54)
        self.notes.setPlaceholderText("Observaciones del cierre (opcional)")
        box.addRow("Notas", self.notes)
        lay.addLayout(box)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Cerrar caja")
        bb.button(QDialogButtonBox.Ok).setObjectName("Primary")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._update()
        self.counted.setFocus()

    def _from_denoms(self):
        total = sum(d * sp.value() for d, sp in self.spins.items())
        self.counted.setValue(total)
        self._update()

    def _update(self, *_):
        counted = self.counted.value()
        diff = counted - self.sm.expected
        if diff == 0:
            self.diff_lbl.setText("Cuadra exacto ✓")
            self.diff_lbl.setObjectName("Success")
        else:
            self.diff_lbl.setText(("Sobran " if diff > 0 else "Faltan ") + fmt_money(abs(diff)))
            self.diff_lbl.setObjectName("Warning" if abs(diff) < 5000 else "Danger")
        repolish(self.diff_lbl)
        withdraw = max(0, counted - self.keep.value())
        self.withdraw_lbl.setText(fmt_money(withdraw))

    def accept(self):
        counted = self.counted.value()
        diff = counted - self.sm.expected
        if diff and not confirm(self, f"La caja no cuadra ({'sobran' if diff > 0 else 'faltan'} {fmt_money(abs(diff))}). "
                                      "¿Cerrar de todas formas? Quedará registrado.", danger=True, yes="Cerrar"):
            return
        withdraw = max(0, counted - self.keep.value())
        denoms = {d: sp.value() for d, sp in self.spins.items() if sp.value()}
        try:
            with self.ctx.session() as s:
                cash.close_session(s, self.cs.id, counted, self.ctx.actor, denoms, withdraw,
                                   self.target.currentData() if withdraw else None, self.notes.toPlainText())
            super().accept()
        except Exception as exc:
            show_error(self, exc)


class CashPage(Page):
    topics = {Topics.CASH, Topics.SALES, Topics.EXPENSES, Topics.FINANCE, Topics.CUSTOMERS, Topics.PURCHASES}

    def __init__(self, ctx: AppContext):
        super().__init__(ctx)
        self.cs: CashSession | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)
        self.header_box = QVBoxLayout()
        root.addLayout(self.header_box)
        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # --- turno actual
        self.stack = QStackedWidget()
        closed = QWidget()
        cl = QVBoxLayout(closed)
        frame, fl = card(title="La caja está cerrada")
        self.closed_info = label("", "Muted", wrap=True)
        fl.addWidget(self.closed_info)
        open_btn = button("Abrir caja", self.open_cash, "Primary")
        open_btn.setMinimumHeight(44)
        fl.addWidget(open_btn, 0, Qt.AlignLeft)
        cl.addWidget(frame)
        cl.addStretch(1)
        self.stack.addWidget(closed)

        opened = QWidget()
        ol = QVBoxLayout(opened)
        ol.setContentsMargins(0, 8, 0, 0)
        kpis = QHBoxLayout()
        self.k_base = KpiCard("Base inicial")
        self.k_sales = KpiCard("Ventas en efectivo")
        self.k_abonos = KpiCard("Abonos en efectivo")
        self.k_out = KpiCard("Gastos y retiros")
        self.k_expected = KpiCard("Efectivo que debe haber")
        for k in (self.k_base, self.k_sales, self.k_abonos, self.k_out, self.k_expected):
            kpis.addWidget(k)
        ol.addLayout(kpis)
        kpis2 = QHBoxLayout()
        self.k_total = KpiCard("Ventas del turno")
        self.k_other = KpiCard("Cobrado por otros medios")
        self.k_credit = KpiCard("Fiado en el turno")
        self.k_voids = KpiCard("Anulaciones")
        for k in (self.k_total, self.k_other, self.k_credit, self.k_voids):
            kpis2.addWidget(k)
        ol.addLayout(kpis2)
        actions = QHBoxLayout()
        actions.addWidget(button("Gasto de caja", self.cash_expense, "", "Ctrl+G"))
        actions.addWidget(button("Retiro de efectivo", lambda: self.move_cash("out")))
        actions.addWidget(button("Ingreso de efectivo", lambda: self.move_cash("in")))
        actions.addStretch(1)
        actions.addWidget(button("Cerrar caja (arqueo)", self.close_cash, "Primary", "Ctrl+K"))
        ol.addLayout(actions)
        body = QHBoxLayout()
        self.movs = DataTable([
            Col("Hora", lambda m: m.at, "time", width=90),
            Col("Tipo", lambda m: MoneyKind.LABELS.get(m.kind, m.kind), width=140),
            Col("Detalle", lambda m: m.description, stretch=True),
            Col("Valor", lambda m: m.amount, "money", width=110,
                color=lambda m: "success" if m.amount > 0 else "danger"),
        ], search=True, placeholder="Buscar movimiento…", export_name="movimientos_caja")
        f1, l1 = card(title="Movimientos de efectivo del turno")
        l1.addWidget(self.movs)
        body.addWidget(f1, 3)
        self.methods = DataTable([
            Col("Medio", lambda m: m.name, stretch=True),
            Col("Ventas", lambda m: m.sales, "money", width=100),
            Col("Abonos", lambda m: m.abonos, "money", width=100),
            Col("Total", lambda m: m.total, "money", width=110, bold=lambda m: True),
        ])
        f2, l2 = card(title="Cobrado por medio de pago")
        l2.addWidget(self.methods)
        body.addWidget(f2, 2)
        ol.addLayout(body, 1)
        self.stack.addWidget(opened)
        tabs.addTab(self.stack, "Turno actual")

        # --- historial
        hist = QWidget()
        hl = QVBoxLayout(hist)
        self.history = DataTable([
            Col("#", lambda c: c.number, "int", width=50),
            Col("Equipo", lambda c: c.device_id, width=70),
            Col("Abierta", lambda c: c.opened_at, "datetime", width=150),
            Col("Cerrada", lambda c: c.closed_at, "datetime", width=150),
            Col("Base", lambda c: c.opening_amount, "money", width=100),
            Col("Esperado", lambda c: c.expected_cash if c.closed_at else None, "money", width=110),
            Col("Contado", lambda c: c.counted_cash if c.closed_at else None, "money", width=110),
            Col("Diferencia", lambda c: c.difference if c.closed_at else None, "money", width=100,
                color=lambda c: None if not c.difference else ("success" if c.difference > 0 else "danger")),
            Col("Retirado", lambda c: c.withdrawn, "money", width=100),
            Col("Notas", lambda c: c.notes, stretch=True),
        ], search=True, export_name="cierres_de_caja")
        self.history.activated.connect(self.show_session)
        hl.addWidget(label("Doble clic o Enter para ver el detalle de un cierre.", "Hint"))
        hl.addWidget(self.history)
        tabs.addTab(hist, "Historial de cierres")
        shortcut(self, "Ctrl+G", self.cash_expense)
        shortcut(self, "Ctrl+K", self.close_cash)

    def refresh(self):
        with self.ctx.session() as s:
            self.cs = cash.current_session(s, self.ctx.actor.device_id)
            drawer = cash.device_drawer(s, self.ctx.drawer_account_id)
            sm = cash.summary(s, self.cs) if self.cs else None
            movs = []
            if self.cs:
                movs = list(s.scalars(alive(AccountMovement).where(
                    AccountMovement.cash_session_id == self.cs.id,
                    AccountMovement.account_id == self.cs.account_id).order_by(AccountMovement.at.desc())))
            last = cash.last_closed(s, self.ctx.actor.device_id)
            history = cash.list_sessions(s)
            book = finance.account_balances(s).get(drawer.id, 0) if drawer else 0
        while self.header_box.count():
            w = self.header_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        subtitle = f"Equipo «{self.ctx.config.device_name}» · cajón: {drawer.name if drawer else '—'}"
        if self.cs:
            subtitle += f" · turno #{self.cs.number} abierto {fmt_datetime(self.cs.opened_at)}"
        self.header_box.addWidget(page_header("Caja", subtitle))
        self.history.set_rows(history)
        if self.cs is None:
            self.stack.setCurrentIndex(0)
            txt = f"En el cajón deberían quedar {fmt_money(book)}."
            if last:
                txt = (f"Último cierre: {fmt_datetime(last.closed_at)} · contado {fmt_money(last.counted_cash)}"
                       f" · diferencia {fmt_money(last.difference)} · retirado {fmt_money(last.withdrawn)}.\n" + txt)
            self.closed_info.setText(txt)
            return
        self.stack.setCurrentIndex(1)
        self.k_base.set(fmt_money(sm.opening))
        self.k_sales.set(fmt_money(sm.cash_sales))
        self.k_abonos.set(fmt_money(sm.cash_abonos))
        out = sm.cash_expenses + sm.cash_out
        extra = []
        if sm.cash_in:
            extra.append(f"ingresos +{fmt_money(sm.cash_in)}")
        if sm.voids:
            extra.append(f"anulaciones {fmt_money(sm.voids)}")
        if sm.adjustments:
            extra.append(f"ajustes {fmt_money(sm.adjustments)}")
        self.k_out.set(fmt_money(out), f"Gastos {fmt_money(sm.cash_expenses)} · retiros {fmt_money(sm.cash_out)}"
                       + ("".join(" · " + e for e in extra)))
        self.k_expected.set(fmt_money(sm.expected), "Base + entradas − salidas", "primary")
        self.k_total.set(fmt_money(sm.sales_total), f"{sm.sales_count} ventas")
        self.k_other.set(fmt_money(sm.non_cash_total), "Nequi, transferencias, tarjeta…")
        self.k_credit.set(fmt_money(sm.credit_total), "Quedó por cobrar", "warning" if sm.credit_total else None)
        self.k_voids.set(str(sm.void_count), "ventas anuladas")
        self.movs.set_rows(movs)
        self.methods.set_rows([m for m in sm.by_method if m.total])

    def open_cash(self):
        if OpenCashDialog(self, self.ctx).exec() == QDialog.Accepted:
            self.ctx.notify(Topics.CASH)

    def close_cash(self):
        if self.cs is None:
            return
        with self.ctx.session() as s:
            from granizapp.core.services import sales as sales_svc

            tabs = sales_svc.list_open_tabs(s, self.ctx.actor.device_id)
            sm = cash.summary(s, s.get(CashSession, self.cs.id))
        if tabs and not confirm(self, f"Hay {len(tabs)} cuenta(s) abierta(s) sin cobrar "
                                      f"({', '.join(t.label for t in tabs[:5])}). ¿Cerrar la caja igual?",
                                danger=True, yes="Cerrar igual"):
            return
        number = self.cs.number
        dlg = CloseCashDialog(self, self.ctx, self.cs, sm)
        if dlg.exec() == QDialog.Accepted:
            counted = dlg.counted.value()
            self.ctx.notify(Topics.CASH, Topics.FINANCE)  # refresca la pantalla (self.cs pasa a None)
            info(self, f"Caja #{number} cerrada.\nEsperado {fmt_money(sm.expected)} · contado {fmt_money(counted)}.")

    def cash_expense(self):
        if self.cs is None:
            show_error(self, "Abra la caja para registrar gastos pagados con el efectivo del cajón.")
            return
        with self.ctx.session() as s:
            cats = finance.list_expense_categories(s)
            paths = finance.expense_category_paths(cats)
        options = sorted(((c.id, paths[c.id]) for c in cats), key=lambda x: x[1])
        data = FormDialog.ask(self, "Gasto pagado con efectivo de la caja", [
            Field("description", "Descripción", required=True, placeholder="Ej: hielo x2, bolsas de basura"),
            Field("amount", "Valor", "money", required=True),
            Field("category_id", "Categoría", "choice", options=options, default="seed-exp-ins-hielo"),
            Field("receipt", "Factura / soporte"),
        ], subtitle="Sale del cajón y se descuenta del efectivo esperado del turno.")
        if data is None:
            return
        data["account_id"] = self.cs.account_id

        def do():
            with self.ctx.session() as s:
                return finance.record_expense(s, data, self.ctx.actor)

        if run(self, do):
            self.ctx.notify(Topics.CASH, Topics.EXPENSES, Topics.FINANCE)

    def move_cash(self, direction: str):
        if self.cs is None:
            return
        with self.ctx.session() as s:
            accounts = [(a.id, a.name) for a in finance.list_accounts(s) if a.id != self.cs.account_id]
        opts = [("", "— Ninguna: sale/entra como ajuste o socio —")] + accounts
        title = "Retiro de efectivo" if direction == "out" else "Ingreso de efectivo"
        data = FormDialog.ask(self, title, [
            Field("amount", "Valor", "money", required=True),
            Field("account", "Desde / hacia la cuenta", "choice", options=opts,
                  default="seed-acc-fuerte" if direction == "out" else ""),
            Field("capital", "Es retiro/aporte del socio", "bool",
                  help="Marque si el dinero es para el dueño (retiro) o lo pone el dueño (aporte)."),
            Field("description", "Motivo", required=True,
                  placeholder="Ej: guardar en caja fuerte, cambio de billetes, sencillo"),
        ])
        if data is None:
            return

        def do():
            with self.ctx.session() as s:
                cs = s.get(CashSession, self.cs.id)
                cash.cash_in_out(s, cs, data["amount"], direction, data["description"], self.ctx.actor,
                                 data["account"] or None, data["capital"])
            return True

        if run(self, do):
            self.ctx.notify(Topics.CASH, Topics.FINANCE)

    def show_session(self, cs: CashSession):
        with self.ctx.session() as s:
            sm = cash.summary(s, s.get(CashSession, cs.id))
        denoms = json.loads(cs.denominations or "{}") if cs.denominations else {}
        lines = [
            f"Caja #{cs.number} · equipo {cs.device_id}",
            f"Abierta: {fmt_datetime(cs.opened_at)}" + (f" · Cerrada: {fmt_datetime(cs.closed_at)}" if cs.closed_at else ""),
            "",
            f"Base: {fmt_money(sm.opening)}",
            f"Ventas en efectivo: {fmt_money(sm.cash_sales)}",
            f"Abonos en efectivo: {fmt_money(sm.cash_abonos)}",
            f"Gastos/pagos desde caja: −{fmt_money(sm.cash_expenses)}",
            f"Ingresos: {fmt_money(sm.cash_in)} · Retiros: −{fmt_money(sm.cash_out)}",
            f"Esperado: {fmt_money(cs.expected_cash if cs.closed_at else sm.expected)}",
        ]
        if cs.closed_at:
            lines += [f"Contado: {fmt_money(cs.counted_cash)} · Diferencia: {fmt_money(cs.difference)}",
                      f"Retirado al cierre: {fmt_money(cs.withdrawn)}"]
        lines += ["", f"Ventas: {sm.sales_count} por {fmt_money(sm.sales_total)} · Fiado: {fmt_money(sm.credit_total)}"]
        lines += [f"  {m.name}: {fmt_money(m.total)}" for m in sm.by_method if m.total]
        if denoms:
            lines += ["", "Conteo: " + ", ".join(f"{v}×{fmt_money(int(k))}" for k, v in denoms.items())]
        if cs.notes:
            lines += ["", f"Notas: {cs.notes}"]
        info(self, "\n".join(lines), f"Detalle de caja #{cs.number}")
