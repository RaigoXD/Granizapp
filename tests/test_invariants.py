"""Simulación aleatoria de varios días de operación con verificación de invariantes contables.

Después de cada operación se comprueba que el sistema sigue cuadrado:
* el saldo del cajón es exactamente el «efectivo que debe haber» del turno abierto;
* cada venta cerrada tiene pagado = suma de sus pagos vigentes;
* los saldos de los deudores coinciden con las ventas con saldo;
* una venta o compra anulada deja en cero su efecto en inventario y en dinero;
* los reportes suman lo mismo que las tablas.
"""
import random
from datetime import date

import pytest
from sqlalchemy import func, select

from granizapp.core.models import AccountMovement, Payment, Sale, SaleStatus, StockMovement
from granizapp.core.services import cash, customers, finance, inventory, purchasing, reports, sales
from granizapp.core.services.common import ServiceError, alive
from granizapp.core.services.sales import Cart, CartFlavor, CartLine, CartModifier, PaymentInput

PRODUCTS = [("seed-p-cl9", 8000), ("seed-p-cl12", 14000), ("seed-p-cl16", 18000), ("seed-p-sl9", 6000),
            ("seed-p-corona", 9000), ("seed-p-corona-m", 10000), ("seed-p-soda-sab", 12000), ("seed-p-agua", 1500),
            ("seed-p-promo2x12", 20000), ("seed-p-cremoso", 18000)]
MODS = [("seed-mo-bolitas", "Bolitas explosivas", 1000), ("seed-mo-gomitas", "Gomitas", 1000),
        ("seed-mo-esc-tajin", "Tajín", 0)]
CASH, NEQUI = "seed-pm-efectivo", "seed-pm-nequi"
CL_FLAVORS = [("seed-su-cl-tijuana", "Tijuana"), ("seed-su-cl-ny", "Nueva York"), ("seed-su-cl-habana", "Habana")]


def _net(session, model, ref_id, field):
    return session.scalar(select(func.sum(getattr(model, field))).where(model.ref_id == ref_id, model.deleted.is_(False))) or 0


def check_invariants(session, cs, drawer_id):
    # 1. cajón == efectivo esperado del turno
    if cs is not None:
        sm = cash.summary(session, cs)
        assert finance.account_balances(session)[drawer_id] == sm.expected, "cajón vs efectivo esperado"
    # 2. pagado = suma de pagos vigentes
    for sale in session.scalars(alive(Sale)):
        paid = session.scalar(select(func.sum(Payment.amount)).where(
            Payment.sale_id == sale.id, Payment.voided.is_(False), Payment.deleted.is_(False))) or 0
        if sale.status == SaleStatus.VOID:
            assert sale.paid == 0 and paid == 0, f"venta anulada con pagos vigentes {sale.id}"
            assert abs(_net(session, StockMovement, sale.id, "quantity")) < 1e-6, "anulación dejó inventario"
            assert _net(session, AccountMovement, sale.id, "amount") == 0, "anulación dejó dinero"
        else:
            assert sale.paid == paid, f"pagado {sale.paid} != pagos {paid}"
            assert sale.paid <= sale.total
    # 3. deudores
    bal = customers.balances(session)
    for d in customers.debtors(session):
        assert d.balance == bal[d.customer.id] == customers.customer_balance(session, d.customer.id)
    assert customers.total_receivable(session) == sum(d.balance for d in customers.debtors(session))
    # 4. vasos por sabor = vasos de la línea (con «Sin especificar» incluido)
    from granizapp.core.models import SaleItem, SaleItemModifier
    from granizapp.core.services.catalog import RecipeBook

    book = RecipeBook(session)
    for sale in session.scalars(alive(Sale).where(Sale.status == SaleStatus.CLOSED)):
        for item in session.scalars(alive(SaleItem).where(SaleItem.sale_id == sale.id)):
            for gid, units in book.group_units(item.product_id).items():
                cups = sum(m.quantity for m in session.scalars(alive(SaleItemModifier).where(
                    SaleItemModifier.sale_item_id == item.id, SaleItemModifier.supply_group_id == gid)))
                assert abs(cups - units * item.quantity) < 1e-6, (item.name, cups, units * item.quantity)
    # 5. compras anuladas
    for p in purchasing.list_purchases(session, include_void=True):
        if p.status == "anulada":
            assert abs(_net(session, StockMovement, p.id, "quantity")) < 1e-6


def _sale(rng, session, actor, cs, cust_ids):
    cart = Cart()
    for _ in range(rng.randint(1, 4)):
        pid, price = rng.choice(PRODUCTS)
        line = CartLine(pid, pid, price, rng.choice([1, 1, 1, 2, 3]))
        if (pid.startswith("seed-p-cl") or pid == "seed-p-promo2x12") and rng.random() < 0.8:  # sabores
            line.flavors = [CartFlavor("seed-sg-cl", *rng.choice(CL_FLAVORS)) for _ in range(rng.choice([1, 1, 2]))]
        if pid.startswith("seed-p-cl") and rng.random() < 0.4:
            oid, name, delta = rng.choice(MODS)
            line.modifiers.append(CartModifier(oid, name, delta))
        if rng.random() < 0.1:
            line.discount = min(1000, line.total)
        cart.add(line)
    if rng.random() < 0.1:
        cart.discount = min(2000, cart.subtotal)
    total = cart.total
    mode = rng.random()
    customer_id = None
    if mode < 0.5:
        payments = [PaymentInput(CASH, total, total + rng.choice([0, 0, 5000, 10000]))]
    elif mode < 0.7:
        payments = [PaymentInput(NEQUI, total)]
    elif mode < 0.85:
        part = total // 2
        payments = [PaymentInput(NEQUI, part), PaymentInput(CASH, total - part)]
    else:
        customer_id = rng.choice(cust_ids)
        paid = rng.choice([0, 0, total // 3])
        payments = [PaymentInput(CASH, paid)] if paid else []
    return sales.checkout(session, cart, payments, actor, cs.id, customer_id=customer_id, allow_over_limit=True)


@pytest.mark.parametrize("seed", [20261016, 7, 99, 2024])
def test_random_days_keep_books_balanced(db, actor, seed):
    rng = random.Random(seed)
    with db.session() as s:
        cust_ids = [customers.save_customer(s, {"name": n}).id for n in ("Raigo", "Sofi", "Cris", "Mateo")]
        purchasing.save_supplier(s, {"name": "Los Alpes"})
        drawer_id = finance.drawer_account(s).id
        # inventario inicial para algunos insumos
        for sid, qty in (("seed-su-mezcla-cl", 60000), ("seed-su-vaso12", 500), ("seed-su-corona", 48)):
            inventory.add_movement(s, sid, qty, "inicial", None, "inicial", None, "inicial", actor)
    sale_ids, open_tabs = [], []
    for day in range(6):
        with db.session() as s:
            base = cash.suggested_base(s, actor.device_id) or 200000
            cs = cash.open_session(s, actor, base)
            cs_id = cs.id
        for step in range(rng.randint(8, 20)):
            op = rng.random()
            with db.session() as s:
                cs = s.get(cash.CashSession, cs_id)
                if op < 0.45:
                    sale_ids.append(_sale(rng, s, actor, cs, cust_ids).id)
                elif op < 0.52:
                    cart = Cart(lines=[CartLine("seed-p-cl12", "x", 14000, 2)])
                    open_tabs.append(sales.save_open_tab(s, cart, actor, f"Mesa {step}").id)
                elif op < 0.58 and open_tabs:
                    tab = open_tabs.pop()
                    cart = sales.load_cart(s, tab)
                    cart.add(CartLine("seed-p-agua", "Agua", 1500))
                    sale_ids.append(sales.checkout(s, cart, [PaymentInput(CASH, cart.total)], actor, cs.id).id)
                elif op < 0.66:
                    debtors = customers.debtors(s)
                    if debtors:
                        d = rng.choice(debtors)
                        amount = rng.choice([d.balance, min(5000, d.balance), d.balance // 2 or d.balance])
                        customers.register_abono(s, d.customer.id, amount, rng.choice([CASH, NEQUI]), actor, cs.id)
                elif op < 0.74 and sale_ids:
                    sid = rng.choice(sale_ids)
                    sale = s.get(Sale, sid)
                    if sale.status != SaleStatus.VOID:
                        sales.void_sale(s, sid, actor, "prueba")
                elif op < 0.80:
                    finance.record_expense(s, {"category_id": "seed-exp-ins-hielo", "description": "Hielo",
                                               "amount": rng.choice([4000, 8000]),
                                               "account_id": rng.choice([drawer_id, "seed-acc-nequi", None])}, actor)
                elif op < 0.85:
                    shipping = rng.choice([0, 10000])
                    purchasing.create_purchase(
                        s, actor, [purchasing.PurchaseLineInput("seed-su-mezcla-cl", 2, 115000)],
                        shipping=shipping, pay_amount=rng.choice([0, 60000, 115000 + shipping]),
                        pay_account_id=rng.choice([drawer_id, "seed-acc-banco"]))
                elif op < 0.89:
                    exps = finance.list_expenses(s)
                    if exps:
                        e = rng.choice(exps)
                        if rng.random() < 0.5:
                            finance.void_expense(s, e.id, actor)
                        else:
                            finance.update_expense(s, e.id, {"amount": e.amount + 1000,
                                                             "account_id": rng.choice([drawer_id, "seed-acc-nequi"])}, actor)
                elif op < 0.93:
                    cash.cash_in_out(s, cs, 20000, rng.choice(["in", "out"]), "movimiento",
                                     actor, other_account_id=rng.choice(["seed-acc-fuerte", None]),
                                     as_capital=rng.random() < 0.5)
                elif op < 0.96:
                    inventory.adjust_to_count(s, "seed-su-vaso12", rng.randint(0, 600), actor)
                else:
                    ps = [p for p in purchasing.list_purchases(s) if p.balance]
                    if ps:
                        p = rng.choice(ps)
                        if rng.random() < 0.5:
                            purchasing.pay_purchase(s, p.id, p.balance, drawer_id, actor)
                        else:
                            purchasing.void_purchase(s, p.id, actor, "prueba")
                check_invariants(s, cs, drawer_id)
        with db.session() as s:
            cs = s.get(cash.CashSession, cs_id)
            sm = cash.summary(s, cs)
            diff = rng.choice([0, 0, -1000, 2000])
            counted = max(0, sm.expected + diff)
            keep = min(200000, counted)
            cash.close_session(s, cs.id, counted, actor, withdraw_amount=counted - keep,
                               withdraw_account_id="seed-acc-fuerte" if counted - keep else None)
            assert finance.account_balances(s)[drawer_id] == keep, "tras el cierre queda la base"
            check_invariants(s, None, drawer_id)
    # reportes vs tablas
    with db.session() as s:
        ds = reports.load(s, reports.preset_period("todo"))
        sm = reports.summary(ds)
        closed = [x for x in session_sales(s) if x.status == SaleStatus.CLOSED]
        assert sm.sales_total == sum(x.total for x in closed)
        assert sm.sales_count == len(closed)
        assert abs(sum(r.revenue for r in reports.by_category(ds)) - sm.sales_total) <= len(closed)  # redondeos
        pays = s.scalars(alive(Payment).where(Payment.voided.is_(False))).all()
        assert sum(sm.by_method.values()) == sum(p.amount for p in pays)
        assert sm.abonos == sum(p.amount for p in pays if p.kind == "abono")
        cf = reports.cash_flow(ds)
        assert cf.total_in >= sm.collected_sales + sm.abonos
        assert len(cash.list_sessions(s)) == 6 and all(c.status == "cerrada" for c in cash.list_sessions(s))


def session_sales(s):
    return s.scalars(alive(Sale)).all()


def test_void_sale_from_previous_day_hits_current_drawer(db, actor):
    with db.session() as s:
        drawer = finance.drawer_account(s).id
        cs1 = cash.open_session(s, actor, 100000)
        sale = sales.checkout(s, Cart(lines=[CartLine("seed-p-cl12", "x", 14000, 1)]), [PaymentInput(CASH, 14000)],
                              actor, cs1.id)
        cash.close_session(s, cs1.id, 114000, actor)
        cs2 = cash.open_session(s, actor, 114000)
        sales.void_sale(s, sale.id, actor, "devolución")
        sm = cash.summary(s, cs2)
        assert sm.voids == -14000 and sm.expected == 100000
        assert finance.account_balances(s)[drawer] == 100000


def test_negative_totals_rejected(db, actor):
    with db.session() as s:
        cs = cash.open_session(s, actor, 0)
        line = CartLine("seed-p-cl12", "x", 14000, 1, discount=20000)
        with pytest.raises(ServiceError):
            sales.checkout(s, Cart(lines=[line]), [], actor, cs.id)


def test_product_in_combo_and_supply_in_recipe_cannot_be_deleted(db, actor):
    from granizapp.core.services import catalog

    with db.session() as s:
        with pytest.raises(ServiceError):
            catalog.delete_product(s, "seed-p-cl12")  # está dentro de la Promo x2 12 oz
        with pytest.raises(ServiceError):
            inventory.delete_supply(s, "seed-su-mezcla-cl")  # lo usan las recetas
        catalog.delete_product(s, "seed-p-promo2x12")
        catalog.delete_product(s, "seed-p-cl12")  # ya no está en ningún combo


def test_last_admin_cannot_be_deactivated_and_admin_needs_pin_first(db):
    """Cada operación va en su propia sesión, como en la app (si falla, se deshace completa)."""
    from granizapp.core.services import auth

    with pytest.raises(ServiceError), db.session() as s:
        auth.save_user(s, {"name": "Administrador", "username": "admin", "role": "admin", "active": False},
                       "seed-user-admin")
    with pytest.raises(ServiceError), db.session() as s:  # el cajero no puede tener PIN si el administrador no tiene
        auth.save_user(s, {"name": "Dani", "role": "cajero", "pin": "2222"})
    with db.session() as s:
        assert auth.list_users(s, include_inactive=True)[0].active  # la operación fallida no dejó rastro
        assert len(auth.list_users(s, include_inactive=True)) == 1
        auth.save_user(s, {"name": "Administrador", "username": "admin", "role": "admin", "pin": "1234"},
                       "seed-user-admin")
        dani_id = auth.save_user(s, {"name": "Dani", "role": "cajero", "pin": "2222"}).id
    with pytest.raises(ServiceError), db.session() as s:  # y no puede quitárselo mientras otros tengan
        auth.clear_pin(s, "seed-user-admin")
    with db.session() as s:
        auth.clear_pin(s, dani_id)
        auth.clear_pin(s, "seed-user-admin")
        assert not any(u.pin_hash for u in auth.list_users(s))


def test_drawer_config_must_point_to_a_drawer(db, actor):
    with db.session() as s:
        drawer = cash.device_drawer(s, "seed-acc-nequi")  # una cuenta que no es cajón
        assert drawer.id == "seed-acc-caja"
