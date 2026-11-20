"""Campos de captura (dinero, cantidades) y formularios declarativos."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from PySide6.QtCore import QDate, QDateTime, Qt, QTime, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from granizapp.core.utils import fmt_number, parse_float, parse_money

DAY_LABELS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


class MoneyEdit(QLineEdit):
    """Pesos colombianos. Acepta "14000", "14.000" o "14k". Selecciona todo al entrar."""

    value_changed = Signal(int)

    def __init__(self, value: int = 0, parent=None, big: bool = False, allow_negative: bool = False):
        super().__init__(parent)
        self.allow_negative = allow_negative
        self.setPlaceholderText("$ 0")
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if big:
            self.setObjectName("BigInput")
        self.textEdited.connect(lambda _t: self.value_changed.emit(self.value()))
        self.editingFinished.connect(self._reformat)
        self.setValue(value)

    def value(self) -> int:
        v = parse_money(self.text())
        return v if self.allow_negative else abs(v)

    def setValue(self, value: int) -> None:
        self.setText(fmt_number(value or 0) if value else "")

    def _reformat(self):
        v = self.value()
        self.setText(fmt_number(v) if v else "")

    def focusInEvent(self, e):
        super().focusInEvent(e)
        QTimer.singleShot(0, self, self.selectAll)


class NumberEdit(QLineEdit):
    """Número decimal con coma o punto (cantidades de insumo: 320, 1,5...)."""

    value_changed = Signal(float)

    def __init__(self, value: float = 0, parent=None, decimals: int = 2):
        super().__init__(parent)
        self.decimals = decimals
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.textEdited.connect(lambda _t: self.value_changed.emit(self.value()))
        self.editingFinished.connect(self._reformat)
        self.setValue(value)

    def value(self) -> float:
        return parse_float(self.text())

    def setValue(self, value: float) -> None:
        self.setText(fmt_number(value, self.decimals) if value else "")

    def _reformat(self):
        v = self.value()
        self.setText(fmt_number(v, self.decimals) if v else "")

    def focusInEvent(self, e):
        super().focusInEvent(e)
        QTimer.singleShot(0, self, self.selectAll)


class DaysPicker(QWidget):
    def __init__(self, value: str = "0123456", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.boxes = []
        for i, label in enumerate(DAY_LABELS):
            cb = QCheckBox(label)
            cb.setChecked(str(i) in (value or ""))
            self.boxes.append(cb)
            lay.addWidget(cb)
        lay.addStretch(1)

    def value(self) -> str:
        return "".join(str(i) for i, cb in enumerate(self.boxes) if cb.isChecked())


def to_qdate(d) -> QDate:
    if isinstance(d, datetime):
        d = d.date()
    if isinstance(d, date):
        return QDate(d.year, d.month, d.day)
    return QDate.currentDate()


def from_qdate(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


def to_qdatetime(d: datetime | None) -> QDateTime:
    if d is None:
        return QDateTime.currentDateTime()
    return QDateTime(QDate(d.year, d.month, d.day), QTime(d.hour, d.minute, d.second))


def from_qdatetime(q: QDateTime) -> datetime:
    d, t = q.date(), q.time()
    return datetime(d.year(), d.month(), d.day(), t.hour(), t.minute(), t.second())


def date_edit(value=None) -> QDateEdit:
    w = QDateEdit(to_qdate(value or date.today()))
    w.setCalendarPopup(True)
    w.setDisplayFormat("dd/MM/yyyy")
    return w


@dataclass
class Field:
    key: str
    label: str
    kind: str = "text"  # text|multiline|money|number|int|choice|bool|date|datetime|password|days|label
    options: list[tuple[Any, str]] | None = None
    required: bool = False
    default: Any = None
    help: str = ""
    placeholder: str = ""
    minimum: int = 0
    maximum: int = 1_000_000


class FormDialog(QDialog):
    def __init__(self, parent, title: str, fields: list[Field], values: dict | None = None, subtitle: str = "",
                 width: int = 480, ok_text: str = "Guardar"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.fields = fields
        self.widgets: dict[str, QWidget] = {}
        values = values or {}
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        head = QLabel(title)
        head.setObjectName("SectionTitle")
        lay.addWidget(head)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("Muted")
            sub.setWordWrap(True)
            lay.addWidget(sub)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        for f in fields:
            v = values.get(f.key, f.default)
            w = self._make(f, v)
            self.widgets[f.key] = w
            label = f.label + (" *" if f.required else "")
            if f.help:
                box = QWidget()
                bl = QVBoxLayout(box)
                bl.setContentsMargins(0, 0, 0, 0)
                bl.setSpacing(2)
                bl.addWidget(w)
                hint = QLabel(f.help)
                hint.setObjectName("Hint")
                hint.setWordWrap(True)
                bl.addWidget(hint)
                form.addRow(label, box)
            else:
                form.addRow(label, w)
        lay.addLayout(form)
        self.error = QLabel()
        self.error.setObjectName("Danger")
        self.error.setWordWrap(True)
        self.error.hide()
        lay.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(ok_text)
        buttons.button(QDialogButtonBox.Ok).setObjectName("Primary")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        first = next((self.widgets[f.key] for f in fields if f.kind != "label"), None)
        if first is not None:
            QTimer.singleShot(0, first, first.setFocus)

    def _make(self, f: Field, v) -> QWidget:
        if f.kind == "multiline":
            w = QPlainTextEdit(v or "")
            w.setFixedHeight(70)
            w.setTabChangesFocus(True)
            return w
        if f.kind == "money":
            return MoneyEdit(int(v or 0))
        if f.kind == "number":
            return NumberEdit(float(v or 0))
        if f.kind == "int":
            w = QSpinBox()
            w.setRange(f.minimum, f.maximum)
            w.setValue(int(v or 0))
            return w
        if f.kind == "choice":
            w = QComboBox()
            for value, label in f.options or []:
                w.addItem(label, value)
            idx = w.findData(v)
            if idx >= 0:
                w.setCurrentIndex(idx)
            return w
        if f.kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(v if v is not None else False))
            return w
        if f.kind == "date":
            return date_edit(v)
        if f.kind == "datetime":
            w = QDateTimeEdit(to_qdatetime(v if isinstance(v, datetime) else None))
            w.setCalendarPopup(True)
            w.setDisplayFormat("dd/MM/yyyy hh:mm AP")
            return w
        if f.kind == "days":
            return DaysPicker(v or "0123456")
        if f.kind == "label":
            w = QLabel(str(v or ""))
            w.setWordWrap(True)
            return w
        w = QLineEdit("" if v is None else str(v))
        if f.placeholder:
            w.setPlaceholderText(f.placeholder)
        if f.kind == "password":
            w.setEchoMode(QLineEdit.Password)
        return w

    def values(self) -> dict:
        out = {}
        for f in self.fields:
            w = self.widgets[f.key]
            if f.kind == "multiline":
                out[f.key] = w.toPlainText().strip()
            elif f.kind in ("money", "number"):
                out[f.key] = w.value()
            elif f.kind == "int":
                out[f.key] = w.value()
            elif f.kind == "choice":
                out[f.key] = w.currentData()
            elif f.kind == "bool":
                out[f.key] = w.isChecked()
            elif f.kind == "date":
                out[f.key] = from_qdate(w.date())
            elif f.kind == "datetime":
                out[f.key] = from_qdatetime(w.dateTime())
            elif f.kind == "days":
                out[f.key] = w.value()
            elif f.kind == "label":
                continue
            else:
                out[f.key] = w.text().strip()
        return out

    def accept(self):
        vals = self.values()
        missing = [f.label for f in self.fields if f.required and vals.get(f.key) in (None, "", 0)]
        if missing:
            self.error.setText("Complete: " + ", ".join(missing))
            self.error.show()
            return
        super().accept()

    @classmethod
    def ask(cls, parent, title: str, fields: list[Field], values: dict | None = None, **kw) -> dict | None:
        dlg = cls(parent, title, fields, values, **kw)
        if dlg.exec() == QDialog.Accepted:
            return dlg.values()
        return None
