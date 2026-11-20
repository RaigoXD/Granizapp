"""Flujos con diálogos: cierre de caja, abono, compra y gasto."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from granizapp.core.models import CashSession
from granizapp.core.services import cash, customers, finance, inventory, purchasing, sales
from granizapp.core.services.sales import Cart, CartLine, PaymentInput
from tests.test_ui import _with_modal, ctx, qapp  # noqa: F401  (fixtures compartidos)


def _click(text):
    """Acción para _with_modal: pulsa el botón de un QMessageBox por su texto."""

    def act(box):
        for b in box.buttons():
            if b.text() == text:
                b.click()
                return
        raise AssertionError(f"No hay botón {text!r}")

    return act


def test_close_cash_with_count_and_withdrawal(ctx):
    with ctx.session() as s:
        cs = cash.open_session(s, ctx.actor, 200000)
        sales.checkout(s, Cart(lines=[CartLine("seed-p-cl12", "x", 14000, 2)]), [PaymentInput("seed-pm-efectivo", 28000)],
                       ctx.actor, cs.id)
    from granizapp.ui.modules.cash import CashPage

    page = CashPage(ctx)
    page.show()
    page.safe_refresh()
    assert page.k_expected.value.text() == "$ 228.000"

    def count(dlg):
        dlg.spins[100000].setValue(2)
        dlg.spins[20000].setValue(1)
        dlg.spins[5000].setValue(1)  # 225.000 contado: faltan 3.000
        assert "Faltan $ 3.000" in dlg.diff_lbl.text()
        _with_modal(_click("Cerrar"))  # confirma el descuadre
        dlg.accept()

    _with_modal(count)
    page.close_cash()
    with ctx.session() as s:
        closed = s.get(CashSession, cs.id)
        assert closed.status == "cerrada" and closed.difference == -3000 and closed.withdrawn == 25000
        bal = finance.account_balances(s)
        assert bal["seed-acc-caja"] == 200000 and bal["seed-acc-fuerte"] == 25000


def test_abono_from_debtors_page(ctx):
    with ctx.session() as s:
        cs = cash.open_session(s, ctx.actor, 0)
        c = customers.save_customer(s, {"name": "Cris"})
        sales.checkout(s, Cart(lines=[CartLine("seed-p-sl9", "x", 6000, 2)]), [], ctx.actor, cs.id, customer_id=c.id)
        cid = c.id
    from granizapp.ui.modules.debtors import DebtorsPage

    page = DebtorsPage(ctx)
    page.show()
    page.safe_refresh()
    assert page.k_total.value.text() == "$ 12.000"
    assert "Cris" in page.st_title.text()

    def pay(dlg):
        dlg.amount.setValue(5000)
        dlg.method.setCurrentIndex(1)  # Nequi
        dlg.accept()

    _with_modal(pay)
    page.abono()
    with ctx.session() as s:
        assert customers.customer_balance(s, cid) == 7000
        assert finance.account_balances(s)["seed-acc-nequi"] == 5000


def test_purchase_dialog_updates_stock(ctx):
    from granizapp.ui.modules.purchases import PurchasesPage

    page = PurchasesPage(ctx)
    page.show()
    page.safe_refresh()

    def buy(dlg):
        cb = dlg.table.cellWidget(0, 0)
        cb.setCurrentIndex(cb.findData("seed-su-bolitas"))
        dlg.table.cellWidget(0, 1).setValue(2)
        dlg.table.cellWidget(0, 3).setValue(50000)
        dlg._recalc()
        dlg.shipping.setValue(10000)
        dlg._recalc()
        assert dlg.total_lbl.text() == "$ 60.000"
        dlg.paid.setValue(20000)
        dlg.paid_touched = True
        dlg.account.setCurrentIndex(dlg.account.findData("seed-acc-banco"))
        dlg.save()

    _with_modal(buy)
    page.new_purchase()
    with ctx.session() as s:
        assert inventory.stock_of(s, "seed-su-bolitas") == pytest.approx(2000)
        assert inventory.ensure_supply(s, "seed-su-bolitas").avg_cost == pytest.approx(30.0)  # 60.000 / 2.000 g
        assert purchasing.total_payable(s) == 40000


def test_expense_auto_classified(ctx):
    from granizapp.ui.modules.expenses import ExpensesPage

    page = ExpensesPage(ctx)
    page.show()
    page.safe_refresh()

    def fill(dlg):
        dlg.widgets["description"].setText("Hielo x2 bolsas")
        dlg.widgets["amount"].setValue(8000)
        dlg.widgets["category_id"].setCurrentIndex(0)  # automático
        acc = dlg.widgets["account_id"]
        acc.setCurrentIndex(acc.findData("seed-acc-fuerte"))
        dlg.accept()

    _with_modal(fill)
    page.new_expense()
    with ctx.session() as s:
        exp = finance.list_expenses(s)[0]
        assert exp.category_id == "seed-exp-ins-hielo" and exp.amount == 8000
        assert finance.account_balances(s)["seed-acc-fuerte"] == -8000
