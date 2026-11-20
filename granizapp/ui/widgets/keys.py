"""Widgets que atienden sus propias teclas.

Se usan en lugar de `installEventFilter`: con filtros, al destruir una ventana Qt puede
entregar eventos a un filtro que ya se está destruyendo y la aplicación se cae. Aquí cada
widget llama a un manejador opcional; si devuelve True, la tecla se consumió.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QLineEdit, QTableView

KeyHandler = Callable[[QKeyEvent], bool]


class KeyLineEdit(QLineEdit):
    def __init__(self, *args, on_key: KeyHandler | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_key = on_key

    def keyPressEvent(self, event: QKeyEvent):
        if self.on_key is not None and self.on_key(event):
            event.accept()
            return
        super().keyPressEvent(event)


class KeyTableView(QTableView):
    def __init__(self, *args, on_key: KeyHandler | None = None, on_resize: Callable[[], None] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_key = on_key
        self.on_resize = on_resize

    def keyPressEvent(self, event: QKeyEvent):
        if self.on_key is not None and self.on_key(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def viewportEvent(self, event):
        # el área visible cambia de tamaño también cuando aparece/desaparece la barra vertical
        handled = super().viewportEvent(event)
        if event.type() == QEvent.Resize and self.on_resize is not None:
            self.on_resize()
        return handled

    def detach(self):
        self.on_key = None
        self.on_resize = None
