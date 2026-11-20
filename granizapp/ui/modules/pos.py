"""Vender: punto de venta pensado para teclado (y mouse) en la barra.

Flujo típico:  escribir "cl12" Enter · "2*corona" Enter · Enter (cobrar) · F1 efectivo ·
escribir lo recibido · Enter. El cambio queda a la vista.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from granizapp.core.models import ModifierGroup, ModifierOption, Product
from granizapp.core.services import cash, catalog, customers, inventory, sales
from granizapp.core.services.sales import Cart, CartFlavor, CartLine, CartModifier, PaymentInput, line_from_product
from granizapp.core.services.settings import get_setting
from granizapp.core.utils import WEEKDAYS, fmt_money, fmt_number, normalize
from granizapp.ui.context import AppContext, Topics
from granizapp.ui.dialogs import (
    CustomerPicker,
    FlavorDialog,
    FlavorOption,
    InfoBanner,
    ModifiersDialog,
    OpenTabsDialog,
    PaymentDialog,
    ensure_cash_open,
)
from granizapp.ui.widgets.common import Page, ask_text, button, confirm, label, show_error, shortcut, toast, repolish
from granizapp.ui.widgets.forms import MoneyEdit
from granizapp.ui.widgets.keys import KeyLineEdit
from granizapp.ui.widgets.table import Col, DataTable


@dataclass
class OptionTile:
    """Una adición que se puede agregar escribiendo su nombre (va a la línea seleccionada)."""

    option: ModifierOption
    group: ModifierGroup
    target: str

    @property
    def id(self):
        return self.option.id

    @property
    def name(self):
        return f"+ {self.option.name}"

    @property
    def price(self):
        return self.option.price_delta

    code = ""
    category_id = None

    @property
    def subtitle(self):
        return f"Adición para: {self.target}"


class ProductTiles(QWidget):
    """Cuadrícula de productos filtrable; se maneja con flechas desde el buscador."""

    def __init__(self, on_pick, parent=None):
        super().__init__(parent)
        self.on_pick = on_pick
        self.products: list[Product] = []
        self.colors: dict[str, str] = {}
        self.visible: list[Product] = []
        self.highlight = 0
        self.buttons: list[QPushButton] = []
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        self.cols = 4

    def set_products(self, products: list[Product], colors: dict[str, str]):
        self.products = products
        self.colors = colors
        self.show_products(products)

    def show_products(self, products: list[Product]):
        self.visible = products
        self.highlight = 0 if products else -1
        for b in self.buttons:
            self.grid.removeWidget(b)
            b.setParent(None)
            b.deleteLater()
        self.buttons = []
        for i, p in enumerate(products):
            if isinstance(p, OptionTile):
                text = f"{p.name}   {fmt_money(p.price)}\n{p.subtitle}"
            else:
                text = f"{p.name}\n{p.code + '  ·  ' if p.code else ''}{fmt_money(p.price)}"
            b = QPushButton(text)
            b.setObjectName("Tile")
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(54)
            b.clicked.connect(lambda _c=False, prod=p: self.on_pick(prod))
            self.buttons.append(b)
            self.grid.addWidget(b, i // self.cols, i % self.cols)
        self._paint()

    def _paint(self):
        for i, (b, p) in enumerate(zip(self.buttons, self.visible)):
            color = self.colors.get(p.category_id or "", "#888888") if not isinstance(p, OptionTile) else "#E0457B"
            sel = i == self.highlight
            b.setStyleSheet(
                f"QPushButton#Tile {{ border-left: 5px solid {color};"
                + (f" border-top: 2px solid {color}; border-right: 2px solid {color}; border-bottom: 2px solid {color};"
                   if sel else "") + " }"
            )

    def move(self, delta: int):
        if not self.visible:
            return
        self.highlight = max(0, min(len(self.visible) - 1, self.highlight + delta))
        self._paint()
        if 0 <= self.highlight < len(self.buttons):
            area = self.parent()
            while area is not None and not isinstance(area, QScrollArea):
                area = area.parent()
            if area is not None:
                area.ensureWidgetVisible(self.buttons[self.highlight])

    def current(self) -> Product | None:
        if 0 <= self.highlight < len(self.visible):
            return self.visible[self.highlight]
        return None

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cols = max(2, min(6, self.width() // 190))
        if cols != self.cols:
            self.cols = cols
            for i, b in enumerate(self.buttons):
                self.grid.addWidget(b, i // cols, i % cols)


class PosPage(Page):
    topics = {Topics.CATALOG, Topics.CASH, Topics.SALES, Topics.CUSTOMERS, Topics.SETTINGS}

    def __init__(self, ctx: AppContext):
        super().__init__(ctx)
        self.cart = Cart()
        self.products: list[Product] = []
        self.groups_by_product: dict[str, list] = {}
        self.category_filter: str | None = None
        self.customer_names: dict[str, str] = {}
        self.book: catalog.RecipeBook | None = None  # recetas y sabores (insumos con sabores)
        self.stocks: dict[str, float] = {}
        self.require_flavor = False
        self.flavor_hint: CartFlavor | None = None  # sabor escrito en el buscador: "cl12 ny"
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        # --- izquierda: buscador + productos
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        ll.setSpacing(8)
        head = QHBoxLayout()
        title = label("Vender", "PageTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.cash_lbl = label("", "Muted")
        head.addWidget(self.cash_lbl)
        ll.addLayout(head)
        self.search = KeyLineEdit(on_key=self._search_key)
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Código o nombre del producto · ej: cl12, cl12 ny, 2*corona  (Enter agrega)")
        self.search.textChanged.connect(self._filter)
        ll.addWidget(self.search)
        self.flavor_lbl = label("", "Success")
        self.flavor_lbl.hide()
        ll.addWidget(self.flavor_lbl)
        self.chips_box = QHBoxLayout()
        self.chips_box.setSpacing(6)
        ll.addLayout(self.chips_box)
        self.empty_lbl = label("", "Warning")
        self.empty_lbl.hide()
        ll.addWidget(self.empty_lbl)
        self.tiles = ProductTiles(self.add_product)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 4, 0)
        hl.addWidget(self.tiles)
        hl.addStretch(1)
        scroll.setWidget(holder)
        ll.addWidget(scroll, 1)
        ll.addWidget(label("↑↓ elegir producto · Enter agregar · Enter vacío = cobrar · +/− cantidad · Supr quitar · "
                           "F2 adiciones · F3 cantidad · F4 descuento · F5 cliente · F6 nota · F7 sabor · F8 vaciar · "
                           "F9 cuentas abiertas · F10 guardar cuenta · F11 fiar · F12 cobrar", "Hint", wrap=True))
        split.addWidget(left)

        # --- derecha: la cuenta
        right = QFrame()
        right.setObjectName("Card")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(14, 12, 14, 12)
        rl.setSpacing(8)
        top = QHBoxLayout()
        self.tab_lbl = label("Nueva venta", "SectionTitle")
        top.addWidget(self.tab_lbl)
        top.addStretch(1)
        self.customer_lbl = label("", "Muted")
        top.addWidget(self.customer_lbl)
        rl.addLayout(top)
        self.lines = DataTable([
            Col("Cant.", lambda ln: ln.quantity, "qty", width=56),
            Col("Producto", lambda ln: ln.description + (f"  · {ln.notes}" if ln.notes else ""), stretch=True),
            Col("Precio", lambda ln: ln.unit_price + ln.modifiers_price, "money", width=90),
            Col("Total", lambda ln: ln.total, "money", width=100, bold=lambda ln: True),
        ])
        self.lines.view.setSortingEnabled(False)
        self.lines.view.setFocusPolicy(Qt.NoFocus)
        self.lines.view.verticalHeader().setDefaultSectionSize(34)
        rl.addWidget(self.lines, 1)
        tot = QGridLayout()
        self.sub_lbl = label("", "Muted")
        self.disc_lbl = label("", "Muted")
        self.items_lbl = label("", "Muted")
        self.total_lbl = label(fmt_money(0), "BigTotal")
        tot.addWidget(self.items_lbl, 0, 0)
        tot.addWidget(self.sub_lbl, 0, 1, Qt.AlignRight)
        tot.addWidget(self.disc_lbl, 1, 1, Qt.AlignRight)
        tot.addWidget(label("TOTAL", "Muted"), 2, 0)
        tot.addWidget(self.total_lbl, 2, 1, Qt.AlignRight)
        rl.addLayout(tot)
        self.banner = InfoBanner()
        self.banner.hide()
        rl.addWidget(self.banner)
        b1 = QHBoxLayout()
        b1.addWidget(button("Cuentas abiertas (F9)", self.show_tabs))
        b1.addWidget(button("Guardar cuenta (F10)", self.save_tab))
        rl.addLayout(b1)
        b2 = QHBoxLayout()
        b2.addWidget(button("Fiar (F11)", self.charge_credit, "Big"))
        self.pay_btn = button("COBRAR (F12)", self.charge, "Primary")
        self.pay_btn.setObjectName("Primary")
        self.pay_btn.setMinimumHeight(48)
        self.pay_btn.setStyleSheet("font-size: 14pt; font-weight: 700;")
        b2.addWidget(self.pay_btn, 2)
        rl.addLayout(b2)
        split.addWidget(right)
        split.setSizes([620, 460])
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        self.key_bindings = [
            ("F2", self.edit_modifiers), ("F3", self.change_qty), ("F4", self.discount), ("F5", self.pick_customer),
            ("F6", self.add_note), ("F7", self.change_flavor), ("F8", self.clear_cart), ("F9", self.show_tabs),
            ("F10", self.save_tab), ("F11", self.charge_credit), ("F12", self.charge),
            ("Ctrl+Up", lambda: self.move_line(-1)), ("Ctrl+Down", lambda: self.move_line(1)),
        ]
        for keys, fn in self.key_bindings:
            shortcut(self, keys, fn)

    # --- datos ---------------------------------------------------------------------------
    def refresh(self):
        with self.ctx.session() as s:
            self.products = [p for p in catalog.list_products(s) if p.kind != "servicio" or p.price]
            cats = catalog.list_categories(s)
            self.cat_colors = {c.id: c.color for c in cats}
            self.roots = [c for c in cats if not c.parent_id]
            self.root_of = {c.id: catalog.root_category_of(cats, c.id) for c in cats}
            self.groups_by_product = {p.id: catalog.groups_for_product(s, p.id) for p in self.products}
            self.book = catalog.RecipeBook(s)
            self.stocks = inventory.stock_map(s)
            self.require_flavor = bool(get_setting(s, "require_flavor"))
            cs = cash.current_session(s, self.ctx.actor.device_id)
            self.cash_open = cs is not None
            self.customer_names = {c.id: c.name for c in customers.list_customers(s, True)}
        self.cash_lbl.setText("● Caja abierta" if self.cash_open else "○ Caja cerrada (se abre al cobrar)")
        self.cash_lbl.setObjectName("Success" if self.cash_open else "Warning")
        repolish(self.cash_lbl)
        self._build_chips()
        self.tiles.colors = self.cat_colors
        self._filter(self.search.text())
        self._render_cart()

    def _build_chips(self):
        while self.chips_box.count():
            item = self.chips_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.chip_buttons = []
        options = [(None, "Todos")] + [(c.id, c.name) for c in self.roots if any(
            self.root_of.get(p.category_id) == c.id for p in self.products)]
        for i, (cid, name) in enumerate(options):
            b = QPushButton(name)
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setChecked(cid == self.category_filter)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, c=cid: self._set_category(c))
            self.chips_box.addWidget(b)
            self.chip_buttons.append((cid, b))
        self.chips_box.addStretch(1)

    def _set_category(self, cid):
        self.category_filter = cid
        for c, b in self.chip_buttons:
            b.setChecked(c == cid)
        self._filter(self.search.text())
        self.search.setFocus()

    def _parse_query(self, text: str) -> tuple[float, str]:
        t = text.strip()
        if "*" in t:
            qty_txt, _, rest = t.partition("*")
            try:
                qty = float(qty_txt.replace(",", "."))
                if qty > 0:
                    return qty, rest.strip()
            except ValueError:
                pass
        return 1.0, t

    # --- sabores ---------------------------------------------------------------------------
    def _flavor_groups(self, product_id: str | None, only_asked: bool = True) -> list[str]:
        if self.book is None or not product_id:
            return []
        if only_asked:
            return self.book.asks_flavor(product_id)
        return [g for g in self.book.group_units(product_id) if self.book.variants.get(g)]

    def _match_flavor(self, product_id: str, text: str) -> CartFlavor | None:
        """«ny» o «nueva» -> Nueva York, entre los sabores que usa el producto."""
        nt = normalize(text).strip()
        if not nt or self.book is None:
            return None
        by_name = []
        for gid in self._flavor_groups(product_id, only_asked=False):
            for v in self.book.variants.get(gid, []):
                if (v.variant_code or "").upper() == text.strip().upper():
                    return CartFlavor(gid, v.id, v.variant_name)  # el código gana
                name = normalize(v.variant_name)
                if len(nt) >= 2 and (name.startswith(nt) or all(
                        any(word.startswith(w) for word in name.split()) for w in nt.split())):
                    by_name.append(CartFlavor(gid, v.id, v.variant_name))
        return by_name[0] if by_name else None

    def _split_flavor(self, q: str) -> tuple[str, CartFlavor | None]:
        """Separa el sabor escrito al final: "cl12 ny" -> ("cl12", Nueva York)."""
        words = q.split()
        if len(words) < 2 or catalog.find_product(None, q, self.products):
            return q, None
        for k in (1, 2, 3):
            if len(words) <= k:
                break
            prod_q = " ".join(words[:-k])
            found = catalog.find_product(None, prod_q, self.products)
            if found:
                fl = self._match_flavor(found[0].id, " ".join(words[-k:]))
                if fl is not None:
                    return prod_q, fl
        return q, None

    def _flavor_options(self, group_id: str) -> list[FlavorOption]:
        group = self.book.groups[group_id]
        pq = group.presentation_qty or 1
        return [FlavorOption(v.id, v.variant_name, v.variant_code or "", self.stocks.get(v.id, 0.0) / pq)
                for v in self.book.variants.get(group_id, [])]

    def _ask_flavors(self, line: CartLine, groups: list[str], current: list[CartFlavor] | None = None
                     ) -> list[CartFlavor] | None:
        """Pregunta el sabor de cada grupo. None = canceló."""
        picks: list[CartFlavor] = []
        for gid in groups:
            group = self.book.groups[gid]
            cups = int(round(self.book.group_units(line.product_id).get(gid, 1) * line.quantity)) or 1
            cur = [f.supply_id for f in (current or []) if f.group_id == gid and not f.is_default]
            dlg = FlavorDialog(self, line.name, group.name, self._flavor_options(gid), cups, cur,
                               self.require_flavor, group.presentation_name or "bolsa")
            if dlg.exec() != QDialog.Accepted:
                return None
            names = {v.id: v.variant_name for v in self.book.variants.get(gid, [])}
            picks.extend(CartFlavor(gid, sid, names.get(sid, "?")) for sid in dlg.result_ids())
        return picks

    def change_flavor(self):
        """F7: cambiar el sabor de la línea seleccionada."""
        line = self._current_line()
        if line is None:
            return
        groups = self._flavor_groups(line.product_id, only_asked=False)
        if not groups:
            toast(self, "Este producto no usa insumos con sabores (Inventario › Sabores)")
            return
        picks = self._ask_flavors(line, groups, line.flavors)
        if picks is not None:
            line.flavors = [f for f in line.flavors if f.group_id not in groups] + picks
            self._render_cart()
        self.search.setFocus()

    def _filter(self, text: str = ""):
        _qty, q = self._parse_query(text)
        q, self.flavor_hint = self._split_flavor(q)
        self.flavor_lbl.setVisible(self.flavor_hint is not None)
        if self.flavor_hint is not None:
            self.flavor_lbl.setText(f"Sabor: {self.flavor_hint.name}  ·  Enter agrega")
        products = self.products
        if self.category_filter and not q:
            products = [p for p in products if self.root_of.get(p.category_id) == self.category_filter]
        if q:
            products = catalog.find_product(None, q, products)
            options = self._matching_options(q)
            products = (options + products) if not products else (products + options)
        elif not self.category_filter:
            products = [p for p in products if p.favorite]
        self.tiles.show_products(products)
        self.empty_lbl.setVisible(bool(q) and not products)
        self.empty_lbl.setText(f"Nada coincide con «{q}». Revise el código o búsquelo por nombre.")

    def _matching_options(self, q: str) -> list[OptionTile]:
        line = self._current_line() if hasattr(self, "lines") else None
        nq = normalize(q)
        if line is None or not line.product_id or len(nq) < 3:
            return []
        out = []
        for group, options in self.groups_by_product.get(line.product_id, []):
            for opt in options:
                if all(w in normalize(opt.name) for w in nq.split()):
                    out.append(OptionTile(opt, group, line.name))
        return out

    # --- teclado ---------------------------------------------------------------------------
    def _search_key(self, event) -> bool:
        key = event.key()
        empty = not self.search.text()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            if empty:
                if not self.cart.is_empty():
                    self.charge()
            else:
                self._add_from_search()
            return True
        if key == Qt.Key_Down:
            self.tiles.move(self.tiles.cols if event.modifiers() & Qt.ShiftModifier else 1)
            return True
        if key == Qt.Key_Up:
            self.tiles.move(-(self.tiles.cols if event.modifiers() & Qt.ShiftModifier else 1))
            return True
        if key == Qt.Key_Escape and not empty:
            self.search.clear()
            return True
        if empty and key == Qt.Key_Plus:
            self._bump(1)
            return True
        if empty and key == Qt.Key_Minus:
            self._bump(-1)
            return True
        if empty and key == Qt.Key_Delete:
            self.remove_line()
            return True
        return False

    def activate(self):
        QTimer.singleShot(0, self.search, self.search.setFocus)

    def _add_from_search(self):
        qty, q = self._parse_query(self.search.text())
        product = self.tiles.current()
        if product is None:
            toast(self, f"No hay productos que coincidan con «{q}»")
            self.search.selectAll()  # lo próximo que se escriba reemplaza la búsqueda fallida
            return
        hint = self.flavor_hint
        if hint is not None and (isinstance(product, OptionTile)
                                 or hint.group_id not in self._flavor_groups(product.id, only_asked=False)):
            hint = None  # el sabor escrito no es de este producto: se pregunta
        self.add_product(product, qty, hint)

    # --- carrito ------------------------------------------------------------------------------
    def add_product(self, product: Product | OptionTile, qty: float | None = None, flavor: CartFlavor | None = None):
        if isinstance(product, OptionTile):
            self._add_option(product)
            return
        if qty is None:
            qty, _ = self._parse_query(self.search.text())
        weekday = date.today().weekday()
        if not catalog.is_available_today(product, weekday):
            if not confirm(self, f"«{product.name}» no está disponible los {WEEKDAYS[weekday]}. ¿Venderlo igual?"):
                return
        line = line_from_product(product, qty)
        ask = self._flavor_groups(product.id)
        if flavor is not None:
            line.flavors = [flavor]
            ask = [g for g in ask if g != flavor.group_id]
        if ask:
            picks = self._ask_flavors(line, ask)
            if picks is None:  # canceló: Enter reintenta, escribir reemplaza
                self.search.setFocus()
                self.search.selectAll()
                return
            line.flavors += picks
        groups = self.groups_by_product.get(product.id, [])
        if any(g.ask_on_add or g.min_select for g, _ in groups):
            dlg = ModifiersDialog(self, product.name, groups)
            if dlg.exec() != QDialog.Accepted:
                self.search.setFocus()
                self.search.selectAll()
                return
            line.modifiers = dlg.selected()
        added = self.cart.add(line)
        self.banner.hide()
        self.search.clear()
        self._render_cart(select=self.cart.lines.index(added))
        self.search.setFocus()

    def _add_option(self, tile: OptionTile):
        line = self._current_line()
        if line is None:
            return
        same_group = {o.id for o in self._group_options(line.product_id, tile.group.id)}
        if tile.group.max_select == 1:
            line.modifiers = [m for m in line.modifiers if m.option_id not in same_group]
        if not any(m.option_id == tile.option.id for m in line.modifiers):
            line.modifiers.append(CartModifier(tile.option.id, tile.option.name, tile.option.price_delta))
        self.search.clear()
        self._render_cart()
        self.search.setFocus()

    def _group_options(self, product_id: str | None, group_id: str):
        for group, options in self.groups_by_product.get(product_id or "", []):
            if group.id == group_id:
                return options
        return []

    def _render_cart(self, select: int | None = None):
        cur = self._line_index()
        self.lines.set_rows(self.cart.lines, keep_selection=False)
        idx = select if select is not None else (cur if cur is not None else len(self.cart.lines) - 1)
        if self.cart.lines:
            self.lines.select_row(max(0, min(idx, len(self.cart.lines) - 1)))
        self.items_lbl.setText(f"{fmt_number(self.cart.item_count, 2)} ítems")
        self.sub_lbl.setText(f"Subtotal {fmt_money(self.cart.subtotal)}")
        self.disc_lbl.setText(f"Descuento −{fmt_money(self.cart.discount)}" if self.cart.discount else "")
        self.total_lbl.setText(fmt_money(self.cart.total))
        if self.cart.sale_id:
            self.tab_lbl.setText(f"Cuenta: {self.cart.label}")
        else:
            self.tab_lbl.setText("Nueva venta")
        name = self.customer_names.get(self.cart.customer_id or "", "")
        self.customer_lbl.setText(f"Cliente: {name}" if name else "")

    def _line_index(self) -> int | None:
        row = self.lines.current()
        if row is None:
            return None
        for i, ln in enumerate(self.cart.lines):
            if ln is row:
                return i
        return None

    def _current_line(self) -> CartLine | None:
        i = self._line_index()
        return self.cart.lines[i] if i is not None else None

    def move_line(self, delta: int):
        i = self._line_index()
        if i is None:
            return
        self.lines.select_row(max(0, min(len(self.cart.lines) - 1, i + delta)))

    def _bump(self, delta: int):
        line = self._current_line()
        if line is None:
            return
        line.quantity += delta
        if line.quantity <= 0:
            self.remove_line()
            return
        self._render_cart()

    def remove_line(self):
        i = self._line_index()
        if i is None:
            return
        del self.cart.lines[i]
        self._render_cart(select=max(0, i - 1))

    def change_qty(self):
        line = self._current_line()
        if line is None:
            return
        qty, ok = QInputDialog.getDouble(self, "Cantidad", f"Cantidad de {line.name}:", line.quantity, 0, 1000, 2)
        if ok:
            if qty <= 0:
                self.remove_line()
            else:
                line.quantity = qty
                self._render_cart()
        self.search.setFocus()

    def edit_modifiers(self):
        line = self._current_line()
        if line is None or not line.product_id:
            return
        groups = self.groups_by_product.get(line.product_id, [])
        if not groups:
            toast(self, "Este producto no tiene adiciones configuradas (Productos > Adiciones)")
            return
        dlg = ModifiersDialog(self, line.name, groups, line.modifiers)
        if dlg.exec() == QDialog.Accepted:
            line.modifiers = dlg.selected()
            self._render_cart()
        self.search.setFocus()

    def discount(self):
        if self.cart.is_empty():
            return
        line = self._current_line()
        dlg = QDialog(self)
        dlg.setWindowTitle("Descuento")
        lay = QVBoxLayout(dlg)
        lay.addWidget(label("Descuento en pesos. Deje en 0 para quitarlo.", "Muted"))
        from PySide6.QtWidgets import QFormLayout, QRadioButton

        form = QFormLayout()
        on_line = QRadioButton(f"A la línea: {line.description}" if line else "A la línea")
        on_total = QRadioButton("A toda la venta")
        (on_line if line else on_total).setChecked(True)
        on_line.setEnabled(line is not None)
        amount = MoneyEdit(line.discount if line else self.cart.discount, big=True)
        form.addRow(on_line)
        form.addRow(on_total)
        form.addRow("Valor", amount)
        lay.addLayout(form)
        ok = button("Aplicar", dlg.accept, "Primary")
        amount.returnPressed.connect(dlg.accept)
        lay.addWidget(ok)
        amount.setFocus()
        if dlg.exec() == QDialog.Accepted:
            v = amount.value()
            if on_line.isChecked() and line:
                line.discount = min(v, int(line.quantity * (line.unit_price + line.modifiers_price)))
            else:
                self.cart.discount = min(v, self.cart.subtotal)
            self._render_cart()
        self.search.setFocus()

    def add_note(self):
        line = self._current_line()
        if line is None:
            return
        text = ask_text(self, "Nota", f"Nota para {line.name} (ej: sin hielo, poco licor):", line.notes, required=False)
        if text is not None:
            line.notes = text
            self._render_cart()
        self.search.setFocus()

    def pick_customer(self):
        cid = CustomerPicker.pick(self, self.ctx, "Cliente de la venta", "Asocie la venta a un cliente (opcional).")
        if cid:
            self.cart.customer_id = cid
            with self.ctx.session() as s:
                self.customer_names = {c.id: c.name for c in customers.list_customers(s, True)}
            self._render_cart()
        self.search.setFocus()

    def clear_cart(self, ask: bool = True):
        if self.cart.is_empty() and not self.cart.sale_id:
            return
        if ask and not confirm(self, "¿Vaciar la venta actual?" + (
                "\n(La cuenta abierta guardada no se borra.)" if self.cart.sale_id else "")):
            return
        self.cart = Cart()
        self._render_cart()
        self.search.setFocus()

    # --- cuentas abiertas -----------------------------------------------------------------------
    def save_tab(self):
        if self.cart.is_empty():
            toast(self, "La cuenta está vacía")
            return
        default = self.cart.label or self.customer_names.get(self.cart.customer_id or "", "")
        name = ask_text(self, "Guardar cuenta abierta", "Nombre de la cuenta (mesa o cliente):", default)
        if not name:
            return
        try:
            with self.ctx.session() as s:
                sales.save_open_tab(s, self.cart, self.ctx.actor, name)
            self.ctx.notify(Topics.SALES)
            toast(self, f"Cuenta «{name}» guardada")
            self.cart = Cart()
            self._render_cart()
        except Exception as exc:
            show_error(self, exc)
        self.search.setFocus()

    def show_tabs(self):
        dlg = OpenTabsDialog(self, self.ctx)
        if dlg.exec() == QDialog.Accepted and dlg.chosen:
            if not self.cart.is_empty() and self.cart.sale_id != dlg.chosen:
                if not confirm(self, "Hay productos en la venta actual. ¿Agregarlos a la cuenta que va a abrir?",
                               yes="Agregar", no="Descartar"):
                    self.cart = Cart()
            with self.ctx.session() as s:
                tab = sales.load_cart(s, dlg.chosen)
            for line in self.cart.lines:
                tab.add(line)
            self.cart = tab
            self._render_cart()
        self.search.setFocus()

    # --- cobro -----------------------------------------------------------------------------------
    def _methods(self):
        with self.ctx.session() as s:
            return sales.payment_methods(s)

    def charge(self):
        if self.cart.is_empty():
            return
        cs_id = ensure_cash_open(self, self.ctx)
        if cs_id is None:
            return
        name = self.customer_names.get(self.cart.customer_id or "", "")
        methods = self._methods()
        if not methods:
            show_error(self, "No hay medios de pago activos. Actívelos en Configuración › Medios de pago.")
            return
        dlg = PaymentDialog(self, methods, self.cart.total, allow_credit=True, customer_name=name)
        if dlg.exec() != QDialog.Accepted:
            self.search.setFocus()
            return
        result = dlg.result_value()
        customer_id = self.cart.customer_id
        paid = sum(p.amount for p in result.payments)
        if paid < self.cart.total:
            customer_id = customer_id or CustomerPicker.pick(
                self, self.ctx, "¿A quién se le fía?",
                f"Quedan {fmt_money(self.cart.total - paid)} pendientes. Elija o cree el cliente.")
            if not customer_id:
                self.search.setFocus()
                return
        self._finish(cs_id, result.payments, customer_id, result.change)

    def charge_credit(self):
        if self.cart.is_empty():
            return
        cs_id = ensure_cash_open(self, self.ctx)
        if cs_id is None:
            return
        customer_id = self.cart.customer_id or CustomerPicker.pick(
            self, self.ctx, "Fiar a…", f"Total a fiar: {fmt_money(self.cart.total)}")
        if not customer_id:
            self.search.setFocus()
            return
        with self.ctx.session() as s:
            owed = customers.customer_balance(s, customer_id)
        name = self.customer_names.get(customer_id) or ""
        if not name:
            with self.ctx.session() as s:
                self.customer_names = {c.id: c.name for c in customers.list_customers(s, True)}
            name = self.customer_names.get(customer_id, "")
        if not confirm(self, f"Fiar {fmt_money(self.cart.total)} a {name}.\n"
                             f"Debe actualmente {fmt_money(owed)}; quedará debiendo {fmt_money(owed + self.cart.total)}.",
                       "Confirmar fiado", yes="Fiar"):
            self.search.setFocus()
            return
        self._finish(cs_id, [], customer_id, 0)

    def _finish(self, cs_id: str, payments: list[PaymentInput], customer_id: str | None, change: int):
        allow_over = False
        while True:
            try:
                with self.ctx.session() as s:
                    sale = sales.checkout(s, self.cart, payments, self.ctx.actor, cs_id, customer_id=customer_id,
                                          allow_over_limit=allow_over)
                    code, total, balance = sales.sale_code(sale), sale.total, sale.balance
                break
            except Exception as exc:
                from granizapp.core.services.common import ServiceError

                if isinstance(exc, ServiceError) and "cupo" in str(exc) and not allow_over and self.ctx.is_admin:
                    if confirm(self, f"{exc}\n\n¿Autorizar de todas formas?", danger=True, yes="Autorizar"):
                        allow_over = True
                        continue
                show_error(self, exc)
                return
        self.cart = Cart()
        self._render_cart()
        msg = f"Venta {code} registrada: {fmt_money(total)}."
        if change:
            msg += f"   CAMBIO: {fmt_money(change)}"
        if balance:
            msg += f"   Quedó fiado: {fmt_money(balance)} a {self.customer_names.get(customer_id, '')}"
        self.banner.set(msg, "BannerOk")
        self.banner.show()
        self.ctx.notify(Topics.SALES, Topics.CASH, Topics.INVENTORY, Topics.CUSTOMERS, Topics.FINANCE)
        self.search.setFocus()
