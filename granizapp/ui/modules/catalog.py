"""Productos, categorías y adiciones (grupos de modificadores) con sus recetas."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from granizapp.core.models import Product, ProductKind
from granizapp.core.services import catalog
from granizapp.core.utils import fmt_money
from granizapp.ui.context import AppContext, Topics
from granizapp.ui.recipe_dialog import RecipeDialog
from granizapp.ui.widgets.common import Page, button, confirm, label, page_header, run, shortcut, show_error
from granizapp.ui.widgets.crud import CrudPanel, column_values
from granizapp.ui.widgets.forms import DaysPicker, Field, FormDialog, MoneyEdit, NumberEdit
from granizapp.ui.widgets.table import Col, DataTable

COLORS = [("#7C5CFC", "Morado"), ("#2FB5A8", "Verde agua"), ("#E58A2E", "Naranja"), ("#D9A400", "Amarillo"),
          ("#D9534F", "Rojo"), ("#3A9AD9", "Azul"), ("#E0457B", "Rosado"), ("#8A8A8A", "Gris"), ("#4CAF50", "Verde")]


class ProductDialog(QDialog):
    def __init__(self, parent, ctx: AppContext, product: Product | None, categories: list[tuple[str, str]],
                 groups: list, selected_groups: list[str]):
        super().__init__(parent)
        self.ctx = ctx
        self.product = product
        self.setWindowTitle("Editar producto" if product else "Nuevo producto")
        self.setMinimumWidth(620)
        p = product
        lay = QVBoxLayout(self)
        lay.addWidget(label(self.windowTitle(), "SectionTitle"))
        form = QFormLayout()
        self.name = QLineEdit(p.name if p else "")
        self.code = QLineEdit(p.code if p else "")
        self.code.setPlaceholderText("Código corto para vender rápido, ej: CL12")
        self.category = QComboBox()
        for cid, path in categories:
            self.category.addItem(path, cid)
        if p and p.category_id:
            self.category.setCurrentIndex(max(0, self.category.findData(p.category_id)))
        self.kind = QComboBox()
        for k, text in ProductKind.LABELS.items():
            self.kind.addItem(text, k)
        self.kind.setCurrentIndex(max(0, self.kind.findData(p.kind if p else ProductKind.PREPARED)))
        self.price = MoneyEdit(p.price if p else 0)
        self.size = QLineEdit(p.size_label if p else "")
        self.size.setPlaceholderText("Ej: 12 oz")
        self.volume = NumberEdit(p.volume_ml or 0 if p else 0)
        self.manual_cost = MoneyEdit(p.manual_cost if p else 0)
        self.alcohol = QCheckBox("Contiene licor")
        self.alcohol.setChecked(bool(p.is_alcoholic) if p else False)
        self.track = QCheckBox("Descontar inventario según la receta")
        self.track.setChecked(bool(p.track_inventory) if p else True)
        self.favorite = QCheckBox("Mostrar en la pantalla de venta (favorito)")
        self.favorite.setChecked(bool(p.favorite) if p else True)
        self.active = QCheckBox("Activo")
        self.active.setChecked(bool(p.active) if p else True)
        self.days = DaysPicker(p.available_days if p else "0123456")
        self.notes = QLineEdit(p.notes if p else "")
        form.addRow("Nombre *", self.name)
        form.addRow("Código", self.code)
        form.addRow("Categoría", self.category)
        form.addRow("Tipo", self.kind)
        form.addRow("Precio de venta *", self.price)
        form.addRow("Tamaño", self.size)
        form.addRow("Volumen (ml)", self.volume)
        form.addRow("Costo manual", self.manual_cost)
        form.addRow("", label("Solo si no tiene receta (p. ej. servicios).", "Hint"))
        form.addRow("Días de venta", self.days)
        form.addRow("", self.alcohol)
        form.addRow("", self.track)
        form.addRow("", self.favorite)
        form.addRow("", self.active)
        form.addRow("Notas", self.notes)
        lay.addLayout(form)
        gb = QGroupBox("Adiciones que se le pueden agregar")
        gl = QVBoxLayout(gb)
        self.group_checks = []
        for g in groups:
            cb = QCheckBox(g.name)
            cb.setChecked(g.id in selected_groups)
            cb.setProperty("gid", g.id)
            gl.addWidget(cb)
            self.group_checks.append(cb)
        lay.addWidget(gb)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Guardar")
        bb.button(QDialogButtonBox.Save).setObjectName("Primary")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.saved_id: str | None = None
        self.name.setFocus()

    def save(self):
        data = {
            "name": self.name.text(), "code": self.code.text(), "category_id": self.category.currentData(),
            "kind": self.kind.currentData(), "price": self.price.value(), "size_label": self.size.text().strip(),
            "volume_ml": self.volume.value() or None, "manual_cost": self.manual_cost.value(),
            "is_alcoholic": self.alcohol.isChecked(), "track_inventory": self.track.isChecked(),
            "favorite": self.favorite.isChecked(), "active": self.active.isChecked(),
            "available_days": self.days.value(), "notes": self.notes.text().strip(),
        }
        groups = [cb.property("gid") for cb in self.group_checks if cb.isChecked()]
        try:
            with self.ctx.session() as s:
                prod = catalog.save_product(s, data, self.product.id if self.product else None, self.ctx.actor)
                catalog.set_product_groups(s, prod.id, groups)
                self.saved_id = prod.id
            self.accept()
        except Exception as exc:
            show_error(self, exc)


class CatalogPage(Page):
    topics = {Topics.CATALOG, Topics.INVENTORY}

    def __init__(self, ctx: AppContext):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.addWidget(page_header("Productos y adiciones", "Lo que se vende, a qué precio, con qué receta"))
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        # productos
        w = QWidget()
        wl = QVBoxLayout(w)
        wl.setContentsMargins(0, 8, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(button("Nuevo producto", self.new_product, "Primary", "Ctrl+N"))
        bar.addWidget(button("Editar", self.edit_product, "", "Enter"))
        bar.addWidget(button("Receta / costo", self.edit_recipe, "", "Ctrl+R"))
        bar.addWidget(button("Duplicar", self.duplicate))
        bar.addWidget(button("Eliminar", self.delete_product, "Danger"))
        bar.addStretch(1)
        self.cat_filter = QComboBox()
        self.cat_filter.currentIndexChanged.connect(lambda _i: self._apply_filter())
        bar.addWidget(label("Categoría:"))
        bar.addWidget(self.cat_filter)
        self.show_inactive = QCheckBox("Ver inactivos")
        self.show_inactive.toggled.connect(lambda _c: self.safe_refresh())
        bar.addWidget(self.show_inactive)
        wl.addLayout(bar)
        self.products = DataTable([
            Col("Código", lambda p: p.code, width=70),
            Col("Producto", lambda p: p.name, stretch=True, bold=lambda p: p.favorite and p.active),
            Col("Categoría", lambda p: self.paths.get(p.category_id, ""), width=200),
            Col("Tipo", lambda p: ProductKind.LABELS.get(p.kind, p.kind), width=100),
            Col("Precio", lambda p: p.price, "money", width=90),
            Col("Costo", lambda p: self.costs.get(p.id), "money", width=85),
            Col("Margen", lambda p: self._margin(p), "pct", width=75,
                color=lambda p: self._margin_color(p)),
            Col("Receta", lambda p: "Sí" if self.book.has_recipe(p.id) else "—", width=60,
                color=lambda p: None if self.book.has_recipe(p.id) or p.kind == "servicio" else "warning"),
            Col("Días", lambda p: "Todos" if p.available_days == "0123456" else self._days(p.available_days), width=90),
            Col("Activo", lambda p: p.active, "bool", width=55),
        ], search=True, placeholder="Buscar producto o código…", export_name="productos",
            footer=lambda rows: f"{len(rows)} productos")
        self.products.activated.connect(lambda _p: self.edit_product())
        wl.addWidget(self.products, 1)
        self.tabs.addTab(w, "Productos")

        # categorías
        self.categories_panel = CrudPanel(
            ctx, "Categoría",
            [Col("Categoría", lambda c: self.paths.get(c.id, c.name), stretch=True),
             Col("Color", lambda c: dict(COLORS).get(c.color, c.color), width=110),
             Col("Orden", lambda c: c.sort_order, "int", width=60),
             Col("Activa", lambda c: c.active, "bool", width=60)],
            load=lambda s: catalog.list_categories(s, include_inactive=True),
            fields=lambda s: [
                Field("name", "Nombre", required=True),
                Field("parent_id", "Dentro de", "choice",
                      options=[("", "— Categoría principal —")] + [(c.id, c.name) for c in catalog.list_categories(s)
                                                                   if not c.parent_id]),
                Field("color", "Color", "choice", options=COLORS, default="#7C5CFC"),
                Field("sort_order", "Orden", "int"),
                Field("active", "Activa", "bool", default=True),
            ],
            save=lambda s, d, cid: catalog.save_category(s, d, cid),
            delete=lambda s, cid: catalog.delete_category(s, cid),
            to_values=column_values,
            topics=(Topics.CATALOG,),
        )
        self.tabs.addTab(self.categories_panel, "Categorías")

        # adiciones
        a = QWidget()
        al = QHBoxLayout(a)
        al.setContentsMargins(0, 8, 0, 0)
        split = QSplitter(Qt.Horizontal)
        self.groups_panel = CrudPanel(
            ctx, "Grupo de adiciones",
            [Col("Grupo", lambda g: g.name, stretch=True),
             Col("Máx.", lambda g: g.max_select or "Sin límite", width=80),
             Col("Mín.", lambda g: g.min_select, "int", width=50),
             Col("Preguntar", lambda g: g.ask_on_add, "bool", width=75)],
            load=lambda s: catalog.list_groups(s, include_inactive=True),
            fields=lambda s: [
                Field("name", "Nombre", required=True, placeholder="Ej: Adiciones, Escarchado, Salsas"),
                Field("max_select", "Máximo a elegir", "int", help="0 = sin límite; 1 = elegir solo una opción"),
                Field("min_select", "Mínimo obligatorio", "int", help="1 = obligatorio elegir (p. ej. sabor)"),
                Field("ask_on_add", "Abrir automáticamente al vender", "bool",
                      help="Si se marca, al agregar el producto se abre la ventana de opciones"),
                Field("sort_order", "Orden", "int"),
                Field("active", "Activo", "bool", default=True),
            ],
            save=lambda s, d, gid: catalog.save_group(s, d, gid),
            delete=lambda s, gid: catalog.delete_group(s, gid),
            to_values=column_values,
            topics=(Topics.CATALOG,),
            extra_buttons=[button("Asignar a productos…", self.assign_group)],
        )
        self.groups_panel.table.selection_changed.connect(lambda _g: self._load_options())
        split.addWidget(self.groups_panel)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        self.opt_title = label("Opciones del grupo", "SectionTitle")
        rl.addWidget(self.opt_title)
        ob = QHBoxLayout()
        ob.addWidget(button("Nueva opción", self.new_option, "Primary"))
        ob.addWidget(button("Editar", self.edit_option))
        ob.addWidget(button("Receta de la opción", self.option_recipe))
        ob.addWidget(button("Eliminar", self.delete_option, "Danger"))
        ob.addStretch(1)
        rl.addLayout(ob)
        self.options = DataTable([
            Col("Opción", lambda o: o.name, stretch=True),
            Col("Precio extra", lambda o: o.price_delta, "money", width=100),
            Col("Costo", lambda o: self.book.option_cost(o.id), "money", width=90),
            Col("Activa", lambda o: o.active, "bool", width=60),
        ])
        self.options.activated.connect(lambda _o: self.edit_option())
        rl.addWidget(self.options, 1)
        rl.addWidget(label("La receta de una opción define qué insumo gasta (ej: Bolitas explosivas = 30 g de perlas).",
                           "Hint", wrap=True))
        split.addWidget(right)
        al.addWidget(split)
        self.tabs.addTab(a, "Adiciones y modificadores")
        shortcut(self, "Ctrl+R", self.edit_recipe)
        shortcut(w, "Ctrl+N", self.new_product)

    # --- datos ----------------------------------------------------------------------------------
    def refresh(self):
        with self.ctx.session() as s:
            cats = catalog.list_categories(s, include_inactive=True)
            self.paths = catalog.category_paths(cats)
            self.book = catalog.RecipeBook(s)
            prods = catalog.list_products(s, include_inactive=self.show_inactive.isChecked())
            self.costs = {p.id: self.book.product_cost(p.id) for p in prods}
            self.groups = catalog.list_groups(s, include_inactive=True)
        current = self.cat_filter.currentData()
        self.cat_filter.blockSignals(True)
        self.cat_filter.clear()
        self.cat_filter.addItem("Todas", "")
        for c in cats:
            self.cat_filter.addItem(self.paths[c.id], c.id)
        self.cat_filter.setCurrentIndex(max(0, self.cat_filter.findData(current or "")))
        self.cat_filter.blockSignals(False)
        self.all_products = prods
        self._apply_filter()
        self.categories_panel.refresh()
        self.groups_panel.refresh()
        self._load_options()

    def _apply_filter(self):
        cid = self.cat_filter.currentData()
        rows = self.all_products
        if cid:
            rows = [p for p in rows if p.category_id == cid or self.paths.get(p.category_id, "").startswith(self.paths.get(cid, "~"))]
        self.products.set_rows(rows)

    def _margin(self, p):
        c = self.costs.get(p.id)
        return (p.price - c) / p.price if p.price and c is not None else None

    def _margin_color(self, p):
        m = self._margin(p)
        if m is None:
            return None
        return "danger" if m < 0.4 else ("warning" if m < 0.6 else "success")

    @staticmethod
    def _days(days: str) -> str:
        names = ["L", "M", "X", "J", "V", "S", "D"]
        return "".join(names[int(d)] for d in days if d.isdigit())

    # --- productos ---------------------------------------------------------------------------------
    def _category_options(self):
        return sorted(self.paths.items(), key=lambda kv: kv[1])

    def _product_dialog(self, product: Product | None):
        with self.ctx.session() as s:
            selected = catalog.product_group_ids(s, product.id) if product else []
        dlg = ProductDialog(self, self.ctx, product, self._category_options(), self.groups, selected)
        if dlg.exec() == QDialog.Accepted:
            self.ctx.notify(Topics.CATALOG)
            return dlg.saved_id
        return None

    def new_product(self):
        pid = self._product_dialog(None)
        if pid and confirm(self, "Producto creado. ¿Definir ahora su receta (insumos que gasta)?"):
            self.products.select_where(lambda p: p.id == pid)
            self.edit_recipe()

    def edit_product(self):
        p = self.products.current()
        if p is not None:
            self._product_dialog(p)

    def edit_recipe(self):
        p = self.products.current()
        if p is None:
            return
        if RecipeDialog(self, self.ctx, product_id=p.id, title=p.name, price=p.price).exec() == QDialog.Accepted:
            self.ctx.notify(Topics.CATALOG)

    def duplicate(self):
        p = self.products.current()
        if p is None:
            return

        def do():
            with self.ctx.session() as s:
                data = {k: getattr(p, k) for k in catalog.PRODUCT_FIELDS}
                data["name"] = f"{p.name} (copia)"
                data["code"] = ""
                new = catalog.save_product(s, data, actor=self.ctx.actor)
                catalog.set_product_groups(s, new.id, catalog.product_group_ids(s, p.id))
                lines = [{"supply_id": ln.supply_id, "sub_product_id": ln.sub_product_id, "quantity": ln.quantity}
                         for ln in catalog.recipe_lines(s, p.id)]
                if lines:
                    catalog.set_recipe(s, lines, new.id)
                return new.id

        new_id = run(self, do)
        if new_id:
            self.ctx.notify(Topics.CATALOG)
            self.products.select_where(lambda x: x.id == new_id)

    def delete_product(self):
        p = self.products.current()
        if p is None:
            return
        if confirm(self, f"¿Eliminar «{p.name}»? Las ventas pasadas se conservan.", danger=True, yes="Eliminar"):
            def do():
                with self.ctx.session() as s:
                    catalog.delete_product(s, p.id, self.ctx.actor)
                return True

            if run(self, do):
                self.ctx.notify(Topics.CATALOG)

    # --- opciones ------------------------------------------------------------------------------------
    def _load_options(self):
        g = self.groups_panel.table.current()
        if g is None:
            self.options.set_rows([])
            self.opt_title.setText("Opciones del grupo")
            return
        self.opt_title.setText(f"Opciones de «{g.name}»")
        with self.ctx.session() as s:
            self.options.set_rows(catalog.list_options(s, g.id, include_inactive=True))

    def _option_form(self, values=None):
        return FormDialog.ask(self, "Opción", [
            Field("name", "Nombre", required=True, placeholder="Ej: Bolitas explosivas"),
            Field("price_delta", "Precio extra", "money", help="0 si no cobra extra"),
            Field("sort_order", "Orden", "int"),
            Field("active", "Activa", "bool", default=True),
        ], values)

    def new_option(self):
        g = self.groups_panel.table.current()
        if g is None:
            return
        data = self._option_form()
        if data is None:
            return
        data["group_id"] = g.id

        def do():
            with self.ctx.session() as s:
                return catalog.save_option(s, data).id

        oid = run(self, do)
        if oid:
            self.ctx.notify(Topics.CATALOG)
            if confirm(self, "¿Definir qué insumo gasta esta opción (receta)?"):
                self.options.select_where(lambda o: o.id == oid)
                self.option_recipe()

    def edit_option(self):
        o = self.options.current()
        if o is None:
            return
        data = self._option_form(column_values(o))
        if data is None:
            return

        def do():
            with self.ctx.session() as s:
                catalog.save_option(s, data, o.id)
            return True

        if run(self, do):
            self.ctx.notify(Topics.CATALOG)

    def option_recipe(self):
        o = self.options.current()
        if o is None:
            return
        if RecipeDialog(self, self.ctx, option_id=o.id, title=o.name, price=o.price_delta).exec() == QDialog.Accepted:
            self.ctx.notify(Topics.CATALOG)

    def delete_option(self):
        o = self.options.current()
        if o is None or not confirm(self, f"¿Eliminar la opción «{o.name}»?", danger=True, yes="Eliminar"):
            return

        def do():
            with self.ctx.session() as s:
                catalog.delete_option(s, o.id)
            return True

        if run(self, do):
            self.ctx.notify(Topics.CATALOG)

    def assign_group(self):
        g = self.groups_panel.table.current()
        if g is None:
            return
        with self.ctx.session() as s:
            prods = catalog.list_products(s)
            linked = {p.id for p in prods if g.id in catalog.product_group_ids(s, p.id)}
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Productos con «{g.name}»")
        dlg.resize(420, 520)
        lay = QVBoxLayout(dlg)
        lay.addWidget(label(f"Marque los productos que pueden llevar «{g.name}»", "SectionTitle"))
        lst = QListWidget()
        for p in prods:
            it = QListWidgetItem(f"{p.name}  ·  {fmt_money(p.price)}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if p.id in linked else Qt.Unchecked)
            it.setData(Qt.UserRole, p.id)
            lst.addItem(it)
        lay.addWidget(lst, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return

        def do():
            with self.ctx.session() as s:
                for i in range(lst.count()):
                    it = lst.item(i)
                    pid = it.data(Qt.UserRole)
                    groups = catalog.product_group_ids(s, pid)
                    want = it.checkState() == Qt.Checked
                    if want and g.id not in groups:
                        catalog.set_product_groups(s, pid, groups + [g.id])
                    elif not want and g.id in groups:
                        catalog.set_product_groups(s, pid, [x for x in groups if x != g.id])
            return True

        if run(self, do):
            self.ctx.notify(Topics.CATALOG)
