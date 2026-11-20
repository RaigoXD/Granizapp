"""Auditoría: migración del esquema, eventos registrados y pantalla."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import inspect, text

from granizapp.core.db import SCHEMA_VERSION, Database
from granizapp.core.models import AuditLog
from granizapp.core.services import audit as audit_svc
from granizapp.core.services import auth, cash, catalog, inventory, sales
from granizapp.core.services.common import ServiceError
from granizapp.core.services.sales import Cart, CartLine, PaymentInput
from granizapp.core.utils import local_to_utc, utc_to_local
from granizapp.ui.modules import MODULES
from tests.test_ui import ctx, qapp  # noqa: F401


def test_migration_adds_device_id_to_old_databases(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    db.init_schema()
    with db.engine.begin() as conn:  # simular una base de la versión 1
        conn.execute(text("ALTER TABLE audit_log DROP COLUMN device_id"))
        conn.execute(text("UPDATE _meta SET value = '1' WHERE key = 'schema_version'"))
    assert "device_id" not in {c["name"] for c in inspect(db.engine).get_columns("audit_log")}
    assert db.init_schema() is False  # base existente: solo migra
    assert "device_id" in {c["name"] for c in inspect(db.engine).get_columns("audit_log")}
    assert db.get_meta("schema_version") == str(SCHEMA_VERSION)
    with db.session() as s:
        s.add(AuditLog(action="prueba"))
    with db.session() as s:
        assert s.query(AuditLog).one().device_id == ""
    db.dispose()


def test_events_are_recorded_with_user_and_device(db, actor):
    with db.session() as s:
        cs = cash.open_session(s, actor, 100000)
        catalog.save_product(s, {"name": "Granizado CL 12 oz", "price": 15000, "code": "CL12", "kind": "preparado"},
                             "seed-p-cl12", actor)
        cart = Cart(lines=[CartLine("seed-p-cl12", "x", 15000, 2, discount=1000)], discount=2000)
        sale = sales.checkout(s, cart, [PaymentInput("seed-pm-efectivo", 27000)], actor, cs.id)
        sales.void_sale(s, sale.id, actor, "cliente se arrepintió")
        inventory.adjust_to_count(s, "seed-su-vaso12", 40, actor)
        auth.save_user(s, {"name": "Administrador", "username": "admin", "role": "admin", "pin": "1234"},
                       "seed-user-admin", actor)
        with pytest.raises(ServiceError):
            auth.authenticate(s, "seed-user-admin", "0000", "T1")
        auth.authenticate(s, "seed-user-admin", "1234", "T1")
        cash.close_session(s, cs.id, 99000, actor)
    with db.session() as s:
        entries = audit_svc.list_entries(s)
        actions = [e.action for e in entries]
        for expected in ("abrir_caja", "cambiar_precio", "descuento", "anular_venta", "conteo_inventario",
                         "editar_usuario", "ingreso_fallido", "ingreso", "cerrar_caja"):
            assert expected in actions, expected
        assert all(e.device_id == "T1" for e in entries)
        price = next(e for e in entries if e.action == "cambiar_precio")
        assert "$ 14.000 → $ 15.000" in price.detail
        disc = next(e for e in entries if e.action == "descuento")
        assert "$ 3.000" in disc.detail
        labels = audit_svc.entity_labels(s, entries)
        assert labels[("product", "seed-p-cl12")] == "Granizado CL 12 oz"
        assert labels[("sale", sale.id)].startswith("Venta T1-")
        assert labels[("cash_session", cs.id)] == "Caja #1 (T1)"
        # filtros
        assert all(audit_svc.action_group(e.action) == "Ventas" for e in audit_svc.list_entries(s, group="Ventas"))
        assert [e.action for e in audit_svc.list_entries(s, query="arrepint")] == ["anular_venta"]
        assert audit_svc.list_entries(s, user_id="seed-user-admin")
        sm = audit_svc.summarize(s, entries, None, None)
        assert sm.voids == 1 and sm.discounts == 1 and sm.price_changes == 1
        assert sm.inventory_adjustments == 1 and sm.failed_logins == 1
        assert sm.cash_differences == 1 and sm.cash_difference_total == -1000
        # el periodo se filtra en hora local aunque se guarde en UTC
        now = datetime.now()
        assert audit_svc.list_entries(s, now - timedelta(minutes=5), now + timedelta(minutes=5))
        assert not audit_svc.list_entries(s, now + timedelta(hours=1), now + timedelta(hours=2))
        assert utc_to_local(local_to_utc(now)) == now


def test_failed_login_is_kept_even_though_login_fails(db):
    with db.session() as s:
        auth.save_user(s, {"name": "Administrador", "username": "admin", "role": "admin", "pin": "1234"},
                       "seed-user-admin")
    with pytest.raises(ServiceError), db.session() as s:
        auth.authenticate(s, "seed-user-admin", "9999", "T1")
    with db.session() as s:
        assert [e.action for e in audit_svc.list_entries(s, action="ingreso_fallido")] == ["ingreso_fallido"]


def test_audit_module_is_admin_only_and_page_opens(ctx):
    spec = next(m for m in MODULES if m.key == "audit")
    assert spec.allowed("admin") and not spec.allowed("cajero")
    with ctx.session() as s:
        cs = cash.open_session(s, ctx.actor, 50000)
        sale = sales.checkout(s, Cart(lines=[CartLine("seed-p-cl9", "x", 8000)]), [PaymentInput("seed-pm-efectivo", 8000)],
                              ctx.actor, cs.id)
        sales.void_sale(s, sale.id, ctx.actor, "prueba de auditoría")
    from granizapp.ui.modules.audit import AuditPage

    page = AuditPage(ctx)
    page.show()
    page.safe_refresh()
    rows = page.table.rows()
    assert {r.action for r in rows} >= {"abrir_caja", "anular_venta"}
    assert page.k_voids.value.text() == "1"
    page.group.setCurrentIndex(page.group.findData("Caja"))
    assert {r.action for r in page.table.rows()} == {"abrir_caja"}
    page.group.setCurrentIndex(0)
    page.table.set_query("auditoría")
    assert [r.action for r in page.table.visible_rows()] == ["anular_venta"]
    assert not ctx.messages, ctx.messages
