"""Parámetros del negocio guardados en la base de datos (se sincronizan entre equipos)."""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from granizapp.core.models import Setting

DEFAULTS: dict[str, object] = {
    "business_name": "The Spot",
    "business_nit": "",
    "business_phone": "",
    "business_address": "",
    "business_city": "",
    "ticket_footer": "¡Gracias por tu visita!",
    "default_cash_base": 200000,
    "currency_symbol": "$",
    "low_stock_alerts": True,
    "allow_negative_stock": True,
    "require_customer_phone": False,
    # Sabores: exigir elegir el sabor al vender (si no, se permite «Sin especificar») y
    # cuántas semanas de venta debe cubrir el pedido sugerido de bolsas
    "require_flavor": False,
    "flavor_cover_weeks": 2,
    "setup_done": False,
}


def get_setting(session: Session, key: str):
    row = session.get(Setting, key)
    if row is None or row.deleted:
        return DEFAULTS.get(key)
    try:
        return json.loads(row.value)
    except ValueError:
        return row.value


def set_setting(session: Session, key: str, value) -> None:
    raw = json.dumps(value, ensure_ascii=False)
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(id=key, value=raw))
    elif row.value != raw or row.deleted:
        row.value = raw
        row.deleted = False


def all_settings(session: Session) -> dict:
    return {key: get_setting(session, key) for key in DEFAULTS}
