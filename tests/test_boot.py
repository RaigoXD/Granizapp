"""Arranque real de la aplicación en un proceso aparte (asistente, bienvenida, PIN, cierre limpio).

Va en un subproceso porque, una vez que la app termina su ciclo (app.exec y salida), Qt queda en
estado «cerrando» y afectaría a las demás pruebas del mismo proceso.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DRIVER = r'''
import json, os, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
app = QApplication([])
log = []
mode = sys.argv[2]

def tick():
    w = QApplication.activeModalWidget()
    name = type(w).__name__ if w else None
    if name == "SetupWizard":
        w.business.setText("The Spot")
        w.import_cb.setChecked(False)
        if mode == "pin":
            w.pin.setText("1234")
        log.append("wizard"); w.accept()
    elif name == "LoginDialog":
        w.pin.setText("9999"); w.accept(); log.append("bad:" + w.error.text())
        w.pin.setText("1234"); w.accept(); log.append("login")
    elif name == "HelpDialog":
        log.append("welcome:" + (w.browser.current_key or "")); w.accept()
    elif w is None and log and log[-1] != "main":
        win = next((x for x in QApplication.topLevelWidgets()
                    if type(x).__name__ == "MainWindow" and x.isVisible()), None)
        if win is not None and any(e.startswith("welcome") for e in log):
            log.append("main"); win.close(); app.quit(); return
    QTimer.singleShot(50, tick)

QTimer.singleShot(50, tick)
guard = QTimer(); guard.setSingleShot(True); guard.timeout.connect(app.quit); guard.start(20000)
from granizapp.app import main
code = main(["granizapp"])
from granizapp.config import AppConfig
print(json.dumps({"code": code, "log": log, "welcome_seen": AppConfig.load().welcome_seen}))
'''


def _run(tmp_path, mode: str) -> dict:
    env = dict(os.environ, GRANIZAPP_HOME=str(tmp_path / "home"), QT_QPA_PLATFORM="offscreen",
               PYTHONIOENCODING="utf-8")
    out = subprocess.run([sys.executable, "-c", DRIVER, str(ROOT), mode], capture_output=True, text=True,
                         encoding="utf-8", env=env, timeout=120)
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_first_run_wizard_welcome_and_clean_exit(tmp_path):
    res = _run(tmp_path, "nopin")
    assert res["code"] == 0
    assert res["log"] == ["wizard", "welcome:inicio", "main"]
    assert res["welcome_seen"] is True
    # la segunda vez ya no muestra asistente ni bienvenida
    res2 = _run(tmp_path, "nopin")
    assert "wizard" not in res2["log"] and not any(x.startswith("welcome") for x in res2["log"])


def test_first_run_with_pin_requires_login(tmp_path):
    res = _run(tmp_path, "pin")
    assert res["log"][:3] == ["wizard", "bad:PIN incorrecto", "login"]
    assert res["log"][-2:] == ["welcome:inicio", "main"]
