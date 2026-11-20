"""Pruebas contra un Postgres real (se omiten si no hay uno configurado).

    set GRANIZAPP_TEST_PG=postgresql://granizapp:granizapp@127.0.0.1:15433/granizapp
"""
import os

import pytest
from sqlalchemy import text

from granizapp.config import normalize_pg_url
from granizapp.core.db import Database
from granizapp.core.models import Base, Product
from granizapp.core.services import cash, customers, inventory, reports, sales
from granizapp.core.services.common import Actor
from granizapp.core.services.sales import Cart, CartLine, PaymentInput
from granizapp.core.services.seed import seed_defaults
from granizapp.core.services.sync import check_connection, synchronize

PG = os.environ.get("GRANIZAPP_TEST_PG")
pytestmark = pytest.mark.skipif(not PG, reason="Defina GRANIZAPP_TEST_PG para probar contra Postgres")


@pytest.fixture()
def pg_url():
    url = normalize_pg_url(PG)
    db = Database(url)
    with db.engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("DROP SEQUENCE IF EXISTS granizapp_rev_seq"))
    db.dispose()
    return url


def _local(tmp_path, name):
    db = Database(f"sqlite:///{(tmp_path / f'{name}.db').as_posix()}")
    db.init_schema()
    with db.session() as s:
        seed_defaults(s)
    return db


def _sell(db, device, product="seed-p-cl12", price=14000, qty=1, customer_id=None, pay=True, drawer=None):
    actor = Actor("seed-user-admin", device, "Admin", "admin")
    with db.session() as s:
        cs = cash.current_session(s, device) or cash.open_session(s, actor, 200000, account_id=drawer)
        payments = [PaymentInput("seed-pm-efectivo", price * qty)] if pay else []
        sale = sales.checkout(s, Cart(lines=[CartLine(product, "x", price, qty)]), payments, actor, cs.id,
                              customer_id=customer_id)
        return sale.id


def test_connection_ok(pg_url):
    assert "PostgreSQL" in check_connection(pg_url)


def test_direct_postgres_mode(pg_url):
    db = Database(pg_url)
    assert db.init_schema() is True
    with db.session() as s:
        seed_defaults(s)
    raigo_id = None
    with db.session() as s:
        raigo_id = customers.save_customer(s, {"name": "Raigo"}).id
    _sell(db, "PG", qty=2)
    _sell(db, "PG", qty=1, customer_id=raigo_id, pay=False)
    with db.session() as s:
        assert customers.customer_balance(s, raigo_id) == 14000
        assert inventory.stock_map(s)["seed-su-mezcla-cl"] == pytest.approx(-960)
        ds = reports.load(s, reports.preset_period("hoy"))
        assert reports.summary(ds).sales_total == 42000
        # el trigger asigna revisiones
        revs = s.execute(text("select min(rev) from sales")).scalar()
        assert revs and revs > 0
    db.dispose()


def test_two_devices_sync(pg_url, tmp_path):
    a = _local(tmp_path, "a")
    b = _local(tmp_path, "b")

    # A configura y vende
    with a.session() as s:
        p = s.get(Product, "seed-p-cl12")
        p.price = 15000
        p.name = "Granizado CL 12 oz (nuevo precio)"
        raigo = customers.save_customer(s, {"name": "Raigo"})
        raigo_id = raigo.id
    _sell(a, "AAA", price=15000, qty=2)
    _sell(a, "AAA", price=15000, qty=1, customer_id=raigo_id, pay=False)
    r1 = synchronize(a, pg_url)
    assert r1.ok, r1.error
    assert r1.pushed > 0

    # B llega con sus datos semilla: no debe pisar el producto que A cambió
    r2 = synchronize(b, pg_url)
    assert r2.ok, r2.error
    with b.session() as s:
        p = s.get(Product, "seed-p-cl12")
        assert p.price == 15000 and "nuevo precio" in p.name
        assert customers.customer_balance(s, raigo_id) == 15000
        assert len(sales.list_sales(s)) == 2

    # B es una segunda caja con su propio cajón: vende y abona; A cambia otro producto
    from granizapp.core.services import finance

    with b.session() as s:
        drawer_b = finance.save_account(s, {"name": "Caja 2", "is_drawer": True}).id
    _sell(b, "BBB", qty=3, drawer=drawer_b)
    with b.session() as s:
        cs = cash.current_session(s, "BBB")
        customers.register_abono(s, raigo_id, 5000, "seed-pm-nequi", Actor("seed-user-admin", "BBB"), cs.id)
    with a.session() as s:
        s.get(Product, "seed-p-corona").price = 9500
        s.get(Product, "seed-p-agua").deleted = True
    assert synchronize(b, pg_url).ok
    assert synchronize(a, pg_url).ok
    assert synchronize(b, pg_url).ok

    for db in (a, b):
        with db.session() as s:
            assert len(sales.list_sales(s)) == 3
            assert customers.customer_balance(s, raigo_id) == 10000
            assert s.get(Product, "seed-p-corona").price == 9500
            assert s.get(Product, "seed-p-agua").deleted is True
            assert inventory.stock_map(s)["seed-su-mezcla-cl"] == pytest.approx(-320 * 6)
            bal = finance.account_balances(s)
            assert bal["seed-acc-caja"] == 200000 + 30000 and bal[drawer_b] == 200000 + 42000
            assert bal["seed-acc-nequi"] == 5000
    from granizapp.core.services.sync import pending_count

    assert pending_count(a) == 0 and pending_count(b) == 0
    # una sincronización sin cambios no mueve nada
    r = synchronize(a, pg_url)
    assert r.ok and r.pushed == 0
    for db in (a, b):
        db.dispose()


def test_all_tables_exist_in_postgres(pg_url):
    db = Database(pg_url)
    db.init_schema()
    with db.engine.connect() as conn:
        names = {r[0] for r in conn.execute(text("select tablename from pg_tables where schemaname='public'"))}
    assert set(Base.metadata.tables) <= names
    db.dispose()
