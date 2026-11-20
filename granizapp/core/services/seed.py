"""Datos iniciales para un negocio de granizados (basados en The Spot).

Los ids son fijos ("seed-...") para que dos equipos que arrancan por separado no
dupliquen categorías ni medios de pago al sincronizar. `seed_defaults` es idempotente:
solo crea lo que falta, nunca pisa lo que el usuario ya cambió.

Las cantidades de las recetas y los costos de los insumos son ESTIMADOS de referencia
(precios de proveedores colombianos a 2026 y porciones típicas). Se deben ajustar con
las compras reales y con la calibración "1 bolsa rinde N vasos" del módulo de Costeo.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from granizapp.core.models import (
    Account,
    AccountKind,
    ExpenseCategory,
    ExpenseType,
    ModifierGroup,
    ModifierOption,
    PaymentMethod,
    Product,
    ProductCategory,
    ProductKind,
    ProductModifierGroup,
    RecipeLine,
    Role,
    SaleItem,
    SaleItemModifier,
    Setting,
    Supply,
    SupplyCategory,
    SupplyGroup,
    Unit,
    User,
)
from granizapp.core.services.common import alive
from granizapp.core.services.inventory import DEFAULT_VARIANT, variant_display_name
from granizapp.core.services.settings import DEFAULTS

# --- cuentas y medios de pago -----------------------------------------------------------
ACCOUNTS = [
    ("seed-acc-caja", "Caja registradora", AccountKind.CASH, True, 1),
    ("seed-acc-fuerte", "Efectivo guardado (caja fuerte)", AccountKind.CASH, False, 2),
    ("seed-acc-nequi", "Nequi", AccountKind.WALLET, False, 3),
    ("seed-acc-banco", "Cuenta bancaria", AccountKind.BANK, False, 4),
    ("seed-acc-daviplata", "Daviplata", AccountKind.WALLET, False, 5),
]

PAYMENT_METHODS = [
    ("seed-pm-efectivo", "Efectivo", "seed-acc-caja", True, 1),
    ("seed-pm-nequi", "Nequi", "seed-acc-nequi", False, 2),
    ("seed-pm-transferencia", "Transferencia / Bre-B", "seed-acc-banco", False, 3),
    ("seed-pm-daviplata", "Daviplata", "seed-acc-daviplata", False, 4),
    ("seed-pm-tarjeta", "Tarjeta (datáfono)", "seed-acc-banco", False, 5),
]

# --- categorías de gasto: (id, nombre, padre, tipo, palabras clave) -------------------------
EXPENSE_CATEGORIES = [
    ("seed-exp-insumos", "Insumos y mercancía", None, ExpenseType.COST, ""),
    ("seed-exp-ins-mezclas", "Mezclas, sabores y licor", "seed-exp-insumos", ExpenseType.COST,
     "mercado,sabores,mezcla,licor,jarabe,cocteles,ctails,sirope,siropes,cremoso,cremosos,quipitos,producto"),
    ("seed-exp-ins-bebidas", "Cervezas y bebidas", "seed-exp-insumos", ExpenseType.COST,
     "cerveza,cervezas,paca,corona,coronas,club,budweiser,bud,soda,sodas,bretana,bretanas,agua en botella"),
    ("seed-exp-ins-toppings", "Toppings, dulces y escarchados", "seed-exp-insumos", ExpenseType.COST,
     "gomas,gomitas,bombones,candys,dulces,chamoy,tajin,leche condensada,chantilly,cremas,perlas,bolitas,sal"),
    ("seed-exp-ins-desechables", "Vasos y desechables", "seed-exp-insumos", ExpenseType.COST,
     "vasos,vaso,pitillos,pititllos,tapas,servilletas,bolsas plasticas"),
    ("seed-exp-ins-hielo", "Hielo", "seed-exp-insumos", ExpenseType.COST, "hielo"),
    ("seed-exp-envios", "Envíos y transporte", None, ExpenseType.OPERATING,
     "envio,envios,domicilio,transporte,flete,pago envio,envio mercado"),
    ("seed-exp-nomina", "Nómina y personal", None, ExpenseType.PAYROLL, ""),
    ("seed-exp-nomina-sueldos", "Sueldos / turnos", "seed-exp-nomina", ExpenseType.PAYROLL,
     "pago dani,pago danny,sueldo,nomina,quincena"),
    ("seed-exp-nomina-extras", "Horas extra", "seed-exp-nomina", ExpenseType.PAYROLL, "hora extra,horas extra"),
    ("seed-exp-nomina-adelantos", "Adelantos", "seed-exp-nomina", ExpenseType.PAYROLL, "adelanto,anticipo"),
    ("seed-exp-nomina-bonos", "Bonificaciones y propinas", "seed-exp-nomina", ExpenseType.PAYROLL, "bono,bonificacion"),
    ("seed-exp-nomina-seguridad", "Seguridad social y prestaciones", "seed-exp-nomina", ExpenseType.PAYROLL,
     "seguridad social,arl,eps,pension,prima,cesantias"),
    ("seed-exp-servicios", "Servicios públicos e internet", None, ExpenseType.OPERATING,
     "energia,luz,servicios,internet,gas natural,acueducto,celular,plan de datos"),
    ("seed-exp-arriendo", "Arriendo del local", None, ExpenseType.OPERATING, "arriendo,alquiler"),
    ("seed-exp-marketing", "Publicidad y decoración", None, ExpenseType.OPERATING,
     "stickers,stikers,stickets,sticker,decoracion,decoraciones,publicidad,volantes,pauta"),
    ("seed-exp-mantenimiento", "Mantenimiento y repuestos", None, ExpenseType.OPERATING,
     "repuestos,repuesto,mantenimiento,reparacion,pegante,arreglo"),
    ("seed-exp-aseo", "Aseo y limpieza", None, ExpenseType.OPERATING,
     "bolsas de basura,aseo,jabon,limpieza,desinfectante"),
    ("seed-exp-inversion", "Equipos y mobiliario", None, ExpenseType.INVESTMENT,
     "sillas,mesas,mesa,ventilador,maquina,televisor,nevera,congelador,mueble,granizadora"),
    ("seed-exp-impuestos", "Impuestos y trámites", None, ExpenseType.TAXES,
     "impuesto,camara de comercio,dian,ica,rut,sayco,bomberos"),
    ("seed-exp-financiero", "Comisiones bancarias", None, ExpenseType.FINANCIAL, "comision,4x1000,cuota de manejo"),
    ("seed-exp-otros", "Otros gastos", None, ExpenseType.OPERATING, ""),
]

# --- categorías de producto ---------------------------------------------------------------
PRODUCT_CATEGORIES = [
    ("seed-pc-granizados", "Granizados", None, "#7C5CFC", 1),
    ("seed-pc-gr-cl", "Con licor (CL)", "seed-pc-granizados", "#7C5CFC", 1),
    ("seed-pc-gr-sl", "Sin licor (SL)", "seed-pc-granizados", "#2FB5A8", 2),
    ("seed-pc-gr-cremosos", "Cremosos y especiales", "seed-pc-granizados", "#E58A2E", 3),
    ("seed-pc-cervezas", "Cervezas", None, "#D9A400", 2),
    ("seed-pc-cerv-sola", "Cerveza sola", "seed-pc-cervezas", "#D9A400", 1),
    ("seed-pc-cerv-mich", "Micheladas", "seed-pc-cervezas", "#D9534F", 2),
    ("seed-pc-sodas", "Sodas y bebidas", None, "#3A9AD9", 3),
    ("seed-pc-promos", "Promociones", None, "#E0457B", 4),
    ("seed-pc-adiciones", "Adiciones", None, "#8A8A8A", 5),
    ("seed-pc-otros", "Otros y servicios", None, "#6B7280", 6),
    ("seed-pc-historicos", "Históricos (importados)", None, "#9CA3AF", 99),
]

# --- insumos: (id, nombre, categoría, unidad, presentación, contenido, costo presentación, mínimo base)
SUPPLY_CATEGORIES = [
    ("seed-sc-mezclas", "Mezclas y bases de granizado", 1),
    ("seed-sc-toppings", "Toppings y adiciones", 2),
    ("seed-sc-escarchados", "Escarchados y salsas", 3),
    ("seed-sc-siropes", "Siropes y saborizantes", 4),
    ("seed-sc-bebidas", "Bebidas para reventa", 5),
    ("seed-sc-desechables", "Vasos y desechables", 6),
    ("seed-sc-marca", "Marca y empaque", 7),
    ("seed-sc-otros", "Otros insumos", 8),
]

# --- insumos con sabores (bolsas de 6 L que vienen en varios sabores) ----------------------
# (id grupo, nombre, categoría, unidad, presentación, contenido, insumo «Sin especificar», costo bolsa)
# El insumo «Sin especificar» conserva el id del insumo genérico de la versión 1.2: así su
# existencia, costo y kardex siguen intactos al actualizar.
SUPPLY_GROUPS = [
    ("seed-sg-cl", "Mezcla granizado con licor (bolsa 6 L)", "seed-sc-mezclas", Unit.ML, "bolsa", 6000,
     "seed-su-mezcla-cl", 57500),
    ("seed-sg-sl", "Mezcla granizado sin licor (bolsa 6 L)", "seed-sc-mezclas", Unit.ML, "bolsa", 6000,
     "seed-su-mezcla-sl", 40000),
    ("seed-sg-crem", "Base cremosa con licor (bolsa 6 L)", "seed-sc-mezclas", Unit.ML, "bolsa", 6000,
     "seed-su-base-cremosa", 57500),
]
# sabores vistos en el Excel: (id, grupo, sabor, código para vender, mínimo en bolsas)
VARIANTS = [
    ("seed-su-cl-tijuana", "seed-sg-cl", "Tijuana", "TIJ", 1),
    ("seed-su-cl-ny", "seed-sg-cl", "Nueva York", "NY", 1),
    ("seed-su-cl-sanandres", "seed-sg-cl", "San Andrés", "SA", 1),
    ("seed-su-cl-habana", "seed-sg-cl", "Habana", "HAB", 1),
    ("seed-su-cl-ibiza", "seed-sg-cl", "Ibiza", "IBI", 1),
    ("seed-su-sl-bubalu", "seed-sg-sl", "Bubalú", "BUB", 1),
    ("seed-su-sl-chicle", "seed-sg-sl", "Chicle", "CHI", 1),
]
# versión 1.2: los sabores eran opciones del grupo de adiciones «Sabor»
OLD_FLAVOR_GROUP = "seed-mg-sabor"
OLD_FLAVOR_OPTIONS = {
    "seed-mo-sab-tijuana": "seed-su-cl-tijuana", "seed-mo-sab-ny": "seed-su-cl-ny",
    "seed-mo-sab-sanandres": "seed-su-cl-sanandres", "seed-mo-sab-habana": "seed-su-cl-habana",
    "seed-mo-sab-ibiza": "seed-su-cl-ibiza", "seed-mo-sab-bubalu": "seed-su-sl-bubalu",
    "seed-mo-sab-chicle": "seed-su-sl-chicle",
}

SUPPLIES = [
    ("seed-su-bolitas", "Bolitas explosivas (perlas)", "seed-sc-toppings", Unit.G, "tarro", 1000, 25000, 500),
    ("seed-su-gomitas", "Gomitas", "seed-sc-toppings", Unit.UNIT, "paquete", 100, 16000, 50),
    ("seed-su-bombones", "Bombones / masmelos", "seed-sc-toppings", Unit.UNIT, "paquete", 50, 9900, 20),
    ("seed-su-leche-cond", "Leche condensada", "seed-sc-toppings", Unit.G, "bolsa", 1000, 14000, 300),
    ("seed-su-chantilly", "Crema chantilly", "seed-sc-toppings", Unit.G, "bolsa", 1000, 32000, 300),
    ("seed-su-sal-michelar", "Sal para michelar", "seed-sc-escarchados", Unit.G, "bolsa", 500, 10000, 150),
    ("seed-su-tajin", "Tajín", "seed-sc-escarchados", Unit.G, "frasco", 400, 29900, 100),
    ("seed-su-chamoy", "Chamoy", "seed-sc-escarchados", Unit.ML, "botella", 1000, 20000, 250),
    ("seed-su-limon", "Limón", "seed-sc-escarchados", Unit.UNIT, "bolsa", 50, 15000, 10),
    ("seed-su-sirope", "Sirope saborizado para sodas", "seed-sc-siropes", Unit.ML, "botella", 1000, 25000, 300),
    ("seed-su-corona", "Cerveza Corona 355 ml", "seed-sc-bebidas", Unit.UNIT, "caja x24", 24, 87600, 12),
    ("seed-su-club", "Cerveza Club Colombia", "seed-sc-bebidas", Unit.UNIT, "paca x24", 24, 79200, 12),
    ("seed-su-bud", "Cerveza Budweiser", "seed-sc-bebidas", Unit.UNIT, "paca x24", 24, 54000, 12),
    ("seed-su-soda", "Soda Bretaña", "seed-sc-bebidas", Unit.UNIT, "paca x18", 18, 50000, 6),
    ("seed-su-agua", "Agua en botella", "seed-sc-bebidas", Unit.UNIT, "paca x24", 24, 18000, 6),
    ("seed-su-vaso9", "Vaso 9 oz", "seed-sc-desechables", Unit.UNIT, "paquete x50", 50, 7100, 50),
    ("seed-su-vaso12", "Vaso 12 oz", "seed-sc-desechables", Unit.UNIT, "paquete x50", 50, 7100, 50),
    ("seed-su-vaso16", "Vaso 16 oz", "seed-sc-desechables", Unit.UNIT, "paquete x50", 50, 9000, 50),
    ("seed-su-vaso-premium", "Vaso premium (cremosos)", "seed-sc-desechables", Unit.UNIT, "paquete x25", 25, 25000, 25),
    ("seed-su-vaso-mich", "Vaso michelero", "seed-sc-desechables", Unit.UNIT, "paquete x25", 25, 9500, 25),
    ("seed-su-pitillo", "Pitillos", "seed-sc-desechables", Unit.UNIT, "paquete x100", 100, 7000, 100),
    ("seed-su-sticker", "Sticker de marca", "seed-sc-marca", Unit.UNIT, "rollo x500", 500, 116000, 100),
]

# --- productos: (id, nombre, código, categoría, tipo, precio, tamaño, ml, alcohol, activo, días, favorito)
ALL_DAYS = "0123456"
PRODUCTS = [
    ("seed-p-cl9", "Granizado CL 9 oz", "CL9", "seed-pc-gr-cl", ProductKind.PREPARED, 8000, "9 oz", 266, True, True, ALL_DAYS, True),
    ("seed-p-cl12", "Granizado CL 12 oz", "CL12", "seed-pc-gr-cl", ProductKind.PREPARED, 14000, "12 oz", 355, True, True, ALL_DAYS, True),
    ("seed-p-cl16", "Granizado CL 16 oz", "CL16", "seed-pc-gr-cl", ProductKind.PREPARED, 18000, "16 oz", 473, True, True, ALL_DAYS, True),
    ("seed-p-sl9", "Granizado SL 9 oz", "SL9", "seed-pc-gr-sl", ProductKind.PREPARED, 6000, "9 oz", 266, False, True, ALL_DAYS, True),
    ("seed-p-sl12", "Granizado SL 12 oz", "SL12", "seed-pc-gr-sl", ProductKind.PREPARED, 12000, "12 oz", 355, False, True, ALL_DAYS, True),
    ("seed-p-sl16", "Granizado SL 16 oz", "SL16", "seed-pc-gr-sl", ProductKind.PREPARED, 16000, "16 oz", 473, False, True, ALL_DAYS, True),
    ("seed-p-cremoso", "Cremoso", "CREM", "seed-pc-gr-cremosos", ProductKind.PREPARED, 18000, "16 oz", 473, True, True, ALL_DAYS, True),
    ("seed-p-quip8", "Quipitos 8 oz", "QP8", "seed-pc-gr-cremosos", ProductKind.PREPARED, 10000, "8 oz", 237, True, True, ALL_DAYS, False),
    ("seed-p-quip12", "Quipitos 12 oz", "QP12", "seed-pc-gr-cremosos", ProductKind.PREPARED, 14000, "12 oz", 355, True, True, ALL_DAYS, False),
    ("seed-p-quip16", "Quipitos 16 oz", "QP16", "seed-pc-gr-cremosos", ProductKind.PREPARED, 18000, "16 oz", 473, True, True, ALL_DAYS, False),
    ("seed-p-esp15", "Especial de 15K", "ESP15", "seed-pc-gr-cremosos", ProductKind.PREPARED, 15000, "12 oz", 355, True, True, ALL_DAYS, False),
    ("seed-p-alpinito", "Alpinito / Piña colada", "ALP", "seed-pc-gr-cremosos", ProductKind.PREPARED, 18000, "16 oz", 473, True, False, ALL_DAYS, False),
    ("seed-p-cle9", "Granizado CL Especial 9 oz", "CLE9", "seed-pc-gr-cl", ProductKind.PREPARED, 10000, "9 oz", 266, True, False, ALL_DAYS, False),
    ("seed-p-cle12", "Granizado CL Especial 12 oz", "CLE12", "seed-pc-gr-cl", ProductKind.PREPARED, 16000, "12 oz", 355, True, False, ALL_DAYS, False),
    ("seed-p-corona", "Corona", "COR", "seed-pc-cerv-sola", ProductKind.RESALE, 9000, "355 ml", 355, True, True, ALL_DAYS, True),
    ("seed-p-club", "Club Colombia", "CLUB", "seed-pc-cerv-sola", ProductKind.RESALE, 6000, "", None, True, True, ALL_DAYS, True),
    ("seed-p-bud", "Budweiser", "BUD", "seed-pc-cerv-sola", ProductKind.RESALE, 5000, "", None, True, True, ALL_DAYS, True),
    ("seed-p-corona-m", "Corona michelada", "CORM", "seed-pc-cerv-mich", ProductKind.PREPARED, 10000, "", None, True, True, ALL_DAYS, True),
    ("seed-p-club-m", "Club michelada", "CLUBM", "seed-pc-cerv-mich", ProductKind.PREPARED, 7000, "", None, True, True, ALL_DAYS, True),
    ("seed-p-bud-m", "Budweiser michelada", "BUDM", "seed-pc-cerv-mich", ProductKind.PREPARED, 6000, "", None, True, True, ALL_DAYS, True),
    ("seed-p-soda", "Soda normal", "SODA", "seed-pc-sodas", ProductKind.PREPARED, 10000, "", None, False, True, ALL_DAYS, True),
    ("seed-p-soda-sab", "Soda saborizada", "SODAS", "seed-pc-sodas", ProductKind.PREPARED, 12000, "", None, False, True, ALL_DAYS, True),
    ("seed-p-agua", "Agua", "AGUA", "seed-pc-sodas", ProductKind.RESALE, 1500, "", None, False, True, ALL_DAYS, True),
    ("seed-p-promo17", "Promo 17K (lun-jue)", "P17", "seed-pc-promos", ProductKind.COMBO, 17000, "", None, True, True, "0123", True),
    ("seed-p-promo2x12", "Promo x2 12 oz", "P2X12", "seed-pc-promos", ProductKind.COMBO, 20000, "12 oz", None, True, False, ALL_DAYS, False),
    ("seed-p-promo2x16", "Promo x2 16 oz", "P2X16", "seed-pc-promos", ProductKind.COMBO, 28000, "16 oz", None, True, False, ALL_DAYS, False),
    ("seed-p-adicion", "Adición", "ADI", "seed-pc-adiciones", ProductKind.EXTRA, 1000, "", None, False, True, ALL_DAYS, True),
    ("seed-p-evento", "Evento / servicio especial", "EVENTO", "seed-pc-otros", ProductKind.SERVICE, 0, "", None, False, True, ALL_DAYS, False),
]

GRANIZADO_CUPS = {"9 oz": "seed-su-vaso9", "12 oz": "seed-su-vaso12", "16 oz": "seed-su-vaso16"}
# ml de mezcla por vaso (≈ 87-90 % del volumen nominal; el resto es espacio y escarchado)
MIX_ML = {"9 oz": 230, "12 oz": 320, "16 oz": 430, "8 oz": 200}


def _granizado(mix_group: str, size: str) -> list[tuple[str, float]]:
    """La mezcla es un insumo con sabores ("grp:"): el sabor se elige al vender."""
    return [(mix_group, MIX_ML[size]), (GRANIZADO_CUPS[size], 1), ("seed-su-pitillo", 1), ("seed-su-sticker", 1)]


def _michelada(beer: str) -> list[tuple[str, float]]:
    return [(beer, 1), ("seed-su-vaso-mich", 1), ("seed-su-sal-michelar", 8), ("seed-su-limon", 1), ("seed-su-pitillo", 1)]


# receta: producto -> [(insumo o "prod:<id>", cantidad)]
RECIPES: dict[str, list[tuple[str, float]]] = {
    "seed-p-cl9": _granizado("grp:seed-sg-cl", "9 oz"),
    "seed-p-cl12": _granizado("grp:seed-sg-cl", "12 oz"),
    "seed-p-cl16": _granizado("grp:seed-sg-cl", "16 oz"),
    "seed-p-sl9": _granizado("grp:seed-sg-sl", "9 oz"),
    "seed-p-sl12": _granizado("grp:seed-sg-sl", "12 oz"),
    "seed-p-sl16": _granizado("grp:seed-sg-sl", "16 oz"),
    "seed-p-cle9": _granizado("grp:seed-sg-cl", "9 oz") + [("seed-su-chamoy", 15), ("seed-su-tajin", 5)],
    "seed-p-cle12": _granizado("grp:seed-sg-cl", "12 oz") + [("seed-su-chamoy", 15), ("seed-su-tajin", 5)],
    "seed-p-cremoso": [("grp:seed-sg-crem", 400), ("seed-su-vaso-premium", 1), ("seed-su-chantilly", 30),
                       ("seed-su-leche-cond", 20), ("seed-su-pitillo", 1), ("seed-su-sticker", 1)],
    "seed-p-quip8": [("grp:seed-sg-crem", 200), ("seed-su-vaso9", 1), ("seed-su-pitillo", 1)],
    "seed-p-quip12": [("grp:seed-sg-crem", 320), ("seed-su-vaso12", 1), ("seed-su-pitillo", 1)],
    "seed-p-quip16": [("grp:seed-sg-crem", 430), ("seed-su-vaso16", 1), ("seed-su-pitillo", 1)],
    "seed-p-esp15": [("grp:seed-sg-crem", 320), ("seed-su-vaso12", 1), ("seed-su-chamoy", 15),
                     ("seed-su-tajin", 5), ("seed-su-pitillo", 1)],
    "seed-p-alpinito": [("grp:seed-sg-crem", 400), ("seed-su-vaso-premium", 1), ("seed-su-pitillo", 1)],
    "seed-p-corona": [("seed-su-corona", 1)],
    "seed-p-club": [("seed-su-club", 1)],
    "seed-p-bud": [("seed-su-bud", 1)],
    "seed-p-corona-m": _michelada("seed-su-corona"),
    "seed-p-club-m": _michelada("seed-su-club"),
    "seed-p-bud-m": _michelada("seed-su-bud"),
    "seed-p-soda": [("seed-su-soda", 1), ("seed-su-vaso16", 1), ("seed-su-limon", 1), ("seed-su-pitillo", 1)],
    "seed-p-soda-sab": [("seed-su-soda", 1), ("seed-su-vaso16", 1), ("seed-su-sirope", 30), ("seed-su-pitillo", 1)],
    "seed-p-agua": [("seed-su-agua", 1)],
    "seed-p-promo2x12": [("prod:seed-p-cl12", 2)],
    "seed-p-promo2x16": [("prod:seed-p-cl16", 2)],
}

MANUAL_COSTS = {"seed-p-adicion": 300}

# --- modificadores --------------------------------------------------------------------------
MODIFIER_GROUPS = [
    # (id, nombre, min, max, preguntar al agregar, orden)
    ("seed-mg-adiciones", "Adiciones", 0, 0, False, 1),
    ("seed-mg-escarchado", "Escarchado", 0, 1, False, 2),
]

MODIFIER_OPTIONS = [
    # (id, grupo, nombre, precio, receta)
    ("seed-mo-bolitas", "seed-mg-adiciones", "Bolitas explosivas", 1000, [("seed-su-bolitas", 30)]),
    ("seed-mo-gomitas", "seed-mg-adiciones", "Gomitas", 1000, [("seed-su-gomitas", 5)]),
    ("seed-mo-bombones", "seed-mg-adiciones", "Bombones", 1000, [("seed-su-bombones", 3)]),
    ("seed-mo-chamoy", "seed-mg-adiciones", "Chamoy", 1000, [("seed-su-chamoy", 15)]),
    ("seed-mo-leche", "seed-mg-adiciones", "Leche condensada", 1000, [("seed-su-leche-cond", 20)]),
    ("seed-mo-chantilly", "seed-mg-adiciones", "Crema chantilly", 1000, [("seed-su-chantilly", 30)]),
    ("seed-mo-esc-sal", "seed-mg-escarchado", "Sal michelada", 0, [("seed-su-sal-michelar", 8)]),
    ("seed-mo-esc-tajin", "seed-mg-escarchado", "Tajín", 0, [("seed-su-tajin", 5)]),
    ("seed-mo-esc-chamoy", "seed-mg-escarchado", "Chamoy + Tajín", 1000, [("seed-su-chamoy", 15), ("seed-su-tajin", 5)]),
]

GRANIZADO_PRODUCTS = ["seed-p-cl9", "seed-p-cl12", "seed-p-cl16", "seed-p-sl9", "seed-p-sl12", "seed-p-sl16",
                      "seed-p-cle9", "seed-p-cle12"]
CREMOSO_PRODUCTS = ["seed-p-cremoso", "seed-p-quip8", "seed-p-quip12", "seed-p-quip16", "seed-p-esp15", "seed-p-alpinito"]
MICHELADA_PRODUCTS = ["seed-p-corona-m", "seed-p-club-m", "seed-p-bud-m"]

PRODUCT_GROUPS: dict[str, list[str]] = {}
for pid in GRANIZADO_PRODUCTS:
    PRODUCT_GROUPS[pid] = ["seed-mg-adiciones", "seed-mg-escarchado"]
for pid in CREMOSO_PRODUCTS:
    PRODUCT_GROUPS[pid] = ["seed-mg-adiciones", "seed-mg-escarchado"]
for pid in MICHELADA_PRODUCTS:
    PRODUCT_GROUPS[pid] = ["seed-mg-escarchado"]
PRODUCT_GROUPS["seed-p-soda-sab"] = ["seed-mg-adiciones"]
PRODUCT_GROUPS["seed-p-promo17"] = ["seed-mg-adiciones"]


# Fecha antigua para los datos semilla: cualquier cambio hecho por el usuario en otro
# equipo es más reciente y gana al sincronizar (un equipo nuevo no pisa lo configurado).
SEED_TS = datetime(2000, 1, 1)


def _add_missing(session: Session, model, obj_id: str, **fields) -> bool:
    if session.get(model, obj_id) is not None:
        return False
    session.add(model(id=obj_id, created_at=SEED_TS, updated_at=SEED_TS, **fields))
    return True


def seed_defaults(session: Session, with_catalog: bool = True) -> None:
    for i, (aid, name, kind, drawer, order) in enumerate(ACCOUNTS):
        _add_missing(session, Account, aid, name=name, kind=kind, is_drawer=drawer, sort_order=order)
    for mid, name, acc, is_cash, order in PAYMENT_METHODS:
        _add_missing(session, PaymentMethod, mid, name=name, account_id=acc, is_cash=is_cash, sort_order=order)
    for order, (cid, name, parent, etype, kw) in enumerate(EXPENSE_CATEGORIES):
        _add_missing(session, ExpenseCategory, cid, name=name, parent_id=parent, type=etype, keywords=kw, sort_order=order)
    _add_missing(session, User, "seed-user-admin", name="Administrador", username="admin", role=Role.ADMIN)
    for key, value in DEFAULTS.items():
        _add_missing(session, Setting, key, value=json.dumps(value, ensure_ascii=False))
    session.flush()
    if with_catalog:
        migrate_flavors(session)  # bases de la versión 1.2: pasa a insumos con sabores (solo la primera vez)
        seed_catalog(session)


def _seed_flavor_groups(session: Session) -> None:
    """Base nueva: crea los insumos con sabores con su «Sin especificar» y los sabores del Excel."""
    for order, (gid, name, cat, unit, pres, qty, default_id, pres_cost) in enumerate(SUPPLY_GROUPS, 1):
        if session.get(SupplyGroup, gid) is None and session.get(Supply, default_id) is None:
            unit_cost = pres_cost / qty
            _add_missing(session, SupplyGroup, gid, name=name, category_id=cat, unit=unit, presentation_name=pres,
                         presentation_qty=qty, default_supply_id=default_id, sort_order=order)
            _add_missing(session, Supply, default_id, name=f"{name} · {DEFAULT_VARIANT}", category_id=cat, unit=unit,
                         presentation_name=pres, presentation_qty=qty, avg_cost=unit_cost, last_cost=unit_cost,
                         group_id=gid, variant_name=DEFAULT_VARIANT)
    session.flush()
    _seed_variants(session)


def _seed_variants(session: Session) -> None:
    for vid, gid, flavor, code, min_pres in VARIANTS:
        group = session.get(SupplyGroup, gid)
        if group is None or group.deleted:
            continue
        default = session.get(Supply, group.default_supply_id) if group.default_supply_id else None
        unit_cost = default.avg_cost if default is not None and default.avg_cost else 0.0
        _add_missing(session, Supply, vid, name=variant_display_name(group, flavor), category_id=group.category_id,
                     unit=group.unit, presentation_name=group.presentation_name,
                     presentation_qty=group.presentation_qty, avg_cost=unit_cost, last_cost=unit_cost,
                     min_stock=min_pres * (group.presentation_qty or 1), group_id=gid, variant_name=flavor,
                     variant_code=code)
    session.flush()


def migrate_flavors(session: Session) -> bool:
    """Convierte una base de la versión 1.2 al manejo de sabores. Solo actúa una vez por
    grupo (cuando el insumo genérico existe y todavía no es parte de un grupo):

    * la bolsa genérica pasa a ser «Sin especificar» del grupo, con su existencia, costo y kardex;
    * las recetas que gastaban la bolsa genérica gastan ahora el grupo (sabor al vender);
    * se crean los sabores (con el costo actual de la bolsa) y los que el usuario había agregado
      al grupo «Sabor» de las adiciones;
    * las ventas anteriores quedan con su sabor como sabor real (reportes por sabor completos);
    * el grupo de adiciones «Sabor» se retira (ya no hace falta).
    """
    from sqlalchemy import select

    from granizapp.core.services.catalog import RecipeBook

    migrated = []
    for order, (gid, _name, _cat, _unit, pres, qty, default_id, _cost) in enumerate(SUPPLY_GROUPS, 1):
        generic = session.get(Supply, default_id)
        if generic is None or generic.group_id:
            continue
        group = session.get(SupplyGroup, gid)
        if group is None:
            group = SupplyGroup(id=gid, name=generic.name, category_id=generic.category_id, unit=generic.unit,
                                presentation_name=generic.presentation_name or pres,
                                presentation_qty=generic.presentation_qty or qty, default_supply_id=default_id,
                                sort_order=order, active=True, created_at=SEED_TS, updated_at=SEED_TS)
            session.add(group)
            session.flush()
        generic.group_id = gid
        generic.variant_name = DEFAULT_VARIANT
        generic.name = variant_display_name(group, DEFAULT_VARIANT)
        generic.min_stock = 0  # las alertas ahora son por sabor
        for line in session.scalars(alive(RecipeLine).where(RecipeLine.supply_id == default_id)):
            line.supply_group_id = gid
            line.supply_id = None
        migrated.append(gid)
    if not migrated:
        return False
    session.flush()
    _seed_variants(session)

    # sabores de la v1.2 (opciones del grupo «Sabor») -> sabores reales
    option_map = dict(OLD_FLAVOR_OPTIONS)
    old_group = session.get(ModifierGroup, OLD_FLAVOR_GROUP)
    if old_group is not None:
        cl = session.get(SupplyGroup, "seed-sg-cl")
        existing = {(s.group_id, s.variant_name.lower()): s.id
                    for s in session.scalars(alive(Supply).where(Supply.group_id.is_not(None)))}
        for opt in session.scalars(select(ModifierOption).where(ModifierOption.group_id == old_group.id)):
            if opt.id in option_map or opt.deleted or cl is None:
                continue
            key = (cl.id, (opt.name or "").strip().lower())
            if key not in existing:  # sabor agregado por el usuario: va a la mezcla con licor
                default = session.get(Supply, cl.default_supply_id)
                v = Supply(name=variant_display_name(cl, opt.name.strip()), category_id=cl.category_id, unit=cl.unit,
                           presentation_name=cl.presentation_name, presentation_qty=cl.presentation_qty,
                           avg_cost=default.avg_cost if default else 0, last_cost=default.avg_cost if default else 0,
                           group_id=cl.id, variant_name=opt.name.strip())
                session.add(v)
                session.flush()
                existing[key] = v.id
            option_map[opt.id] = existing[key]
    variants = {s.id: s for s in session.scalars(select(Supply).where(Supply.id.in_(list(option_map.values()))))}
    for mod in session.scalars(alive(SaleItemModifier).where(SaleItemModifier.option_id.in_(list(option_map)))):
        variant = variants.get(option_map[mod.option_id])
        item = session.get(SaleItem, mod.sale_item_id)
        if variant is None or item is None:
            continue
        mod.supply_id = variant.id
        mod.supply_group_id = variant.group_id
        mod.name = variant.variant_name
        mod.quantity = item.quantity
        mod.option_id = None
    session.flush()

    # ventas anteriores de granizados sin sabor: quedan como «Sin especificar»
    book = RecipeBook(session)
    flavored = {(m.sale_item_id, m.supply_group_id) for m in session.scalars(
        alive(SaleItemModifier).where(SaleItemModifier.supply_id.is_not(None)))}
    units_of: dict[str, dict[str, float]] = {}
    for item in session.scalars(alive(SaleItem).where(SaleItem.product_id.is_not(None))):
        if item.product_id not in units_of:
            units_of[item.product_id] = book.group_units(item.product_id)
        for gid, units in units_of[item.product_id].items():
            if gid in migrated and (item.id, gid) not in flavored:
                default = book.default_of(gid)
                if default:
                    session.add(SaleItemModifier(sale_item_id=item.id, supply_id=default, supply_group_id=gid,
                                                 name=DEFAULT_VARIANT, quantity=units * item.quantity))

    # retirar el grupo de adiciones «Sabor»
    if old_group is not None and not old_group.deleted:
        old_group.deleted = True
        old_group.active = False
        for opt in session.scalars(alive(ModifierOption).where(ModifierOption.group_id == old_group.id)):
            opt.deleted = True
        for link in session.scalars(alive(ProductModifierGroup).where(ProductModifierGroup.group_id == old_group.id)):
            link.deleted = True
    session.flush()
    return True


def seed_catalog(session: Session) -> None:
    for cid, name, parent, color, order in PRODUCT_CATEGORIES:
        _add_missing(session, ProductCategory, cid, name=name, parent_id=parent, color=color, sort_order=order,
                     active=cid != "seed-pc-historicos")
    for cid, name, order in SUPPLY_CATEGORIES:
        _add_missing(session, SupplyCategory, cid, name=name, sort_order=order)
    session.flush()
    _seed_flavor_groups(session)
    for sid, name, cat, unit, pres, qty, pres_cost, min_stock in SUPPLIES:
        unit_cost = pres_cost / qty
        _add_missing(session, Supply, sid, name=name, category_id=cat, unit=unit, presentation_name=pres,
                     presentation_qty=qty, avg_cost=unit_cost, last_cost=unit_cost, min_stock=min_stock)
    for order, row in enumerate(PRODUCTS):
        pid, name, code, cat, kind, price, size, ml, alcohol, active, days, fav = row
        _add_missing(session, Product, pid, name=name, code=code, category_id=cat, kind=kind, price=price,
                     size_label=size, volume_ml=ml, is_alcoholic=alcohol, active=active, available_days=days,
                     favorite=fav, sort_order=order, manual_cost=MANUAL_COSTS.get(pid, 0),
                     track_inventory=kind != ProductKind.SERVICE,
                     notes="Defina qué incluye la promo en Productos > Receta" if pid == "seed-p-promo17" else "")
    for gid, name, mn, mx, ask, order in MODIFIER_GROUPS:
        _add_missing(session, ModifierGroup, gid, name=name, min_select=mn, max_select=mx, ask_on_add=ask, sort_order=order)
    session.flush()
    for order, (oid, gid, name, price, recipe) in enumerate(MODIFIER_OPTIONS):
        if _add_missing(session, ModifierOption, oid, group_id=gid, name=name, price_delta=price, sort_order=order):
            for i, (sid, qty) in enumerate(recipe):
                _add_missing(session, RecipeLine, f"{oid}-r{i}", modifier_option_id=oid, supply_id=sid, quantity=qty)
    for pid, groups in PRODUCT_GROUPS.items():
        for i, gid in enumerate(groups):
            _add_missing(session, ProductModifierGroup, f"{pid}-{gid}", product_id=pid, group_id=gid, sort_order=i)
    for pid, lines in RECIPES.items():
        for i, (ref, qty) in enumerate(lines):
            rid = f"{pid}-r{i}"
            if ref.startswith("prod:"):
                _add_missing(session, RecipeLine, rid, product_id=pid, sub_product_id=ref[5:], quantity=qty)
            elif ref.startswith("grp:"):
                _add_missing(session, RecipeLine, rid, product_id=pid, supply_group_id=ref[4:], quantity=qty)
            else:
                _add_missing(session, RecipeLine, rid, product_id=pid, supply_id=ref, quantity=qty)
    session.flush()
