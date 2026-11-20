"""Ventana principal: barra lateral por secciones, páginas por módulo y barra de estado."""
from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from granizapp import APP_NAME
from granizapp.core.services import cash
from granizapp.core.services.settings import get_setting
from granizapp.core.utils import fmt_long_date
from granizapp.ui.context import AppContext, Topics
from granizapp.ui.modules import MODULES
from granizapp.ui.registry import SECTIONS, ModuleSpec

log = logging.getLogger(__name__)


class SyncWorker(QObject):
    finished = Signal(object)
    progress = Signal(str)

    def __init__(self, db, url):
        super().__init__()
        self.db, self.url = db, url

    def run(self):
        from granizapp.core.services.sync import synchronize

        result = synchronize(self.db, self.url, progress=self.progress.emit)
        self.finished.emit(result)


class MainWindow(QMainWindow):
    logout_requested = Signal()

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.pages: dict[str, QWidget] = {}
        self.frames: dict[str, QWidget] = {}
        self.banners: dict[str, QWidget] = {}
        self.current_key: str | None = None
        self.specs: dict[str, ModuleSpec] = {}
        self.buttons: dict[str, QPushButton] = {}
        self._sync_thread: QThread | None = None
        with ctx.session() as s:
            self.business = get_setting(s, "business_name") or "Mi negocio"
        self.setWindowTitle(f"{self.business} · {APP_NAME}")
        self.resize(1360, 820)
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._sidebar())
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self._statusbar()
        ctx.bus.navigate.connect(self.navigate)
        ctx.bus.changed.connect(self._on_changed)
        ctx.bus.status.connect(lambda t: self.statusBar().showMessage(t, 5000))
        ctx.bus.help_requested.connect(self.open_help_topic)
        ctx.bus.help_reset.connect(self.reset_banners)
        QShortcut(QKeySequence("F1"), self, activated=self.show_help)
        first = next(iter(self.specs))
        self.navigate("pos" if "pos" in self.specs else first)
        self._update_status()
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._update_status)
        self._clock.start(30_000)
        self._setup_sync()

    # --- barra lateral -------------------------------------------------------------------
    def _sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setAttribute(Qt.WA_StyledBackground, True)
        side.setFixedWidth(228)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 0, 0, 10)
        lay.setSpacing(0)
        brand = QLabel(self.business)
        brand.setObjectName("Brand")
        brand.setWordWrap(True)
        sub = QLabel(f"{APP_NAME} · {self.ctx.config.device_name}")
        sub.setObjectName("BrandSub")
        lay.addWidget(brand)
        lay.addWidget(sub)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }"
            "QScrollBar:vertical { background: transparent; width: 6px; }"
            "QScrollBar::handle:vertical { background: rgba(255,255,255,0.18); border-radius: 3px; }")
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(0)
        group = QButtonGroup(self)
        group.setExclusive(True)
        role = self.ctx.actor.role
        for section in SECTIONS:
            mods = [m for m in MODULES if m.section == section and m.allowed(role)]
            if not mods:
                continue
            title = QLabel(section)
            title.setObjectName("NavSection")
            il.addWidget(title)
            for m in mods:
                text = m.title + (f"     {m.shortcut}" if m.shortcut else "")
                b = QPushButton(text)
                b.setCheckable(True)
                b.setCursor(Qt.PointingHandCursor)
                b.setToolTip(m.description)
                b.clicked.connect(lambda _c=False, key=m.key: self.navigate(key))
                group.addButton(b)
                il.addWidget(b)
                self.buttons[m.key] = b
                self.specs[m.key] = m
                if m.shortcut:
                    QShortcut(QKeySequence(m.shortcut), self, activated=lambda key=m.key: self.navigate(key))
        il.addStretch(1)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)
        help_row = QHBoxLayout()
        help_row.setContentsMargins(12, 6, 12, 0)
        help_btn = QPushButton("?  Cómo se usa este módulo (F1)")
        help_btn.setObjectName("HelpLink")
        help_btn.setCursor(Qt.PointingHandCursor)
        help_btn.clicked.connect(lambda: self.show_help())
        help_row.addWidget(help_btn, 1)
        lay.addLayout(help_row)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 6, 8, 0)
        user = QLabel(f"{self.ctx.actor.user_name}")
        user.setObjectName("UserName")
        bottom.addWidget(user, 1)
        out = QPushButton("Cambiar usuario")
        out.setObjectName("Logout")
        out.setCursor(Qt.PointingHandCursor)
        out.clicked.connect(self.logout_requested.emit)
        bottom.addWidget(out)
        lay.addLayout(bottom)
        return side

    def navigate(self, key: str):
        spec = self.specs.get(key)
        if spec is None:
            return None
        page = self.pages.get(key)
        if page is None:
            try:
                page = spec.factory(self.ctx)
            except Exception as exc:
                log.exception("No se pudo abrir el módulo %s", key)
                from granizapp.ui.widgets.common import show_error

                show_error(self, exc)
                return None
            self.pages[key] = page
            frame = self._frame(key, page)
            self.frames[key] = frame
            self.stack.addWidget(frame)
        self.current_key = key
        self.stack.setCurrentWidget(self.frames[key])
        self.buttons[key].setChecked(True)
        if hasattr(page, "activate"):
            page.activate()
        return page

    def current_page(self):
        return self.pages.get(self.current_key) if self.current_key else None

    # --- ayuda ------------------------------------------------------------------------------
    def _frame(self, key: str, page: QWidget) -> QWidget:
        """Envuelve la página con su guía rápida (visible hasta que el usuario la oculta)."""
        from granizapp.help.content import topic
        from granizapp.ui.help_ui import HelpBanner

        frame = QWidget(self.stack)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        t = topic(key)
        if t is not None and t.quick:
            holder = QWidget(frame)
            hl = QVBoxLayout(holder)
            hl.setContentsMargins(20, 12, 20, 0)
            banner = HelpBanner(t, holder)
            banner.full_requested.connect(self.show_help)
            banner.hide_requested.connect(self.hide_banner)
            hl.addWidget(banner)
            lay.addWidget(holder)
            # se decide la visibilidad ya dentro de la ventana: un widget sin padre que se muestra
            # se vuelve ventana propia por un instante y le roba el foco a la principal
            holder.setVisible(key not in self.ctx.config.help_hidden)
            self.banners[key] = holder
        lay.addWidget(page, 1)
        return frame

    def hide_banner(self, key: str):
        if key in self.banners:
            self.banners[key].hide()
        if key not in self.ctx.config.help_hidden:
            self.ctx.config.help_hidden.append(key)
            self.ctx.config.save()
        self.statusBar().showMessage("Guía oculta. F1 abre el tutorial completo cuando lo necesite.", 6000)

    def reset_banners(self):
        self.ctx.config.help_hidden = []
        self.ctx.config.save()
        for holder in self.banners.values():
            holder.show()

    def show_help(self, key: str | None = None):
        from granizapp.ui.help_ui import HelpDialog

        key = key if isinstance(key, str) and key else (self.current_key or "inicio")
        HelpDialog(self, key, on_all=self.open_help_topic).exec()

    def open_help_topic(self, key: str = "inicio"):
        page = self.navigate("help")
        if page is not None and hasattr(page, "show_topic"):
            page.show_topic(key)

    # --- barra de estado ------------------------------------------------------------------
    def _statusbar(self):
        bar = self.statusBar()
        self.cash_status = QLabel()
        self.sync_status = QLabel()
        self.user_status = QLabel()
        bar.addPermanentWidget(self.cash_status)
        bar.addPermanentWidget(self.sync_status)
        bar.addPermanentWidget(self.user_status)

    def _on_changed(self, topic: str):
        if topic in (Topics.CASH, Topics.ALL):
            self._update_status()

    def _update_status(self):
        try:
            with self.ctx.session() as s:
                cs = cash.current_session(s, self.ctx.actor.device_id)
            self.cash_status.setText(f"Caja #{cs.number} abierta" if cs else "Caja cerrada")
        except Exception:
            self.cash_status.setText("Sin conexión a la base de datos")
        mode = "Postgres (en línea)" if not self.ctx.db.is_sqlite else "Base local"
        self.user_status.setText(f"{self.ctx.actor.user_name} · {mode} · {fmt_long_date(datetime.now())}")

    # --- sincronización automática ---------------------------------------------------------
    def _setup_sync(self):
        cfg = self.ctx.config
        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self.sync_now)
        if cfg.sync_enabled and cfg.postgres_url and self.ctx.db.is_sqlite:
            self._sync_timer.start(max(1, cfg.sync_interval_min) * 60_000)
            QTimer.singleShot(5_000, self, self.sync_now)
            self.sync_status.setText("Sincronización: pendiente")
        else:
            self.sync_status.setText("")

    def sync_now(self, on_done=None):
        cfg = self.ctx.config
        if not (cfg.postgres_url and self.ctx.db.is_sqlite) or self._sync_thread is not None:
            return False
        from granizapp.config import normalize_pg_url

        self.sync_status.setText("Sincronizando…")
        thread = QThread(self)
        worker = SyncWorker(self.ctx.db, normalize_pg_url(cfg.postgres_url))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(lambda t: self.sync_status.setText(t))

        def done(result):
            self.sync_status.setText(
                f"Sincronizado {result.finished:%I:%M %p}" if result.ok else "Sincronización con error")
            self.sync_status.setToolTip(result.text())
            if result.ok and result.pulled:
                self.ctx.notify(Topics.ALL)
            thread.quit()
            if on_done:
                on_done(result)

        worker.finished.connect(done)
        thread.finished.connect(lambda: setattr(self, "_sync_thread", None))
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._sync_thread = thread
        self._sync_worker = worker
        thread.start()
        return True

    def closeEvent(self, e):
        if self._sync_thread is not None:
            self._sync_thread.quit()
            self._sync_thread.wait(3000)
        super().closeEvent(e)
