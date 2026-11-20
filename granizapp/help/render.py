"""Convierte los tutoriales a HTML (pantalla de ayuda, guía impresa y hoja de atajos).

Solo usa el HTML/CSS que entiende el motor de texto de Qt (QTextBrowser / QTextDocument).
"""
from __future__ import annotations

import html
import re
from datetime import date

from granizapp.help.content import Topic

LIGHT = {"text": "#1C1F26", "muted": "#5F6673", "primary": "#5B3BE2", "kbd_bg": "#ECE8FF", "kbd_text": "#2A1F6B",
         "rule": "#D9DCE3", "tip_bg": "#F3F0FF", "head_bg": "#F4F5F8"}
DARK = {"text": "#E7E9EE", "muted": "#A3AAB6", "primary": "#A996FF", "kbd_bg": "#2E2A4D", "kbd_text": "#E4DEFF",
        "rule": "#353945", "tip_bg": "#24213A", "head_bg": "#22252D"}

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_KEY = re.compile(r"`(.+?)`")
_PATH = re.compile(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])")


def inline(text: str, c: dict, links: bool = True) -> str:
    """**negrita**, `tecla` e *Módulo › Pestaña* a HTML (escapando lo demás)."""
    s = html.escape(text, quote=False)
    s = _KEY.sub(lambda m: f'<span style="background-color:{c["kbd_bg"]}; color:{c["kbd_text"]}; '
                           f'font-family:Consolas,monospace; font-weight:600;">&nbsp;{m.group(1)}&nbsp;</span>', s)
    s = _BOLD.sub(r"<b>\1</b>", s)
    s = _PATH.sub(lambda m: f'<span style="color:{c["primary"]}; font-weight:600;">{m.group(1)}</span>', s)
    return s


def topic_html(t: Topic, c: dict | None = None, with_title: bool = True, links: bool = True,
               titles: dict[str, str] | None = None) -> str:
    c = c or LIGHT
    parts = []
    if with_title:
        parts.append(f'<h1 style="color:{c["text"]}; margin-bottom:2px;">{html.escape(t.title)}</h1>')
    parts.append(f'<p style="color:{c["muted"]}; font-size:11pt; margin-top:0;">{inline(t.summary, c)}</p>')
    if t.quick:
        items = "".join(f"<li style='margin-bottom:3px;'>{inline(q, c)}</li>" for q in t.quick)
        parts.append(f'<table width="100%" cellpadding="8" style="background-color:{c["tip_bg"]};">'
                     f'<tr><td><b style="color:{c["primary"]};">Lo esencial</b><ul style="margin-top:4px;">{items}'
                     f'</ul></td></tr></table>')
    for task in t.tasks:
        steps = "".join(f"<li style='margin-bottom:4px;'>{inline(s, c)}</li>" for s in task.steps)
        parts.append(f'<h3 style="color:{c["primary"]}; margin-bottom:2px;">{html.escape(task.title)}</h3>'
                     f'<ol style="margin-top:2px;">{steps}</ol>')
    if t.faq:
        for q, a in t.faq:
            parts.append(f'<p style="margin-bottom:1px;"><b style="color:{c["text"]};">{html.escape(q)}</b></p>'
                         f'<p style="margin-top:0; color:{c["text"]};">{inline(a, c)}</p>')
    if t.keys:
        rows = "".join(
            f'<tr><td style="padding:3px 10px 3px 0;" width="34%">{inline(f"`{k}`", c)}</td>'
            f'<td style="padding:3px 0;">{inline(v, c)}</td></tr>' for k, v in t.keys)
        parts.append(f'<h3 style="color:{c["primary"]}; margin-bottom:2px;">Teclas</h3>'
                     f'<table cellspacing="0" width="100%">{rows}</table>')
    if t.tips:
        tips = "".join(f"<li style='margin-bottom:3px;'>{inline(x, c)}</li>" for x in t.tips)
        parts.append(f'<h3 style="color:{c["primary"]}; margin-bottom:2px;">Consejos</h3><ul>{tips}</ul>')
    if t.related and titles:
        rel = [k for k in t.related if k in titles]
        if rel:
            if links:
                items = " · ".join(f'<a href="topic:{k}" style="color:{c["primary"]};">{html.escape(titles[k])}</a>'
                                   for k in rel)
            else:
                items = " · ".join(html.escape(titles[k]) for k in rel)
            parts.append(f'<p style="color:{c["muted"]};">Ver también: {items}</p>')
    return f'<div style="color:{c["text"]}; font-size:10.5pt;">{"".join(parts)}</div>'


def guide_html(topics: list[Topic], business: str = "", version: str = "") -> str:
    """Guía completa para imprimir o guardar en PDF (colores claros, sin enlaces)."""
    c = LIGHT
    titles = {t.key: t.title for t in topics}
    general = [t for t in topics if t.group == "general"]
    modules = [t for t in topics if t.group != "general"]
    index = "".join(f"<li>{html.escape(t.title)}</li>" for t in general + modules)
    cover = (f'<h1 style="font-size:24pt; color:{c["primary"]}; margin-bottom:0;">Guía de uso de GranizApp</h1>'
             f'<p style="font-size:13pt; color:{c["muted"]}; margin-top:2px;">{html.escape(business)}'
             f'{" · versión " + html.escape(version) if version else ""} · {date.today():%d/%m/%Y}</p>'
             f'<p>Cómo usar cada parte de la aplicación, paso a paso. En la aplicación, <b>F1</b> abre el tutorial del '
             f'módulo en el que esté.</p><h2>Contenido</h2><ol>{index}</ol>')
    body = [cover]
    for t in general + modules:
        body.append('<p style="page-break-before: always;"></p>')
        body.append(topic_html(t, c, with_title=True, links=False, titles=titles))
    return f"<html><body style='font-family:Segoe UI,Arial; color:{c['text']};'>{''.join(body)}</body></html>"


def cheatsheet_html(business: str = "") -> str:
    """Hoja de atajos de una página para pegar junto al computador de la barra."""
    c = LIGHT

    def block(title: str, rows: list[tuple[str, str]]) -> str:
        r = "".join(f'<tr><td width="36%" style="padding:2px 6px 2px 0;">{inline(f"`{k}`", c)}</td>'
                    f'<td style="padding:2px 0;">{inline(v, c)}</td></tr>' for k, v in rows)
        return (f'<p style="margin:10px 0 3px 0; color:{c["primary"]}; font-weight:700; font-size:13pt;">'
                f'{html.escape(title)}</p><table cellspacing="0" width="100%">{r}</table>')

    left = "".join([
        block("Vender (Ctrl+1)", [
            ("cl12 + Enter", "Agregar producto por código"),
            ("3*cl12", "Agregar 3 unidades"),
            ("↑ ↓", "Elegir otro producto encontrado"),
            ("+  −", "Cantidad de la línea"),
            ("Supr", "Quitar la línea"),
            ("Ctrl+↑ ↓", "Cambiar de línea"),
            ("F2", "Adiciones (bolitas, escarchado, sabor)"),
            ("bolit + Enter", "Agregar adición a la línea"),
            ("F3 / F4 / F6", "Cantidad / descuento / nota"),
            ("F5", "Cliente de la venta"),
            ("F8", "Vaciar la venta"),
            ("F10", "Guardar cuenta abierta (mesa)"),
            ("F9", "Ver y retomar cuentas abiertas"),
            ("F11", "Fiar"),
            ("Enter (vacío) o F12", "COBRAR"),
        ]),
        block("Ventana de cobro", [
            ("F1", "Efectivo → escriba lo recibido → ve el cambio"),
            ("F2 / F3", "Nequi / Transferencia"),
            ("F4 / F5", "Daviplata / Tarjeta"),
            ("valor + Enter", "Pago parcial (luego otro medio)"),
            ("F11", "Dejar el saldo fiado"),
            ("Esc", "Volver sin cobrar"),
        ]),
    ])
    right = "".join([
        block("Caja (Ctrl+2)", [
            ("Abrir caja", "Al llegar, con la base contada"),
            ("Ctrl+G", "Gasto pagado con plata del cajón"),
            ("Retiro de efectivo", "Plata a la caja fuerte o al dueño"),
            ("Ctrl+K", "Cerrar caja: contar billetes y dejar base"),
        ]),
        block("Deudores (Ctrl+3)", [
            ("Enter", "Registrar abono del cliente"),
            ("Mensaje de cobro", "Texto listo para WhatsApp"),
        ]),
        block("Otros módulos", [
            ("Ctrl+4", "Historial de ventas (anular)"),
            ("Ctrl+5", "Productos y precios"),
            ("Ctrl+6", "Inventario y conteo"),
            ("Ctrl+7 / Ctrl+8", "Compras / Gastos"),
            ("Ctrl+9 / Ctrl+0", "Reportes / Resumen"),
            ("F1", "Tutorial del módulo actual"),
        ]),
        block("Un turno", [
            ("1", "Ctrl+2 › Abrir caja"),
            ("2", "Ctrl+1 › vender y cobrar"),
            ("3", "Fiados con F11, mesas con F10"),
            ("4", "Gastos de caja con Ctrl+G"),
            ("5", "Ctrl+K › cerrar caja y dejar la base"),
        ]),
    ])
    return (f"<html><body style='font-family:Segoe UI,Arial; font-size:10.5pt; color:{c['text']};'>"
            f'<p style="margin:0;"><span style="font-size:22pt; font-weight:800; color:{c["primary"]};">GranizApp</span>'
            f'<span style="font-size:14pt; color:{c["muted"]};">&nbsp;&nbsp;·&nbsp;&nbsp;Atajos de teclado'
            f'{" · " + html.escape(business) if business else ""}</span></p>'
            f'<table width="100%" cellspacing="0"><tr><td width="50%" valign="top" style="padding-right:14px;">{left}</td>'
            f'<td width="50%" valign="top">{right}</td></tr></table>'
            f'<p style="margin-top:14px; color:{c["muted"]}; font-size:10.5pt;">En los campos de dinero puede escribir '
            f'14000, 14.000 o 14k. En las tablas: escriba para buscar, Enter para abrir, clic derecho para exportar a '
            f'Excel.</p></body></html>')
