"""Pruebas de la interfaz sin pantalla: flujo de venta con teclado, cobro, fiado y módulos."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from granizapp.config import AppConfig  # noqa: E402
from granizapp.core.services import cash, customers, inventory, sales  # noqa: E402
from granizapp.ui.context import AppContext, Bus  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    from granizapp.ui.theme import apply_theme

    apply_theme(app, "light")
    yield app


@pytest.fixture()
def ctx(db, actor, qapp, monkeypatch, tmp_path):
    shown = []
    for name in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: shown.append(a) or QMessageBox.Ok))
    cfg = AppConfig(device_id=actor.device_id)
    c = AppContext(cfg, db, actor, Bus())
    c.messages = shown
    return c


def _with_modal(action, timeout_ms: int = 5000):
    """Ejecuta `action(dialogo)` sobre el próximo diálogo modal que se abra (deja de esperar
    después de `timeout_ms`, para no quedarse vigilando durante otras pruebas)."""
    left = [timeout_ms // 20]

    def check():
        w = QApplication.activeModalWidget()
        if w is None:
            left[0] -= 1
            if left[0] > 0:
                QTimer.singleShot(20, check)
            return
        w.activateWindow()  # los atajos (F1, F11, números) solo funcionan en la ventana activa
        QTest.qWaitForWindowActive(w, 1000)
        try:
            action(w)
        finally:
            if w.isVisible():  # si la acción falló, no dejar la prueba colgada
                QTimer.singleShot(0, w.reject)

    QTimer.singleShot(20, check)


def _pos(ctx):
    from granizapp.ui.modules.pos import PosPage

    page = PosPage(ctx)
    page.resize(1200, 760)
    page.show()
    page.safe_refresh()
    return page


def _type(page, text):
    QTest.keyClicks(page.search, text)
    QTest.keyClick(page.search, Qt.Key_Return)


def test_keyboard_sale_with_cash_and_change(ctx):
    with ctx.session() as s:
        cash.open_session(s, ctx.actor, 200000)
    page = _pos(ctx)
    _type(page, "cl12 tij")  # producto + sabor escrito: no pregunta
    _type(page, "2*corona m")
    _type(page, "bolit")  # adición a la línea seleccionada (Corona michelada no la tiene) -> nada
    page.lines.select_row(0)
    _type(page, "bolit")  # ahora sí: al granizado
    assert [ln.name for ln in page.cart.lines] == ["Granizado CL 12 oz", "Corona michelada"]
    assert page.cart.lines[0].modifiers[0].name == "Bolitas explosivas"
    assert page.cart.lines[0].description == "Granizado CL 12 oz · Tijuana + Bolitas explosivas"
    assert page.cart.total == 15000 + 20000

    def pay(dlg):
        QTest.keyClick(dlg, Qt.Key_F1)  # efectivo
        QTest.keyClicks(dlg.received, "50k")
        QTest.keyClick(dlg.received, Qt.Key_Return)

    _with_modal(pay)
    QTest.keyClick(page.search, Qt.Key_Return)  # Enter con buscador vacío = cobrar
    assert page.cart.is_empty()
    assert "CAMBIO: $ 15.000" in page.banner.lbl.text()
    with ctx.session() as s:
        cs = cash.current_session(s, ctx.actor.device_id)
        sm = cash.summary(s, cs)
        assert sm.cash_sales == 35000 and sm.expected == 235000
        assert inventory.stock_map(s)["seed-su-bolitas"] == pytest.approx(-30)
        assert inventory.stock_map(s)["seed-su-cl-tijuana"] == pytest.approx(-320)


def test_split_payment_then_credit(ctx):
    with ctx.session() as s:
        cash.open_session(s, ctx.actor, 100000)
        raigo = customers.save_customer(s, {"name": "Raigo"}).id
    page = _pos(ctx)

    def flavors(dlg):  # 3 vasos: un número por vaso (Habana, Ibiza, Ibiza) y se acepta solo
        for key in (Qt.Key_1, Qt.Key_2, Qt.Key_2):
            QTest.keyClick(dlg, key)

    _with_modal(flavors)
    _type(page, "3*cl16")  # 54.000
    assert page.cart.lines[0].description == "Granizado CL 16 oz · Habana + 2× Ibiza"
    page.cart.customer_id = raigo

    def pay(dlg):
        QTest.keyClick(dlg, Qt.Key_F2)  # Nequi
        dlg.amount.setValue(20000)
        QTest.keyClick(dlg.amount, Qt.Key_Return)
        assert dlg.remaining == 34000
        QTest.keyClick(dlg, Qt.Key_F1)
        QTest.keyClicks(dlg.received, "10000")
        QTest.keyClick(dlg.received, Qt.Key_Return)
        assert dlg.remaining == 24000
        QTest.keyClick(dlg, Qt.Key_F11)  # el resto fiado

    _with_modal(pay)
    page.charge()
    with ctx.session() as s:
        assert customers.customer_balance(s, raigo) == 24000
        sale = sales.list_sales(s)[0]
        assert sale.paid == 30000 and sale.is_credit


def test_open_tab_and_modifiers_dialog(ctx):
    page = _pos(ctx)
    _with_modal(lambda dlg: QTest.keyClick(dlg, Qt.Key_0))  # sabor: «sin especificar»
    _type(page, "sl12")
    assert page.cart.lines[0].flavors == []

    def pick(dlg):
        QTest.keyClick(dlg, Qt.Key_1)  # primera opción: bolitas
        QTest.keyClick(dlg, Qt.Key_2)  # gomitas
        dlg.accept()

    _with_modal(pick)
    page.edit_modifiers()
    assert {m.name for m in page.cart.lines[0].modifiers} == {"Bolitas explosivas", "Gomitas"}

    def name_tab(dlg):
        dlg.setTextValue("Mesa 4")
        dlg.accept()

    _with_modal(name_tab)
    page.save_tab()
    assert page.cart.is_empty()
    with ctx.session() as s:
        tabs = sales.list_open_tabs(s)
        assert [t.label for t in tabs] == ["Mesa 4"] and tabs[0].total == 14000


def test_every_module_opens(ctx):
    from granizapp.ui.main_window import MainWindow
    from granizapp.ui.modules import MODULES

    win = MainWindow(ctx)
    win.show()
    for spec in MODULES:
        win.navigate(spec.key)
        QApplication.processEvents()
        assert win.current_page() is win.pages[spec.key]
    assert not ctx.messages, ctx.messages
    # cambiar de tema con todo abierto (antes se caía por re-pulir con setStyle)
    from granizapp.ui.theme import apply_theme

    apply_theme(QApplication.instance(), "dark")
    QApplication.processEvents()
    apply_theme(QApplication.instance(), "light")
    QApplication.processEvents()
    win.close()
    win.deleteLater()
    QApplication.processEvents()
