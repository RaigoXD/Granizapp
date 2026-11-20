"""Piezas de interfaz comunes: página base, encabezados, tarjetas, diálogos y selector de periodo."""
from __future__ import annotations

import logging
import traceback
from contextlib import contextmanager
from datetime import date

from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from granizapp.core.services.common import ServiceError
from granizapp.core.services.reports import PRESETS, Period, preset_period
from granizapp.ui.context import AppContext, Topics

log = logging.getLogger(__name__)


class Page(QWidget):
    """Pantalla de un módulo. Se refresca al mostrarse si algo de lo que muestra cambió."""

    topics: set[str] = set()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.ctx = ctx
        self._stale = True
        ctx.bus.changed.connect(self._on_changed)

    def _on_changed(self, topic: str):
        if topic == Topics.ALL or topic in self.topics:
            if self.isVisible():
                self.safe_refresh()
            else:
                self._stale = True

    def showEvent(self, e):
        super().showEvent(e)
        if self._stale:
            self.safe_refresh()

    def safe_refresh(self):
        self._stale = False
        try:
            self.refresh()
        except Exception as exc:  # una pantalla con error no debe cerrar la app
            log.exception("Error refrescando %s", type(self).__name__)
            show_error(self, exc)

    def refresh(self):
        pass

    def activate(self):
        """Se llama al navegar a la pantalla: deja el cursor en el primer buscador o tabla visible,
        para que Enter, Ctrl+N y los demás atajos funcionen sin tener que hacer clic."""
        QTimer.singleShot(0, self, self._focus_main_table)

    def _focus_main_table(self):
        from granizapp.ui.widgets.table import DataTable

        tables = [t for t in self.findChildren(DataTable) if t.isVisibleTo(self)]
        # primero las tablas con buscador (son la lista principal del módulo)
        tables.sort(key=lambda t: t.search is None)
        if tables:
            (tables[0].search or tables[0].view).setFocus()


def page_header(title: str, subtitle: str = "", actions: list[QWidget] | None = None) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 4)
    text = QVBoxLayout()
    text.setSpacing(0)
    t = QLabel(title)
    t.setObjectName("PageTitle")
    text.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("PageSubtitle")
        text.addWidget(s)
    lay.addLayout(text)
    lay.addStretch(1)
    for a in actions or []:
        lay.addWidget(a)
    return w


def button(text: str, slot=None, kind: str = "", shortcut: str | None = None, tip: str = "") -> QPushButton:
    label = f"{text}  ({shortcut})" if shortcut and len(shortcut) <= 9 else text
    b = QPushButton(label)
    if kind:
        b.setObjectName(kind)
    if slot is not None:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def shortcut(widget: QWidget, keys: str, slot, context=Qt.WidgetWithChildrenShortcut) -> QShortcut:
    sc = QShortcut(QKeySequence(keys), widget)
    sc.setContext(context)
    sc.activated.connect(slot)
    return sc


class KpiCard(QFrame):
    def __init__(self, title: str, value: str = "—", sub: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("KpiCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("KpiTitle")
        self.value = QLabel(value)
        self.value.setObjectName("KpiValue")
        self.sub = QLabel(sub)
        self.sub.setObjectName("KpiSub")
        self.sub.setWordWrap(True)
        lay.addWidget(self.title)
        lay.addWidget(self.value)
        lay.addWidget(self.sub)

    def set(self, value: str, sub: str | None = None, color: str | None = None):
        self.value.setText(value)
        if sub is not None:
            self.sub.setText(sub)
        from granizapp.ui import theme

        self.value.setStyleSheet(f"color: {theme.color(color)};" if color else "")


def card(content: QWidget | None = None, title: str = "", margins: int = 12) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(margins, margins, margins, margins)
    lay.setSpacing(8)
    if title:
        t = QLabel(title)
        t.setObjectName("SectionTitle")
        lay.addWidget(t)
    if content is not None:
        lay.addWidget(content)
    return frame, lay


def label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


def kbd(text: str) -> QLabel:
    return label(text, "Kbd")


# --- mensajes ---------------------------------------------------------------------------
def show_error(parent, exc: Exception | str):
    if isinstance(exc, ServiceError):
        QMessageBox.warning(parent, "No se pudo completar", str(exc))
    elif isinstance(exc, str):
        QMessageBox.warning(parent, "Atención", exc)
    else:
        log.error("Error inesperado: %s", "".join(traceback.format_exception(exc)))
        QMessageBox.critical(parent, "Error inesperado",
                             f"Ocurrió un error inesperado:\n\n{exc}\n\nEl detalle quedó en el registro (logs).")


def info(parent, text: str, title: str = "Listo"):
    QMessageBox.information(parent, title, text)


def confirm(parent, text: str, title: str = "Confirmar", yes: str = "Sí", no: str = "No", danger: bool = False) -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning if danger else QMessageBox.Question)
    box.setWindowTitle(title)
    box.setText(text)
    yes_btn = box.addButton(yes, QMessageBox.AcceptRole)
    no_btn = box.addButton(no, QMessageBox.RejectRole)
    box.setDefaultButton(no_btn if danger else yes_btn)
    box.exec()
    return box.clickedButton() is yes_btn


def ask_text(parent, title: str, prompt: str, default: str = "", required: bool = True) -> str | None:
    while True:
        text, ok = QInputDialog.getText(parent, title, prompt, text=default)
        if not ok:
            return None
        if text.strip() or not required:
            return text.strip()


def run(parent, fn, *args, **kwargs):
    """Ejecuta una acción mostrando los errores de negocio como avisos. Devuelve el resultado o None."""
    try:
        with busy():
            return fn(*args, **kwargs)
    except Exception as exc:
        show_error(parent, exc)
        return None


@contextmanager
def busy():
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()


def toast(widget: QWidget, text: str, ms: int = 3500):
    """Mensaje breve en la barra de estado de la ventana principal."""
    win = widget.window()
    bar = getattr(win, "statusBar", None)
    if callable(bar):
        bar().showMessage(text, ms)


# --- selector de periodo ------------------------------------------------------------------
class PeriodSelector(QWidget):
    changed = Signal(object)

    def __init__(self, default: str = "hoy", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.combo = QComboBox()
        for key, text in PRESETS:
            self.combo.addItem(text, key)
        self.combo.addItem("Personalizado…", "custom")
        self.start = QDateEdit(QDate.currentDate())
        self.end = QDateEdit(QDate.currentDate())
        for w in (self.start, self.end):
            w.setCalendarPopup(True)
            w.setDisplayFormat("dd/MM/yyyy")
            w.dateChanged.connect(self._custom_changed)
        self.combo.setMinimumWidth(170)
        for w in (self.start, self.end):
            w.setFixedWidth(130)
        lay.addWidget(QLabel("Periodo:"))
        lay.addWidget(self.combo)
        lay.addWidget(self.start)
        lay.addWidget(QLabel("a"))
        lay.addWidget(self.end)
        lay.addStretch(1)
        self.combo.currentIndexChanged.connect(self._preset_changed)
        idx = self.combo.findData(default)
        self._block = False
        self.combo.setCurrentIndex(max(0, idx))
        self._preset_changed()

    def _preset_changed(self):
        key = self.combo.currentData()
        custom = key == "custom"
        self.start.setEnabled(custom)
        self.end.setEnabled(custom)
        if not custom:
            p = preset_period(key)
            self._block = True
            self.start.setDate(QDate(p.start.year, p.start.month, p.start.day))
            self.end.setDate(QDate(p.end.year, p.end.month, p.end.day))
            self._block = False
        self.changed.emit(self.period())

    def _custom_changed(self):
        if not self._block and self.combo.currentData() == "custom":
            self.changed.emit(self.period())

    def period(self) -> Period:
        key = self.combo.currentData()
        if key != "custom":
            return preset_period(key)
        s, e = self.start.date(), self.end.date()
        start = date(s.year(), s.month(), s.day())
        end = date(e.year(), e.month(), e.day())
        if end < start:
            start, end = end, start
        return Period(start, end, "Personalizado")


def defer(fn, ms: int = 0):
    QTimer.singleShot(ms, fn)


def repolish(widget: QWidget) -> None:
    """Vuelve a aplicar el estilo tras cambiar el objectName (p. ej. de verde a rojo).

    No usar `w.setStyle(w.style())`: deja el widget apuntando a un estilo que Qt destruye
    al cambiar el tema y la aplicación se cae.
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color: rgba(127,127,127,0.25);")
    return f
