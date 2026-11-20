"""Arranque de la aplicación de escritorio."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from granizapp import APP_NAME, __version__
from granizapp.config import AppConfig, mask_url
from granizapp.core import backup
from granizapp.core.db import Database, set_db
from granizapp.core.services import auth
from granizapp.core.services.seed import seed_defaults
from granizapp.core.services.settings import get_setting
from granizapp.paths import app_home, resource_path
from granizapp.ui.context import AppContext, Bus
from granizapp.ui.theme import apply_theme

log = logging.getLogger("granizapp")


def setup_logging():
    logs = app_home() / "logs"
    logs.mkdir(exist_ok=True)
    handler = RotatingFileHandler(logs / "granizapp.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    def excepthook(exc_type, exc, tb):
        log.critical("Error no controlado", exc_info=(exc_type, exc, tb))
        try:
            QMessageBox.critical(None, "Error inesperado", f"{exc}\n\nEl detalle quedó en {logs}")
        except Exception:
            pass

    sys.excepthook = excepthook


def open_database(config: AppConfig) -> Database | None:
    while True:
        db = Database(config.database_url())
        try:
            fresh = db.init_schema()
            with db.session() as s:
                seed_defaults(s)
            log.info("Base de datos lista (%s, nueva=%s)", mask_url(db.url), fresh)
            return db
        except Exception as exc:
            log.exception("No se pudo abrir la base de datos")
            db.dispose()
            if config.db_mode == "postgres":
                ans = QMessageBox.question(
                    None, "Sin conexión a Postgres",
                    f"No se pudo conectar al servidor Postgres:\n\n{str(exc).splitlines()[0]}\n\n"
                    "¿Trabajar con la base local de este equipo? (Podrá volver a Postgres en Configuración.)",
                )
                if ans == QMessageBox.Yes:
                    config.db_mode = "sqlite"
                    config.save()
                    continue
            else:
                QMessageBox.critical(None, "Error", f"No se pudo abrir la base de datos local:\n\n{exc}")
            return None


def daily_backup(config: AppConfig, db: Database):
    if not db.is_sqlite:
        return
    try:
        dest = config.resolved_backup_dir
        if not backup.backed_up_today(dest):
            path = backup.backup_sqlite(config.resolved_sqlite_path, dest, config.backup_keep)
            log.info("Respaldo diario: %s", path)
    except Exception:
        log.exception("No se pudo hacer el respaldo diario")


def diagnostics(config: AppConfig) -> str:
    """`GranizApp.exe --diagnostico`: revisa base de datos y conexión a Postgres sin abrir ventanas."""
    import platform

    lines = [f"{APP_NAME} {__version__} · Python {platform.python_version()} · {platform.platform()}",
             f"Carpeta de datos: {app_home()}", f"Modo: {config.db_mode} · {mask_url(config.database_url())}"]
    try:
        db = Database(config.database_url())
        db.init_schema()
        with db.session() as s:
            seed_defaults(s)
            from granizapp.core.services import catalog

            lines.append(f"Base de datos OK · {len(catalog.list_products(s))} productos activos")
        db.dispose()
    except Exception as exc:
        lines.append(f"Base de datos ERROR: {exc}")
    try:
        import psycopg

        lines.append(f"psycopg {psycopg.__version__} · implementación {psycopg.pq.__impl__}")
    except Exception as exc:
        lines.append(f"psycopg ERROR: {exc}")
    import os

    url = os.environ.get("GRANIZAPP_TEST_PG") or config.postgres_url
    if url:
        from granizapp.config import normalize_pg_url
        from granizapp.core.services.sync import check_connection

        try:
            lines.append(f"Postgres OK: {check_connection(normalize_pg_url(url))}")
        except Exception as exc:
            lines.append(f"Postgres ERROR: {exc}")
    try:  # ayuda: los tutoriales se cargan y la hoja de atajos sale en PDF
        from granizapp.help import render
        from granizapp.help.content import ALL
        from granizapp.ui.help_ui import export_pdf

        _app = QApplication.instance() or QApplication(["granizapp"])  # plataforma normal: fuentes reales
        probe = app_home() / "diagnostico_ayuda.pdf"
        pages = export_pdf(probe, render.cheatsheet_html())
        probe.unlink(missing_ok=True)
        from PySide6.QtPrintSupport import QPrinter  # noqa: F401  (impresión disponible)

        lines.append(f"Ayuda OK · {len(ALL)} temas · hoja de atajos en PDF: {pages} página(s) · impresión disponible")
    except Exception as exc:
        lines.append(f"Ayuda ERROR: {exc}")
    text = "\n".join(lines)
    (app_home() / "diagnostico.txt").write_text(text, encoding="utf-8")
    return text


def reset_admin_pins(config: AppConfig) -> int:
    """`GranizApp.exe --restablecer-pin`: quita el PIN de los administradores (si nadie lo recuerda)."""
    db = open_database(config)
    if db is None:
        return 1
    ans = QMessageBox.question(
        None, "Restablecer PIN",
        "Se quitará el PIN de todos los administradores para que puedan entrar y poner uno nuevo en "
        "Configuración › Usuarios. Quedará registrado en la bitácora.\n\n¿Continuar?")
    if ans != QMessageBox.Yes:
        db.dispose()
        return 0
    from granizapp.core.models import Role, User
    from granizapp.core.services.common import SYSTEM, audit

    with db.session() as s:
        admins = [u for u in auth.list_users(s, include_inactive=True) if u.role == Role.ADMIN]
        for u in admins:
            s.get(User, u.id).pin_hash = ""
        audit(s, SYSTEM, "restablecer_pin", "user", "", f"{len(admins)} administradores quedaron sin PIN")
    db.dispose()
    QMessageBox.information(None, "Restablecer PIN", "Listo. Abra la aplicación normalmente y ponga un PIN nuevo.")
    return 0


def main(argv=None) -> int:
    setup_logging()
    args = argv or sys.argv
    if "--diagnostico" in args:
        print(diagnostics(AppConfig.load()))
        return 0
    app = QApplication.instance() or QApplication(args)
    if "--restablecer-pin" in args:
        apply_theme(app, "light")
        return reset_admin_pins(AppConfig.load())
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    icon = resource_path("granizapp/assets/icon.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    config = AppConfig.load()
    apply_theme(app, config.theme)
    db = open_database(config)
    if db is None:
        return 1
    set_db(db)
    daily_backup(config, db)

    from granizapp.ui.startup import LoginDialog, SetupWizard

    with db.session() as s:
        setup_done = bool(get_setting(s, "setup_done"))
    if not setup_done:
        wizard = SetupWizard(db, config)
        if wizard.exec() != QDialog.Accepted:
            return 0
        want_import = wizard.want_import
    else:
        want_import = False

    state = {"window": None}

    def start_session() -> bool:
        with db.session() as s:
            needs_login = auth.login_required(s)
            actor = None if needs_login else auth.default_actor(s, config.device_id)
        if needs_login:
            dlg = LoginDialog(db, config)
            if dlg.exec() != QDialog.Accepted:
                return False
            actor = dlg.actor
        from granizapp.ui.main_window import MainWindow

        ctx = AppContext(config=config, db=db, actor=actor, bus=Bus())
        win = MainWindow(ctx)
        win.logout_requested.connect(lambda: restart(win))
        state["window"] = win
        win.showMaximized()
        return True

    def restart(win):
        win.close()
        win.deleteLater()
        if not start_session():
            app.quit()

    if not start_session():
        return 0
    win = state["window"]
    if want_import:
        from granizapp.ui.import_dialog import ImportDialog

        ImportDialog(win, win.ctx).exec()
        win.ctx.notify("*")
    if not config.welcome_seen:
        # la primera vez (también al actualizar desde una versión sin ayuda) se muestran los primeros pasos
        from granizapp.ui.help_ui import HelpDialog

        config.welcome_seen = True
        config.save()
        HelpDialog(win, "inicio", on_all=win.open_help_topic, title="Bienvenido a GranizApp · Primeros pasos").exec()
    code = app.exec()
    daily_backup(config, db)
    close_windows()
    db.dispose()
    return code


def close_windows() -> None:
    """Destruye las ventanas mientras Qt sigue vivo: si quedan para el final de Python, Windows
    puede mostrar un error al cerrar la aplicación (los datos ya están guardados)."""
    from PySide6.QtCore import QEvent

    for w in QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QApplication.processEvents()


if __name__ == "__main__":
    sys.exit(main())
