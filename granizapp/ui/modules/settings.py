"""Configuración: negocio, este equipo, medios de pago, usuarios, base de datos, respaldos e importación."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from granizapp import APP_NAME, __version__
from granizapp.config import mask_url, normalize_pg_url
from granizapp.core import backup
from granizapp.core.models import AccountKind, Role
from granizapp.core.services import auth, finance, sales, staff
from granizapp.core.services.common import audit
from granizapp.core.services.settings import get_setting, set_setting
from granizapp.core.utils import fmt_datetime, fmt_money
from granizapp.paths import app_home
from granizapp.ui.context import AppContext, Topics
from granizapp.ui.widgets.common import Page, busy, button, card, confirm, info, label, page_header, run, show_error, toast
from granizapp.ui.widgets.crud import CrudPanel, column_values
from granizapp.ui.widgets.forms import Field, MoneyEdit
from granizapp.ui.widgets.table import Col, DataTable


class SettingsPage(Page):
    topics = {Topics.SETTINGS, Topics.FINANCE}

    def __init__(self, ctx: AppContext):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.addWidget(page_header("Configuración", f"{APP_NAME} {__version__}"))
        tabs = QTabWidget()
        root.addWidget(tabs, 1)
        tabs.addTab(self._business_tab(), "Negocio")
        tabs.addTab(self._device_tab(), "Este equipo")
        self.methods_panel = CrudPanel(
            ctx, "Medio de pago",
            [Col("Medio de pago", lambda m: m.name, stretch=True),
             Col("Llega a la cuenta", lambda m: self.acc_names.get(m.account_id, ""), width=220),
             Col("Es efectivo", lambda m: m.is_cash, "bool", width=90),
             Col("Orden (F1, F2…)", lambda m: m.sort_order, "int", width=110),
             Col("Activo", lambda m: m.active, "bool", width=60)],
            load=lambda s: sales.payment_methods(s, include_inactive=True),
            fields=lambda s: [
                Field("name", "Nombre", required=True, placeholder="Ej: Nequi, Bancolombia, Bre-B, Datáfono"),
                Field("account_id", "El dinero llega a", "choice", options=[(a.id, a.name) for a in finance.list_accounts(s)]),
                Field("is_cash", "Es efectivo (entra al cajón y calcula cambio)", "bool"),
                Field("sort_order", "Orden en la ventana de cobro", "int", help="1 = F1, 2 = F2…"),
                Field("active", "Activo", "bool", default=True),
            ],
            save=lambda s, d, mid: sales.save_payment_method(s, d, mid),
            to_values=column_values,
            topics=(Topics.SETTINGS,),
        )
        tabs.addTab(self.methods_panel, "Medios de pago")
        self.users_panel = CrudPanel(
            ctx, "Usuario",
            [Col("Nombre", lambda u: u.name, stretch=True),
             Col("Usuario", lambda u: u.username, width=120),
             Col("Rol", lambda u: Role.LABELS.get(u.role, u.role), width=170),
             Col("Tiene PIN", lambda u: bool(u.pin_hash), "bool", width=80),
             Col("Activo", lambda u: u.active, "bool", width=60)],
            load=lambda s: auth.list_users(s, include_inactive=True),
            fields=lambda s: [
                Field("name", "Nombre", required=True),
                Field("username", "Usuario", help="Si lo deja vacío se arma con el nombre"),
                Field("role", "Rol", "choice", options=list(Role.LABELS.items()), default=Role.CASHIER,
                      help="Cajero/bartender: vende, maneja caja, deudores e inventario. Administrador: todo."),
                Field("pin", "PIN (4 a 8 números)", "password", help="Déjelo vacío para no cambiarlo"),
                Field("employee_id", "Empleado asociado", "choice",
                      options=[("", "—")] + [(e.id, e.name) for e in staff.list_employees(s)]),
                Field("active", "Activo", "bool", default=True),
            ],
            save=lambda s, d, uid: auth.save_user(s, d, uid, self.ctx.actor),
            to_values=lambda u: {**column_values(u), "pin": ""},
            topics=(Topics.SETTINGS,),
            extra_buttons=[button("Quitar PIN", self.clear_pin)],
        )
        tabs.addTab(self.users_panel, "Usuarios")
        tabs.addTab(self._db_tab(), "Base de datos y sincronización")
        tabs.addTab(self._backup_tab(), "Respaldos")
        tabs.addTab(self._import_tab(), "Importar Excel")

    # --- negocio --------------------------------------------------------------------------------
    def _business_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        frame, fl = card(title="Datos del negocio")
        form = QFormLayout()
        self.b_name = QLineEdit()
        self.b_nit = QLineEdit()
        self.b_phone = QLineEdit()
        self.b_address = QLineEdit()
        self.b_city = QLineEdit()
        self.b_footer = QLineEdit()
        self.b_base = MoneyEdit(0)
        self.b_theme = QComboBox()
        self.b_theme.addItem("Claro", "light")
        self.b_theme.addItem("Oscuro (para el bar de noche)", "dark")
        self.b_neg = QCheckBox("Permitir vender aunque el inventario quede en negativo")
        form.addRow("Nombre", self.b_name)
        form.addRow("NIT / documento", self.b_nit)
        form.addRow("Teléfono", self.b_phone)
        form.addRow("Dirección", self.b_address)
        form.addRow("Ciudad", self.b_city)
        form.addRow("Mensaje en comprobantes", self.b_footer)
        form.addRow("Base de caja habitual", self.b_base)
        self.b_flavor_req = QCheckBox("Exigir el sabor al vender (sin la opción «Sin especificar»)")
        self.b_cover = QSpinBox()
        self.b_cover.setRange(1, 8)
        self.b_cover.setSuffix(" semanas de venta")
        form.addRow("Sabores", self.b_flavor_req)
        form.addRow("Pedido sugerido de bolsas", self.b_cover)
        form.addRow("Tema de este equipo", self.b_theme)
        fl.addLayout(form)
        fl.addWidget(button("Guardar", self.save_business, "Primary"), 0, Qt.AlignLeft)
        lay.addWidget(frame)
        lay.addStretch(1)
        return w

    def save_business(self):
        def do():
            with self.ctx.session() as s:
                set_setting(s, "business_name", self.b_name.text().strip() or "Mi negocio")
                set_setting(s, "business_nit", self.b_nit.text().strip())
                set_setting(s, "business_phone", self.b_phone.text().strip())
                set_setting(s, "business_address", self.b_address.text().strip())
                set_setting(s, "business_city", self.b_city.text().strip())
                set_setting(s, "ticket_footer", self.b_footer.text().strip())
                set_setting(s, "default_cash_base", self.b_base.value())
                set_setting(s, "require_flavor", self.b_flavor_req.isChecked())
                set_setting(s, "flavor_cover_weeks", self.b_cover.value())
                audit(s, self.ctx.actor, "configurar_negocio", "settings", "",
                      f"{self.b_name.text().strip()} · base {fmt_money(self.b_base.value())}")
            return True

        if run(self, do):
            theme = self.b_theme.currentData()
            if theme != self.ctx.config.theme:
                self.ctx.config.theme = theme
                self.ctx.config.save()
                from PySide6.QtWidgets import QApplication

                from granizapp.ui.theme import apply_theme

                apply_theme(QApplication.instance(), theme)
            self.ctx.notify(Topics.SETTINGS)
            toast(self, "Datos del negocio guardados (el nombre se actualiza al volver a abrir)")

    # --- equipo ------------------------------------------------------------------------------------
    def _device_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        frame, fl = card(title="Este equipo")
        fl.addWidget(label("Cada computador que use la app tiene un código propio: se usa en los números de venta "
                           "y en su turno de caja. Si tiene dos cajas, cada una necesita su propio cajón.", "Muted", wrap=True))
        form = QFormLayout()
        self.d_name = QLineEdit()
        self.d_id = label("", "SectionTitle")
        self.d_drawer = QComboBox()
        form.addRow("Nombre del equipo", self.d_name)
        form.addRow("Código del equipo", self.d_id)
        form.addRow("Cajón (efectivo) de este equipo", self.d_drawer)
        fl.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(button("Guardar", self.save_device, "Primary"))
        row.addWidget(button("Crear un cajón nuevo para este equipo", self.new_drawer))
        row.addStretch(1)
        fl.addLayout(row)
        lay.addWidget(frame)
        paths, pl = card(title="Archivos")
        self.paths_lbl = label("", "Muted", wrap=True)
        self.paths_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pl.addWidget(self.paths_lbl)
        pl.addWidget(button("Abrir carpeta de datos", lambda: os.startfile(str(app_home()))), 0, Qt.AlignLeft)
        lay.addWidget(paths)
        lay.addStretch(1)
        return w

    def save_device(self):
        cfg = self.ctx.config
        cfg.device_name = self.d_name.text().strip() or cfg.device_name
        cfg.drawer_account_id = self.d_drawer.currentData() or ""
        cfg.save()
        toast(self, "Configuración del equipo guardada")
        self.ctx.notify(Topics.CASH)

    def new_drawer(self):
        def do():
            with self.ctx.session() as s:
                acc = finance.save_account(s, {"name": f"Cajón {self.ctx.config.device_name}", "kind": AccountKind.CASH,
                                               "is_drawer": True, "sort_order": 1})
                return acc.id

        aid = run(self, do)
        if aid:
            self.ctx.config.drawer_account_id = aid
            self.ctx.config.save()
            self.ctx.notify(Topics.FINANCE, Topics.CASH)

    # --- base de datos ---------------------------------------------------------------------------
    def _db_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        frame, fl = card(title="¿Dónde se guardan los datos?")
        self.db_status = label("", "Muted", wrap=True)
        fl.addWidget(self.db_status)
        self.r_sqlite = QRadioButton("Base local en este computador (SQLite) — recomendado en el bar: funciona sin internet")
        self.r_pg = QRadioButton("Directamente en el servidor Postgres en línea — requiere internet siempre")
        fl.addWidget(self.r_sqlite)
        fl.addWidget(self.r_pg)
        form = QFormLayout()
        self.pg_url = QLineEdit()
        self.pg_url.setPlaceholderText("postgresql://usuario:contraseña@servidor:5432/basedatos?sslmode=require")
        self.pg_url.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        form.addRow("URL de Postgres", self.pg_url)
        fl.addLayout(form)
        fl.addWidget(label("Sirve cualquier Postgres: Supabase, Neon, Railway, un VPS… Copie la «connection string» "
                           "que le dan (si pide SSL agregue ?sslmode=require).", "Hint", wrap=True))
        row = QHBoxLayout()
        row.addWidget(button("Probar conexión", self.test_pg))
        row.addWidget(button("Guardar (se aplica al reiniciar)", self.save_db, "Primary"))
        row.addStretch(1)
        fl.addLayout(row)
        lay.addWidget(frame)
        f2, l2 = card(title="Sincronización (base local ↔ Postgres)")
        l2.addWidget(label("Con la base local, la app puede subir sus datos al servidor y bajar los de otros equipos "
                           "(por ejemplo, para ver los reportes desde la casa o tener dos cajas). Si no hay internet, "
                           "sigue funcionando y sincroniza cuando vuelva.", "Muted", wrap=True))
        r2 = QHBoxLayout()
        self.sync_enabled = QCheckBox("Sincronizar automáticamente cada")
        self.sync_minutes = QSpinBox()
        self.sync_minutes.setRange(1, 240)
        self.sync_minutes.setSuffix(" min")
        r2.addWidget(self.sync_enabled)
        r2.addWidget(self.sync_minutes)
        r2.addStretch(1)
        l2.addLayout(r2)
        self.sync_info = label("", "Muted", wrap=True)
        l2.addWidget(self.sync_info)
        r3 = QHBoxLayout()
        r3.addWidget(button("Sincronizar ahora", self.sync_now, "Primary"))
        r3.addStretch(1)
        l2.addLayout(r3)
        lay.addWidget(f2)
        lay.addStretch(1)
        return w

    def _pg_url_value(self) -> str:
        return self.pg_url.text().strip()

    def test_pg(self):
        url = self._pg_url_value()
        if not url:
            show_error(self, "Escriba la URL de Postgres")
            return
        from granizapp.core.services.sync import check_connection

        try:
            with busy():
                version = check_connection(normalize_pg_url(url))
            info(self, f"Conexión correcta.\n{version}", "Postgres")
        except Exception as exc:
            from granizapp.core.services.sync import _friendly

            show_error(self, f"No se pudo conectar: {_friendly(exc)}")

    def save_db(self):
        cfg = self.ctx.config
        url = self._pg_url_value()
        mode = "postgres" if self.r_pg.isChecked() else "sqlite"
        if mode == "postgres" and not url:
            show_error(self, "Para trabajar en Postgres escriba la URL")
            return
        if mode == "postgres" and cfg.db_mode != "postgres":
            if not confirm(self, "Al reiniciar, la app trabajará directamente en el servidor. Los datos locales NO se "
                                 "copian solos: primero use «Sincronizar ahora» para subirlos. ¿Continuar?"):
                return
        cfg.db_mode = mode
        cfg.postgres_url = url
        cfg.sync_enabled = self.sync_enabled.isChecked()
        cfg.sync_interval_min = self.sync_minutes.value()
        cfg.save()
        info(self, "Guardado. Cierre y vuelva a abrir la aplicación para aplicar el cambio de base de datos.",
             "Configuración")

    def sync_now(self):
        cfg = self.ctx.config
        url = self._pg_url_value()
        if not url:
            show_error(self, "Escriba y guarde la URL de Postgres primero")
            return
        if not self.ctx.db.is_sqlite:
            show_error(self, "La app ya está trabajando directamente en Postgres; no hace falta sincronizar.")
            return
        if url != cfg.postgres_url:
            cfg.postgres_url = url
            cfg.save()
        win = self.window()
        if hasattr(win, "sync_now"):
            started = win.sync_now(on_done=self._sync_done)
            if started:
                self.sync_info.setText("Sincronizando…")
            else:
                toast(self, "Ya hay una sincronización en curso")

    def _sync_done(self, result):
        self._refresh_sync_info()
        if result.ok:
            toast(self, f"Sincronización lista: {result.text()}")
        else:
            show_error(self, result.text())

    def _refresh_sync_info(self):
        from granizapp.core.services.sync import pending_count

        if not self.ctx.db.is_sqlite:
            self.sync_info.setText("Trabajando directamente en Postgres.")
            return
        last = self.ctx.db.get_meta("last_sync", "")
        try:
            pending = pending_count(self.ctx.db)
        except Exception:
            pending = 0
        self.sync_info.setText(f"Última sincronización: {last.replace('T', ' ') if last else 'nunca'} · "
                               f"cambios pendientes por subir: {pending}")

    # --- respaldos -----------------------------------------------------------------------------------
    def _backup_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        frame, fl = card(title="Respaldos automáticos")
        fl.addWidget(label("Se hace una copia de la base local cada día al abrir y al cerrar la app. "
                           "Guarde la carpeta en OneDrive/Google Drive o una USB para no perder nada.", "Muted", wrap=True))
        form = QFormLayout()
        self.bk_dir = QLineEdit()
        pick = QPushButton("Cambiar…")
        pick.clicked.connect(self._pick_backup_dir)
        row = QHBoxLayout()
        row.addWidget(self.bk_dir, 1)
        row.addWidget(pick)
        rw = QWidget()
        rw.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        self.bk_keep = QSpinBox()
        self.bk_keep.setRange(3, 365)
        form.addRow("Carpeta", rw)
        form.addRow("Conservar los últimos", self.bk_keep)
        fl.addLayout(form)
        btns = QHBoxLayout()
        btns.addWidget(button("Guardar", self._save_backup_cfg))
        btns.addWidget(button("Respaldar ahora", self.backup_now, "Primary"))
        btns.addWidget(button("Abrir carpeta", lambda: os.startfile(str(self.ctx.config.resolved_backup_dir))
                              if self.ctx.config.resolved_backup_dir.exists() else None))
        btns.addWidget(button("Restaurar el seleccionado…", self.restore, "Danger"))
        btns.addStretch(1)
        fl.addLayout(btns)
        self.bk_list = QListWidget()
        fl.addWidget(self.bk_list, 1)
        lay.addWidget(frame, 1)
        return w

    def _pick_backup_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Carpeta de respaldos", self.bk_dir.text())
        if path:
            self.bk_dir.setText(path)

    def _save_backup_cfg(self):
        self.ctx.config.backup_dir = self.bk_dir.text().strip()
        self.ctx.config.backup_keep = self.bk_keep.value()
        self.ctx.config.save()
        self._load_backups()
        toast(self, "Configuración de respaldos guardada")

    def _load_backups(self):
        self.bk_list.clear()
        for p in backup.list_backups(self.ctx.config.resolved_backup_dir):
            self.bk_list.addItem(f"{p.name}   ·   {p.stat().st_size / 1024:,.0f} KB")
            self.bk_list.item(self.bk_list.count() - 1).setData(Qt.UserRole, str(p))

    def backup_now(self):
        if not self.ctx.db.is_sqlite:
            show_error(self, "Con Postgres directo los respaldos los hace el proveedor del servidor.")
            return
        try:
            with busy():
                path = backup.backup_sqlite(self.ctx.config.resolved_sqlite_path, self.ctx.config.resolved_backup_dir,
                                            self.ctx.config.backup_keep, tag="manual")
            self._load_backups()
            toast(self, f"Respaldo creado: {path.name}")
        except Exception as exc:
            show_error(self, exc)

    def restore(self):
        item = self.bk_list.currentItem()
        if item is None or not self.ctx.db.is_sqlite:
            return
        path = Path(item.data(Qt.UserRole))
        if not confirm(self, f"¿Restaurar «{path.name}»?\nLos datos actuales se reemplazan (se guarda una copia de "
                             "seguridad antes). La aplicación se cerrará.", danger=True, yes="Restaurar y cerrar"):
            return
        try:
            self.ctx.db.dispose()
            safety = backup.restore(path, self.ctx.config.resolved_sqlite_path)
            info(self, f"Restaurado. Copia de los datos anteriores: {safety.name}\nVuelva a abrir la aplicación.")
            from PySide6.QtWidgets import QApplication

            QApplication.instance().quit()
        except Exception as exc:
            show_error(self, exc)

    # --- importación ------------------------------------------------------------------------------
    def _import_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        frame, fl = card(title="Importar desde los Excel anteriores")
        fl.addWidget(label("Trae el historial de ventas (Lista de Ventas) y de gastos/ingresos (Dashboard Balance) "
                           "para que los reportes muestren todo desde el primer día.", "Muted", wrap=True))
        row = QHBoxLayout()
        row.addWidget(button("Importar…", self.open_import, "Primary"))
        row.addWidget(button("Borrar lo importado", self.remove_import, "Danger"))
        row.addStretch(1)
        fl.addLayout(row)
        lay.addWidget(frame)
        lay.addStretch(1)
        return w

    def open_import(self):
        from granizapp.ui.import_dialog import ImportDialog

        ImportDialog(self, self.ctx).exec()

    def remove_import(self):
        if not confirm(self, "¿Borrar todas las ventas, gastos y movimientos que vinieron del Excel?", danger=True,
                       yes="Borrar"):
            return
        from granizapp.core.services.excel_import import remove_previous_import

        def do():
            with self.ctx.session() as s:
                return remove_previous_import(s)

        n = run(self, do)
        if n is not None:
            self.ctx.notify(Topics.ALL)
            toast(self, f"Se borraron {n} registros importados")

    # --- usuarios ------------------------------------------------------------------------------------
    def clear_pin(self):
        u = self.users_panel.table.current()
        if u is None or not confirm(self, f"¿Quitar el PIN de {u.name}?"):
            return

        def do():
            with self.ctx.session() as s:
                auth.clear_pin(s, u.id, self.ctx.actor)
            return True

        if run(self, do):
            self.users_panel.refresh()

    # --- refresco -----------------------------------------------------------------------------------
    def refresh(self):
        cfg = self.ctx.config
        with self.ctx.session() as s:
            self.b_name.setText(get_setting(s, "business_name") or "")
            self.b_nit.setText(get_setting(s, "business_nit") or "")
            self.b_phone.setText(get_setting(s, "business_phone") or "")
            self.b_address.setText(get_setting(s, "business_address") or "")
            self.b_city.setText(get_setting(s, "business_city") or "")
            self.b_footer.setText(get_setting(s, "ticket_footer") or "")
            self.b_base.setValue(int(get_setting(s, "default_cash_base") or 0))
            self.b_flavor_req.setChecked(bool(get_setting(s, "require_flavor")))
            self.b_cover.setValue(int(get_setting(s, "flavor_cover_weeks") or 2))
            accounts = finance.list_accounts(s, include_inactive=True)
        self.acc_names = {a.id: a.name for a in accounts}
        self.b_theme.setCurrentIndex(max(0, self.b_theme.findData(cfg.theme)))
        self.d_name.setText(cfg.device_name)
        self.d_id.setText(cfg.device_id)
        self.d_drawer.clear()
        self.d_drawer.addItem("— Usar el cajón principal —", "")
        for a in accounts:
            if a.is_drawer and a.active:
                self.d_drawer.addItem(a.name, a.id)
        self.d_drawer.setCurrentIndex(max(0, self.d_drawer.findData(cfg.drawer_account_id or "")))
        self.paths_lbl.setText(
            f"Base de datos local: {cfg.resolved_sqlite_path}\nConfiguración: {app_home() / 'config.json'}\n"
            f"Registros (logs): {app_home() / 'logs'}\nRespaldos: {cfg.resolved_backup_dir}")
        mode = "Postgres en línea" if not self.ctx.db.is_sqlite else "Base local (SQLite)"
        self.db_status.setText(f"Ahora: {mode} · {mask_url(self.ctx.db.url)}")
        self.r_pg.setChecked(cfg.db_mode == "postgres")
        self.r_sqlite.setChecked(cfg.db_mode != "postgres")
        self.pg_url.setText(cfg.postgres_url)
        self.sync_enabled.setChecked(cfg.sync_enabled)
        self.sync_minutes.setValue(cfg.sync_interval_min or 10)
        self._refresh_sync_info()
        self.bk_dir.setText(str(cfg.resolved_backup_dir))
        self.bk_keep.setValue(cfg.backup_keep)
        self._load_backups()
        self.methods_panel.refresh()
        self.users_panel.refresh()
