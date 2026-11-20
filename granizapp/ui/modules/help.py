"""Ayuda y tutoriales: todos los temas en un lugar, con buscador, impresión y PDF."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from granizapp import __version__
from granizapp.core.services.settings import get_setting
from granizapp.core.utils import normalize
from granizapp.help import render
from granizapp.help.content import Topic, visible_topics
from granizapp.ui import theme
from granizapp.ui.context import AppContext
from granizapp.ui.help_ui import HelpBrowser, export_pdf, print_html
from granizapp.ui.modules import MODULES
from granizapp.ui.widgets.common import Page, button, info, label, page_header, show_error, toast
from granizapp.ui.widgets.keys import KeyLineEdit


def _word_matches(word: str, text: str) -> bool:
    """Coincidencia tolerante a variaciones: «fiar» encuentra «fiados», «abonar» encuentra «abono»."""
    if word in text:
        return True
    if len(word) >= 4 and word[:-1] in text:
        return True
    return len(word) >= 6 and word[:-2] in text


def _searchable(t: Topic) -> str:
    parts = [t.title, t.summary, *t.quick, *t.tips]
    for task in t.tasks:
        parts.append(task.title)
        parts.extend(task.steps)
    for q, a in t.faq:
        parts.extend([q, a])
    for k, v in t.keys:
        parts.extend([k, v])
    return normalize(" ".join(parts))


class HelpPage(Page):
    topics: set[str] = set()

    def __init__(self, ctx: AppContext):
        super().__init__(ctx)
        allowed = {m.key for m in MODULES if m.allowed(ctx.actor.role)}
        self.topic_list = visible_topics(ctx.is_admin, allowed)
        self.index = {t.key: _searchable(t) for t in self.topic_list}
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)
        print_btn = button("Imprimir o guardar en PDF ▾")
        menu = QMenu(print_btn)
        menu.addAction("Imprimir la guía completa…", self.print_guide)
        menu.addAction("Guardar la guía completa en PDF…", self.save_guide_pdf)
        menu.addSeparator()
        menu.addAction("Imprimir la hoja de atajos (1 página)…", self.print_cheatsheet)
        menu.addAction("Guardar la hoja de atajos en PDF…", self.save_cheatsheet_pdf)
        print_btn.setMenu(menu)
        root.addWidget(page_header("Ayuda y tutoriales",
                                   "Cómo usar cada parte de la aplicación. En cualquier módulo, F1 abre su tutorial.",
                                   [print_btn]))
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        self.search = KeyLineEdit(on_key=self._search_key)
        self.search.setPlaceholderText("Buscar en la ayuda (ej. fiar, cerrar caja, receta)…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill)
        ll.addWidget(self.search)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_item)
        ll.addWidget(self.list, 1)
        reset = button("Volver a mostrar las guías rápidas", self.reset_banners,
                       tip="Hace que reaparezcan las instrucciones de arriba de cada módulo")
        ll.addWidget(reset)
        split.addWidget(left)
        self.browser = HelpBrowser()
        self.browser.topic_changed.connect(self._sync_list)
        split.addWidget(self.browser)
        split.setSizes([290, 860])
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)
        self._fill("")
        self.show_topic("inicio")

    # --- índice ---------------------------------------------------------------------------
    def _fill(self, query: str = ""):
        q = normalize(query)
        current = self.browser.current_key if hasattr(self, "browser") else None
        self.list.blockSignals(True)
        self.list.clear()
        bold = QFont()
        bold.setBold(True)
        groups = [("GENERAL", [t for t in self.topic_list if t.group == "general"]),
                  ("MÓDULOS", [t for t in self.topic_list if t.group != "general"])]
        first_match = None
        for header, topics in groups:
            matched = [t for t in topics if not q or all(_word_matches(w, self.index[t.key]) for w in q.split())]
            if not matched:
                continue
            head = QListWidgetItem(header)
            head.setFlags(Qt.NoItemFlags)
            head.setFont(bold)
            head.setForeground(QBrush(theme.qcolor("muted")))
            self.list.addItem(head)
            for t in matched:
                item = QListWidgetItem(f"   {t.title}")
                item.setData(Qt.UserRole, t.key)
                self.list.addItem(item)
                if first_match is None:
                    first_match = item
                if t.key == current:
                    self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if q and first_match is not None:
            self.list.setCurrentItem(first_match)
        if self.list.count() == 0:
            empty = QListWidgetItem("Nada coincide con la búsqueda")
            empty.setFlags(Qt.NoItemFlags)
            self.list.addItem(empty)

    def _search_key(self, event) -> bool:
        if event.key() in (Qt.Key_Down, Qt.Key_Up):
            self.list.setFocus()
            return True
        return False

    def _on_item(self, item, _prev=None):
        if item is not None and item.data(Qt.UserRole):
            self.browser.show_topic(item.data(Qt.UserRole))

    def _sync_list(self, key: str):
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.UserRole) == key and self.list.currentItem() is not it:
                self.list.blockSignals(True)
                self.list.setCurrentItem(it)
                self.list.blockSignals(False)
                break

    def show_topic(self, key: str):
        if key not in self.index:
            key = "inicio"
        if self.search.text():
            self.search.clear()
        self.browser.show_topic(key)

    def activate(self):
        QTimer.singleShot(0, self.search, self.search.setFocus)

    def refresh(self):
        # el contenido es fijo; solo se re-pinta por si cambió el tema claro/oscuro
        if self.browser.current_key:
            self.browser.show_topic(self.browser.current_key)

    # --- acciones -------------------------------------------------------------------------------
    def _business(self) -> str:
        with self.ctx.session() as s:
            return get_setting(s, "business_name") or ""

    def guide(self) -> str:
        return render.guide_html(self.topic_list, self._business(), __version__)

    def cheatsheet(self) -> str:
        return render.cheatsheet_html(self._business())

    def _save_pdf(self, html: str, default_name: str):
        start = str(Path.home() / "Documents" / default_name)
        path, _ = QFileDialog.getSaveFileName(self, "Guardar PDF", start, "PDF (*.pdf)")
        if not path:
            return None
        try:
            pages = export_pdf(path, html)
        except Exception as exc:
            show_error(self, exc)
            return None
        toast(self, f"PDF guardado ({pages} página{'s' if pages != 1 else ''}): {path}")
        return path

    def save_guide_pdf(self):
        self._save_pdf(self.guide(), "Guía de uso GranizApp.pdf")

    def save_cheatsheet_pdf(self):
        self._save_pdf(self.cheatsheet(), "Atajos GranizApp.pdf")

    def print_guide(self):
        try:
            if print_html(self, self.guide()):
                toast(self, "Guía enviada a la impresora")
        except Exception as exc:
            show_error(self, exc)

    def print_cheatsheet(self):
        try:
            if print_html(self, self.cheatsheet()):
                toast(self, "Hoja de atajos enviada a la impresora")
        except Exception as exc:
            show_error(self, exc)

    def reset_banners(self):
        self.ctx.bus.help_reset.emit()
        info(self, "Listo: las guías rápidas vuelven a aparecer arriba de cada módulo.", "Ayuda")
