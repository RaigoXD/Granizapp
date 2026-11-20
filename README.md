# GranizApp · The Spot

Aplicación de escritorio para manejar un negocio de granizados: **punto de venta pensado para teclado**,
caja con arqueo, **deudores (fiados)**, inventario de insumos con **recetas por vaso**, compras y
proveedores, gastos con categorías contables, cuentas de dinero (caja, Nequi, banco), nómina,
reportes y estado de resultados.

Funciona **sin internet con SQLite** en el computador del bar y se puede **conectar a un Postgres en
línea** (Supabase, Neon, Railway…) para sincronizar varios equipos o trabajar directamente en el servidor.

![Vender](docs/capturas/vender.png)

---

## 1. Instalar y abrir

En este computador ya quedó instalada: **doble clic en el ícono «GranizApp» del escritorio**
(el programa está en `C:\Users\Usuario\GranizApp`, junto con la guía en PDF).

Para instalarla en otro computador:

1. Copie la carpeta `C:\Users\Usuario\GranizApp` (o descomprima `dist/GranizApp-1.3.0-windows.zip`) en una carpeta
   fija, por ejemplo `C:\GranizApp`.
2. Abra `GranizApp.exe` (para el escritorio: clic derecho › *Enviar a* › *Escritorio*).
3. La primera vez aparece un asistente: nombre del negocio, base de caja (por defecto $ 200.000), nombre del equipo y,
   si quiere, un **PIN** para el administrador. Después se muestran los **Primeros pasos**.
4. Deje marcado **«Importar el historial desde los Excel»**: busca automáticamente en *Descargas*
   `Lista de Ventas - The Spot.xlsx` y `Dashboard Balance.xlsx`.

> Si Windows muestra «Windows protegió su PC» (el programa no está firmado):
> *Más información › Ejecutar de todas formas*.

**Actualizar** a una versión nueva = reemplazar la carpeta del programa. Los datos no viven ahí, así que no se pierden.

Dónde quedan los datos:

| Qué | Dónde |
|---|---|
| Base de datos local | `%LOCALAPPDATA%\GranizApp\granizapp.db` |
| Configuración de este equipo | `%LOCALAPPDATA%\GranizApp\config.json` |
| Respaldos automáticos (1 por día) | `Documentos\GranizApp\Respaldos` |
| Registro de errores | `%LOCALAPPDATA%\GranizApp\logs` |

## 2. Ayuda y tutoriales dentro de la app

* Al entrar por primera vez a cada módulo aparece arriba una **guía rápida** con lo esencial
  (se quita con **Ocultar guía**).
* **F1** (o el botón **? Cómo se usa este módulo**, abajo en el menú) abre el **tutorial completo** del módulo en
  el que está: paso a paso, teclas y consejos.
* **Ayuda y tutoriales** (menú *Sistema*) reúne todo: primeros pasos, un día en la barra, todos los atajos,
  preguntas frecuentes, cómo se calculan las cifras y un tutorial por cada módulo, con buscador.
  Desde ahí: **Imprimir o guardar en PDF** la guía completa o la **hoja de atajos de una página** para pegar junto
  al computador, y **Volver a mostrar las guías rápidas**.
* Los mismos documentos están listos en la carpeta del programa y en `docs/`:
  [Guia de uso GranizApp.pdf](docs/Guia%20de%20uso%20GranizApp.pdf) (32 páginas) y
  [Atajos GranizApp.pdf](docs/Atajos%20GranizApp.pdf) (1 página).
* Los cajeros solo ven los tutoriales de los módulos que usan.

![Guía rápida arriba del módulo](docs/capturas/guia_rapida.png)
![Ayuda y tutoriales](docs/capturas/ayuda.png)

## 3. Primeros pasos recomendados

1. **Conteo inicial de inventario** — *Inventario › Conteo físico*: escriba lo que hay (en bolsas, paquetes,
   pacas…). Desde ahí cada venta descuenta según la receta y cada compra suma.
2. **Revisar precios y recetas** — *Productos y adiciones*. Las recetas vienen con cantidades de referencia
   (p. ej. 320 ml de mezcla para un 12 oz). Ajústelas con la calibración real: *Costeo y rendimiento ›
   Rendimiento por bolsa* → «1 bolsa dio N vasos» → *Aplicar a la receta*.
3. **Registrar las compras** con su costo real (*Compras*): el costo promedio de cada insumo se actualiza solo,
   y con él el costo por vaso y el margen.
4. **Crear usuarios con PIN** para el personal (*Configuración › Usuarios*). El rol *Cajero/bartender* solo ve
   Vender, Caja, Deudores, Historial e Inventario.
5. **Definir la «Promo 17K»** (qué incluye) en *Productos › Receta*: hoy no tiene receta y su costo sale en $ 0.

## 4. El día a día en la barra

| Momento | Dónde | Qué hacer |
|---|---|---|
| Al abrir | Caja (Ctrl+2) | **Abrir caja** con la base contada. |
| Cada venta | Vender (Ctrl+1) | Escribir el código (`cl12`) + Enter. `2*corona` agrega 2. Enter con el buscador vacío = **cobrar**. |
| Cobro | Ventana de cobro | **F1** efectivo (escribir lo recibido → muestra el **cambio**), **F2** Nequi, **F3** transferencia… Si paga una parte con cada medio, se registra **pago mixto**. |
| Fiado | Vender | **F11** → elegir o escribir el cliente (se crea al vuelo). |
| Mesa / cliente que sigue pidiendo | Vender | **F10** guardar cuenta abierta · **F9** retomarla. |
| Hielo, bolsas, etc. | Caja | **Gasto de caja** (Ctrl+G): sale del efectivo del cajón. |
| Abono de un deudor | Deudores (Ctrl+3) | Seleccionar y Enter. Se aplica a las deudas más antiguas. |
| Al cerrar | Caja | **Cerrar caja (arqueo)**: contar billetes, ver si sobra o falta, dejar la base y retirar el resto. |

### Atajos de teclado

| Tecla | Acción | | Tecla | Acción |
|---|---|---|---|---|
| Ctrl+1…9, Ctrl+0 | Ir a cada módulo | | F2 | Adiciones de la línea (bolitas, escarchado) |
| `cl12 ny` | Agregar con el sabor (código o nombre del sabor) | | F7 | Cambiar el sabor de la línea |
| ↑ ↓ | Elegir producto encontrado | | F3 / F4 / F6 | Cantidad / descuento / nota |
| `+` / `−` | Subir/bajar cantidad | | F5 | Asignar cliente |
| Supr | Quitar línea | | F8 | Vaciar venta |
| Ctrl+↑ / Ctrl+↓ | Moverse entre líneas | | F9 / F10 | Cuentas abiertas / guardar cuenta |
| Enter (vacío) | Cobrar | | F11 / F12 | Fiar / cobrar |
| F1 | Tutorial del módulo actual | | Clic derecho en tablas | Exportar a Excel |

Escribir el nombre de una adición (p. ej. `bolit`) con una línea seleccionada la agrega a esa línea.

## 5. Módulos

| Sección | Módulo | Para qué |
|---|---|---|
| Operación | **Vender** | Punto de venta, sabor por número o escrito (`cl12 ny`), cobro mixto, cambio, fiado, cuentas abiertas, descuentos, notas. |
| | **Caja** | Turno con base, efectivo esperado en vivo, gastos de caja, retiros/ingresos, arqueo por billetes, historial de cierres. |
| | **Deudores y clientes** | Quién debe y desde cuándo, estado de cuenta, abonos, fiados y abonos por día, mensaje de cobro para WhatsApp, cupo de fiado por cliente. |
| | **Historial de ventas** | Ventas por periodo, detalle, pagos, anulación con motivo (devuelve inventario y dinero). |
| Productos e inventario | **Productos y adiciones** | Productos por categoría (Granizados › Con licor / Sin licor / Cremosos, Cervezas › Micheladas…), precio, código, días de venta (promos lun-jue), adiciones y sus recetas. |
| | **Inventario** | Existencias en presentaciones reales («3,5 bolsas (21.000 ml)»), alertas de mínimo, conteo físico, mermas, kardex, catálogo de insumos. **Sabores**: bolsas por sabor, vasos vendidos, días que alcanzan, pedido sugerido para WhatsApp y compra armada. |
| | **Costeo y rendimiento** | Costo y margen por vaso, desglose por insumo, cuántos vasos rinde cada bolsa, calibración. |
| | **Compras / Proveedores** | Compras que entran al inventario (con envío prorrateado), pagos de contado o a crédito, cuentas por pagar, directorio. |
| Finanzas | **Resumen** | Ventas de hoy y del mes, caja, fiados, gráficos y alertas. |
| | **Gastos** | Por categoría contable, con clasificación automática por palabras clave. |
| | **Cuentas y capital** | Saldos de Caja, Caja fuerte, Nequi, banco; libro por cuenta; transferencias; aportes y retiros de socio; préstamos; ajustes. |
| | **Personal y nómina** | Empleados y pagos (sueldo, horas extra, adelantos, bonos) que quedan como gasto de nómina. |
| | **Reportes** | Productos, categorías, sabores, horas y días, **estado de resultados**, **flujo de caja**, gastos y **comparativo mensual**; todo exportable a Excel. |
| Sistema | **Configuración** | Negocio, equipo, medios de pago, usuarios/PIN, base de datos y sincronización, respaldos, importación. |
| | **Auditoría** | Bitácora inalterable: quién hizo qué, cuándo y desde qué equipo (anulaciones, descuentos, caja y sus diferencias, abonos, ajustes de inventario, cambios de precio, usuarios, PIN fallidos). |
| | **Ayuda y tutoriales** | Tutorial de cada módulo, atajos, preguntas frecuentes; imprimir o guardar la guía en PDF. |

![Auditoría](docs/capturas/auditoria.png)

![Inventario › Sabores](docs/capturas/sabores.png)

![Elegir el sabor al vender](docs/capturas/vender_sabor.png)

## 6. ¿Cómo se calcula la ganancia?

* **Estado de resultados (por recetas)**: Ventas − costo de lo vendido (según las recetas) − mermas = *utilidad bruta*;
  menos nómina, operación (servicios, envíos, publicidad…), impuestos y financieros = *utilidad operacional*.
  Las compras de insumos **no** se restan aquí (ya están en el costo de lo vendido) y las inversiones en equipos van aparte.
* **Resultado de caja**: Ventas − todo lo que salió (insumos, gastos, inversiones). Es la misma cuenta que se llevaba
  en la hoja *Balances* del Excel.

Las categorías de gasto tienen un **tipo contable** (costo, operativo, nómina, inversión, impuestos, financiero) que
define en qué renglón aparecen. Se pueden crear subcategorías y palabras clave en *Gastos › Categorías de gasto*.

## 7. Postgres en línea y varias cajas

En *Configuración › Base de datos y sincronización*:

* **Base local + sincronización (recomendado)**: el bar trabaja siempre en SQLite (rápido, sin depender del
  internet) y cada N minutos sube y baja cambios al Postgres. El dueño puede abrir la app en otro computador
  conectado al mismo servidor y ver todo. Si se cae el internet, se sigue vendiendo y se sincroniza al volver.
* **Postgres directo**: la app trabaja sobre el servidor (requiere internet todo el tiempo).

Para obtener un Postgres gratuito: crear un proyecto en [Supabase](https://supabase.com) o [Neon](https://neon.tech),
copiar la *connection string* (`postgresql://usuario:clave@host:5432/postgres?sslmode=require`), pegarla, **Probar
conexión** y **Guardar**.

Con **dos cajas** cada computador necesita su propio cajón de efectivo: *Configuración › Este equipo › Crear un cajón
nuevo para este equipo*. Los números de venta llevan el código del equipo (`640E-00012`) para no repetirse.

## 8. Respaldos y problemas

Cada día se copia la base local a `Documentos\GranizApp\Respaldos` (se guardan los últimos 30). Se puede respaldar
y restaurar desde *Configuración › Respaldos*. Recomendado: que esa carpeta quede en OneDrive/Google Drive.

`GranizApp.exe --diagnostico` revisa la base de datos, la conexión a Postgres y la ayuda, y deja el resultado en
`%LOCALAPPDATA%\GranizApp\diagnostico.txt`.

Si **ningún administrador recuerda su PIN**: cierre la app, presione `Windows+R` y ejecute
`"C:\Users\Usuario\GranizApp\GranizApp.exe" --restablecer-pin`. Quita el PIN de los administradores (queda
registrado en la bitácora) para que entren y pongan uno nuevo.

## 9. Para desarrolladores

```
granizapp/
  config.py, paths.py            configuración del equipo y rutas
  core/
    models/                      tablas por dominio: catálogo, inventario, ventas, compras, finanzas, personas
    services/                    reglas de negocio sin interfaz (ventas, caja, deudores, inventario, costeo,
                                 compras, finanzas, nómina, reportes, sincronización, importación, semillas)
    db.py, backup.py, export.py  conexión SQLite/Postgres + migraciones, respaldos, Excel
  help/                          tutoriales: content.py (fuente única) y render.py (HTML, guía, hoja de atajos)
  ui/
    modules/                     una pantalla por módulo (registradas en modules/__init__.py)
    widgets/                     tabla genérica, formularios, campos de dinero, gráficos, CRUD
    dialogs.py, main_window.py   diálogos compartidos y ventana principal
    help_ui.py                   guía rápida por módulo, tutorial con F1, imprimir y PDF
tests/                           pruebas (núcleo, interfaz, ayuda, arranque, importación, Postgres)
```

Correr desde el código y probar:

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run.py
.venv\Scripts\python -m pytest tests
```

Las pruebas de Postgres se activan con la variable `GRANIZAPP_TEST_PG` (por ejemplo un contenedor
`docker run -e POSTGRES_PASSWORD=x -p 15433:5432 postgres:16-alpine`). `GRANIZAPP_HOME` permite usar otra carpeta
de datos (pruebas, otra sucursal).

Empaquetar el `.exe`: `.\build.ps1 -Python .venv\Scripts\python.exe` (deja el zip en `dist/`).

Detalles de diseño (modelo de datos, sincronización, cómo agregar un módulo o un campo): [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).
Análisis de los datos importados: [docs/ANALISIS_INICIAL.md](docs/ANALISIS_INICIAL.md).

## 10. Historial de versiones

* **1.3.0** — **Sabores de las bolsas**: cada bolsa de 6 L (con licor, sin licor, cremosa) es un *insumo con
  sabores*; cada sabor tiene su existencia, costo y mínimo. La receta gasta la bolsa y en *Vender* se elige el
  sabor (número en la ventana de sabores, escrito después del código —`cl12 ny`— o `F7`); una promo x2 o
  `3*cl16` puede llevar varios sabores. Nueva pestaña *Inventario › Sabores* (vasos por sabor, bolsas por semana,
  días que alcanzan, pedido sugerido para WhatsApp, compra con el pedido armado, conteo por sabor y reparto de
  bolsas sin sabor) y reporte *Sabores* con vasos, ventas y margen. Lo vendido sin sabor queda en «Sin
  especificar» (opcionalmente se puede exigir el sabor). Al actualizar desde la 1.2 la bolsa genérica pasa a ser
  «Sin especificar» con su existencia y kardex, y las ventas anteriores conservan su sabor.

* **1.2.0** — Módulo **Auditoría**; la bitácora registra además cambios de precio, descuentos, usuarios, ingresos
  (y fallidos) y el equipo desde el que se hizo cada acción. Corregidos: cantidades con punto de miles que se
  leían como decimales (una bolsa de «6.000» ml quedaba en 6 ml al editar el insumo o en la calculadora de
  rendimiento); los reportes por producto y categoría ignoraban los descuentos sobre toda la venta; se podía
  dejar un descuento mayor que la línea, borrar un producto que estaba dentro de una promo o un insumo usado en
  recetas, desactivar al último administrador, darle PIN a un cajero sin que el administrador tuviera uno
  (cualquiera podía entrar como administrador con el PIN vacío) y elegir como cajón una cuenta que no lo era;
  un conteo físico a medio escribir ya no se borra cuando la app se refresca.
* **1.1.0** — Tutoriales en cada módulo, guía rápida, F1, módulo Ayuda, guía y hoja de atajos en PDF,
  `--restablecer-pin`.
* **1.0.0** — Versión inicial.

## 11. Pendiente / ideas siguientes

* Impresión de comprobantes en impresora térmica (58/80 mm).
* Facturación electrónica DIAN (si el negocio la requiere, se integraría con un proveedor tecnológico).
* Vista web o móvil de solo lectura para el dueño (se puede construir sobre el mismo Postgres).
