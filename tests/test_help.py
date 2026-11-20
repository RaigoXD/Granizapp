"""Ayuda: cada módulo tiene tutorial, F1 y guía rápida funcionan, la guía sale en PDF."""
import re

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from granizapp.help import render
from granizapp.help.content import ALL, BY_KEY, GENERAL, visible_topics
from granizapp.ui.modules import MODULES
from tests.test_ui import _with_modal, ctx, qapp  # noqa: F401


def test_every_module_has_a_tutorial():
    module_keys = {m.key for m in MODULES}
    topic_keys = {t.key for t in ALL if t.group == "modulo"}
    assert module_keys == topic_keys, (module_keys ^ topic_keys)
    for t in ALL:
        assert t.title and t.summary
        assert t.tasks or t.faq or t.keys, f"{t.key} no tiene contenido"
        for rel in t.related:
            assert rel in BY_KEY, f"{t.key} enlaza a un tema inexistente: {rel}"
    for m in MODULES:
        if m.key != "help":
            assert BY_KEY[m.key].quick, f"{m.key} no tiene guía rápida"
    assert len({t.key for t in ALL}) == len(ALL)


def test_cashier_only_sees_bar_topics():
    allowed = {m.key for m in MODULES if m.allowed("cajero")}
    keys = {t.key for t in visible_topics(False, allowed)}
    assert {"pos", "cash", "debtors", "sales", "inventory", "help", "inicio", "dia", "faq", "atajos"} <= keys
    assert not keys & {"reports", "costing", "settings", "finance", "cifras"}


def test_render_markup():
    html = render.inline("Presione `F1` y luego **Guardar** en *Caja › Cerrar*. Use `3*cl12`.", render.LIGHT)
    assert "<b>Guardar</b>" in html and "F1" in html and "3*cl12" in html
    assert "Caja › Cerrar" in html and "*" not in html.replace("3*cl12", "")
    for t in ALL:
        out = render.topic_html(t, render.LIGHT, titles={k: v.title for k, v in BY_KEY.items()})
        assert "**" not in out and "`" not in out, t.key
    assert "page-break-before" in render.guide_html(ALL, "The Spot", "1.0")


def test_pdfs(tmp_path, qapp):  # noqa: F811
    from granizapp.ui.help_ui import export_pdf, pdf_page_count

    sheet = tmp_path / "atajos.pdf"
    assert export_pdf(sheet, render.cheatsheet_html("The Spot")) == 1  # cabe en una sola hoja
    guide = tmp_path / "guia.pdf"
    pages = export_pdf(guide, render.guide_html(ALL, "The Spot", "1.0"))
    assert pages >= len(ALL)  # cada tema empieza en página nueva
    assert pdf_page_count(guide) == pages


def test_banner_f1_and_help_page(ctx):
    from granizapp.ui.main_window import MainWindow

    win = MainWindow(ctx)
    win.show()
    QApplication.processEvents()
    assert win.current_key == "pos"
    assert win.banners["pos"].isVisible()  # guía rápida en la primera visita

    # F1 abre el tutorial del módulo actual
    seen = []

    def check(dlg):
        seen.append((type(dlg).__name__, dlg.browser.current_key, "Vender" in dlg.browser.toPlainText()))
        dlg.accept()

    _with_modal(check)
    win.show_help()
    assert seen == [("HelpDialog", "pos", True)]

    # ocultar la guía se recuerda en la configuración del equipo
    win.hide_banner("pos")
    assert not win.banners["pos"].isVisible() and "pos" in ctx.config.help_hidden
    win.navigate("cash")
    QApplication.processEvents()
    assert win.banners["cash"].isVisible()

    # «Ver toda la ayuda» lleva al módulo de ayuda en ese tema
    win.open_help_topic("debtors")
    page = win.current_page()
    assert win.current_key == "help" and page.browser.current_key == "debtors"
    page.search.setText("fiar")
    keys = [page.list.item(i).data(Qt.UserRole) for i in range(page.list.count())]
    assert "pos" in keys and "debtors" in keys and "settings" not in keys
    page.search.setText("zzzz-no-existe")
    assert page.list.count() == 1
    page.search.clear()

    # los enlaces «Ver también» navegan entre temas
    from PySide6.QtCore import QUrl

    page.browser.anchorClicked.emit(QUrl("topic:cash"))
    assert page.browser.current_key == "cash"

    # volver a mostrar las guías (el aviso de confirmación es un QMessageBox simulado en las pruebas)
    page.reset_banners()
    assert ctx.config.help_hidden == [] and win.banners["pos"].isVisibleTo(win.frames["pos"])
    assert [m[1] for m in ctx.messages] == ["Ayuda"], ctx.messages
    win.close()
    win.deleteLater()
    QApplication.processEvents()


def test_ctrl_n_works_right_after_navigating(ctx):
    """Al entrar a un módulo el foco queda en su tabla, así Ctrl+N responde sin hacer clic."""
    from granizapp.ui.main_window import MainWindow

    win = MainWindow(ctx)
    win.show()
    win.activateWindow()
    QTest.qWaitForWindowActive(win, 1000)
    win.navigate("suppliers")
    QApplication.processEvents()
    opened = []

    def check(dlg):
        opened.append(dlg.windowTitle())
        dlg.reject()

    _with_modal(check)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key_N, Qt.ControlModifier)
    QApplication.processEvents()
    assert opened and "proveedor" in opened[0].lower()
    win.close()
    win.deleteLater()
    QApplication.processEvents()
