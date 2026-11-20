"""Módulos de la aplicación. Cada uno es independiente y se carga al abrirlo por primera vez.

Agregar un módulo = una línea aquí + un archivo en esta carpeta con su página.
"""
from __future__ import annotations

from importlib import import_module

from granizapp.ui.registry import ADMIN_ONLY, ModuleSpec


def _lazy(module: str, cls: str):
    def factory(ctx):
        return getattr(import_module(f"granizapp.ui.modules.{module}"), cls)(ctx)

    return factory


MODULES: list[ModuleSpec] = [
    # OPERACIÓN
    ModuleSpec("pos", "Vender", "OPERACIÓN", _lazy("pos", "PosPage"), "Ctrl+1",
               description="Punto de venta: cobrar, fiar y cuentas abiertas"),
    ModuleSpec("cash", "Caja", "OPERACIÓN", _lazy("cash", "CashPage"), "Ctrl+2",
               description="Apertura, gastos de caja, retiros y cierre con arqueo"),
    ModuleSpec("debtors", "Deudores y clientes", "OPERACIÓN", _lazy("debtors", "DebtorsPage"), "Ctrl+3",
               description="Quién debe, fiados del día, abonos y estado de cuenta"),
    ModuleSpec("sales", "Historial de ventas", "OPERACIÓN", _lazy("sales_history", "SalesHistoryPage"), "Ctrl+4",
               description="Ventas por fecha, detalle y anulaciones"),
    # PRODUCTOS E INVENTARIO
    ModuleSpec("catalog", "Productos y adiciones", "PRODUCTOS E INVENTARIO", _lazy("catalog", "CatalogPage"), "Ctrl+5",
               ADMIN_ONLY, "Productos, precios, categorías, adiciones y recetas"),
    ModuleSpec("inventory", "Inventario", "PRODUCTOS E INVENTARIO", _lazy("inventory", "InventoryPage"), "Ctrl+6",
               description="Existencias de insumos, conteos, mermas y kardex"),
    ModuleSpec("costing", "Costeo y rendimiento", "PRODUCTOS E INVENTARIO", _lazy("costing", "CostingPage"), "",
               ADMIN_ONLY, "Costo por vaso, márgenes y cuántos vasos rinde cada bolsa"),
    ModuleSpec("purchases", "Compras", "PRODUCTOS E INVENTARIO", _lazy("purchases", "PurchasesPage"), "Ctrl+7",
               ADMIN_ONLY, "Compras de insumos y cuentas por pagar"),
    ModuleSpec("suppliers", "Proveedores", "PRODUCTOS E INVENTARIO", _lazy("suppliers", "SuppliersPage"), "",
               ADMIN_ONLY, "Directorio de proveedores e historial de compras"),
    # FINANZAS
    ModuleSpec("dashboard", "Resumen", "FINANZAS", _lazy("dashboard", "DashboardPage"), "Ctrl+0",
               ADMIN_ONLY, "Indicadores del día y del mes, alertas"),
    ModuleSpec("expenses", "Gastos", "FINANZAS", _lazy("expenses", "ExpensesPage"), "Ctrl+8",
               ADMIN_ONLY, "Gastos por categoría contable"),
    ModuleSpec("finance", "Cuentas y capital", "FINANZAS", _lazy("finance", "FinancePage"), "",
               ADMIN_ONLY, "Saldos de Caja, Nequi y bancos; transferencias, aportes y retiros"),
    ModuleSpec("staff", "Personal y nómina", "FINANZAS", _lazy("staff", "StaffPage"), "",
               ADMIN_ONLY, "Empleados y pagos"),
    ModuleSpec("reports", "Reportes", "FINANZAS", _lazy("reports", "ReportsPage"), "Ctrl+9",
               ADMIN_ONLY, "Estado de resultados, flujo de caja, productos, horas y comparativo mensual"),
    # SISTEMA
    ModuleSpec("settings", "Configuración", "SISTEMA", _lazy("settings", "SettingsPage"), "",
               ADMIN_ONLY, "Negocio, equipo, medios de pago, usuarios, base de datos, respaldos e importación"),
    ModuleSpec("audit", "Auditoría", "SISTEMA", _lazy("audit", "AuditPage"), "",
               ADMIN_ONLY, "Bitácora: quién hizo qué y cuándo (anulaciones, descuentos, caja, precios, usuarios)"),
    ModuleSpec("help", "Ayuda y tutoriales", "SISTEMA", _lazy("help", "HelpPage"), "",
               description="Tutoriales de cada módulo, atajos, preguntas frecuentes, guía para imprimir"),
]
