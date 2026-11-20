import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from granizapp.core.db import Database, set_db  # noqa: E402
from granizapp.core.services.common import Actor  # noqa: E402
from granizapp.core.services.seed import seed_defaults  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANIZAPP_HOME", str(tmp_path))
    database = Database(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    database.init_schema()
    with database.session() as s:
        seed_defaults(s)
    set_db(database)
    yield database
    set_db(None)
    database.dispose()


@pytest.fixture(autouse=True)
def _restore_excepthook():
    """app.main() instala un manejador global de errores con ventana; en pruebas se restaura
    el normal para que los errores se vean en la consola."""
    original = sys.excepthook
    yield
    sys.excepthook = original if original is not None else sys.__excepthook__


@pytest.fixture()
def actor():
    return Actor(user_id="seed-user-admin", device_id="T1", user_name="Admin", role="admin")


def pytest_configure(config):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_sessionfinish(session, exitstatus):
    """Cerrar las ventanas de las pruebas antes de que Python destruya QApplication."""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    if QApplication.instance() is not None:
        from granizapp.app import close_windows

        close_windows()
        import gc

        gc.collect()
