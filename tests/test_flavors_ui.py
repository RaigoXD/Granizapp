"""Sabores en la interfaz: Vender (escribir el sabor, ventana de sabores, F7), Inventario › Sabores,
receta con insumo con sabores, reporte por sabor y compra con el pedido sugerido."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from granizapp.core.services import cash, inventory
from granizapp.core.services.settings import set_setting
from tests.test_ui import _pos, _type, _with_modal, ctx, qapp  # noqa: F401

TIJ, NY, HAB = "seed-su-cl-tijuana", "seed-su-cl-ny", "seed-su-cl-habana"


def test_pos_typed_flavor_dialog_and_f7(ctx):
    with ctx.session() as s:
        cash.open_session(s, ctx.actor, 0)
        inventory.add_movement(s, NY, 12000, "inicial", None, "inicial", None, "inicial", ctx.actor)
    page = _pos(ctx)
    page.search.setText("cl12 ny")
    assert page.flavor_lbl.isVisible() and "Nueva York" in page.flavor_lbl.text()
    assert page.tiles.current().code == "CL12"
    QTest.keyClick(page.search, Qt.Key_Return)
    _type(page, "cl12 york")  # por nombre: se suma a la misma línea
    assert len(page.cart.lines) == 1 and page.cart.lines[0].quantity == 2
    assert page.cart.lines[0].description == "Granizado CL 12 oz · Nueva York"

    seen = {}

    def choose(dlg):  # ventana de sabores: muestra existencias; letras saltan al sabor
        seen["rows"] = [dlg.list.item(i).text() for i in range(dlg.list.count())]
        QTest.keyClicks(dlg.list, "tij")
        seen["current"] = dlg.list.currentItem().text()
        QTest.keyClick(dlg.list, Qt.Key_Return)

    _with_modal(choose)
    _type(page, "cl9")
    assert "Tijuana" in seen["current"]
    assert any("Nueva York" in r and "2,0 bolsas" in r for r in seen["rows"])
    assert any("Habana" in r and "agotado" in r for r in seen["rows"])
    assert seen["rows"][-1].strip().startswith("0.") and "Sin especificar" in seen["rows"][-1]
    assert page.cart.lines[1].description == "Granizado CL 9 oz · Tijuana"

    page.lines.select_row(1)
    assert ("F7", page.change_flavor) in [(k, fn) for k, fn in page.key_bindings]
    _with_modal(lambda dlg: QTest.keyClick(dlg, Qt.Key_1))  # F7: cambiar a Habana
    page.change_flavor()
    assert page.cart.lines[1].description == "Granizado CL 9 oz · Habana"

    _with_modal(lambda dlg: None)  # la ventana se cierra sola (Esc) -> no se agrega nada
    _type(page, "sl9")
    assert len(page.cart.lines) == 2 and page.search.selectedText() == "sl9"  # escribir reemplaza
    _type(page, "corona")  # sin sabores: no pregunta
    assert page.cart.lines[-1].name == "Corona" and len(page.cart.lines) == 3
    assert not ctx.messages, ctx.messages


def test_pos_required_flavor_hides_unspecified(ctx):
    with ctx.session() as s:
        set_setting(s, "require_flavor", True)
    page = _pos(ctx)
    rows = {}

    def look(dlg):
        rows["all"] = [dlg.list.item(i).text() for i in range(dlg.list.count())]
        QTest.keyClick(dlg, Qt.Key_2)

    _with_modal(look)
    _type(page, "sl12")
    assert not any("Sin especificar" in r for r in rows["all"])
    assert page.cart.lines[0].description == "Granizado SL 12 oz · Chicle"


def test_flavors_tab_stats_order_and_actions(ctx):
    from granizapp.ui.modules.inventory import InventoryPage

    with ctx.session() as s:
        inventory.add_movement(s, "seed-su-mezcla-cl", 12000, "inicial", None, "inicial", None, "inicial", ctx.actor)
        inventory.add_movement(s, TIJ, 3000, "inicial", None, "inicial", None, "inicial", ctx.actor)
    page = InventoryPage(ctx)
    page.resize(1300, 800)
    page.show()
    page.safe_refresh()
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())][:2] == ["Existencias", "Sabores"]
    tab = page.flavors
    names = [st.supply.variant_name for st in tab.table.rows()]
    assert names == ["Habana", "Ibiza", "Nueva York", "San Andrés", "Tijuana", "Sin especificar"]
    assert not tab.btn_reassign.isHidden() and "2 bolsas sin sabor" in tab.banner.lbl.text().replace(",00", "")
    text = tab.order_text()
    assert text.startswith("Pedido The Spot") and "Tijuana" in text and "1 bolsa Habana" in text
    tab.copy_order()
    assert QApplication.clipboard().text() == text
    # «Sin especificar» en Existencias no es «Agotado»
    status = {r.supply.id: r.status for r in page.rows}
    assert status["seed-su-mezcla-cl"] == "sin_sabor" and status[HAB] == "agotado"
    # cambiar de grupo
    tab.group_cb.setCurrentIndex(tab.group_cb.findData("seed-sg-sl"))
    assert [st.supply.variant_name for st in tab.table.rows()] == ["Bubalú", "Chicle", "Sin especificar"]
    tab.group_cb.setCurrentIndex(tab.group_cb.findData("seed-sg-crem"))
    assert "todavía no tiene sabores" in tab.banner.lbl.text()
    assert not ctx.messages[1:], ctx.messages  # el único aviso fue el del pedido copiado


def test_recipe_dialog_uses_the_flavor_group(ctx):
    from granizapp.ui.recipe_dialog import RecipeDialog

    dlg = RecipeDialog(None, ctx, product_id="seed-p-cl12", title="Granizado CL 12 oz", price=14000)
    first = dlg.table.cellWidget(0, 0)
    assert first.currentData() == "g:seed-sg-cl" and "sabor al vender" in first.currentText()
    options = [first.itemData(i) for i in range(first.count())]
    assert "s:seed-su-mezcla-cl" not in options and f"s:{TIJ}" in options  # «Sin especificar» no se ofrece
    assert "1 bolsa de Mezcla granizado con licor (bolsa 6 L) rinde 18,8" in dlg.yield_lbl.text()
    assert "Margen" in dlg.totals.text()
    dlg.save()  # guarda igual que estaba
    with ctx.session() as s:
        from granizapp.core.services import catalog

        lines = catalog.recipe_lines(s, "seed-p-cl12")
        assert lines[0].supply_group_id == "seed-sg-cl" and lines[0].quantity == pytest.approx(320)
    dlg.deleteLater()


def test_reports_flavor_tab_and_purchase_prefill(ctx):
    from granizapp.core.services.sales import Cart, CartFlavor, CartLine, PaymentInput, checkout
    from granizapp.ui.modules.purchases import PurchaseDialog
    from granizapp.ui.modules.reports import ReportsPage

    with ctx.session() as s:
        cs = cash.open_session(s, ctx.actor, 0)
        cart = Cart(lines=[CartLine("seed-p-cl12", "Granizado CL 12 oz", 14000, 2,
                                    flavors=[CartFlavor("seed-sg-cl", TIJ, "Tijuana")])])
        checkout(s, cart, [PaymentInput("seed-pm-efectivo", 28000)], ctx.actor, cs.id)
    page = ReportsPage(ctx)
    page.show()
    page.safe_refresh()
    tabs = [page.tabs.tabText(i) for i in range(page.tabs.count())]
    assert "Sabores" in tabs and "Adiciones" in tabs
    rows = {r.name: r for r in page.flavors.rows()}
    assert rows["Tijuana"].cups == 2 and rows["Tijuana"].revenue == pytest.approx(28000)

    dlg = PurchaseDialog(None, ctx, prefill=[(TIJ, 2, 115000), (NY, 1, 57500)])
    assert dlg.table.rowCount() == 2
    assert dlg.table.cellWidget(0, 0).currentData() == TIJ and dlg.table.cellWidget(1, 3).value() == 57500
    combo = dlg.table.cellWidget(0, 0)
    assert "seed-su-mezcla-cl" not in [combo.itemData(i) for i in range(combo.count())]
    assert dlg.total_lbl.text() == "$ 172.500"
    dlg.save()
    with ctx.session() as s:
        assert inventory.stock_of(s, TIJ) == pytest.approx(12000 - 640)
    assert not ctx.messages, ctx.messages
