"""Diálogos compartidos entre módulos: cobro, adiciones, cliente, cuentas abiertas y caja."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from granizapp.core.models import Customer, ModifierGroup, ModifierOption, PaymentMethod
from granizapp.core.services import cash, customers, finance
from granizapp.core.services.sales import CartModifier, PaymentInput, sale_code
from granizapp.core.services.settings import get_setting
from granizapp.core.utils import fmt_datetime, fmt_money, matches
from granizapp.ui import theme
from granizapp.ui.context import AppContext
from granizapp.ui.widgets.common import label, show_error, repolish
from granizapp.ui.widgets.forms import MoneyEdit
from granizapp.ui.widgets.keys import KeyLineEdit
from granizapp.ui.widgets.table import Col, DataTable


# --- cobro ---------------------------------------------------------------------------------
@dataclass
class PaymentResult:
    payments: list[PaymentInput]
    leave_credit: bool = False

    @property
    def change(self) -> int:
        return sum(max(0, p.received - p.amount) for p in self.payments)


class PaymentDialog(QDialog):
    """Cobro rápido: F1..F6 eligen medio de pago, se escribe lo recibido y Enter.

    Si el valor es menor al total se registra como pago parcial y se sigue con otro medio
    (pago mixto). F11 deja el saldo como fiado.
    """

    def __init__(self, parent, methods: list[PaymentMethod], total: int, allow_credit: bool = True,
                 customer_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Cobrar")
        self.setMinimumWidth(560)
        self.methods = methods
        self.total = total
        self.payments: list[PaymentInput] = []
        self.leave_credit = False
        self.current = 0
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(label("Total a cobrar", "Muted"))
        top.addStretch(1)
        self.total_lbl = label(fmt_money(total), "BigTotal")
        top.addWidget(self.total_lbl)
        lay.addLayout(top)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.method_buttons: list[QPushButton] = []
        for i, m in enumerate(methods[:6]):
            b = QPushButton(f"F{i + 1}  {m.name}")
            b.setCheckable(True)
            b.setObjectName("Chip")
            b.setMinimumHeight(36)
            b.clicked.connect(lambda _c=False, idx=i: self.select_method(idx))
            grid.addWidget(b, i // 3, i % 3)
            self.method_buttons.append(b)
            QShortcut(QKeySequence(f"F{i + 1}"), self, activated=lambda idx=i: self.select_method(idx))
        lay.addLayout(grid)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.amount = MoneyEdit(total, big=True)
        self.amount.value_changed.connect(self._update)
        self.received = MoneyEdit(0, big=True)
        self.received.setPlaceholderText("Exacto")
        self.received.value_changed.connect(self._update)
        self.received_lbl = QLabel("Recibido (efectivo)")
        form.addRow("Valor de este pago", self.amount)
        form.addRow(self.received_lbl, self.received)
        lay.addLayout(form)
        info = QHBoxLayout()
        self.change_lbl = label("", "Success")
        self.change_lbl.setStyleSheet("font-size: 16pt;")
        self.remaining_lbl = label("", "Muted")
        info.addWidget(self.remaining_lbl)
        info.addStretch(1)
        info.addWidget(self.change_lbl)
        lay.addLayout(info)
        self.list = QListWidget()
        self.list.setMaximumHeight(90)
        self.list.hide()
        lay.addWidget(self.list)
        hint = label("Enter: registrar  ·  F1–F6: medio de pago  ·  Esc: cancelar"
                     + ("  ·  F11: dejar saldo fiado" if allow_credit else ""), "Hint")
        lay.addWidget(hint)
        btns = QHBoxLayout()
        self.credit_btn = QPushButton("Dejar saldo fiado (F11)" + (f" a {customer_name}" if customer_name else ""))
        self.credit_btn.clicked.connect(self.credit)
        self.allow_credit = allow_credit
        QShortcut(QKeySequence("F11"), self, activated=self.credit)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton("Registrar pago (Enter)")
        self.ok.setObjectName("Primary")
        self.ok.clicked.connect(self.register)
        btns.addWidget(self.credit_btn)
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(self.ok)
        lay.addLayout(btns)
        self.credit_btn.setVisible(allow_credit)  # ya ubicado en la ventana
        for w in (self.amount, self.received):
            w.returnPressed.connect(self.register)
        self.select_method(0)

    @property
    def remaining(self) -> int:
        return self.total - sum(p.amount for p in self.payments)

    def select_method(self, idx: int):
        if idx >= len(self.methods):
            return
        self.current = idx
        for i, b in enumerate(self.method_buttons):
            b.setChecked(i == idx)
        is_cash = self.methods[idx].is_cash
        self.received.setVisible(is_cash)
        self.received_lbl.setVisible(is_cash)
        self.amount.setValue(self.remaining)
        self.received.setValue(0)
        target = self.received if is_cash else self.amount
        QTimer.singleShot(0, target, target.setFocus)
        self._update()

    def _update(self, *_):
        m = self.methods[self.current]
        amount = self.amount.value()
        msg = f"Pendiente: {fmt_money(self.remaining)}"
        self.remaining_lbl.setText(msg)
        if m.is_cash and self.received.value():
            change = self.received.value() - min(amount, self.remaining)
            if change >= 0:
                self.change_lbl.setText(f"Cambio: {fmt_money(change)}")
                self.change_lbl.setObjectName("Success")
            else:
                self.change_lbl.setText(f"Faltan {fmt_money(-change)}")
                self.change_lbl.setObjectName("Danger")
            repolish(self.change_lbl)
        else:
            self.change_lbl.setText("")

    def register(self):
        m = self.methods[self.current]
        remaining = self.remaining
        amount = min(self.amount.value() or remaining, remaining)
        received = self.received.value() if m.is_cash else amount
        if m.is_cash and received and received < amount:
            # recibió menos que el valor: se toma lo recibido como pago parcial
            amount = received
        if amount <= 0:
            if remaining <= 0:
                self.accept()
            return
        self.payments.append(PaymentInput(m.id, amount, max(received, amount) if m.is_cash else amount))
        self.list.addItem(f"{m.name}: {fmt_money(amount)}"
                          + (f"  (recibido {fmt_money(received)}, cambio {fmt_money(received - amount)})"
                             if m.is_cash and received > amount else ""))
        self.list.show()
        if self.remaining <= 0:
            self.accept()
            return
        self.select_method(0 if not m.is_cash else min(1, len(self.methods) - 1))

    def credit(self):
        if not self.allow_credit:
            return
        self.leave_credit = True
        self.accept()

    def result_value(self) -> PaymentResult:
        return PaymentResult(self.payments, self.leave_credit)


# --- adiciones / modificadores ----------------------------------------------------------------
class ModifiersDialog(QDialog):
    """Lista de opciones por grupo. Números 1-9 marcan/desmarcan, Espacio también, Enter acepta."""

    def __init__(self, parent, product_name: str, groups: list[tuple[ModifierGroup, list[ModifierOption]]],
                 selected: list[CartModifier] | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Adiciones · {product_name}")
        self.setMinimumSize(420, 420)
        self.groups = groups
        chosen = {m.option_id for m in (selected or [])}
        lay = QVBoxLayout(self)
        lay.addWidget(label(product_name, "SectionTitle"))
        lay.addWidget(label("Números 1–9 o Espacio para marcar · Enter para aceptar · Esc para salir", "Hint"))
        self.list = QListWidget()
        self.option_items: list[QListWidgetItem] = []
        bold = QFont()
        bold.setBold(True)
        n = 0
        for group, options in groups:
            head = QListWidgetItem(group.name.upper() + (f"  (máx. {group.max_select})" if group.max_select else ""))
            head.setFlags(Qt.NoItemFlags)
            head.setFont(bold)
            head.setForeground(QBrush(theme.qcolor("muted")))
            self.list.addItem(head)
            for opt in options:
                n += 1
                key = str(n) if n <= 9 else " "
                price = f"   +{fmt_money(opt.price_delta)}" if opt.price_delta else ""
                item = QListWidgetItem(f"  {key}.  {opt.name}{price}")
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if opt.id in chosen else Qt.Unchecked)
                item.setData(Qt.UserRole, (group, opt))
                self.list.addItem(item)
                self.option_items.append(item)
        self.list.itemChanged.connect(self._enforce)
        self.list.itemActivated.connect(lambda it: self._toggle(it))
        lay.addWidget(self.list, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Aceptar (Enter)")
        bb.button(QDialogButtonBox.Ok).setObjectName("Primary")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for i in range(min(9, len(self.option_items))):
            QShortcut(QKeySequence(str(i + 1)), self, activated=lambda idx=i: self._toggle(self.option_items[idx]))
        QShortcut(QKeySequence(Qt.Key_Space), self.list, activated=lambda: self._toggle(self.list.currentItem()))
        self.list.setFocus()
        if self.option_items:
            self.list.setCurrentItem(self.option_items[0])

    def _toggle(self, item: QListWidgetItem | None):
        if item is None or not (item.flags() & Qt.ItemIsUserCheckable):
            return
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
        self.list.setCurrentItem(item)

    def _enforce(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        if not data or item.checkState() != Qt.Checked:
            return
        group, opt = data
        if group.max_select:
            same = [it for it in self.option_items if it.data(Qt.UserRole)[0].id == group.id
                    and it.checkState() == Qt.Checked and it is not item]
            excess = len(same) + 1 - group.max_select
            self.list.blockSignals(True)
            for it in same[:max(0, excess)]:
                it.setCheckState(Qt.Unchecked)
            self.list.blockSignals(False)

    def accept(self):
        for group, _opts in self.groups:
            count = sum(1 for it in self.option_items
                        if it.data(Qt.UserRole)[0].id == group.id and it.checkState() == Qt.Checked)
            if group.min_select and count < group.min_select:
                show_error(self, f"Elija al menos {group.min_select} en «{group.name}»")
                return
        super().accept()

    def selected(self) -> list[CartModifier]:
        out = []
        for it in self.option_items:
            if it.checkState() == Qt.Checked:
                _g, opt = it.data(Qt.UserRole)
                out.append(CartModifier(opt.id, opt.name, opt.price_delta))
        return out


# --- sabor ----------------------------------------------------------------------------------
@dataclass
class FlavorOption:
    supply_id: str
    name: str
    code: str = ""
    stock: float = 0.0  # en presentaciones (bolsas)


class _FlavorList(QListWidget):
    """Lista de sabores: al escribir letras salta al sabor cuyo código o nombre empieza así."""

    def __init__(self, on_search):
        super().__init__()
        self.on_search = on_search

    def keyboardSearch(self, search: str):  # noqa: N802 (API de Qt)
        self.on_search(search)


class FlavorDialog(QDialog):
    """Elegir el sabor de una línea.

    1–9 elige el sabor. Con varios vasos (3*cl12, promo x2) cada número agrega un vaso y al
    completar se acepta solo; Retroceso quita el último. 0 = sin especificar. Letras saltan al
    código o nombre (ny, tij…). Enter acepta, Esc cancela.
    """

    def __init__(self, parent, title: str, group_name: str, options: list[FlavorOption], cups: int = 1,
                 current: list[str] | None = None, required: bool = False, presentation: str = "bolsa"):
        super().__init__(parent)
        self.setWindowTitle(f"Sabor · {title}")
        self.setMinimumSize(440, 440)
        self.options = options
        self.cups = max(1, int(cups))
        self.required = required
        self.picks: list[str] = list(current or [])[: self.cups]
        self.skip = False  # «sin especificar»
        self._typed = ""
        self._typed_timer = QTimer(self)
        self._typed_timer.setSingleShot(True)
        self._typed_timer.setInterval(900)
        self._typed_timer.timeout.connect(self._reset_typed)
        lay = QVBoxLayout(self)
        lay.addWidget(label(title, "SectionTitle"))
        lay.addWidget(label(group_name, "Muted"))
        how = "1–9 elige" if self.cups == 1 else f"1–9 agrega un vaso (son {self.cups}) · Retroceso quita el último"
        lay.addWidget(label(f"{how} · letras buscan (ny, tij…) · Enter acepta · "
                            + ("Esc cancela" if required else "0 = sin especificar · Esc cancela"), "Hint", wrap=True))
        self.list = _FlavorList(self._jump)
        bold = QFont()
        bold.setBold(True)
        for i, opt in enumerate(options):
            key = f"{i + 1}." if i < 9 else "   "
            stock = f"{opt.stock:.1f}".replace(".", ",") + f" {presentation}{'' if abs(opt.stock - 1) < 1e-9 else 's'}"
            state = "  · agotado" if opt.stock <= 0.0001 else ""
            code = f"  [{opt.code}]" if opt.code else ""
            item = QListWidgetItem(f"  {key}  {opt.name}{code}      {stock}{state}")
            item.setData(Qt.UserRole, opt.supply_id)
            if opt.stock <= 0.0001:
                item.setForeground(QBrush(theme.qcolor("muted")))
            self.list.addItem(item)
        if not required:
            item = QListWidgetItem("  0.  Sin especificar")
            item.setData(Qt.UserRole, "")
            item.setForeground(QBrush(theme.qcolor("muted")))
            self.list.addItem(item)
        self.list.itemActivated.connect(self._activated)
        lay.addWidget(self.list, 1)
        self.picked_lbl = label("", "SectionTitle")
        self.picked_lbl.setVisible(self.cups > 1)
        lay.addWidget(self.picked_lbl)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Aceptar (Enter)")
        bb.button(QDialogButtonBox.Ok).setObjectName("Primary")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self._accept_current)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for i in range(min(9, len(options))):
            QShortcut(QKeySequence(str(i + 1)), self, activated=lambda idx=i: self.pick(self.options[idx].supply_id))
        if not required:
            QShortcut(QKeySequence("0"), self, activated=self.choose_unspecified)
        QShortcut(QKeySequence(Qt.Key_Backspace), self, activated=self.undo)
        self.list.setFocus()
        start = 0
        if self.picks:
            ids = [o.supply_id for o in options]
            start = ids.index(self.picks[-1]) if self.picks[-1] in ids else 0
        if self.list.count():
            self.list.setCurrentRow(start)
        self._show_picks()

    # --- acciones ------------------------------------------------------------------------
    def pick(self, supply_id: str):
        if self.cups == 1:
            self.picks = [supply_id]
            self.accept()
            return
        if len(self.picks) >= self.cups:
            self.picks = []
        self.picks.append(supply_id)
        self._show_picks()
        if len(self.picks) == self.cups:
            self.accept()

    def choose_unspecified(self):
        self.picks = []
        self.skip = True
        self.accept()

    def undo(self):
        if self.picks:
            self.picks.pop()
            self._show_picks()

    def _activated(self, item: QListWidgetItem):
        sid = item.data(Qt.UserRole)
        if sid:
            self.pick(sid)
        elif not self.required:
            self.choose_unspecified()

    def _accept_current(self):
        if self.picks:
            self.accept()
            return
        item = self.list.currentItem()
        if item is not None:
            self._activated(item)

    def _show_picks(self):
        names = {o.supply_id: o.name for o in self.options}
        chosen = ", ".join(names.get(p, "?") for p in self.picks) or "ninguno"
        self.picked_lbl.setText(f"Vasos con sabor: {len(self.picks)} de {self.cups} · {chosen}")

    def _jump(self, text: str):
        from granizapp.core.utils import normalize

        self._typed += text
        self._typed_timer.start()
        q = normalize(self._typed).strip()
        if not q:
            return
        for i, opt in enumerate(self.options):
            if normalize(opt.code).startswith(q) or normalize(opt.name).startswith(q):
                self.list.setCurrentRow(i)
                return

    def _reset_typed(self):
        self._typed = ""

    def result_ids(self) -> list[str]:
        return list(self.picks)


# --- cliente --------------------------------------------------------------------------------
class CustomerPicker(QDialog):
    """Buscar cliente por nombre o crearlo escribiendo el nombre y Enter."""

    def __init__(self, parent, ctx: AppContext, title: str = "Seleccionar cliente", subtitle: str = ""):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(title)
        self.setMinimumSize(520, 460)
        self.customer_id: str | None = None
        with ctx.session() as s:
            self.customers = customers.list_customers(s)
            self.balances = customers.balances(s)
        lay = QVBoxLayout(self)
        lay.addWidget(label(title, "SectionTitle"))
        if subtitle:
            lay.addWidget(label(subtitle, "Muted", wrap=True))
        self.search = KeyLineEdit(on_key=self._search_key)
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Nombre del cliente (Enter para elegir o crear)")
        lay.addWidget(self.search)
        self.table = DataTable([
            Col("Cliente", lambda c: c.name, stretch=True),
            Col("Teléfono", lambda c: c.phone, width=120),
            Col("Debe", lambda c: self.balances.get(c.id, 0), "money", width=110,
                color=lambda c: "danger" if self.balances.get(c.id, 0) else None),
        ])
        self.table.set_rows(self.customers)
        self.table.activated.connect(self._choose)
        lay.addWidget(self.table, 1)
        self.create_lbl = label("", "Hint")
        lay.addWidget(self.create_lbl)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._enter)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.search.setFocus()
        self._filter("")

    def _search_key(self, event) -> bool:
        if event.key() in (Qt.Key_Down, Qt.Key_Up):
            self.table.focus_table()
            return True
        return False

    def _filter(self, text: str):
        self.table.set_query(text)
        exact = any(c.name.strip().lower() == text.strip().lower() for c in self.customers)
        if text.strip() and not exact:
            self.create_lbl.setText(f"Enter sin coincidencias = crear el cliente «{text.strip()}»")
        else:
            self.create_lbl.setText("")
        if self.table.visible_rows():
            self.table.select_first()

    def _enter(self):
        rows = self.table.visible_rows()
        text = self.search.text().strip()
        if rows and (not text or any(matches(text, r.name) for r in rows)):
            self._choose(self.table.current() or rows[0])
        elif text:
            try:
                with self.ctx.session() as s:
                    c = customers.quick_customer(s, text)
                    self.customer_id = c.id
                self.ctx.notify("clientes")
                self.accept()
            except Exception as exc:
                show_error(self, exc)

    def _choose(self, c: Customer):
        self.customer_id = c.id
        self.accept()

    @classmethod
    def pick(cls, parent, ctx, title="Seleccionar cliente", subtitle="") -> str | None:
        dlg = cls(parent, ctx, title, subtitle)
        return dlg.customer_id if dlg.exec() == QDialog.Accepted else None


# --- cuentas abiertas ------------------------------------------------------------------------
class OpenTabsDialog(QDialog):
    def __init__(self, parent, ctx: AppContext):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Cuentas abiertas")
        self.setMinimumSize(560, 400)
        self.chosen: str | None = None
        self.discard_id: str | None = None
        from granizapp.core.services import sales

        with ctx.session() as s:
            tabs = sales.list_open_tabs(s)
            counts = {t.id: sum(i.quantity for i in sales.sale_items(s, t.id)) for t in tabs}
        lay = QVBoxLayout(self)
        lay.addWidget(label("Cuentas abiertas (mesas / clientes que siguen pidiendo)", "SectionTitle"))
        self.table = DataTable([
            Col("Cuenta", lambda t: t.label, stretch=True, bold=lambda t: True),
            Col("#", lambda t: sale_code(t), width=90),
            Col("Abierta", lambda t: t.opened_at, "time", width=90),
            Col("Ítems", lambda t: counts.get(t.id, 0), "qty", width=60),
            Col("Total", lambda t: t.total, "money", width=110),
        ], search=True, placeholder="Buscar cuenta…")
        self.table.set_rows(tabs)
        self.table.activated.connect(self._open)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        b_open = QPushButton("Abrir (Enter)")
        b_open.setObjectName("Primary")
        b_open.clicked.connect(lambda: self._open(self.table.current()))
        b_del = QPushButton("Descartar cuenta…")
        b_del.setObjectName("Danger")
        b_del.clicked.connect(self._discard)
        b_close = QPushButton("Cerrar")
        b_close.clicked.connect(self.reject)
        row.addWidget(b_del)
        row.addStretch(1)
        row.addWidget(b_close)
        row.addWidget(b_open)
        lay.addLayout(row)
        if tabs:
            self.table.select_first()
            self.table.search.setFocus()

    def _open(self, tab):
        if tab is not None:
            self.chosen = tab.id
            self.accept()

    def _discard(self):
        from granizapp.ui.widgets.common import ask_text

        tab = self.table.current()
        if tab is None:
            return
        reason = ask_text(self, "Descartar cuenta", f"Motivo para descartar «{tab.label}» ({fmt_money(tab.total)}):")
        if reason:
            from granizapp.core.services import sales

            try:
                with self.ctx.session() as s:
                    sales.discard_open_tab(s, tab.id, self.ctx.actor, reason)
                self.ctx.notify("ventas")
                self.table.set_rows([r for r in self.table.rows() if r.id != tab.id])
            except Exception as exc:
                show_error(self, exc)


# --- apertura de caja --------------------------------------------------------------------------
class OpenCashDialog(QDialog):
    def __init__(self, parent, ctx: AppContext):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Abrir caja")
        self.setMinimumWidth(420)
        with ctx.session() as s:
            suggested = cash.suggested_base(s, ctx.actor.device_id, ctx.drawer_account_id)
            default = int(get_setting(s, "default_cash_base") or 0)
            drawer = cash.device_drawer(s, ctx.drawer_account_id)
            last = cash.last_closed(s, ctx.actor.device_id)
        lay = QVBoxLayout(self)
        lay.addWidget(label("Abrir caja", "SectionTitle"))
        lay.addWidget(label(
            f"Cuente el efectivo del cajón «{drawer.name if drawer else '—'}» y escriba la base con la que empieza."
            + (f"\nÚltimo cierre: {fmt_datetime(last.closed_at)} (quedaron {fmt_money(suggested)} en el cajón)." if last else ""),
            "Muted", wrap=True))
        self.amount = MoneyEdit(suggested or default, big=True)
        self.amount.returnPressed.connect(self.accept)
        form = QFormLayout()
        form.addRow("Base inicial", self.amount)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Abrir caja")
        bb.button(QDialogButtonBox.Ok).setObjectName("Primary")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.amount.setFocus()

    def accept(self):
        try:
            with self.ctx.session() as s:
                cash.open_session(s, self.ctx.actor, self.amount.value(), account_id=self.ctx.drawer_account_id)
            self.ctx.notify("caja", "finanzas")
            super().accept()
        except Exception as exc:
            show_error(self, exc)


def ensure_cash_open(parent, ctx: AppContext) -> str | None:
    """Devuelve el id del turno abierto; si no hay, ofrece abrir la caja."""
    with ctx.session() as s:
        cs = cash.current_session(s, ctx.actor.device_id)
        if cs is not None:
            return cs.id
    from granizapp.ui.widgets.common import confirm

    if not confirm(parent, "La caja está cerrada. ¿Abrirla ahora para poder cobrar?", "Caja cerrada",
                   yes="Abrir caja", no="Cancelar"):
        return None
    if OpenCashDialog(parent, ctx).exec() != QDialog.Accepted:
        return None
    with ctx.session() as s:
        cs = cash.current_session(s, ctx.actor.device_id)
        return cs.id if cs else None


def accounts_choice(session, include_drawer: bool = True) -> list[tuple[str, str]]:
    return [(a.id, a.name) for a in finance.list_accounts(session) if include_drawer or not a.is_drawer]


def default_pay_account(ctx: AppContext, session) -> str | None:
    """Cuenta sugerida para pagar gastos: el cajón de este equipo si la caja está abierta."""
    cs = cash.current_session(session, ctx.actor.device_id)
    if cs is not None:
        return cs.account_id
    drawer = cash.device_drawer(session, ctx.drawer_account_id)
    return drawer.id if drawer else None


class InfoBanner(QWidget):
    def __init__(self, text: str = "", kind: str = "Banner", parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QFrame

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame()
        self.frame.setObjectName(kind)
        fl = QHBoxLayout(self.frame)
        fl.setContentsMargins(12, 8, 12, 8)
        self.lbl = QLabel(text)
        self.lbl.setWordWrap(True)
        fl.addWidget(self.lbl, 1)
        lay.addWidget(self.frame)

    def set(self, text: str, kind: str = "Banner"):
        self.lbl.setText(text)
        self.frame.setObjectName(kind)
        repolish(self.frame)
        self.setVisible(bool(text))
