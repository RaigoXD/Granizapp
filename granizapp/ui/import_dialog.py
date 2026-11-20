"""Importar el historial desde los Excel anteriores (Lista de Ventas + Dashboard Balance)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from granizapp.core.services import excel_import
from granizapp.core.utils import fmt_money
from granizapp.ui.context import AppContext
from granizapp.ui.widgets.common import busy, label, show_error
from granizapp.ui.widgets.forms import date_edit, from_qdate
from granizapp.ui.widgets.table import Col, DataTable


def _guess(name: str) -> str:
    p = Path.home() / "Downloads" / name
    return str(p) if p.exists() else ""


class ImportDialog(QDialog):
    def __init__(self, parent, ctx: AppContext):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Importar historial desde Excel")
        self.resize(760, 640)
        lay = QVBoxLayout(self)
        lay.addWidget(label("Importar historial desde Excel", "SectionTitle"))
        lay.addWidget(label(
            "Trae las ventas día por día (con productos y medio de pago) y los gastos, para tener reportes desde el "
            "inicio. Lo importado no mueve inventario ni saldos de cuentas. Puede repetirse: reemplaza la importación anterior.",
            "Muted", wrap=True))
        form = QFormLayout()
        self.sales_path = QLineEdit(_guess("Lista de Ventas - The Spot.xlsx"))
        self.balance_path = QLineEdit(_guess("Dashboard Balance.xlsx"))
        form.addRow("Lista de ventas (una hoja por día)", self._picker(self.sales_path))
        form.addRow("Balance (hojas Gastos e Ingresos)", self._picker(self.balance_path))
        self.first_date = date_edit(date(2026, 6, 28))
        form.addRow("Fecha de la primera hoja de ventas", self.first_date)
        lay.addLayout(form)
        self.cb_sales = QCheckBox("Importar ventas diarias")
        self.cb_expenses = QCheckBox("Importar gastos (clasificados automáticamente por categoría)")
        self.cb_capital = QCheckBox("«Total inicial» como aporte de capital")
        self.cb_events = QCheckBox("«Evento» y otros ingresos que no son ventas como «Otro ingreso»")
        self.cb_unorg = QCheckBox("«Ventas para organizar» como otro ingreso (puede duplicar ventas ya detalladas)")
        for cb, on in ((self.cb_sales, True), (self.cb_expenses, True), (self.cb_capital, True), (self.cb_events, True),
                       (self.cb_unorg, False)):
            cb.setChecked(on)
            lay.addWidget(cb)
        self.run_btn = QPushButton("Importar")
        self.run_btn.setObjectName("Primary")
        self.run_btn.clicked.connect(self.run)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.run_btn)
        lay.addLayout(row)
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setPlaceholderText("Aquí aparece el resultado de la importación")
        lay.addWidget(self.result, 1)
        lay.addWidget(label("Conciliación: ventas del Excel de Ingresos vs. hojas diarias", "Hint"))
        self.recon = DataTable([
            Col("Mes", lambda r: r[0], stretch=True),
            Col("Ingresos (Balance)", lambda r: r[1], "money", width=150),
            Col("Hojas diarias", lambda r: r[2], "money", width=150),
            Col("Diferencia", lambda r: r[2] - r[1], "money", width=130,
                color=lambda r: None if r[2] == r[1] else "warning"),
        ])
        self.recon.setMaximumHeight(170)
        lay.addWidget(self.recon)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        lay.addWidget(close)

    def _picker(self, edit: QLineEdit):
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        b = QPushButton("Buscar…")

        def pick():
            path, _ = QFileDialog.getOpenFileName(self, "Elegir archivo", edit.text() or str(Path.home() / "Downloads"),
                                                  "Excel (*.xlsx *.xlsm)")
            if path:
                edit.setText(path)

        b.clicked.connect(pick)
        row.addWidget(b)
        from PySide6.QtWidgets import QWidget

        w = QWidget()
        w.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        return w

    def run(self):
        sales_path = self.sales_path.text().strip() or None
        balance_path = self.balance_path.text().strip() or None
        for p in (sales_path, balance_path):
            if p and not Path(p).exists():
                show_error(self, f"No se encontró el archivo:\n{p}")
                return
        if not sales_path and not balance_path:
            show_error(self, "Elija al menos un archivo")
            return
        opts = excel_import.ImportOptions(
            sales_path=sales_path, balance_path=balance_path, first_sheet_date=from_qdate(self.first_date.date()),
            import_sales=self.cb_sales.isChecked(), import_expenses=self.cb_expenses.isChecked(),
            initial_total_as_capital=self.cb_capital.isChecked(), events_as_other_income=self.cb_events.isChecked(),
            unorganized_as_other_income=self.cb_unorg.isChecked(), replace_previous=True)
        try:
            with busy(), self.ctx.session() as s:
                report = excel_import.run_import(s, opts, self.ctx.actor)
        except Exception as exc:
            show_error(self, exc)
            return
        text = report.text()
        if report.removed_previous:
            text = f"Se reemplazaron {report.removed_previous} registros de una importación anterior.\n" + text
        if report.expense_by_category:
            text += "\n\nGastos por categoría:\n" + "\n".join(
                f"  {k}: {fmt_money(v)}" for k, v in sorted(report.expense_by_category.items(), key=lambda kv: -kv[1]))
        self.result.setPlainText(text)
        self.recon.set_rows(report.reconciliation)
        self.ctx.notify("*")
