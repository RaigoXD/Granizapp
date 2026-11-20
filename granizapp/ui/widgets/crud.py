"""Panel genérico de listado + crear/editar/borrar, para catálogos simples.

Cada uso define columnas, campos del formulario y funciones de servicio; así agregar un
catálogo nuevo (p. ej. "Mesas" o "Sucursales") son pocas líneas.
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from granizapp.ui.context import AppContext
from granizapp.ui.widgets.common import busy, button, confirm, run, shortcut, show_error
from granizapp.ui.widgets.forms import Field, FormDialog
from granizapp.ui.widgets.table import Col, DataTable


def column_values(obj) -> dict:
    """Valores de las columnas de un registro (sin tocar relaciones perezosas)."""
    return {c.key: getattr(obj, c.key, None) for c in obj.__table__.columns}


class CrudPanel(QWidget):
    def __init__(
        self,
        ctx: AppContext,
        title: str,
        cols: list[Col],
        load: Callable[[Any], list],
        fields: Callable[[Any], list[Field]],
        save: Callable[[Any, dict, str | None], Any],
        delete: Callable[[Any, str], None] | None = None,
        to_values: Callable[[Any], dict] | None = None,
        topics: tuple[str, ...] = (),
        search: bool = True,
        extra_buttons: list[QWidget] | None = None,
        admin_only: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.ctx = ctx
        self.title = title
        self._load = load
        self._fields = fields
        self._save = save
        self._delete = delete
        self._to_values = to_values or column_values
        self.topics = topics
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.btn_new = button("Nuevo", self.new, "Primary", "Ctrl+N")
        self.btn_edit = button("Editar", self.edit, "", "Enter")
        bar.addWidget(self.btn_new)
        bar.addWidget(self.btn_edit)
        if delete is not None:
            self.btn_del = button("Eliminar", self.remove, "Danger", "Supr")
            bar.addWidget(self.btn_del)
        for b in extra_buttons or []:
            bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.table = DataTable(cols, search=search, export_name=title.lower().replace(" ", "_"))
        self.table.activated.connect(lambda _r: self.edit())
        lay.addWidget(self.table, 1)
        shortcut(self, "Ctrl+N", self.new)
        if delete is not None:
            shortcut(self.table.view, "Delete", self.remove)
        if admin_only and not ctx.is_admin:
            for b in (self.btn_new, self.btn_edit):
                b.setEnabled(False)
            if delete is not None:
                self.btn_del.setEnabled(False)

    def refresh(self):
        with self.ctx.session() as s:
            rows = self._load(s)
        self.table.set_rows(rows)

    def new(self):
        self._open(None)

    def edit(self):
        row = self.table.current()
        if row is not None:
            self._open(row)

    def _open(self, obj):
        if not self.btn_new.isEnabled():
            return
        with self.ctx.session() as s:
            fields = self._fields(s)
        values = self._to_values(obj) if obj is not None else {}
        title = ("Editar " if obj else "Nuevo: ") + self.title.lower()
        while True:  # si hay un error se vuelve a abrir con lo que se escribió
            data = FormDialog.ask(self, title, fields, values)
            if data is None:
                return
            try:
                with busy(), self.ctx.session() as s:
                    self._save(s, data, obj.id if obj is not None else None)
                break
            except Exception as exc:
                show_error(self, exc)
                values = {**values, **data}
        self.refresh()
        self.ctx.notify(*self.topics)

    def remove(self):
        row = self.table.current()
        if row is None or self._delete is None or not self.btn_new.isEnabled():
            return
        name = getattr(row, "name", "") or "el registro"
        if not confirm(self, f"¿Eliminar {name}?", danger=True, yes="Eliminar", no="Cancelar"):
            return

        def do():
            with self.ctx.session() as s:
                self._delete(s, row.id)
            return True

        if run(self, do):
            self.refresh()
            self.ctx.notify(*self.topics)
