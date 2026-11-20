"""Pruebas del flujo de negocio: venta, inventario, fiado, caja, compras y gastos."""
import pytest

from granizapp.core.models import Sale, SaleStatus
from granizapp.core.services import cash, catalog, costing, customers, finance, inventory, purchasing, sales, staff
from granizapp.core.services.common import ServiceError
from granizapp.core.services.sales import Cart, CartLine, CartModifier, PaymentInput

EFECTIVO = "seed-pm-efectivo"
NEQUI = "seed-pm-nequi"
MIX_CL = "seed-su-mezcla-cl"


def _cl12_line(qty=1, mods=None):
    return CartLine("seed-p-cl12", "Granizado CL 12 oz", 14000, qty, mods or [])


def _open(s, actor, base=200000):
    return cash.open_session(s, actor, base)


def test_seed_is_idempotent(db):
    from granizapp.core.services.seed import seed_defaults

    with db.session() as s:
        n = len(catalog.list_products(s, True))
        seed_defaults(s)
        assert len(catalog.list_products(s, True)) == n
        assert finance.drawer_account(s).id == "seed-acc-caja"


def test_recipe_cost_and_yield(db):
    with db.session() as s:
        book = catalog.RecipeBook(s)
        cons = book.expand_product("seed-p-cl12", 2)
        assert cons[MIX_CL] == pytest.approx(640)
        assert cons["seed-su-vaso12"] == 2
        # costo = 320 ml * 57500/6000 + vaso + pitillo + sticker
        expected = 320 * 57500 / 6000 + 7100 / 50 + 7000 / 100 + 116000 / 500
        assert book.product_cost("seed-p-cl12") == pytest.approx(expected)
        # combo: promo x2 12 oz = 2 granizados CL 12
        assert book.expand_product("seed-p-promo2x12")[MIX_CL] == pytest.approx(640)
        supply = inventory.ensure_supply(s, MIX_CL)
        rows = {r.product.code: r for r in costing.yields_for_supply(s, supply)}
        assert rows["CL12"].units_per_presentation == pytest.approx(6000 / 320)
        assert costing.quantity_from_yield(6000, 18) == pytest.approx(333.333, rel=1e-3)


def test_cash_sale_consumes_stock_and_records_money(db, actor):
    with db.session() as s:
        cs = _open(s, actor)
        cart = Cart()
        cart.add(_cl12_line(2, [CartModifier("seed-mo-bolitas", "Bolitas explosivas", 1000)]))
        cart.add(CartLine("seed-p-corona-m", "Corona michelada", 10000))
        assert cart.total == 2 * 15000 + 10000
        sale = sales.checkout(s, cart, [PaymentInput(EFECTIVO, 40000, received=50000)], actor, cs.id)
        assert sale.status == SaleStatus.CLOSED and sale.paid == 40000 and not sale.is_credit
        stock = inventory.stock_map(s)
        assert stock[MIX_CL] == pytest.approx(-640)
        assert stock["seed-su-bolitas"] == pytest.approx(-60)
        assert stock["seed-su-corona"] == pytest.approx(-1)
        assert sale.cost_total > 0
        sm = cash.summary(s, cs)
        assert sm.cash_sales == 40000
        assert sm.expected == 240000
        assert finance.account_balances(s)["seed-acc-caja"] == 240000


def test_split_payment_and_credit_then_abono(db, actor):
    with db.session() as s:
        cs = _open(s, actor)
        raigo = customers.save_customer(s, {"name": "Raigo"})
        cart = Cart(lines=[_cl12_line(4)])  # 56.000
        with pytest.raises(ServiceError):
            sales.checkout(s, cart, [PaymentInput(EFECTIVO, 10000)], actor, cs.id)  # sin cliente
        sale = sales.checkout(s, cart, [PaymentInput(EFECTIVO, 10000), PaymentInput(NEQUI, 6000)], actor, cs.id,
                              customer_id=raigo.id)
        assert sale.is_credit and sale.balance == 40000
        assert customers.customer_balance(s, raigo.id) == 40000
        assert [d.customer.name for d in customers.debtors(s)] == ["Raigo"]
        from datetime import date

        assert len(customers.credit_sales_on(s, date.today())) == 1
        cart2 = Cart(lines=[CartLine("seed-p-club", "Club Colombia", 6000, 3)])
        sales.checkout(s, cart2, [], actor, cs.id, customer_id=raigo.id)  # todo fiado
        assert customers.customer_balance(s, raigo.id) == 58000
        pays = customers.register_abono(s, raigo.id, 50000, NEQUI, actor, cs.id)
        assert sum(p.amount for p in pays) == 50000 and len(pays) == 2  # FIFO sobre dos ventas
        assert customers.customer_balance(s, raigo.id) == 8000
        with pytest.raises(ServiceError):
            customers.register_abono(s, raigo.id, 9000, EFECTIVO, actor, cs.id)
        st = customers.statement(s, raigo.id)
        assert st[-1].balance == 8000
        sm = cash.summary(s, cs)
        nequi = next(m for m in sm.by_method if m.method_id == NEQUI)
        assert nequi.sales == 6000 and nequi.abonos == 50000
        assert sm.expected == 210000  # solo el efectivo
        customers.void_abono(s, pays[0].group_id, actor, "error")
        assert customers.customer_balance(s, raigo.id) == 58000


def test_credit_limit(db, actor):
    with db.session() as s:
        cs = _open(s, actor)
        c = customers.save_customer(s, {"name": "Sofi", "credit_limit": 20000})
        with pytest.raises(ServiceError):
            sales.checkout(s, Cart(lines=[_cl12_line(2)]), [], actor, cs.id, customer_id=c.id)
        sale = sales.checkout(s, Cart(lines=[_cl12_line(2)]), [], actor, cs.id, customer_id=c.id, allow_over_limit=True)
        assert sale.balance == 28000


def test_open_tab_then_checkout(db, actor):
    with db.session() as s:
        cs = _open(s, actor)
        cart = Cart(lines=[_cl12_line(1)])
        tab = sales.save_open_tab(s, cart, actor, "Mesa 3")
        assert tab.status == SaleStatus.OPEN
        assert inventory.stock_map(s).get(MIX_CL, 0) == 0  # aún no descuenta
        loaded = sales.load_cart(s, tab.id)
        loaded.add(_cl12_line(1))
        loaded.add(CartLine("seed-p-agua", "Agua", 1500))
        assert loaded.lines[0].quantity == 2  # se agrupan iguales
        sales.save_open_tab(s, loaded, actor, "Mesa 3")
        assert len(sales.list_open_tabs(s)) == 1
        sale = sales.checkout(s, sales.load_cart(s, tab.id), [PaymentInput(EFECTIVO, 29500)], actor, cs.id)
        assert sale.id == tab.id and sale.total == 29500
        assert len(sales.sale_items(s, sale.id)) == 2
        assert sales.list_open_tabs(s) == []
        assert inventory.stock_map(s)[MIX_CL] == pytest.approx(-640)


def test_void_sale_restores_stock_and_cash(db, actor):
    with db.session() as s:
        cs = _open(s, actor)
        sale = sales.checkout(s, Cart(lines=[_cl12_line(1)]), [PaymentInput(EFECTIVO, 14000)], actor, cs.id)
        sales.void_sale(s, sale.id, actor, "Cliente no lo quiso")
        assert inventory.stock_map(s)[MIX_CL] == pytest.approx(0)
        assert finance.account_balances(s)["seed-acc-caja"] == 200000
        sm = cash.summary(s, cs)
        assert sm.expected == 200000 and sm.void_count == 1 and sm.sales_total == 0


def test_close_cash_with_difference_and_withdrawal(db, actor):
    with db.session() as s:
        cs = _open(s, actor)
        sales.checkout(s, Cart(lines=[_cl12_line(5)]), [PaymentInput(EFECTIVO, 70000)], actor, cs.id)
        finance.record_expense(s, {"category_id": "seed-exp-ins-hielo", "description": "Hielo", "amount": 4000,
                                   "account_id": "seed-acc-caja"}, actor)
        sm = cash.summary(s, cs)
        assert sm.cash_expenses == 4000 and sm.expected == 266000
        result = cash.close_session(s, cs.id, 265000, actor, {50000: 5, 10000: 1, 5000: 1},
                                    withdraw_amount=65000, withdraw_account_id="seed-acc-fuerte")
        assert result.expected == 266000
        assert cs.difference == -1000 and cs.status == "cerrada"
        bal = finance.account_balances(s)
        assert bal["seed-acc-caja"] == 200000  # queda la base de mañana
        assert bal["seed-acc-fuerte"] == 65000
        assert cash.suggested_base(s, actor.device_id) == 200000
        cs2 = cash.open_session(s, actor, 200000)
        assert cash.summary(s, cs2).expected == 200000


def test_purchase_updates_average_cost_and_payables(db, actor):
    with db.session() as s:
        sup = purchasing.save_supplier(s, {"name": "Distribuidora Los Alpes"})
        supply = inventory.ensure_supply(s, MIX_CL)
        p = purchasing.create_purchase(
            s, actor,
            [purchasing.PurchaseLineInput(MIX_CL, 10, 600000)],
            supplier_id=sup.id, shipping=60000, pay_amount=300000, pay_account_id="seed-acc-banco",
        )
        assert p.total == 660000 and p.balance == 360000
        assert inventory.stock_of(s, MIX_CL) == pytest.approx(60000)
        assert supply.avg_cost == pytest.approx(660000 / 60000)  # stock previo 0: costo = landed
        assert purchasing.total_payable(s) == 360000
        purchasing.pay_purchase(s, p.id, 360000, "seed-acc-caja", actor)
        assert purchasing.total_payable(s) == 0
        # segunda compra a otro precio: promedio ponderado
        purchasing.create_purchase(s, actor, [purchasing.PurchaseLineInput(MIX_CL, 10, 540000)])
        assert supply.avg_cost == pytest.approx((60000 * 11 + 60000 * 9) / 120000)


def test_inventory_count_and_waste(db, actor):
    with db.session() as s:
        diff = inventory.adjust_to_count(s, "seed-su-vaso12", 120, actor)
        assert diff == 120
        inventory.register_adjustment(s, "seed-su-vaso12", 5, "merma", actor, "se rompieron")
        assert inventory.stock_of(s, "seed-su-vaso12") == 115
        low = {r.supply.id for r in inventory.low_stock(s)}
        assert "seed-su-cl-tijuana" in low  # cada sabor tiene su mínimo (1 bolsa)
        assert MIX_CL not in low  # «Sin especificar» no alerta


def test_expense_edit_and_void_keep_ledger_consistent(db, actor):
    with db.session() as s:
        exp = finance.record_expense(s, {"category_id": "seed-exp-servicios", "description": "Energía",
                                         "amount": 345000, "account_id": "seed-acc-banco"}, actor)
        assert finance.account_balances(s)["seed-acc-banco"] == -345000
        finance.update_expense(s, exp.id, {"amount": 300000, "account_id": "seed-acc-banco"}, actor)
        finance.update_expense(s, exp.id, {"amount": 310000, "account_id": "seed-acc-nequi"}, actor)
        bal = finance.account_balances(s)
        assert bal["seed-acc-banco"] == 0 and bal["seed-acc-nequi"] == -310000
        finance.void_expense(s, exp.id, actor)
        bal = finance.account_balances(s)
        assert bal["seed-acc-banco"] == 0 and bal["seed-acc-nequi"] == 0


def test_payroll_and_classification(db, actor):
    with db.session() as s:
        emp = staff.save_employee(s, {"name": "Dani", "base_pay": 650000})
        e = staff.pay_employee(s, emp.id, 650000, "sueldo", "seed-acc-fuerte", actor)
        assert e.category_id == "seed-exp-nomina-sueldos"
        cats = finance.list_expense_categories(s)
        assert finance.classify_expense(cats, "Pago Danny 18").id == "seed-exp-nomina-sueldos"
        assert finance.classify_expense(cats, "Mercado sabores").id == "seed-exp-ins-mezclas"
        assert finance.classify_expense(cats, "Sillas y mesas").id == "seed-exp-inversion"
        assert finance.classify_expense(cats, "Repuestos maquina").id == "seed-exp-mantenimiento"
        assert finance.classify_expense(cats, "Gastos Bretañas").id == "seed-exp-ins-bebidas"


def test_sale_numbers_per_device(db, actor):
    with db.session() as s:
        cs = _open(s, actor)
        a = sales.checkout(s, Cart(lines=[_cl12_line()]), [PaymentInput(EFECTIVO, 14000)], actor, cs.id)
        b = sales.checkout(s, Cart(lines=[_cl12_line()]), [PaymentInput(EFECTIVO, 14000)], actor, cs.id)
        assert (a.number, b.number) == (1, 2)
        assert sales.sale_code(b) == "T1-00002"
        assert s.query(Sale).count() == 2
