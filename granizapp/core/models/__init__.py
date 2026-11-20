"""Modelos de datos, agrupados por dominio. Importar este paquete registra todas las tablas."""
from granizapp.core.models.base import Base, Entity, local_now, new_id, synced_tables, utcnow
from granizapp.core.models.catalog import (
    ModifierGroup,
    ModifierOption,
    Product,
    ProductCategory,
    ProductKind,
    ProductModifierGroup,
    RecipeLine,
)
from granizapp.core.models.finance import (
    Account,
    AccountKind,
    AccountMovement,
    CashSession,
    CashSessionStatus,
    Expense,
    ExpenseCategory,
    ExpenseType,
    FinancialEntry,
    MoneyKind,
)
from granizapp.core.models.inventory import MovementKind, StockMovement, Supply, SupplyCategory, SupplyGroup, Unit
from granizapp.core.models.people import AuditLog, Employee, PayType, Role, Setting, User
from granizapp.core.models.purchasing import (
    Purchase,
    PurchaseItem,
    PurchaseStatus,
    Supplier,
    SupplierPayment,
)
from granizapp.core.models.sales import (
    Customer,
    Payment,
    PaymentKind,
    PaymentMethod,
    Sale,
    SaleItem,
    SaleItemModifier,
    SaleStatus,
)

__all__ = [name for name in dir() if not name.startswith("_")]
