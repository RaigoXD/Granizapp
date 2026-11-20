"""Ingreso con PIN y asistente de primer uso."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from granizapp import APP_NAME
from granizapp.config import AppConfig
from granizapp.core.db import Database
from granizapp.core.models import Role, User
from granizapp.core.services import auth
from granizapp.core.services.common import Actor
from granizapp.core.services.settings import get_setting, set_setting
from granizapp.ui.widgets.common import label, show_error
from granizapp.ui.widgets.forms import MoneyEdit


class LoginDialog(QDialog):
    def __init__(self, db: Database, config: AppConfig):
        super().__init__()
        self.db = db
        self.config = config
        self.actor: Actor | None = None
        self.setWindowTitle(f"{APP_NAME} · Ingresar")
        self.setMinimumSize(380, 420)
        with db.session() as s:
            self.users = auth.list_users(s)
            business = get_setting(s, "business_name")
        lay = QVBoxLayout(self)
        lay.addWidget(label(business or APP_NAME, "PageTitle"))
        lay.addWidget(label("Elija su usuario y escriba el PIN", "Muted"))
        self.list = QListWidget()
        for u in self.users:
            item = QListWidgetItem(f"{u.name}   ·   {Role.LABELS.get(u.role, u.role)}")
            item.setData(Qt.UserRole, u.id)
            self.list.addItem(item)
            if u.username == config.last_username:
                self.list.setCurrentItem(item)
        if self.list.currentRow() < 0 and self.users:
            self.list.setCurrentRow(0)
        lay.addWidget(self.list, 1)
        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.Password)
        self.pin.setPlaceholderText("PIN")
        self.pin.setObjectName("BigInput")
        self.pin.returnPressed.connect(self.accept)
        lay.addWidget(self.pin)
        self.error = label("", "Danger")
        lay.addWidget(self.error)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Ingresar")
        bb.button(QDialogButtonBox.Ok).setObjectName("Primary")
        bb.button(QDialogButtonBox.Cancel).setText("Salir")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.list.itemActivated.connect(lambda _i: self.pin.setFocus())
        self.pin.setFocus()

    def accept(self):
        item = self.list.currentItem()
        if item is None:
            return
        try:
            with self.db.session() as s:
                self.actor = auth.authenticate(s, item.data(Qt.UserRole), self.pin.text(), self.config.device_id)
                user = s.get(User, self.actor.user_id)
                self.config.last_username = user.username
            self.config.save()
            super().accept()
        except Exception as exc:
            self.error.setText(str(exc))
            self.pin.selectAll()
            self.pin.setFocus()


class SetupWizard(QDialog):
    """Primer uso: datos del negocio, base de caja y (opcional) PIN del administrador."""

    def __init__(self, db: Database, config: AppConfig):
        super().__init__()
        self.db = db
        self.config = config
        self.want_import = False
        self.setWindowTitle(f"Bienvenido a {APP_NAME}")
        self.setMinimumWidth(520)
        with db.session() as s:
            name = get_setting(s, "business_name")
            base = int(get_setting(s, "default_cash_base") or 0)
        lay = QVBoxLayout(self)
        lay.addWidget(label(f"Bienvenido a {APP_NAME}", "PageTitle"))
        lay.addWidget(label(
            "Ya quedaron cargados los productos, insumos, recetas de referencia, medios de pago "
            "(Efectivo, Nequi, Transferencia, Daviplata, Tarjeta) y las categorías de gastos. "
            "Todo se puede cambiar después en Configuración y Productos.", "Muted", wrap=True))
        form = QFormLayout()
        self.business = QLineEdit(name or "")
        self.nit = QLineEdit()
        self.phone = QLineEdit()
        self.city = QLineEdit()
        self.base = MoneyEdit(base)
        self.device = QLineEdit(config.device_name)
        self.admin_name = QLineEdit("Administrador")
        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.Password)
        self.pin.setPlaceholderText("Opcional: 4 a 8 números")
        form.addRow("Nombre del negocio *", self.business)
        form.addRow("NIT / documento", self.nit)
        form.addRow("Teléfono", self.phone)
        form.addRow("Ciudad", self.city)
        form.addRow("Base de caja habitual", self.base)
        form.addRow("Nombre de este equipo", self.device)
        form.addRow("Su nombre (administrador)", self.admin_name)
        form.addRow("PIN del administrador", self.pin)
        lay.addLayout(form)
        hint = QLabel("Si deja el PIN vacío, la aplicación abre sin pedir ingreso. Cuando cree usuarios con PIN "
                      "para el personal, el bartender solo verá Vender, Caja, Deudores, Ventas e Inventario.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.import_cb = QCheckBox("Importar ahora el historial desde los Excel (Lista de Ventas y Dashboard Balance)")
        self.import_cb.setChecked(True)
        lay.addWidget(self.import_cb)
        bb = QDialogButtonBox(QDialogButtonBox.Ok)
        bb.button(QDialogButtonBox.Ok).setText("Empezar")
        bb.button(QDialogButtonBox.Ok).setObjectName("Primary")
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)

    def accept(self):
        if not self.business.text().strip():
            show_error(self, "Escriba el nombre del negocio")
            return
        try:
            with self.db.session() as s:
                set_setting(s, "business_name", self.business.text().strip())
                set_setting(s, "business_nit", self.nit.text().strip())
                set_setting(s, "business_phone", self.phone.text().strip())
                set_setting(s, "business_city", self.city.text().strip())
                set_setting(s, "default_cash_base", self.base.value())
                admin = s.get(User, "seed-user-admin")
                if admin is not None:
                    data = {"name": self.admin_name.text().strip() or "Administrador", "username": "admin",
                            "role": Role.ADMIN, "active": True}
                    if self.pin.text().strip():
                        data["pin"] = self.pin.text().strip()
                    auth.save_user(s, data, admin.id)
                set_setting(s, "setup_done", True)
            self.config.device_name = self.device.text().strip() or self.config.device_name
            self.config.save()
            self.want_import = self.import_cb.isChecked()
            super().accept()
        except Exception as exc:
            show_error(self, exc)
