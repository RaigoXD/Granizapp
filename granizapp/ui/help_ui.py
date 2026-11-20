"""Ayuda dentro de la app: guía rápida arriba de cada módulo, tutorial con F1, impresión y PDF."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QMarginsF, Qt, QUrl, Signal
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from granizapp.help import render
from granizapp.help.content import BY_KEY, Topic, topic
from granizapp.ui import theme


def colors() -> dict:
    return render.DARK if theme.is_dark() else render.LIGHT


def titles() -> dict[str, str]:
    return {k: t.title for k, t in BY_KEY.items()}


class HelpBanner(QFrame):
    """Guía rápida que aparece arriba de un módulo hasta que el usuario la oculta."""

    full_requested = Signal(str)
    hide_requested = Signal(str)

    def __init__(self, t: Topic, parent=None):
        super().__init__(parent)
        self.key = t.key
        self.setObjectName("HelpBanner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 12, 10)
        lay.setSpacing(14)
        text = QVBoxLayout()
        text.setSpacing(4)
        title = QLabel(f"Guía rápida · {t.title}")
        title.setObjectName("HelpTitle")
        text.addWidget(title)
        c = colors()
        bullets = "".join(f"<li style='margin-bottom:2px;'>{render.inline(q, c)}</li>" for q in t.quick)
        body = QLabel(f"<ul style='margin:0; -qt-list-indent:1;'>{bullets}</ul>")
        body.setTextFormat(Qt.RichText)
        body.setWordWrap(True)
        text.addWidget(body)
        lay.addLayout(text, 1)
        buttons = QVBoxLayout()
        full = QPushButton("Ver tutorial completo (F1)")
        full.setObjectName("Primary")
        full.setCursor(Qt.PointingHandCursor)
        full.clicked.connect(lambda: self.full_requested.emit(self.key))
        hide = QPushButton("Ocultar guía")
        hide.setCursor(Qt.PointingHandCursor)
        hide.clicked.connect(lambda: self.hide_requested.emit(self.key))
        buttons.addWidget(full)
        buttons.addWidget(hide)
        buttons.addStretch(1)
        lay.addLayout(buttons)


class HelpBrowser(QTextBrowser):
    """Muestra temas de ayuda; los enlaces «Ver también» abren otro tema."""

    topic_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HelpBrowser")
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._on_link)
        self.current_key: str | None = None

    def show_topic(self, key: str) -> bool:
        t = topic(key)
        if t is None:
            return False
        self.current_key = key
        self.setHtml(render.topic_html(t, colors(), titles=titles()))
        self.verticalScrollBar().setValue(0)
        self.topic_changed.emit(key)
        return True

    def _on_link(self, url: QUrl):
        target = url.toString()
        if target.startswith("topic:"):
            self.show_topic(target.split(":", 1)[1])


class HelpDialog(QDialog):
    """Tutorial completo de un módulo (se abre con F1)."""

    def __init__(self, parent, key: str, on_all=None, title: str | None = None):
        super().__init__(parent)
        if topic(key) is None:
            key = "inicio"
        t = topic(key)
        self.setWindowTitle(title or f"Cómo se usa · {t.title}")
        self.resize(820, 680)
        lay = QVBoxLayout(self)
        self.browser = HelpBrowser()
        self.browser.show_topic(key)
        lay.addWidget(self.browser, 1)
        row = QHBoxLayout()
        if on_all is not None:
            all_btn = QPushButton("Ver toda la ayuda y tutoriales")
            all_btn.clicked.connect(lambda: (self.accept(), on_all(self.browser.current_key or key)))
            row.addWidget(all_btn)
        row.addStretch(1)
        close = QPushButton("Cerrar")
        close.setObjectName("Primary")
        close.clicked.connect(self.accept)
        close.setDefault(True)
        row.addWidget(close)
        lay.addLayout(row)


# --- impresión y PDF ------------------------------------------------------------------------
def _document(html: str) -> QTextDocument:
    doc = QTextDocument()
    doc.setDefaultFont(QFont("Segoe UI", 10))
    doc.setHtml(html)
    return doc


def export_pdf(path: str | Path, html: str) -> int:
    """Guarda el HTML como PDF tamaño carta. Devuelve el número de páginas."""
    path = str(path)
    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.Letter))
    writer.setPageMargins(QMarginsF(6, 6, 6, 6), QPageLayout.Millimeter)
    writer.setTitle("GranizApp")
    writer.setCreator("GranizApp")
    _document(html).print_(writer)
    del writer  # cierra el archivo
    return pdf_page_count(path)


def pdf_page_count(path: str | Path) -> int:
    data = Path(path).read_bytes()
    return len(re.findall(rb"/Type\s*/Page(?![s\w])", data))


def print_html(parent, html: str) -> bool:
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter

    printer = QPrinter(QPrinter.HighResolution)
    printer.setPageSize(QPageSize(QPageSize.Letter))
    dlg = QPrintDialog(printer, parent)
    dlg.setWindowTitle("Imprimir")
    if dlg.exec() != QDialog.Accepted:
        return False
    _document(html).print_(printer)
    return True
