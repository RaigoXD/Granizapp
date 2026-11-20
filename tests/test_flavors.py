"""Insumos con sabores: bolsas de 6 L que vienen en varios sabores.

La receta gasta el grupo («320 ml de mezcla con licor») y al vender se elige el sabor, que tiene
su propia existencia, costo y mínimo. Lo vendido sin sabor va a «Sin especificar».
"""
import shutil
from pathlib import Path

import pytest
from sqlalchemy import inspect

from granizapp.core.db import SCHEMA_VERSION, Database
from granizapp.core.models import (
    ModifierGroup,
    ProductModifierGroup,
    RecipeLine,
    Sale,
    SaleItem,
    SaleItemModifier,
    SaleStatus,
    Supply,
    SupplyGroup,
)
from granizapp.core.services import cash, catalog, inventory, purchasing, reports, sales
from granizapp.core.services.common import ServiceError
from granizapp.core.services.sales import Cart, CartFlavor, CartLine, PaymentInput
from granizapp.core.services.seed import seed_defaults
from granizapp.core.services.settings import set_setting

CL = "seed-sg-cl"
SIN_CL = "seed-su-mezcla-cl"
TIJ = "seed-su-cl-tijuana"
NY = "seed-su-cl-ny"
CASH = "seed-pm-efectivo"
FIXTURE = Path(__file__).parent / "fixtures" / "granizapp_v1_2.db"


def tij(name="Tijuana"):
    return CartFlavor(CL, TIJ, name)


def ny():
    return CartFlavor(CL, NY, "Nueva York")


def cl12(qty=1, flavors=None):
    return CartLine("seed-p-cl12", "Granizado CL 12 oz", 14000, qty, flavors=list(flavors or []))


def sell(s, actor, cs, *lines):
    cart = Cart()
    for line in lines:
        cart.add(line, merge=False)
    return sales.checkout(s, cart, [PaymentInput(CASH, cart.total)], actor, cs.id)


def flavor_rows(s, sale):
    item_ids = [i.id for i in s.query(SaleItem).filter(SaleItem.sale_id == sale.id, SaleItem.deleted.is_(False))]
    return s.query(SaleItemModifier).filter(SaleItemModifier.sale_item_id.in_(item_ids),
                                            SaleItemModifier.supply_id.is_not(None)).all()


def test_seed_has_flavor_groups_from_the_excel(db):
    with db.session() as s:
        groups = {g.id: g for g in inventory.list_supply_groups(s)}
        assert set(groups) == {"seed-sg-cl", "seed-sg-sl", "seed-sg-crem"}
        names = [v.variant_name for v in inventory.list_variants(s, CL)]
        assert names == ["Habana", "Ibiza", "Nueva York", "San Andrés", "Tijuana", "Sin especificar"]
        assert [v.variant_name for v in inventory.list_variants(s, "seed-sg-sl")] == ["Bubalú", "Chicle",
                                                                                      "Sin especificar"]
        assert groups[CL].default_supply_id == SIN_CL
        tijuana = s.get(Supply, TIJ)
        assert tijuana.name == "Mezcla granizado con licor (bolsa 6 L) · Tijuana" and tijuana.variant_code == "TIJ"
        assert tijuana.min_stock == 6000 and tijuana.unit == "ml" and tijuana.presentation_qty == 6000
        line = s.query(RecipeLine).filter_by(id="seed-p-cl12-r0").one()
        assert line.supply_group_id == CL and line.supply_id is None
        assert s.get(ModifierGroup, "seed-mg-sabor") is None  # el sabor ya no es una adición
        book = catalog.RecipeBook(s)
        assert book.asks_flavor("seed-p-cl12") == [CL]
        assert book.group_units("seed-p-promo2x12") == {CL: 2}
        assert book.asks_flavor("seed-p-cremoso") == []  # la base cremosa aún no tiene sabores
        assert book.asks_flavor("seed-p-corona") == []


def test_sale_with_flavor_consumes_that_flavor(db, actor):
    with db.session() as s:
        cs = cash.open_session(s, actor, 0)
        sale = sell(s, actor, cs, cl12(2, [tij()]))
        stock = inventory.stock_map(s)
        assert stock[TIJ] == pytest.approx(-640) and stock.get(SIN_CL, 0) == 0
        item = s.query(SaleItem).filter_by(sale_id=sale.id).one()
        assert item.name == "Granizado CL 12 oz · Tijuana"
        rows = flavor_rows(s, sale)
        assert [(r.supply_id, r.quantity) for r in rows] == [(TIJ, 2)]


def test_sale_without_flavor_goes_to_sin_especificar(db, actor):
    with db.session() as s:
        cs = cash.open_session(s, actor, 0)
        sale = sell(s, actor, cs, cl12())
        assert inventory.stock_map(s)[SIN_CL] == pytest.approx(-320)
        assert [(r.supply_id, r.name, r.quantity) for r in flavor_rows(s, sale)] == [(SIN_CL, "Sin especificar", 1)]
        ds = reports.load(s, reports.preset_period("hoy"))
        assert {(r.name, r.cups) for r in reports.by_flavor(ds)} == {("Sin especificar", 1)}


def test_promo_with_two_flavors_splits_the_mix(db, actor):
    with db.session() as s:
        cs = cash.open_session(s, actor, 0)
        promo = CartLine("seed-p-promo2x12", "Promo x2 12 oz", 20000, 1, flavors=[tij(), ny()])
        assert promo.description == "Promo x2 12 oz · Tijuana + Nueva York"
        sale = sell(s, actor, cs, promo)
        stock = inventory.stock_map(s)
        assert stock[TIJ] == pytest.approx(-320) and stock[NY] == pytest.approx(-320)
        assert stock["seed-su-vaso12"] == -2
        assert sorted((r.supply_id, r.quantity) for r in flavor_rows(s, sale)) == sorted([(TIJ, 1), (NY, 1)])
        ds = reports.load(s, reports.preset_period("hoy"))
        rows = {r.name: r for r in reports.by_flavor(ds)}
        assert rows["Tijuana"].cups == 1 and rows["Nueva York"].cups == 1
        assert rows["Tijuana"].revenue == pytest.approx(10000) and rows["Nueva York"].revenue == pytest.approx(10000)
        # 3 vasos de Tijuana en una sola línea
        sale2 = sell(s, actor, cs, cl12(3, [tij()]))
        assert [(r.supply_id, r.quantity) for r in flavor_rows(s, sale2)] == [(TIJ, 3)]
        assert CartLine("x", "Promo", 1, flavors=[tij(), tij()]).flavor_text == "2× Tijuana"


def test_cost_follows_the_flavor_and_unspecified_uses_the_average(db, actor):
    with db.session() as s:
        purchasing.create_purchase(s, actor, [purchasing.PurchaseLineInput(NY, 1, 69500)])  # NY más cara
        book = catalog.RecipeBook(s)
        per_ml = {sid: book.supplies[sid].avg_cost for sid in (TIJ, NY)}
        assert per_ml[NY] == pytest.approx(69500 / 6000) and per_ml[TIJ] == pytest.approx(57500 / 6000)
        base = book.product_cost("seed-p-cl12", {CL: {TIJ: 1}}) - 320 * per_ml[TIJ]
        assert book.product_cost("seed-p-cl12", {CL: {NY: 1}}) == pytest.approx(base + 320 * per_ml[NY])
        avg = sum(v.avg_cost for v in book.variants[CL]) / len(book.variants[CL])
        assert book.product_cost("seed-p-cl12") == pytest.approx(base + 320 * avg)
        cs = cash.open_session(s, actor, 0)
        sale = sell(s, actor, cs, cl12(1, [ny()]))
        item = s.query(SaleItem).filter_by(sale_id=sale.id).one()
        assert item.unit_cost == pytest.approx(base + 320 * per_ml[NY])


def test_require_flavor_setting(db, actor):
    with db.session() as s:
        set_setting(s, "require_flavor", True)
        cs = cash.open_session(s, actor, 0)
        with pytest.raises(ServiceError, match="sabor"):
            sell(s, actor, cs, cl12())
        with pytest.raises(ServiceError, match="sabor"):
            sell(s, actor, cs, cl12(1, [CartFlavor(CL, SIN_CL, "Sin especificar", True)]))
        sell(s, actor, cs, cl12(1, [tij()]))
        sell(s, actor, cs, CartLine("seed-p-corona", "Corona", 9000))  # sin sabores: no aplica
        sell(s, actor, cs, CartLine("seed-p-cremoso", "Cremoso", 18000))  # grupo sin sabores aún


def test_open_tab_keeps_flavors_and_void_restores_stock(db, actor):
    with db.session() as s:
        cs = cash.open_session(s, actor, 0)
        cart = Cart(lines=[cl12(1, [ny()]), CartLine("seed-p-promo2x12", "Promo x2 12 oz", 20000, 1,
                                                     flavors=[tij(), ny()])])
        tab = sales.save_open_tab(s, cart, actor, "Mesa 2")
        loaded = sales.load_cart(s, tab.id)
        assert loaded.lines[0].description == "Granizado CL 12 oz · Nueva York"
        assert sorted(f.name for f in loaded.lines[1].flavors) == ["Nueva York", "Tijuana"]
        assert loaded.lines[0].same_as(cl12(1, [ny()])) and not loaded.lines[0].same_as(cl12(1, [tij()]))
        sale = sales.checkout(s, loaded, [PaymentInput(CASH, loaded.total)], actor, cs.id)
        stock = inventory.stock_map(s)
        assert stock[NY] == pytest.approx(-640) and stock[TIJ] == pytest.approx(-320)
        sales.void_sale(s, sale.id, actor, "prueba")
        stock = inventory.stock_map(s)
        assert stock[NY] == pytest.approx(0) and stock[TIJ] == pytest.approx(0)
        ds = reports.load(s, reports.preset_period("hoy"))
        assert reports.by_flavor(ds) == []  # las ventas anuladas no cuentan


def test_flavor_stats_suggested_order_and_whatsapp_text(db, actor):
    with db.session() as s:
        inventory.add_movement(s, TIJ, 6000, "inicial", None, "inicial", None, "inicial", actor)
        inventory.add_movement(s, NY, 30000, "inicial", None, "inicial", None, "inicial", actor)
        cs = cash.open_session(s, actor, 0)
        sell(s, actor, cs, cl12(20, [tij()]))  # 6.400 ml: más de una bolsa
        group = s.get(SupplyGroup, CL)
        stats = {st.supply.variant_name: st for st in inventory.flavor_stats(s, group, days=7, cover_weeks=2)}
        t = stats["Tijuana"]
        assert t.cups == 20 and t.sold_pres == pytest.approx(6400 / 6000)
        assert t.per_week == pytest.approx(6400 / 6000) and t.status == "agotado"
        assert t.days_left == 0 and t.suggested == 3  # 2 semanas × 1,07 bolsas = 2,13 -> 3 (no queda nada)
        assert stats["Nueva York"].suggested == 0 and stats["Nueva York"].days_left is None  # 5 bolsas, sin ventas
        assert stats["Ibiza"].suggested == 1  # sin ventas pero debajo del mínimo (1 bolsa)
        assert stats["Sin especificar"].suggested == 0 and stats["Sin especificar"].is_default
        text = inventory.order_text(group, list(stats.values()), "The Spot")
        assert "• 3 bolsas Tijuana" in text and "• 1 bolsa Ibiza" in text and "Nueva York" not in text
        assert text.splitlines()[-1].startswith("Total:")


def test_flavor_crud_rules(db, actor):
    with db.session() as s:
        mar = inventory.save_variant(s, CL, {"variant_name": "Maracuyá", "variant_code": "mar", "min_pres": 2,
                                             "pres_cost": 60000, "initial": 1.5}, actor=actor)
        assert mar.name.endswith("· Maracuyá") and mar.variant_code == "MAR" and mar.min_stock == 12000
        assert mar.avg_cost == pytest.approx(10) and inventory.stock_of(s, mar.id) == 9000
        with pytest.raises(ServiceError, match="Ya existe"):
            inventory.save_variant(s, CL, {"variant_name": "maracuyá"})
        with pytest.raises(ServiceError, match="código"):
            inventory.save_variant(s, CL, {"variant_name": "Mango", "variant_code": "TIJ"})
        with pytest.raises(ServiceError, match="Sin especificar"):
            inventory.delete_supply(s, SIN_CL)
        renamed = inventory.save_variant(s, CL, {"variant_name": "Otro"}, SIN_CL)
        assert renamed.variant_name == "Sin especificar"  # el predeterminado no se renombra
        with pytest.raises(ServiceError, match="recetas"):
            inventory.delete_supply_group(s, CL)
        g = inventory.save_supply_group(s, {"name": "Base frutal (bolsa 5 L)", "unit": "ml", "presentation_qty": 5000,
                                            "presentation_name": "bolsa", "pres_cost": 50000}, actor=actor)
        default = s.get(Supply, g.default_supply_id)
        assert default.variant_name == "Sin especificar" and default.avg_cost == pytest.approx(10)
        inventory.save_supply_group(s, {"name": "Base frutal (bolsa 4 L)", "unit": "ml", "presentation_qty": 4000}, g.id)
        assert s.get(Supply, g.default_supply_id).presentation_qty == 4000
        assert s.get(Supply, g.default_supply_id).name == "Base frutal (bolsa 4 L) · Sin especificar"
        inventory.delete_supply_group(s, g.id)
        assert s.get(SupplyGroup, g.id).deleted


def _sale_v12(s, actor, cs, option_id=None, qty=1, product="seed-p-cl12"):
    """Venta escrita como la escribía la versión 1.2 (sabor = opción del grupo «Sabor»)."""
    sale = Sale(number=99, device_id="T1", status=SaleStatus.CLOSED, closed_at=cs.opened_at, total=14000 * qty,
                subtotal=14000 * qty, paid=14000 * qty, cash_session_id=cs.id)
    s.add(sale)
    s.flush()
    item = SaleItem(sale_id=sale.id, product_id=product, name="Granizado CL 12 oz", quantity=qty, unit_price=14000,
                    total=14000 * qty)
    s.add(item)
    s.flush()
    if option_id:
        s.add(SaleItemModifier(sale_item_id=item.id, option_id=option_id, name="Tijuana"))
    return item


def test_migration_of_a_real_v1_2_database(tmp_path, actor):
    path = tmp_path / "v12.db"
    shutil.copy(FIXTURE, path)
    db = Database(f"sqlite:///{path.as_posix()}")
    assert db.get_meta("schema_version") == "2"
    assert db.init_schema() is False  # base existente: migra el esquema
    assert db.get_meta("schema_version") == str(SCHEMA_VERSION)
    cols = {c["name"] for c in inspect(db.engine).get_columns("supplies")}
    assert {"group_id", "variant_name", "variant_code"} <= cols
    assert "quantity" in {c["name"] for c in inspect(db.engine).get_columns("sale_item_modifiers")}
    with db.session() as s:  # datos de la v1.2: existencias, ventas con y sin sabor, un sabor propio
        assert s.get(SupplyGroup, CL) is None and s.get(Supply, SIN_CL).group_id is None
        assert s.get(ModifierGroup, "seed-mg-sabor") is not None
        inventory.add_movement(s, SIN_CL, 15000, "inicial", None, "inicial", None, "inicial", actor)
        cs = cash.open_session(s, actor, 0)
        with_flavor = _sale_v12(s, actor, cs, "seed-mo-sab-tijuana", qty=2).id
        without = _sale_v12(s, actor, cs).id
        mine = catalog.save_option(s, {"group_id": "seed-mg-sabor", "name": "Maracuyá"})
        custom = _sale_v12(s, actor, cs, mine.id).id
    with db.session() as s:  # primer arranque de la v1.3
        seed_defaults(s)
    with db.session() as s:
        group = s.get(SupplyGroup, CL)
        generic = s.get(Supply, SIN_CL)
        assert group.default_supply_id == SIN_CL and group.name == "Mezcla granizado con licor (bolsa 6 L)"
        assert generic.group_id == CL and generic.name.endswith("· Sin especificar") and generic.min_stock == 0
        assert inventory.stock_of(s, SIN_CL) == 15000  # la existencia se conserva
        assert {v.variant_name for v in inventory.list_variants(s, CL)} >= {"Tijuana", "Maracuyá", "Sin especificar"}
        line = s.query(RecipeLine).filter_by(id="seed-p-cl12-r0").one()
        assert line.supply_group_id == CL and line.supply_id is None
        rows = {r.sale_item_id: r for r in s.query(SaleItemModifier).filter(SaleItemModifier.supply_id.is_not(None))}
        assert rows[with_flavor].supply_id == TIJ and rows[with_flavor].quantity == 2 and rows[with_flavor].option_id is None
        assert rows[without].supply_id == SIN_CL and rows[without].quantity == 1
        assert s.get(Supply, rows[custom].supply_id).variant_name == "Maracuyá"
        assert s.get(ModifierGroup, "seed-mg-sabor").deleted
        assert not s.query(ProductModifierGroup).filter_by(group_id="seed-mg-sabor", deleted=False).count()
        n_supplies, n_mods = s.query(Supply).count(), s.query(SaleItemModifier).count()
    with db.session() as s:  # segundo arranque: no repite nada
        seed_defaults(s)
    with db.session() as s:
        assert s.query(Supply).count() == n_supplies and s.query(SaleItemModifier).count() == n_mods
        cs = cash.current_session(s, actor.device_id)
        sale = sell(s, actor, cs, cl12(1, [CartFlavor(CL, TIJ, "Tijuana")]), cl12())
        stock = inventory.stock_map(s)
        assert stock[TIJ] == pytest.approx(-320) and stock[SIN_CL] == pytest.approx(15000 - 320)
        assert sale.cost_total > 0
    db.dispose()


def test_reassign_unspecified_is_not_a_loss(db, actor):
    with db.session() as s:
        inventory.add_movement(s, SIN_CL, 15000, "inicial", None, "inicial", None, "inicial", actor)
        assert inventory.reassign_unspecified(s, CL, {TIJ: 1.5, NY: 1}, actor) == 2.5
        stock = inventory.stock_map(s)
        assert stock[SIN_CL] == pytest.approx(0) and stock[TIJ] == 9000 and stock[NY] == 6000
        with pytest.raises(ServiceError, match="Solo hay"):
            inventory.reassign_unspecified(s, CL, {TIJ: 0.5}, actor)
        with pytest.raises(ServiceError):
            inventory.reassign_unspecified(s, CL, {"seed-su-sl-chicle": 0}, actor)
        ds = reports.load(s, reports.preset_period("hoy"))
        assert reports.summary(ds).losses_value == pytest.approx(0)


def test_counting_flavors_fixes_cups_sold_without_flavor(db, actor):
    """10 vasos vendidos sin sabor (de Tijuana): al contar los sabores y dejar «Sin especificar»
    en 0, la merma neta es cero (el costo ya está en el costo de lo vendido)."""
    with db.session() as s:
        inventory.add_movement(s, TIJ, 6000, "inicial", None, "inicial", None, "inicial", actor)
        cs = cash.open_session(s, actor, 0)
        sell(s, actor, cs, cl12(10))
        assert inventory.stock_map(s)[SIN_CL] == pytest.approx(-3200)
        group = s.get(SupplyGroup, CL)
        st = {x.supply.id: x for x in inventory.flavor_stats(s, group)}
        assert st[SIN_CL].status == "sin_sabor" and st[SIN_CL].status_label == "Vendido sin sabor"
        inventory.adjust_to_count(s, TIJ, 2800, actor)
        inventory.adjust_to_count(s, SIN_CL, 0, actor)
        ds = reports.load(s, reports.preset_period("hoy"))
        assert reports.summary(ds).losses_value == pytest.approx(0)
        assert inventory.stock_map(s)[TIJ] == 2800
