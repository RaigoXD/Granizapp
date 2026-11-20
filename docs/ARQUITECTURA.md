# Arquitectura de GranizApp

## Capas

```
ui/modules/*  ──►  core/services/*  ──►  core/models/*  ──►  SQLAlchemy  ──►  SQLite | Postgres
(pantallas)        (reglas de negocio)    (tablas)
```

* **Modelos** (`core/models`): solo estructura. Un archivo por dominio.
* **Servicios** (`core/services`): toda la lógica (cobrar, abonar, cerrar caja, costear, importar…). Reciben una
  sesión de base de datos y un `Actor` (usuario + equipo). No saben nada de Qt, así que se prueban sin interfaz
  y servirían igual para una API web o una app móvil.
* **Interfaz** (`ui`): cada módulo es una `Page` registrada en `ui/modules/__init__.py`; la barra lateral, los
  atajos Ctrl+N y los permisos por rol salen de ese registro. Las pantallas se avisan cambios con un bus de
  eventos (`ctx.notify(Topics.SALES)`) y se refrescan solas cuando se muestran.

## Modelo de datos por dominio

| Dominio | Tablas | Notas |
|---|---|---|
| Catálogo | `product_categories` (jerárquica), `products`, `modifier_groups`, `modifier_options`, `product_modifier_groups`, `recipe_lines` | Una receta pertenece a un producto o a una opción de adición; puede consumir un insumo, un **insumo con sabores** (`supply_group_id`: el sabor se elige al vender) o **otro producto** (combos/promos). |
| Inventario | `supply_categories`, `supply_groups`, `supplies`, `stock_movements` | Unidad base (ml, g, und) + presentación de compra (bolsa de 6.000 ml). La existencia es la **suma del kardex**; el costo es promedio ponderado. Un `supply_group` (bolsa con sabores) agrupa insumos variante (`supplies.group_id`, `variant_name`, `variant_code`); su `default_supply_id` («Sin especificar») recibe lo vendido sin sabor. |
| Ventas | `sales`, `sale_items`, `sale_item_modifiers` (adiciones y **sabores**: `supply_id` + `quantity` = vasos de ese sabor), `payments`, `payment_methods`, `customers` | Una venta abierta es una «cuenta abierta». El saldo `total − paid` > 0 es fiado. Un abono se reparte en pagos a las ventas más antiguas (`group_id`). |
| Compras | `suppliers`, `purchases`, `purchase_items`, `supplier_payments` | El envío se prorratea en el costo unitario. Saldo pendiente = cuenta por pagar. |
| Finanzas | `accounts`, `account_movements`, `expense_categories` (con tipo contable), `expenses`, `financial_entries`, `cash_sessions` | `account_movements` es el **libro único de dinero**: cada cobro, abono, gasto, pago a proveedor, transferencia o aporte escribe una fila con signo. |
| Personas/sistema | `employees`, `users` (PIN con PBKDF2), `settings` (clave = id), `audit_log` | La bitácora guarda anulaciones, descuentos, ajustes, cierres de caja, cambios de precio, usuarios e ingresos, con el equipo que lo hizo. |

Principios:

* **Nada se borra físicamente** (`deleted = true`) y **nada se edita en silencio**: anular o corregir genera
  asientos contrarios (inventario y dinero), así la caja de ayer no cambia por una anulación de hoy.
* **Dinero en pesos enteros** (COP no usa centavos en la práctica); cantidades de insumo en `float`.
* **Hora de negocio** local de Colombia (sin zona); `updated_at` en UTC para sincronizar.

## Caja

`cash_sessions` por equipo. Efectivo esperado = base + movimientos del cajón asociados al turno
(ventas y abonos en efectivo, gastos de caja, retiros/ingresos, anulaciones). La diferencia del arqueo se registra
como ajuste; el retiro al cierre es una transferencia a otra cuenta (p. ej. caja fuerte) hecha **después** de
cerrar, así no altera el arqueo y el cajón queda con la base del día siguiente.

## Sincronización SQLite ↔ Postgres

Cada tabla tiene: `id` UUID (texto), `updated_at` (UTC), `deleted`, `dirty` (pendiente de subir) y `rev`.

1. **Subir**: filas locales con `dirty = true`; en el servidor gana la versión con `updated_at` más reciente.
2. **Bajar**: filas con `rev` mayor al último visto. `rev` lo pone un **trigger de Postgres** con una secuencia
   (`granizapp_rev_seq`), así no depende de los relojes de los PCs. Se revisan con solapamiento las últimas
   revisiones por si una transacción confirmó tarde.
3. Si el servidor rechazó una fila por tener una versión más nueva, se descarga esa versión.
4. Solo se limpia `dirty` en filas que no cambiaron mientras se sincronizaba.

Los datos semilla tienen ids fijos (`seed-…`) y fecha antigua: un equipo nuevo no duplica categorías ni pisa lo
que el dueño cambió en otro equipo. Inventario y dinero son movimientos (no saldos), por eso dos cajas vendiendo
a la vez no se pisan. Las llaves foráneas son `DEFERRABLE INITIALLY DEFERRED` para poder insertar en cualquier orden.

## Cómo extender

**Nuevo módulo** (p. ej. «Eventos»):
1. Modelos en `core/models/eventos.py` (heredar de `Entity`) e importarlos en `core/models/__init__.py`.
2. Servicio en `core/services/eventos.py`.
3. Pantalla `ui/modules/eventos.py` con `class EventosPage(Page)`; para catálogos simples `CrudPanel` resuelve
   lista + formulario en pocas líneas.
4. Una línea en `ui/modules/__init__.py` (`ModuleSpec(...)`) con sección, atajo y roles.

**Tutorial del módulo nuevo** (obligatorio, lo exige una prueba): agregar un `Topic` con la misma clave del módulo
en `granizapp/help/content.py` (resumen, `quick` para la guía rápida, `tasks` paso a paso, teclas y consejos).
Con eso aparece la guía rápida al entrar, F1 abre el tutorial, sale en *Ayuda y tutoriales* y en la guía PDF.

**Nuevo campo en una tabla existente**:
1. Agregarlo al modelo.
2. Subir `SCHEMA_VERSION` en `core/db.py` y registrar una migración con `add_column(conn, "tabla", Column(...))`.
   Se aplica sola al abrir la app (también en el servidor Postgres al sincronizar).

**Nuevo medio de pago / cuenta / categoría**: desde la propia app (Configuración, Cuentas y capital, Gastos).

## Pruebas

* `tests/test_core.py`: venta, inventario, fiado/abono, cupo, cuentas abiertas, anulación, cierre de caja,
  compras y costo promedio, conteo, gastos, nómina.
* `tests/test_import.py`: importador con Excel sintéticos y mapeo de productos viejos.
* `tests/test_ui.py`, `tests/test_ui_flows.py`: interfaz sin pantalla con teclado real (F1, F11, números),
  cobro mixto, fiado, cierre de caja, abono, compra, gasto, cambio de tema.
* `tests/test_postgres.py`: modo Postgres directo y dos cajas sincronizando (requiere `GRANIZAPP_TEST_PG`).
* `tests/test_help.py`: cada módulo tiene tutorial y guía rápida, F1, búsqueda, enlaces, PDF de 1 página, Ctrl+N
  al entrar a un módulo.
* `tests/test_boot.py`: arranque real en un proceso aparte (asistente, PIN, bienvenida y cierre sin errores).
* `tests/test_invariants.py`: **simulación aleatoria** de varios días (ventas, fiados, abonos, anulaciones,
  gastos, compras, conteos, cierres) con 4 semillas, verificando tras cada operación que cajón = efectivo
  esperado, pagado = pagos, deudores cuadran, anulaciones netas en cero y reportes = tablas. Es la primera
  prueba que conviene ampliar cuando se agregue una operación nueva que mueva dinero o inventario.
* `tests/test_utils.py`: formatos de dinero/cantidades de ida y vuelta (lo que se muestra se vuelve a leer igual).
* `tests/test_audit.py`: migración de esquema (v1 → v2), eventos de bitácora y pantalla de Auditoría.
* `tests/test_flavors.py` y `tests/test_flavors_ui.py`: sabores (consumo, costo, promos con dos sabores, cuentas
  abiertas, pedido sugerido, conteo y reparto sin merma, migración de una base real de la 1.2) y su interfaz.

## Sabores (insumos con variantes)

* `RecipeBook` resuelve las líneas de grupo con `choices = {grupo: {sabor: proporción}}` (`CartLine.choices`,
  una elección por vaso: promo x2 Tijuana + Nueva York = mitad y mitad). Sin elección va al predeterminado y se
  costea con el promedio de los sabores (`group_cost`). `group_units(producto)` = vasos del grupo por unidad.
* Al cobrar, `_write_flavors` deja una fila por elección con sus vasos (y «Sin especificar» si no se eligió):
  los reportes por sabor y `inventory.flavor_stats` (ritmo, días que alcanza, pedido sugerido) salen de ahí y del
  kardex. `require_flavor` (configuración) exige elegir.
* Migración desde la 1.2 (`seed.migrate_flavors`, una sola vez): la bolsa genérica se vuelve «Sin especificar»
  del grupo (mismo id: conserva existencia y kardex), las recetas pasan al grupo, las ventas con la opción
  «Sabor» quedan con el sabor real y el grupo de adiciones «Sabor» se retira. La prueba usa una base real de la
  1.2 (`tests/fixtures/granizapp_v1_2.db`).

## Bitácora (Auditoría)

`common.audit(session, actor, acción, entidad, id, detalle)` escribe en `audit_log` (usuario, equipo, UTC).
Las acciones y sus etiquetas/grupos viven en `core/services/audit.py` (`ACTIONS`); al agregar una acción nueva,
registrarla ahí para que la pantalla la muestre con nombre y la cuente en los indicadores.

## Lecciones de Qt que conviene respetar

* No usar `installEventFilter` en widgets hijos: al destruir la ventana Qt puede llamar a un filtro a medio
  destruir. Las teclas se atienden con `KeyLineEdit` / `KeyTableView` (`ui/widgets/keys.py`).
* No re-pintar con `w.setStyle(w.style())` (se cae al cambiar el tema): usar `repolish(w)`.
* No mostrar (`setVisible(True)`) un widget antes de meterlo en su layout: se abre un instante como ventana suelta
  y le roba el foco a la principal.
* Las llamadas diferidas a un widget van con contexto: `QTimer.singleShot(0, w, w.metodo)`, así Qt las descarta
  si el widget ya no existe.
* Al salir, `close_windows()` destruye las ventanas mientras Qt sigue vivo.
