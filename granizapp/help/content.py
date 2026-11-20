"""Tutoriales de la aplicación: un tema por módulo más temas generales.

Es la única fuente del contenido de ayuda: de aquí salen la guía rápida que aparece al
entrar a cada módulo, el tutorial completo (F1), la sección «Ayuda y tutoriales» y la
guía en PDF para imprimir.

Formato dentro de los textos: **negrita**, `tecla o código` y *Módulo › Pestaña*.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Task:
    title: str
    steps: list[str]


@dataclass
class Topic:
    key: str                      # igual a la clave del módulo (ModuleSpec.key) o un tema general
    title: str
    summary: str
    group: str = "modulo"         # "general" | "modulo"
    quick: list[str] = field(default_factory=list)      # guía rápida (aparece arriba del módulo)
    tasks: list[Task] = field(default_factory=list)     # paso a paso
    faq: list[tuple[str, str]] = field(default_factory=list)  # (pregunta, respuesta)
    keys: list[tuple[str, str]] = field(default_factory=list)  # (tecla, acción)
    tips: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    admin_only: bool = False


# ---------------------------------------------------------------------------------------
# Temas generales
# ---------------------------------------------------------------------------------------
GENERAL: list[Topic] = [
    Topic(
        key="inicio",
        group="general",
        title="Primeros pasos",
        summary="Lo que conviene hacer una sola vez para dejar la aplicación lista, y cómo moverse por ella.",
        tasks=[
            Task("Dejar la app lista (una sola vez)", [
                "Complete el asistente de bienvenida: nombre del negocio, base de caja habitual y, si quiere, "
                "un PIN para el administrador.",
                "Importe el historial de los Excel: *Configuración › Importar Excel › Importar…* (si no lo hizo en "
                "el asistente). La app encuentra sola los archivos en *Descargas*.",
                "Haga el **conteo inicial de inventario**: *Inventario › Conteo físico*. Escriba lo que hay de cada "
                "insumo (en bolsas, paquetes o pacas) y presione **Aplicar conteo**.",
                "Revise **precios y códigos** en *Productos y adiciones*.",
                "Ponga el **saldo real** de Nequi, banco y caja fuerte: *Cuentas y capital › Ajustar saldo real*.",
                "Cree un **usuario con PIN** para cada persona que atiende: *Configuración › Usuarios › Nuevo*.",
                "Defina qué incluye la **Promo 17K**: *Productos y adiciones* › seleccione la promo › "
                "**Receta / costo**.",
                "(Opcional) Conecte un **Postgres en línea** para ver la información desde otro computador: "
                "*Configuración › Base de datos y sincronización*.",
            ]),
            Task("Moverse por la app", [
                "A la izquierda está el menú por secciones. Cada módulo tiene un atajo: `Ctrl+1` Vender, "
                "`Ctrl+2` Caja, `Ctrl+3` Deudores, `Ctrl+4` Historial, `Ctrl+5` Productos, `Ctrl+6` Inventario, "
                "`Ctrl+7` Compras, `Ctrl+8` Gastos, `Ctrl+9` Reportes, `Ctrl+0` Resumen.",
                "`F1` abre el tutorial del módulo en el que está.",
                "Al entrar por primera vez a un módulo aparece una **guía rápida** arriba. Se quita con "
                "**Ocultar guía** y se puede volver a mostrar desde *Ayuda y tutoriales*.",
                "En todas las tablas: escriba en el buscador para filtrar (no importan tildes ni mayúsculas), "
                "use las flechas para moverse, `Enter` para abrir y **clic derecho** para copiar o exportar a Excel.",
                "En los campos de dinero puede escribir `14000`, `14.000` o `14k`.",
            ]),
        ],
        tips=[
            "Todo se guarda al instante: no hay un botón de «guardar» general.",
            "La app funciona sin internet. Cada día hace sola un respaldo de los datos.",
            "Las acciones delicadas (anulaciones, ajustes, cierres de caja) quedan registradas con el usuario que "
            "las hizo.",
        ],
        related=["dia", "atajos", "faq"],
    ),
    Topic(
        key="dia",
        group="general",
        title="Un día en la barra",
        summary="El recorrido completo de un turno, desde que se abre la caja hasta el cierre.",
        tasks=[
            Task("Al llegar", [
                "Abra la app con doble clic en el ícono **GranizApp** del escritorio.",
                "Si pide PIN, elija su nombre y escriba su PIN.",
                "Vaya a *Caja* (`Ctrl+2`) › **Abrir caja**. Cuente el efectivo del cajón y escriba la base.",
            ]),
            Task("Durante el turno", [
                "Venda en *Vender* (`Ctrl+1`): escriba el código (`cl12`) y `Enter`; la app pregunta el sabor "
                "(número del sabor). Más rápido: `cl12 ny` ya lleva el sabor. Con el buscador vacío, `Enter` cobra.",
                "En el cobro: `F1` efectivo (escriba lo que le entregan y verá el cambio), `F2` Nequi, "
                "`F3` transferencia.",
                "Si alguien pide fiado: `F11` y el nombre del cliente.",
                "Si una mesa sigue pidiendo: `F10` guarda la cuenta con un nombre y `F9` la vuelve a abrir.",
                "Si compra hielo o algo pequeño con plata del cajón: *Caja* › **Gasto de caja** (`Ctrl+G`).",
                "Si un deudor paga: *Deudores* (`Ctrl+3`) › seleccionarlo › `Enter`.",
            ]),
            Task("Al cerrar", [
                "Cobre o guarde las cuentas abiertas (`F9` en *Vender* muestra cuáles quedan).",
                "*Caja* › **Cerrar caja (arqueo)** (`Ctrl+K`).",
                "Cuente billetes y monedas en las casillas: la app dice si cuadra, sobra o falta.",
                "Deje la base para el próximo turno; el resto pasa a la caja fuerte (o a la cuenta que elija).",
                "Una vez por semana: *Inventario › Sabores* › **Contar sabores** y **Copiar pedido para WhatsApp**.",
                "Cierre la app. El respaldo del día se hace solo.",
            ]),
        ],
        tips=[
            "Si la caja no cuadra, revise en *Caja* los movimientos del turno: los gastos sin registrar y las "
            "ventas cobradas con el medio equivocado son las causas más comunes.",
            "Lo que se cobra por Nequi o transferencia no entra al cajón: aparece en «Cobrado por otros medios».",
        ],
        related=["pos", "cash", "debtors"],
    ),
    Topic(
        key="atajos",
        group="general",
        title="Atajos de teclado",
        summary="Todo se puede hacer con el teclado. Estas son las teclas más útiles.",
        keys=[
            ("Ctrl+1 … Ctrl+9, Ctrl+0", "Ir a cada módulo (Vender, Caja, Deudores, Historial, Productos, "
                                        "Inventario, Compras, Gastos, Reportes, Resumen)"),
            ("F1", "Tutorial del módulo actual"),
            ("código + Enter", "Vender: agregar el producto (ej. `cl12`)"),
            ("código + sabor", "Vender: agregar con el sabor ya elegido (ej. `cl12 ny`, `sl9 chicle`)"),
            ("3*código", "Vender: agregar varias unidades (ej. `3*cl12`)"),
            ("↑ ↓ (Shift = saltar fila)", "Vender: elegir entre los productos encontrados"),
            ("Enter con el buscador vacío", "Vender: cobrar"),
            ("+  /  −", "Vender: subir o bajar la cantidad de la línea seleccionada"),
            ("Ctrl+↑  /  Ctrl+↓", "Vender: cambiar de línea seleccionada"),
            ("Supr", "Vender: quitar la línea · Tablas: eliminar el registro"),
            ("F2", "Vender: adiciones de la línea (bolitas, escarchado)"),
            ("F7", "Vender: cambiar el sabor de la línea"),
            ("F3 / F4 / F6", "Vender: cantidad exacta / descuento / nota de la línea"),
            ("F5", "Vender: asignar cliente a la venta"),
            ("F8", "Vender: vaciar la venta"),
            ("F9 / F10", "Vender: ver cuentas abiertas / guardar la venta como cuenta abierta"),
            ("F11", "Vender: fiar (queda en Deudores) · Cobro: dejar el saldo fiado"),
            ("F12", "Vender: cobrar"),
            ("F1 … F6 en el cobro", "Elegir medio de pago (Efectivo, Nequi, Transferencia…)"),
            ("1 … 9 / Espacio", "Ventana de adiciones: marcar o desmarcar opciones"),
            ("1 … 9 / 0 / letras", "Ventana de sabores: elegir el sabor / sin especificar / buscar por código"),
            ("Ctrl+G / Ctrl+K", "Caja: gasto de caja / cerrar caja"),
            ("Ctrl+A", "Deudores: registrar abono"),
            ("Ctrl+N", "Crear nuevo (producto, cliente, compra, gasto, proveedor…)"),
            ("Ctrl+R", "Productos: receta y costo del producto"),
            ("Enter", "Tablas: abrir o editar el registro seleccionado"),
            ("Ctrl+C / clic derecho", "Tablas: copiar la fila / exportar a Excel"),
            ("Esc", "Cerrar una ventana sin guardar · Vender: borrar lo escrito en el buscador"),
        ],
        related=["pos"],
    ),
    Topic(
        key="faq",
        group="general",
        title="Preguntas frecuentes y problemas",
        summary="Soluciones rápidas a lo que más suele pasar.",
        faq=[
            ("Me equivoqué en una venta que ya cobré",
             "*Historial de ventas* › selecciónela › **Anular venta…** y escriba el motivo. Vuelven el inventario y el "
             "dinero; luego véndala bien. Solo un administrador puede anular."),
            ("Cobré con el medio de pago equivocado",
             "Anule la venta en *Historial de ventas* y vuelva a cobrarla con el medio correcto."),
            ("La caja no cuadra al cerrar",
             "Revise en *Caja* los movimientos del turno. Lo más común: un gasto pagado con plata del cajón que no se "
             "registró (use **Gasto de caja**), una venta en efectivo registrada como Nequi o al revés, o plata que se "
             "sacó sin registrar el **Retiro de efectivo**. La diferencia queda anotada en el cierre."),
            ("Un cliente pagó solo una parte de lo que debe",
             "*Deudores* › selecciónelo › **Registrar abono** con el valor que pagó. El resto sigue pendiente."),
            ("Un cliente paga una parte y fía el resto en el momento de comprar",
             "En el cobro escriba en «Valor de este pago» lo que paga, `Enter`, y luego `F11` para dejar el resto fiado."),
            ("El inventario dice «Agotado» o sale negativo y sí hay",
             "Falta el conteo inicial o hay compras sin registrar. Haga *Inventario › Conteo físico* y registre las "
             "compras en *Compras*."),
            ("¿Qué es «Sin especificar» en los sabores?",
             "Es donde va la mezcla de los vasos que se vendieron sin elegir el sabor. Si queda negativa, los sabores "
             "muestran más bolsas de las que hay: haga *Inventario › Sabores* › **Contar sabores** (deje «Sin "
             "especificar» en 0) y se corrige. Para que no pase, elija siempre el sabor; en *Configuración › Negocio* "
             "se puede volver obligatorio."),
            ("Llegó un sabor nuevo",
             "*Inventario › Sabores* › **Nuevo sabor**: nombre, código corto (ej. `MAR` para vender con `cl12 mar`), "
             "costo de la bolsa y mínimo. Desde ese momento aparece en *Vender*."),
            ("Un producto sale con costo $ 0 o margen de 100 %",
             "No tiene receta. *Productos y adiciones* › selecciónelo › **Receta / costo** y agregue los insumos."),
            ("Se fue el internet o la luz",
             "La app no necesita internet y lo registrado ya quedó guardado. Si usa sincronización con Postgres, se pone "
             "al día sola cuando vuelva la conexión."),
            ("¿Dónde están mis datos? ¿Hay copia de seguridad?",
             "La app guarda una copia cada día en *Documentos › GranizApp › Respaldos* (las últimas 30). Desde "
             "*Configuración › Respaldos* puede hacer una copia en el momento o restaurar una."),
            ("Quiero usar la app en otro computador",
             "Copie la carpeta del programa a ese computador. Para que los dos vean la misma información, conéctelos a "
             "un Postgres en *Configuración › Base de datos y sincronización*."),
            ("Olvidé mi PIN",
             "Un administrador lo cambia o lo quita en *Configuración › Usuarios* (**Editar** o **Quitar PIN**)."),
            ("La pantalla se ve muy clara de noche",
             "*Configuración › Negocio › Tema de este equipo › Oscuro*."),
        ],
        related=["dia", "atajos"],
    ),
    Topic(
        key="cifras",
        group="general",
        title="Cómo se calculan las cifras",
        summary="Qué significa cada número de los reportes y de dónde sale.",
        admin_only=True,
        faq=[
            ("Costo por vaso",
             "Suma de los insumos de la receta × su **costo promedio**. El costo promedio se actualiza con cada compra "
             "registrada (si compra más caro, sube; si compra más barato, baja)."),
            ("Utilidad bruta",
             "Ventas − costo de lo vendido (según las recetas) − mermas y diferencias de inventario."),
            ("Utilidad operacional (estado de resultados)",
             "Utilidad bruta − nómina − gastos de operación (servicios, arriendo, envíos, publicidad…) − impuestos y "
             "gastos financieros. Las compras de insumos no se restan aquí porque ya están en el costo de lo vendido; "
             "las inversiones en equipos van aparte."),
            ("Resultado de caja",
             "Ventas + otros ingresos − todo lo que se pagó (insumos, gastos e inversiones). Es la cuenta de la hoja "
             "«Balances» del Excel: dice cuánta plata quedó, aunque haya inventario guardado."),
            ("Efectivo que debe haber en la caja",
             "Base + ventas en efectivo + abonos en efectivo − gastos de caja − retiros + ingresos (± anulaciones)."),
            ("Fiado del periodo",
             "Lo que quedó sin pagar en las ventas del periodo (lo que se abonó después aparece en «Abonos»)."),
            ("Tipo contable de los gastos",
             "Cada categoría de gasto tiene un tipo (costo, operativo, nómina, inversión, impuestos, financiero) que "
             "decide en qué renglón del estado de resultados aparece. Se cambia en *Gastos › Categorías de gasto*."),
        ],
        related=["reports", "costing", "expenses"],
    ),
]


# ---------------------------------------------------------------------------------------
# Un tema por módulo (la clave es la misma del módulo)
# ---------------------------------------------------------------------------------------
MODULES: list[Topic] = [
    Topic(
        key="pos",
        title="Vender",
        summary="Registrar ventas rápido con el teclado: agregar productos y adiciones, cobrar con uno o varios medios "
                "de pago, fiar y manejar cuentas abiertas (mesas).",
        quick=[
            "Escriba el código o el nombre (ej. `cl12`) y `Enter` para agregar. `2*cl12` agrega dos.",
            "Sabor: escríbalo después del código (`cl12 ny`) o elíjalo con su número en la ventana que aparece; "
            "`0` = sin especificar · `F7` lo cambia.",
            "`Enter` con el buscador vacío cobra: `F1` efectivo (muestra el cambio), `F2` Nequi, `F3` transferencia.",
            "`F11` fía la venta a un cliente · `F10` guarda una cuenta abierta (mesa) · `F9` la retoma.",
            "`F2` adiciones de la línea (bolitas, escarchado) · `+` / `−` cantidad · `Supr` quita la línea.",
        ],
        tasks=[
            Task("Agregar productos", [
                "Escriba en el buscador el código (`cl12`, `sl9`, `cor`, `corm`) o parte del nombre (`soda sab`).",
                "El primer producto encontrado queda resaltado; con `↑` `↓` elige otro (`Shift` salta de fila).",
                "Presione `Enter` para agregarlo. Para varias unidades escriba la cantidad y un asterisco: `3*cl12`.",
                "Con el mouse: haga clic en la ficha del producto. Los botones de categoría (Granizados, Cervezas…) "
                "filtran las fichas; «Todos» muestra los favoritos.",
            ]),
            Task("Elegir el sabor", [
                "Al agregar un granizado aparece la ventana de sabores con lo que queda de cada uno (en bolsas).",
                "Presione el número del sabor (`1` a `9`), o escriba sus letras (`ny`, `tij`) y `Enter`. `0` = sin "
                "especificar; `Esc` cancela.",
                "Más rápido: escriba el sabor después del código, `cl12 ny` o `cl12 nueva`, y `Enter`: se agrega sin "
                "preguntar. El sabor se ve en verde debajo del buscador.",
                "Varios vasos en una línea (`3*cl16`) o una promo x2: cada número es un vaso (`1` `2` `2` = uno de "
                "Habana y dos de Ibiza); al completar se acepta solo. `Retroceso` quita el último.",
                "Para cambiar el sabor de una línea: selecciónela y `F7`.",
                "Cada sabor descuenta su propia bolsa del inventario; por eso conviene elegirlo siempre.",
            ]),
            Task("Corregir la cuenta", [
                "Con el buscador vacío, `+` y `−` suben o bajan la cantidad de la línea seleccionada.",
                "`Ctrl+↑` / `Ctrl+↓` cambian la línea seleccionada; `Supr` la quita.",
                "`F3` escribe una cantidad exacta, `F4` aplica un descuento (a la línea o a toda la venta) y `F6` agrega "
                "una nota (ej. «sin hielo»).",
                "`F8` vacía toda la venta.",
            ]),
            Task("Agregar adiciones (bolitas, escarchado)", [
                "Seleccione la línea del granizado y presione `F2`.",
                "Marque las opciones con los números `1` a `9` o con `Espacio`, y `Enter` para aceptar.",
                "Atajo: con la línea seleccionada, escriba parte del nombre de la adición (`bolit`, `tajin`, `chamoy`) y "
                "`Enter`: se agrega a esa línea.",
                "El precio extra de cada adición se suma solo al total.",
            ]),
            Task("Cobrar", [
                "Presione `Enter` con el buscador vacío (o `F12`). Si la caja está cerrada, la app ofrece abrirla.",
                "Elija el medio de pago: `F1` Efectivo, `F2` Nequi, `F3` Transferencia / Bre-B, `F4` Daviplata, "
                "`F5` Tarjeta (el orden se cambia en *Configuración › Medios de pago*).",
                "En efectivo, escriba lo que le entregan en «Recibido» (ej. `50k`) y `Enter`: la app muestra el **cambio**.",
                "Si dejan el valor exacto, solo presione `Enter`.",
                "Al terminar, arriba de los botones aparece un aviso verde con el número de la venta y el cambio.",
            ]),
            Task("Pago con dos medios (mixto)", [
                "En la ventana de cobro elija el primer medio (ej. `F2` Nequi).",
                "En «Valor de este pago» escriba solo lo que se paga por ese medio y `Enter`.",
                "La ventana sigue abierta con lo que falta: elija el otro medio (ej. `F1` Efectivo) y `Enter`.",
            ]),
            Task("Fiar", [
                "Con los productos en la cuenta presione `F11`.",
                "Busque al cliente escribiendo su nombre; si no existe, escriba el nombre completo y `Enter` para crearlo.",
                "Confirme: la app muestra cuánto debía y cuánto quedará debiendo.",
                "Si paga una parte: cobre normalmente, escriba lo que paga y luego `F11` en la ventana de cobro para "
                "dejar el resto fiado.",
                "Lo fiado queda en *Deudores y clientes*.",
            ]),
            Task("Cuentas abiertas (mesas o clientes que siguen pidiendo)", [
                "Agregue lo que pidieron y presione `F10`. Escriba un nombre (ej. «Mesa 3» o «Raigo») y `Enter`.",
                "La venta queda guardada sin cobrar y la pantalla queda libre para seguir vendiendo.",
                "Para volver a ella: `F9`, elija la cuenta y `Enter`. Agregue lo nuevo y vuelva a `F10`, o cobre.",
                "Para borrar una cuenta que no se va a cobrar: `F9` › **Descartar cuenta…** (pide motivo).",
            ]),
        ],
        keys=[
            ("Enter", "Agregar el producto resaltado · con el buscador vacío: cobrar"),
            ("↑ ↓", "Elegir producto encontrado"),
            ("+ / −", "Cantidad de la línea"),
            ("Supr", "Quitar la línea"),
            ("F2", "Adiciones"),
            ("F7", "Sabor de la línea"),
            ("F3 / F4 / F6", "Cantidad / descuento / nota"),
            ("F5", "Cliente de la venta"),
            ("F8", "Vaciar la venta"),
            ("F9 / F10", "Cuentas abiertas / guardar cuenta"),
            ("F11", "Fiar"),
            ("F12", "Cobrar"),
            ("Esc", "Borrar lo escrito en el buscador"),
        ],
        tips=[
            "Use códigos cortos y fáciles de recordar (se cambian en *Productos y adiciones*).",
            "Si escribe algo que no existe, el texto queda seleccionado: escriba de nuevo y se reemplaza.",
            "Las promociones con días (ej. Promo 17K de lunes a jueves) avisan si se venden otro día.",
            "Cada venta descuenta del inventario los insumos de su receta (mezcla del sabor elegido, vaso, "
            "pitillo, sticker…).",
        ],
        related=["cash", "debtors", "sales", "catalog"],
    ),
    Topic(
        key="cash",
        title="Caja",
        summary="Controlar el efectivo del cajón en cada turno: base, gastos pagados con la caja, retiros y arqueo al "
                "cerrar.",
        quick=[
            "Al empezar el turno: **Abrir caja** y escriba la base que contó.",
            "**Gasto de caja** (`Ctrl+G`) para lo que se paga con plata del cajón (hielo, bolsas, domicilios).",
            "Arriba ve en vivo el **efectivo que debe haber** en el cajón.",
            "Al terminar: **Cerrar caja (arqueo)** (`Ctrl+K`), cuente billetes y deje la base.",
        ],
        tasks=[
            Task("Abrir la caja", [
                "Presione **Abrir caja**.",
                "Cuente el efectivo del cajón y escriba la base (la app sugiere lo que quedó en el último cierre).",
                "Presione **Abrir caja**. Si lo contado no coincide con lo que debía haber, la diferencia queda anotada.",
            ]),
            Task("Registrar un gasto pagado con plata de la caja", [
                "Presione **Gasto de caja** (`Ctrl+G`).",
                "Escriba la descripción (ej. «Hielo x2»), el valor y la categoría.",
                "Guarde: el valor sale del efectivo esperado y queda en *Gastos*.",
            ]),
            Task("Sacar o meter efectivo", [
                "**Retiro de efectivo**: para guardar plata en la caja fuerte o llevarla al banco. Elija la cuenta de "
                "destino (ej. «Efectivo guardado (caja fuerte)»).",
                "Si la plata es para el dueño, marque «Es retiro/aporte del socio» (no cuenta como gasto).",
                "**Ingreso de efectivo**: cuando se mete sencillo o plata de otra cuenta.",
            ]),
            Task("Cerrar la caja (arqueo)", [
                "Cobre o guarde las cuentas abiertas; si quedan, la app avisa.",
                "Presione **Cerrar caja (arqueo)** (`Ctrl+K`).",
                "Escriba cuántos billetes y monedas hay de cada denominación (o el total en «Efectivo contado»).",
                "La app compara con lo que «Debería haber» y muestra si cuadra, sobra o falta.",
                "En «Dejar de base para el próximo turno» deje la base (por defecto la habitual); el resto se retira a "
                "la cuenta elegida en «Llevar el retiro a».",
                "Escriba notas si hace falta y presione **Cerrar caja**.",
            ]),
            Task("Revisar cierres anteriores", [
                "Pestaña **Historial de cierres**: base, esperado, contado, diferencia y retiro de cada turno.",
                "`Enter` o doble clic sobre un cierre muestra el detalle (ventas por medio de pago, conteo de billetes).",
            ]),
        ],
        keys=[("Ctrl+G", "Gasto de caja"), ("Ctrl+K", "Cerrar caja")],
        tips=[
            "Lo cobrado por Nequi, transferencia o tarjeta no entra al cajón: aparece en «Cobrado por otros medios».",
            "Cada computador tiene su propio turno de caja. Si tiene dos cajas, cree un cajón para cada una en "
            "*Configuración › Este equipo*.",
            "Las anulaciones de ventas en efectivo restan del turno abierto.",
        ],
        related=["dia", "pos", "finance"],
    ),
    Topic(
        key="debtors",
        title="Deudores y clientes",
        summary="Saber quién debe, cuánto y desde cuándo; registrar abonos y cobrar.",
        quick=[
            "La lista muestra quién debe, cuánto y hace cuántos días (naranja más de 7, rojo más de 15).",
            "Seleccione un cliente y presione `Enter` para registrar un abono.",
            "**Mensaje de cobro** copia un texto listo para pegar en WhatsApp.",
            "Los fiados se hacen desde *Vender* con `F11`.",
        ],
        tasks=[
            Task("Registrar un abono", [
                "En la pestaña **Deudores** seleccione al cliente.",
                "Presione `Enter` (o **Registrar abono**, `Ctrl+A`).",
                "Escriba el valor (por defecto, todo lo que debe) y el medio de pago.",
                "Presione **Registrar abono**. Se aplica a las deudas más antiguas primero.",
            ]),
            Task("Ver el estado de cuenta", [
                "Al seleccionar un deudor, a la derecha aparecen sus compras fiadas y sus abonos con el saldo.",
                "**Exportar estado de cuenta** lo guarda en Excel para enviarlo.",
                "Para anular un abono equivocado: seleccione la fila «Abono», `Enter`, confirme y escriba el motivo.",
            ]),
            Task("Cobrar por WhatsApp", [
                "Seleccione el deudor y presione **Mensaje de cobro**.",
                "Abra el chat del cliente en WhatsApp y pegue (`Ctrl+V`).",
            ]),
            Task("Ver lo fiado y abonado en un día", [
                "Pestaña **Fiados y abonos por día** y elija la fecha.",
            ]),
            Task("Administrar clientes", [
                "Pestaña **Clientes**: **Nuevo** (`Ctrl+N`), **Editar** (`Enter`), **Eliminar** (`Supr`).",
                "«Cupo máximo de fiado»: si el cliente lo supera, la venta fiada se bloquea (un administrador puede "
                "autorizarla). 0 = sin límite.",
                "Un cliente que debe no se puede eliminar; desmarque «Activo» para ocultarlo.",
            ]),
        ],
        keys=[("Enter / Ctrl+A", "Registrar abono"), ("Ctrl+N", "Nuevo cliente (pestaña Clientes)")],
        tips=["Revise cada semana los deudores en rojo (más de 15 días) y envíeles el mensaje de cobro."],
        related=["pos", "sales"],
    ),
    Topic(
        key="sales",
        title="Historial de ventas",
        summary="Buscar cualquier venta, ver qué se vendió y cómo se pagó, y anular ventas equivocadas.",
        quick=[
            "Elija el periodo y el estado (pagadas, con saldo, anuladas o cuentas abiertas).",
            "Seleccione una venta para ver productos, costo, margen y pagos.",
            "**Anular venta…** devuelve el inventario y el dinero (solo administrador, pide motivo).",
        ],
        tasks=[
            Task("Buscar una venta", [
                "Elija el periodo (Hoy, Ayer, Esta semana, Este mes…) o «Personalizado…» con fechas.",
                "Filtre por estado si hace falta.",
                "Escriba en el buscador el número de venta, el cliente o el nombre de la cuenta.",
            ]),
            Task("Anular una venta", [
                "Seleccione la venta y presione **Anular venta…** (solo administradores).",
                "Confirme y escriba el motivo.",
                "Vuelve el inventario; el dinero se reversa (si fue en efectivo, sale del turno de caja abierto).",
                "Si fue un error al cobrar, vuelva a hacer la venta correctamente en *Vender*.",
            ]),
        ],
        tips=[
            "Las ventas importadas del Excel dicen «(Excel)» y no se pueden anular.",
            "Arriba se ven el total vendido, el número de ventas, el ticket promedio y el saldo pendiente del periodo.",
        ],
        related=["pos", "reports"],
    ),
    Topic(
        key="catalog",
        title="Productos y adiciones",
        summary="Lo que se vende: productos, precios, códigos, categorías, adiciones y la receta (insumos que gasta "
                "cada uno).",
        admin_only=True,
        quick=[
            "Seleccione un producto y `Enter` para cambiar precio, código o categoría.",
            "**Receta / costo** (`Ctrl+R`): qué insumos gasta cada vaso y cuánto deja.",
            "Pestaña *Adiciones y modificadores*: bolitas, escarchado y su precio extra. Los sabores de las "
            "bolsas están en *Inventario › Sabores*.",
            "Desmarque «Activo» para ocultar un producto sin perder su historial.",
        ],
        tasks=[
            Task("Cambiar un precio", [
                "Seleccione el producto (puede buscarlo arriba) y presione `Enter`.",
                "Cambie «Precio de venta» y presione **Guardar**. Las ventas anteriores conservan su precio.",
            ]),
            Task("Crear un producto", [
                "Presione **Nuevo producto** (`Ctrl+N`).",
                "Escriba nombre, un código corto (ej. `CL20`), categoría, tipo y precio.",
                "Tipos: **Preparado** (granizados, micheladas), **Reventa** (cerveza, agua), **Combo / Promo** (incluye "
                "otros productos), **Adición** y **Servicio** (sin inventario).",
                "Marque los días de venta (promos solo algunos días), si contiene licor y si debe aparecer como favorito.",
                "Marque qué adiciones se le pueden agregar y presione **Guardar**. La app ofrece definir la receta.",
            ]),
            Task("Definir la receta (costo por vaso)", [
                "Seleccione el producto y presione **Receta / costo** (`Ctrl+R`).",
                "**Agregar línea**, elija el insumo y escriba la cantidad que gasta UNA unidad vendida (ml, g o und). "
                "Ej.: 320 ml de mezcla, 1 vaso de 12 oz, 1 pitillo, 1 sticker.",
                "Para la mezcla elija «Mezcla granizado con licor (bolsa 6 L) · sabor al vender»: así el sabor se "
                "pregunta en *Vender* y cada sabor descuenta su bolsa. Elija un sabor fijo solo si el producto "
                "siempre lleva ese sabor.",
                "Para combos agregue productos («Producto: Granizado CL 12 oz» × 2).",
                "Abajo ve el costo, el margen y cuántos vasos rinde cada bolsa. Presione **Guardar receta**.",
                "**Calibrar**: si sabe que una bolsa le rindió 18 vasos, la app calcula la cantidad por vaso.",
            ]),
            Task("Duplicar u ocultar", [
                "**Duplicar** copia el producto con su receta (útil para crear otro tamaño).",
                "Para que no salga en la venta, desmarque «Activo»; para que no salga entre las fichas sin buscarlo, "
                "desmarque «favorito». «Ver inactivos» los muestra de nuevo.",
            ]),
            Task("Categorías", [
                "Pestaña **Categorías**: nombre, «Dentro de» (para subcategorías como Granizados › Con licor), color "
                "(el borde de la ficha en *Vender*) y orden.",
            ]),
            Task("Adiciones y modificadores", [
                "Pestaña **Adiciones y modificadores**. A la izquierda los grupos (Adiciones, Escarchado).",
                "En cada grupo: «Máximo a elegir» (1 = solo una, como el escarchado), «Mínimo obligatorio» (1 = obligatorio) "
                "y «Abrir automáticamente al vender».",
                "A la derecha las opciones con su precio extra. **Receta de la opción** define el insumo que gasta "
                "(ej. Bolitas explosivas = 30 g).",
                "**Asignar a productos…** marca a qué productos aplica el grupo.",
            ]),
        ],
        keys=[("Ctrl+N", "Nuevo producto"), ("Enter", "Editar"), ("Ctrl+R", "Receta / costo")],
        tips=[
            "Los márgenes en rojo (menos de 40 %) merecen revisión de precio o receta.",
            "Las cantidades de las recetas iniciales son de referencia: ajústelas con la calibración real.",
        ],
        related=["costing", "inventory", "pos"],
    ),
    Topic(
        key="inventory",
        title="Inventario",
        summary="Cuánto queda de cada insumo (bolsas de mezcla, perlas, sales, vasos, cervezas), con alertas, conteos "
                "y mermas.",
        quick=[
            "Existencias en bolsas, paquetes o pacas, con alerta cuando algo se está acabando.",
            "*Sabores*: cuántas bolsas quedan de cada sabor, cuántos vasos se venden, cuántos días alcanzan y qué "
            "pedir.",
            "*Conteo físico*: escriba lo que contó y **Aplicar conteo** (al empezar y cada semana).",
            "**Merma / daño** para lo que se perdió, se dañó o se regaló.",
            "Las ventas descuentan solas; las compras (en *Compras*) suman.",
        ],
        tasks=[
            Task("Sabores de las bolsas", [
                "Pestaña **Sabores**. Arriba elija la bolsa (con licor, sin licor, cremosa) y el periodo.",
                "Por sabor: existencia, mínimo, vasos vendidos, bolsas por semana, días que alcanza y **Pedir** "
                "(lo que cubre las semanas elegidas al ritmo de venta, y nunca menos que el mínimo).",
                "**Nuevo sabor**: nombre, código para vender (`NY` → `cl12 ny`), costo de la bolsa, mínimo y lo que "
                "hay hoy. `Enter` sobre un sabor lo edita; desmárquelo como activo cuando ya no lo venda.",
                "**Copiar pedido para WhatsApp**: copia el pedido sugerido; péguelo en el chat del proveedor "
                "(`Ctrl+V`).",
                "**Registrar compra del pedido**: abre *Nueva compra* con los sabores y cantidades ya puestos; "
                "ajuste lo que llegó y el valor.",
            ]),
            Task("Contar los sabores", [
                "**Contar sabores** muestra todos los sabores de la bolsa con lo que dice el sistema.",
                "Cuente las bolsas físicas y escriba cuántas hay de cada sabor (`2,5` = dos y media).",
                "Deje «Sin especificar» en 0: toda bolsa física tiene sabor. Así se corrige lo que se vendió sin "
                "elegir sabor.",
                "La app muestra las diferencias antes de aplicarlas.",
            ]),
            Task("Bolsas sin sabor (al empezar a manejar sabores)", [
                "Las bolsas que había antes quedan en «Sin especificar». **Repartir bolsas sin sabor**: escriba "
                "cuántas son de cada sabor. No es merma: solo cambian de sabor.",
            ]),
            Task("Otra bolsa con sabores", [
                "**Nuevo insumo con sabores** (ej. una base frutal de 5 L): nombre, unidad, presentación y contenido.",
                "Agregue sus sabores y póngala en la receta de los productos (*Productos › Receta*).",
            ]),
            Task("Hacer el conteo físico", [
                "Pestaña **Conteo físico**.",
                "En «Contado» escriba lo que hay en la presentación indicada; acepta decimales (`2,5` bolsas).",
                "Deje vacío lo que no contó y presione **Aplicar conteo**.",
                "La diferencia contra el sistema queda registrada como sobrante o merma.",
                "Para un solo insumo: en *Existencias* selecciónelo y presione **Contar este insumo**.",
            ]),
            Task("Registrar una merma o daño", [
                "Presione **Merma / daño**, elija el insumo y la cantidad en unidad base (ml, g o und) y el motivo.",
            ]),
            Task("Entrada o ajuste manual", [
                "**Entrada o ajuste manual**: positivo suma, negativo resta. Para compras use mejor *Compras*.",
            ]),
            Task("Ver los movimientos (kardex)", [
                "Pestaña **Kardex**: elija periodo, insumo y tipo de movimiento (venta, compra, conteo, merma…).",
            ]),
            Task("Crear o editar insumos (administrador)", [
                "Pestaña **Insumos** › **Nuevo** (`Ctrl+N`).",
                "Unidad base: ml para líquidos, g para polvos y perlas, und para vasos y botellas.",
                "Presentación de compra y su contenido: bolsa = 6000 ml; paquete x50 = 50 und.",
                "Costo de una presentación (se actualiza solo con las compras), mínimo para la alerta y proveedor.",
            ]),
        ],
        tips=[
            "Cuente cada semana lo más caro (bolsas de mezcla, perlas, cerveza) para detectar pérdidas a tiempo.",
            "Si algo sale negativo, falta el conteo inicial o hay compras sin registrar.",
            "«Sin especificar» negativo = vasos vendidos sin elegir sabor: se corrige con **Contar sabores**.",
        ],
        related=["purchases", "costing", "catalog"],
    ),
    Topic(
        key="costing",
        title="Costeo y rendimiento",
        summary="Cuánto cuesta cada vaso, cuánto deja y cuántos vasos rinde cada bolsa.",
        admin_only=True,
        quick=[
            "Costo y margen de cada producto (verde: bien · naranja: revisar · rojo: deja poco).",
            "*Rendimiento por bolsa*: cuántos vasos salen de cada bolsa.",
            "Cuando se acabe una bolsa, cuente los vasos que dio y use **Aplicar cantidad a la receta**.",
        ],
        tasks=[
            Task("Revisar márgenes", [
                "Pestaña **Costo por producto**: precio, costo, ganancia por unidad y margen.",
                "Al seleccionar un producto, abajo aparece el desglose por insumo.",
                "`Enter` abre la receta para corregirla.",
            ]),
            Task("Calibrar con el rendimiento real", [
                "Cuando se termine una bolsa, cuente cuántos vasos salieron de ella.",
                "Pestaña **Rendimiento por bolsa** › elija el insumo (ej. «Mezcla granizado con licor»).",
                "En «Rendimiento real: 1 bolsa dio» escriba los vasos, elija el producto en «Aplicar a la receta de» y "
                "presione **Aplicar cantidad a la receta**.",
            ]),
            Task("Calculadora teórica", [
                "Escriba el volumen de la bolsa, el tamaño del vaso (oz) y qué tan lleno se sirve: muestra los vasos "
                "teóricos.",
            ]),
            Task("Costo de las adiciones", [
                "Pestaña **Adiciones**: cobro extra, costo y ganancia. Las que no cobran (ej. escarchado incluido) "
                "muestran cuánto cuesta regalarlas.",
            ]),
        ],
        tips=["Los costos se actualizan solos con cada compra registrada."],
        related=["catalog", "purchases", "cifras"],
    ),
    Topic(
        key="purchases",
        title="Compras",
        summary="Registrar lo que se compra a proveedores: entra al inventario, actualiza el costo de las recetas y, "
                "si quedó debiendo, queda en cuentas por pagar.",
        admin_only=True,
        quick=[
            "**Nueva compra** (`Ctrl+N`): proveedor, insumos, cantidades, valor y envío.",
            "Lo comprado entra al inventario y actualiza el costo de las recetas.",
            "Si quedó debiendo, aparece en *Cuentas por pagar*; `Enter` para registrar el pago.",
        ],
        tasks=[
            Task("Registrar una compra", [
                "Presione **Nueva compra** (`Ctrl+N`).",
                "Elija el proveedor (o **+ Proveedor** para crearlo), la fecha y el número de factura si lo hay.",
                "En cada línea: insumo, cantidad en presentaciones (ej. `10` bolsas) y el valor total de esa línea. "
                "**Agregar insumo** para más líneas.",
                "Escriba el **envío / flete**: se reparte en el costo de los insumos.",
                "«Pagado ahora»: lo que pagó (por defecto todo). Si quedó debiendo, escriba menos o 0 y elija «Vence».",
                "«Pagado desde»: de dónde salió la plata (Caja registradora si fue del cajón, Nequi, banco…).",
                "Presione **Registrar compra**.",
            ]),
            Task("Pagar una compra a crédito", [
                "Pestaña **Cuentas por pagar** › seleccione la factura › `Enter`.",
                "Escriba el valor y la cuenta desde la que paga.",
            ]),
            Task("Anular una compra", [
                "Seleccione la compra › **Anular compra** y escriba el motivo: sale del inventario lo que había entrado "
                "y se reversan los pagos.",
            ]),
        ],
        keys=[("Ctrl+N", "Nueva compra"), ("Enter", "Pagar (en Cuentas por pagar)")],
        tips=[
            "No registre la misma compra también como gasto: se contaría doble. Compras = insumos que van al "
            "inventario; *Gastos* = todo lo demás.",
            "Las bolsas de mezcla se compran por sabor («… · Tijuana», «… · Nueva York»). Desde *Inventario › "
            "Sabores* › **Registrar compra del pedido** la compra queda armada.",
        ],
        related=["suppliers", "inventory", "expenses"],
    ),
    Topic(
        key="suppliers",
        title="Proveedores",
        summary="Directorio de proveedores con su historial de compras y lo que se les debe.",
        admin_only=True,
        quick=[
            "**Nuevo** (`Ctrl+N`) para agregar un proveedor: teléfono, ciudad y qué le compra.",
            "A la derecha: historial de compras y cuánto se le debe.",
        ],
        tasks=[
            Task("Agregar o editar un proveedor", [
                "**Nuevo** (`Ctrl+N`) o seleccione uno y `Enter`.",
                "Datos: nombre, NIT, contacto, teléfono/WhatsApp, ciudad, qué le compramos y condiciones de pago.",
            ]),
        ],
        tips=["Un proveedor al que se le debe no se puede eliminar; desmárquelo como «Activo»."],
        related=["purchases"],
    ),
    Topic(
        key="dashboard",
        title="Resumen",
        summary="Cómo va el día y el mes de un vistazo, y qué requiere atención.",
        admin_only=True,
        quick=[
            "Ventas, caja, fiados y gastos de hoy y del mes de un vistazo.",
            "*Atención* lista lo que hay que resolver: insumos agotados, deudores viejos, facturas vencidas.",
        ],
        tasks=[
            Task("Leer el resumen", [
                "**Hoy**: ventas (comparadas con ayer), número de ventas, ticket promedio, efectivo que debe haber en la "
                "caja, total por cobrar y gastos del día.",
                "**Este mes**: ventas, utilidad bruta, gastos, resultado de caja y cuentas por pagar.",
                "Gráficos: ventas de los últimos 30 días y promedio por día de la semana.",
                "**Atención**: avisos para resolver (caja abierta hace mucho, insumos por agotarse, deudores de más de "
                "15 días, facturas vencidas, productos sin receta).",
            ]),
        ],
        related=["reports", "cifras"],
    ),
    Topic(
        key="expenses",
        title="Gastos",
        summary="Todo lo que sale y no es compra de inventario: nómina, servicios, arriendo, envíos, publicidad, "
                "mantenimiento y equipos.",
        admin_only=True,
        quick=[
            "**Nuevo gasto** (`Ctrl+N`): descripción, valor y de dónde salió la plata.",
            "Deje la categoría en «Clasificar automáticamente» y la app la elige por la descripción.",
            "`Enter` para editar · **Anular** devuelve la plata a la cuenta.",
            "Compras de insumos van en *Compras*; gastos de caja durante el turno, en *Caja*.",
        ],
        tasks=[
            Task("Registrar un gasto", [
                "Presione **Nuevo gasto** (`Ctrl+N`).",
                "Escriba la descripción (ej. «Pago energía») y el valor.",
                "Categoría: elija una o deje «Clasificar automáticamente» («hielo» → Hielo, «energía» → Servicios…).",
                "«Pagado desde»: la cuenta de donde salió la plata, o «No mover dinero» si no quiere afectar saldos.",
                "Opcional: proveedor, empleado (si es nómina) y número de factura. Presione **Guardar**.",
            ]),
            Task("Corregir o anular", [
                "`Enter` sobre un gasto para editarlo (queda registro del cambio).",
                "**Anular** lo quita de los reportes y devuelve la plata a la cuenta.",
            ]),
            Task("Categorías de gasto", [
                "Pestaña **Categorías de gasto**: cree subcategorías, elija el **tipo contable** (define el renglón del "
                "estado de resultados) y escriba palabras clave para la clasificación automática.",
            ]),
        ],
        keys=[("Ctrl+N", "Nuevo gasto"), ("Enter", "Editar")],
        tips=[
            "La nómina se registra mejor desde *Personal y nómina* (queda asociada al empleado).",
            "Equipos y muebles (máquina, mesas, ventilador) van en «Equipos y mobiliario»: son inversión y no "
            "afectan la utilidad operacional.",
        ],
        related=["cash", "staff", "cifras"],
    ),
    Topic(
        key="finance",
        title="Cuentas y capital",
        summary="Dónde está la plata (caja, caja fuerte, Nequi, banco, Daviplata) y los movimientos entre cuentas y "
                "con los dueños.",
        admin_only=True,
        quick=[
            "Saldos de Caja, Caja fuerte, Nequi, banco y Daviplata, con su libro de movimientos.",
            "**Transferir entre cuentas** (ej. consignar el efectivo en el banco).",
            "**Aporte de capital** / **Retiro de socio** para la plata del dueño (no son ventas ni gastos).",
            "**Ajustar saldo real** para cuadrar con el extracto.",
        ],
        tasks=[
            Task("Ver saldos y movimientos", [
                "Seleccione una cuenta: a la derecha aparece su libro con el saldo después de cada movimiento.",
                "Elija el periodo para ver movimientos anteriores.",
            ]),
            Task("Transferir", [
                "**Transferir entre cuentas**: elija origen, destino y valor (ej. de «Efectivo guardado» a «Cuenta "
                "bancaria» al consignar).",
            ]),
            Task("Plata del dueño y otros ingresos", [
                "**Aporte de capital**: plata que pone el dueño.",
                "**Retiro de socio**: plata que el dueño saca para él (no es un gasto del negocio).",
                "**Otro ingreso**: eventos u otros ingresos que no son ventas del día.",
                "**Préstamo**: dinero prestado que entra.",
            ]),
            Task("Cuadrar con el extracto", [
                "Seleccione la cuenta › **Ajustar saldo real** › escriba el saldo que muestra Nequi o el banco.",
                "Hágalo el primer día para cargar los saldos iniciales.",
            ]),
            Task("Crear cuentas", [
                "**Nueva cuenta**: nombre, tipo (efectivo, banco, billetera) y saldo inicial.",
                "Marque «Es el cajón de una caja registradora» solo para el efectivo de un mostrador.",
            ]),
        ],
        tips=["Los saldos se calculan con lo registrado en la app; por eso conviene cuadrarlos de vez en cuando."],
        related=["cash", "expenses"],
    ),
    Topic(
        key="staff",
        title="Personal y nómina",
        summary="Empleados y sus pagos (sueldo, horas extra, adelantos, bonificaciones), que quedan como gasto de "
                "nómina.",
        admin_only=True,
        quick=[
            "Agregue a cada empleado con su forma y valor de pago.",
            "**Registrar pago**: sueldo, horas extra, adelanto o bono (queda como gasto de nómina).",
        ],
        tasks=[
            Task("Agregar un empleado", [
                "**Nuevo** (`Ctrl+N`): nombre, cargo, forma de pago (quincenal, semanal, por turno…), valor por periodo "
                "y valor de la hora extra.",
            ]),
            Task("Registrar un pago", [
                "Seleccione al empleado › **Registrar pago**.",
                "Elija el concepto (Sueldo / turno, Horas extra, Adelanto, Bonificación / propina, Seguridad social), "
                "el valor, la cuenta desde la que paga y la fecha.",
                "A la derecha ve los pagos del periodo elegido.",
            ]),
        ],
        tips=["Para que un empleado use la app con PIN, créele un usuario en *Configuración › Usuarios*."],
        related=["expenses", "settings"],
    ),
    Topic(
        key="reports",
        title="Reportes",
        summary="Cómo va el negocio en cualquier periodo: ventas, productos, horas, ganancias, flujo de caja y "
                "comparativo mensual.",
        admin_only=True,
        quick=[
            "Elija el periodo arriba; cada pestaña es un reporte.",
            "*Estado de resultados*: cuánto se ganó · *Flujo de caja*: cuánta plata entró y salió.",
            "**Exportar todo a Excel** o clic derecho en cualquier tabla.",
        ],
        tasks=[
            Task("Las pestañas", [
                "**Resumen**: ventas, ticket promedio, utilidad bruta, margen, fiado, abonos, gastos y resultado de caja; "
                "gráfico por día y cobro por medio de pago.",
                "**Productos** y **Categorías**: qué se vende más y cuánto deja.",
                "**Sabores**: vasos, ventas y margen de cada sabor (una promo con dos sabores se reparte entre "
                "ellos; «Sin especificar» = vendidos sin elegir sabor).",
                "**Adiciones**: las adiciones y escarchados más pedidos.",
                "**Horas y días**: a qué horas y qué días se vende más.",
                "**Estado de resultados**: ventas − costo − gastos = utilidad.",
                "**Flujo de caja**: entradas y salidas de dinero del periodo.",
                "**Gastos por categoría** y **Comparativo mensual** (mes a mes desde el inicio).",
            ]),
            Task("Exportar", [
                "**Exportar todo a Excel** guarda todos los reportes del periodo en un archivo.",
                "Clic derecho en cualquier tabla › **Exportar tabla a Excel…**.",
            ]),
        ],
        tips=["Las ventas importadas del Excel no tienen hora; el reporte por horas usa solo las registradas en caja."],
        related=["cifras", "dashboard"],
    ),
    Topic(
        key="settings",
        title="Configuración",
        summary="Datos del negocio, este computador, medios de pago, usuarios, base de datos, respaldos e importación.",
        admin_only=True,
        quick=[
            "*Negocio*: nombre, base de caja habitual y tema claro u oscuro.",
            "*Usuarios*: cree un usuario con PIN para cada persona.",
            "*Medios de pago*: el orden define las teclas F1, F2… del cobro.",
            "*Base de datos*: conexión a Postgres en línea · *Respaldos*: copias de seguridad.",
        ],
        tasks=[
            Task("Negocio", [
                "Nombre, NIT, teléfono, dirección, base de caja habitual y tema (claro u oscuro) de este equipo.",
                "**Sabores**: «Exigir el sabor al vender» quita la opción «Sin especificar». «Pedido sugerido de "
                "bolsas»: cuántas semanas de venta cubre el pedido de *Inventario › Sabores*.",
            ]),
            Task("Usuarios y PIN", [
                "**Nuevo**: nombre, rol (*Administrador* ve todo; *Cajero / bartender* solo ve Vender, Caja, Deudores, "
                "Historial, Inventario y Ayuda) y un PIN de 4 a 8 números.",
                "Cuando existe al menos un PIN, la app pide ingreso al abrir. **Cambiar usuario** está abajo en el menú.",
                "**Quitar PIN** deja a ese usuario sin clave.",
                "Si ningún administrador recuerda su PIN: cierre la app, presione `Windows+R` y ejecute "
                "`\"C:\\Users\\Usuario\\GranizApp\\GranizApp.exe\" --restablecer-pin` (use la ruta donde esté el "
                "programa). Quita el PIN de los administradores y queda registrado.",
            ]),
            Task("Medios de pago", [
                "Cada medio dice a qué cuenta llega el dinero y si es efectivo (entra al cajón y calcula cambio).",
                "«Orden en la ventana de cobro» define la tecla: el primero es `F1`, el segundo `F2`, y así.",
            ]),
            Task("Este equipo", [
                "Nombre del equipo y su código (va en el número de cada venta).",
                "Si tiene dos cajas, **Crear un cajón nuevo para este equipo** en el segundo computador.",
            ]),
            Task("Base de datos y sincronización (Postgres)", [
                "Cree un Postgres gratuito (Supabase o Neon) y copie la «connection string».",
                "Péguela en «URL de Postgres», **Probar conexión** y **Guardar**.",
                "Recomendado: dejar «Base local» y marcar «Sincronizar automáticamente»; la barra funciona sin internet "
                "y los datos suben cuando hay conexión. **Sincronizar ahora** lo hace en el momento.",
                "«Directamente en el servidor» exige internet todo el tiempo; se aplica al reiniciar la app.",
            ]),
            Task("Respaldos", [
                "Se hace una copia diaria en *Documentos › GranizApp › Respaldos*. Cambie la carpeta si quiere guardarla "
                "en OneDrive o una USB.",
                "**Respaldar ahora** hace una copia en el momento; **Restaurar el seleccionado…** vuelve a una copia "
                "(la app se cierra).",
            ]),
            Task("Importar Excel", [
                "**Importar…** trae el historial de ventas y gastos de los Excel anteriores; reimportar reemplaza lo "
                "importado antes. **Borrar lo importado** lo quita.",
            ]),
        ],
        related=["inicio", "faq"],
    ),
    Topic(
        key="audit",
        title="Auditoría",
        summary="La bitácora de la aplicación: quién hizo cada acción delicada, cuándo y desde qué equipo. "
                "No se puede editar ni borrar.",
        admin_only=True,
        quick=[
            "Registra anulaciones, descuentos, aperturas y cierres de caja (con sus diferencias), abonos, "
            "ajustes de inventario, cambios de precio, cambios de usuarios e ingresos con PIN incorrecto.",
            "Filtre por periodo, usuario y tipo; escriba en el buscador para encontrar una venta o un motivo.",
            "Arriba: cuántas anulaciones, descuentos, cierres descuadrados y PIN fallidos hubo en el periodo.",
        ],
        tasks=[
            Task("Revisar el turno de ayer", [
                "Elija el periodo **Ayer** y el tipo **Caja**: verá la apertura, el cierre y si sobró o faltó.",
                "Cambie a **Ventas** para ver anulaciones y descuentos, con el motivo que escribió el cajero.",
                "`Enter` sobre una fila muestra el detalle completo.",
            ]),
            Task("Ver qué hizo un usuario", [
                "Elija el usuario en la lista. Para que cada quien aparezca con su nombre, cada persona debe "
                "entrar con su propio usuario y PIN (*Configuración › Usuarios*).",
            ]),
            Task("Señales de alerta", [
                "**Cierres con diferencia** en rojo: faltó plata al cerrar (el valor es la suma del periodo).",
                "**PIN incorrecto** repetido: alguien intenta entrar con un usuario que no es el suyo.",
                "Muchas **anulaciones** o **descuentos** del mismo cajero: revise los motivos.",
                "**Ajustes de inventario** frecuentes: puede haber merma o porciones más grandes de lo costeado.",
            ]),
        ],
        tips=[
            "La columna «Equipo» es el código del computador (*Configuración › Este equipo*): útil con dos cajas.",
            "Clic derecho en la tabla exporta la bitácora a Excel.",
        ],
        related=["cash", "sales", "settings"],
    ),
    Topic(
        key="help",
        title="Ayuda y tutoriales",
        summary="Todos los tutoriales de la aplicación en un solo lugar, para leer en pantalla o imprimir.",
        tasks=[
            Task("Usar la ayuda", [
                "A la izquierda están los temas; escriba en el buscador para encontrar una palabra (ej. «fiar»).",
                "En cualquier módulo, `F1` abre su tutorial.",
                "**Imprimir guía…** o **Guardar guía en PDF…** para tenerla en papel; **Hoja de atajos** es una sola "
                "página para pegar junto al computador.",
                "**Volver a mostrar las guías rápidas** hace que reaparezcan las instrucciones de arriba de cada módulo.",
            ]),
        ],
        related=["inicio", "atajos"],
    ),
]

ALL: list[Topic] = GENERAL + MODULES
BY_KEY: dict[str, Topic] = {t.key: t for t in ALL}


def topic(key: str) -> Topic | None:
    return BY_KEY.get(key)


def visible_topics(is_admin: bool, allowed_modules: set[str] | None = None) -> list[Topic]:
    """Temas que puede ver un usuario (los cajeros no ven los de módulos de administración)."""
    out = []
    for t in ALL:
        if t.admin_only and not is_admin:
            continue
        if t.group == "modulo" and allowed_modules is not None and t.key not in allowed_modules:
            continue
        out.append(t)
    return out
