"""Tabla genérica: columnas declarativas, búsqueda sin tildes, orden numérico y exportar a Excel."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QAction, QFont, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from granizapp.core.utils import fmt_date, fmt_datetime, fmt_money, fmt_number, fmt_pct, fmt_time, matches
from granizapp.ui import theme
from granizapp.ui.widgets.keys import KeyLineEdit, KeyTableView

NUMERIC = {"money", "number", "qty", "pct", "int"}


@dataclass
class Col:
    title: str
    get: Callable[[Any], Any]
    kind: str = "text"  # text|money|number|qty|int|pct|date|datetime|time|bool
    width: int | None = None
    stretch: bool = False
    color: Callable[[Any], str | None] | None = None  # nombre de color del tema
    bold: Callable[[Any], bool] | None = None
    tooltip: Callable[[Any], str] | None = None


def format_value(value, kind: str) -> str:
    if value is None or value == "":
        return ""
    if kind == "money":
        return fmt_money(value)
    if kind in ("number", "qty"):
        return fmt_number(value, 2)
    if kind == "int":
        return fmt_number(value, 0)
    if kind == "pct":
        return fmt_pct(value)
    if kind == "date":
        return fmt_date(value)
    if kind == "datetime":
        return fmt_datetime(value)
    if kind == "time":
        return fmt_time(value)
    if kind == "bool":
        return "Sí" if value else "No"
    return str(value)


def _sort_key(value, kind: str):
    if value is None:
        return float("-inf") if kind in NUMERIC else ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if kind in NUMERIC:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float("-inf")
    return str(value).lower()


class RowsModel(QAbstractTableModel):
    def __init__(self, cols: list[Col]):
        super().__init__()
        self.cols = cols
        self.rows: list[Any] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.cols)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.cols[section].title
        if orientation == Qt.Horizontal and role == Qt.TextAlignmentRole:
            kind = self.cols[section].kind
            return int((Qt.AlignRight if kind in NUMERIC else Qt.AlignLeft) | Qt.AlignVCenter)
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        col = self.cols[index.column()]
        if role == Qt.DisplayRole:
            try:
                return format_value(col.get(row), col.kind)
            except Exception:  # una celda con datos raros no debe tumbar la tabla
                return "?"
        if role == Qt.UserRole:
            try:
                return _sort_key(col.get(row), col.kind)
            except Exception:
                return ""
        if role == Qt.UserRole + 1:
            return row
        if role == Qt.TextAlignmentRole:
            return int((Qt.AlignRight if col.kind in NUMERIC else Qt.AlignLeft) | Qt.AlignVCenter)
        if role == Qt.ForegroundRole and col.color is not None:
            name = col.color(row)
            return theme.qcolor(name) if name else None
        if role == Qt.FontRole and col.bold is not None and col.bold(row):
            f = QFont()
            f.setBold(True)
            return f
        if role == Qt.ToolTipRole and col.tooltip is not None:
            return col.tooltip(row)
        return None

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()


class FilterProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.query = ""
        self.setSortRole(Qt.UserRole)

    def set_query(self, q: str):
        if hasattr(self, "beginFilterChange"):  # Qt 6.10+
            self.beginFilterChange()
            self.query = q
            self.endFilterChange()
        else:
            self.query = q
            self.invalidateRowsFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if not self.query:
            return True
        model: RowsModel = self.sourceModel()
        texts = [model.data(model.index(source_row, c)) for c in range(model.columnCount())]
        return matches(self.query, *texts)


class DataTable(QWidget):
    activated = Signal(object)
    selection_changed = Signal(object)

    def __init__(self, cols: list[Col], parent=None, search: bool = False, placeholder: str = "Buscar…",
                 export_name: str = "datos", multi: bool = False, footer: Callable[[list], str] | None = None):
        super().__init__(parent)
        self.cols = cols
        self.export_name = export_name
        self.footer_fn = footer
        self.model = RowsModel(cols)
        self.proxy = FilterProxy()
        self.proxy.setSourceModel(self.model)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.search: QLineEdit | None = None
        if search:
            self.search = KeyLineEdit(on_key=self._search_key)
            self.search.setPlaceholderText(placeholder)
            self.search.setClearButtonEnabled(True)
            self.search.textChanged.connect(self._on_search)
            lay.addWidget(self.search)
        self.view = KeyTableView(on_key=self._view_key, on_resize=self._fit_columns)
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(-1, Qt.AscendingOrder)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection if multi else QAbstractItemView.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(30)
        self.view.setWordWrap(False)
        self.view.setShowGrid(False)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        self.view.doubleClicked.connect(lambda _i: self._emit_activated())
        self.view.selectionModel().currentRowChanged.connect(lambda *_: self.selection_changed.emit(self.current()))
        header = self.view.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(QHeaderView.Interactive)
        self.stretch_cols = [i for i, c in enumerate(cols) if c.stretch]
        for i, c in enumerate(cols):
            self.view.setColumnWidth(i, c.width or 120)
        if not self.stretch_cols:
            header.setStretchLastSection(True)
        lay.addWidget(self.view, 1)
        self.footer = QLabel()
        self.footer.setObjectName("Muted")
        lay.addWidget(self.footer)
        self.footer.setVisible(footer is not None)  # después de ubicarlo: si no, se abre como ventana suelta

    # --- datos --------------------------------------------------------------------------
    def set_rows(self, rows, keep_selection: bool = True):
        current = self.current() if keep_selection else None
        cur_id = getattr(current, "id", None) if current is not None else None
        self.model.set_rows(rows)
        if cur_id is not None:
            self.select_where(lambda r: getattr(r, "id", None) == cur_id)
        self._update_footer()

    def rows(self) -> list:
        return list(self.model.rows)

    def visible_rows(self) -> list:
        out = []
        for r in range(self.proxy.rowCount()):
            out.append(self.proxy.data(self.proxy.index(r, 0), Qt.UserRole + 1))
        return out

    def current(self):
        idx = self.view.currentIndex()
        if not idx.isValid():
            sel = self.view.selectionModel().selectedRows()
            if not sel:
                return None
            idx = sel[0]
        return self.proxy.data(self.proxy.index(idx.row(), 0), Qt.UserRole + 1)

    def selected(self) -> list:
        rows = sorted({i.row() for i in self.view.selectionModel().selectedRows()})
        return [self.proxy.data(self.proxy.index(r, 0), Qt.UserRole + 1) for r in rows]

    def select_row(self, r: int):
        if 0 <= r < self.proxy.rowCount():
            idx = self.proxy.index(r, 0)
            self.view.setCurrentIndex(idx)
            self.view.selectRow(r)
            self.view.scrollTo(idx)

    def select_first(self):
        self.select_row(0)

    def select_where(self, pred):
        for r in range(self.proxy.rowCount()):
            row = self.proxy.data(self.proxy.index(r, 0), Qt.UserRole + 1)
            if pred(row):
                self.select_row(r)
                return True
        return False

    def set_query(self, text: str):
        if self.search is not None:
            self.search.setText(text)
        else:
            self._on_search(text)

    def focus_table(self):
        self.view.setFocus()
        if not self.view.currentIndex().isValid():
            self.select_first()

    # --- internos -------------------------------------------------------------------------
    def _on_search(self, text: str):
        self.proxy.set_query(text)
        self._update_footer()
        if self.proxy.rowCount() and not self.view.currentIndex().isValid():
            self.select_first()

    def _update_footer(self):
        if self.footer_fn is not None:
            self.footer.setText(self.footer_fn(self.visible_rows()))

    def _emit_activated(self):
        row = self.current()
        if row is not None:
            self.activated.emit(row)

    MIN_STRETCH = 170

    def _fit_columns(self):
        """La(s) columna(s) principal(es) toman el espacio libre, sin bajar de un mínimo legible
        (si no cabe, aparece la barra horizontal en vez de aplastar el texto)."""
        if not self.stretch_cols:
            return
        avail = self.view.viewport().width()
        others = [i for i in range(len(self.cols)) if i not in self.stretch_cols]
        declared = {i: self.cols[i].width or 120 for i in others}
        fixed = sum(declared.values())
        need = self.MIN_STRETCH * len(self.stretch_cols)
        scale = 1.0
        if fixed and avail - fixed < need:
            scale = max(0.62, (avail - need) / fixed)  # encoger columnas secundarias hasta un límite
        floors = {"money": 92, "datetime": 128, "date": 88, "time": 72, "int": 46, "qty": 52, "pct": 62}
        for i in others:
            floor = min(declared[i], floors.get(self.cols[i].kind, 60))
            self.view.setColumnWidth(i, max(floor, int(declared[i] * scale)))
        used = sum(self.view.columnWidth(i) for i in others)
        each = max(self.MIN_STRETCH, (avail - used) // len(self.stretch_cols))
        for i in self.stretch_cols:
            if self.view.columnWidth(i) != each:
                self.view.setColumnWidth(i, each)

    def _view_key(self, event) -> bool:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._emit_activated()
            return True
        if event.matches(QKeySequence.Copy):
            self.copy_selection()
            return True
        return False

    def _search_key(self, event) -> bool:
        key = event.key()
        if key in (Qt.Key_Down, Qt.Key_Up):
            self.focus_table()
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter):
            if self.proxy.rowCount():
                if not self.view.currentIndex().isValid():
                    self.select_first()
                self._emit_activated()
            return True
        return False

    def _menu(self, pos):
        menu = QMenu(self)
        act_copy = QAction("Copiar fila", self)
        act_copy.triggered.connect(self.copy_selection)
        act_xlsx = QAction("Exportar tabla a Excel…", self)
        act_xlsx.triggered.connect(self.export)
        menu.addAction(act_copy)
        menu.addAction(act_xlsx)
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def copy_selection(self):
        lines = []
        for row in self.selected() or ([self.current()] if self.current() is not None else []):
            lines.append("\t".join(format_value(c.get(row), c.kind) for c in self.cols))
        QGuiApplication.clipboard().setText("\n".join(lines))

    def export(self):
        from granizapp.core.export import Sheet, export_xlsx

        path, _ = QFileDialog.getSaveFileName(self, "Exportar a Excel", f"{self.export_name}.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        rows = []
        for row in self.visible_rows():
            values = []
            for c in self.cols:
                v = c.get(row)
                if c.kind == "bool":
                    v = "Sí" if v else "No"
                values.append(v)
            rows.append(values)
        export_xlsx(path, [Sheet(self.export_name.replace("_", " ").capitalize(), [c.title for c in self.cols], rows,
                                 [c.kind for c in self.cols])])
        from granizapp.ui.widgets.common import toast

        toast(self, f"Exportado: {path}")


def toolbar(*widgets, stretch_at: int | None = None) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(8)
    for i, w in enumerate(widgets):
        if stretch_at is not None and i == stretch_at:
            lay.addStretch(1)
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    return lay
