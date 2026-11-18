import json
import re
import sys
import time
from datetime import date, datetime

from api_client import ApiClient, ApiError
from PySide6.QtCore import Qt, QDateTime, QSettings, QThread, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QDateTimeEdit,
    QVBoxLayout,
    QWidget,
)


MAROON = "#420D18"
DARK = "#2B0910"
GOLD = "#D4AF37"
BACKGROUND = "#F4F1EC"
MUTED_GOLD = "#A16C19"
APP_NAME = "SIMPATI Developer Desktop"
APP_VERSION = "0.1.0-dev"
APP_DEVELOPER = "SIMPATI"
WINDOW_SIZES = {
    "1024x680": (1024, 680),
    "1280x780": (1280, 780),
    "1440x900": (1440, 900),
}


def settings_store():
    return QSettings("SIMPATI", "DeveloperDesktop")


def apply_saved_branding():
    global MAROON, GOLD
    settings = settings_store()
    primary = QColor(settings.value("branding/primary_color", MAROON))
    accent = QColor(settings.value("branding/accent_color", GOLD))
    if primary.isValid():
        MAROON = primary.name()
    if accent.isValid():
        GOLD = accent.name()


def make_title(text):
    label = QLabel(text)
    label.setObjectName("pageTitle")
    return label


def make_status_label(text):
    label = QLabel(text)
    label.setObjectName("connectionStatus")
    return label


class FormDialog(QDialog):
    def __init__(
        self,
        title,
        fields,
        initial_values=None,
        parent=None,
        submit_handler=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self.fields = fields
        self.inputs = {}
        self.submit_handler = submit_handler

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(12)
        initial_values = initial_values or {}

        for field_spec in fields:
            field_name, required = field_spec[:2]
            choices = field_spec[2] if len(field_spec) > 2 else None
            if choices:
                field = QComboBox()
                field.addItems(choices)
                initial_value = initial_values.get(field_name, choices[0])
                if initial_value in choices:
                    field.setCurrentText(initial_value)
            else:
                field = QLineEdit()
                field.setText(initial_values.get(field_name, ""))
                field.setPlaceholderText(
                    "Wajib diisi" if required else "Opsional"
                )
            self.inputs[field_name] = field
            form.addRow(field_name, field)
        self.form_layout = form

        layout.addLayout(form)
        self.validation_message = QLabel(
            "Validasi formulir tidak akan mengirim atau menyimpan data."
        )
        self.validation_message.setWordWrap(True)
        self.validation_message.setObjectName("subtleText")
        layout.addWidget(self.validation_message)

        buttons = QHBoxLayout()
        self.submit_button = QPushButton(
            "Simpan" if submit_handler else "Validasi"
        )
        self.submit_button.clicked.connect(self.submit_form)
        self.close_button = QPushButton("Tutup")
        self.close_button.setObjectName("secondaryButton")
        self.close_button.clicked.connect(self.close)
        buttons.addStretch()
        buttons.addWidget(self.submit_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

    def value(self, field_name):
        field = self.inputs[field_name]
        if isinstance(field, QComboBox):
            return field.currentText()
        return field.text()

    def values(self):
        return {
            field_name: self.value(field_name)
            for field_name in self.inputs
        }

    def submit_form(self):
        if not self.validate_form():
            return False
        if self.submit_handler:
            self.submit_handler(self)
        return True

    def set_busy(self, busy):
        for field in self.inputs.values():
            field.setEnabled(not busy)
        self.submit_button.setEnabled(not busy)
        self.close_button.setEnabled(not busy)

    def show_error(self, message):
        self.validation_message.setText(message)
        self.validation_message.setStyleSheet("color:#A32323;")

    def validate_form(self):
        missing = [
            field_name
            for field_name, required, *_ in self.fields
            if required and not self.value(field_name).strip()
        ]
        if missing:
            self.validation_message.setText(
                "Lengkapi kolom wajib: " + ", ".join(missing) + "."
            )
            self.validation_message.setStyleSheet("color:#A32323;")
            return False

        if self.submit_handler:
            self.validation_message.setText("Input valid.")
        else:
            self.validation_message.setText(
                "Input valid. Data belum disimpan; formulir ini belum mengirim "
                "data ke API."
            )
        self.validation_message.setStyleSheet(f"color:{MUTED_GOLD};")
        return True


class LoginDialog(QDialog):
    def __init__(
        self, api_client, initial_error=None, parent=None, initial_message=None
    ):
        super().__init__(parent)
        self.api_client = api_client
        self.user = None
        self.setWindowTitle("Login Developer")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.addWidget(make_title("Login Developer"))
        description = QLabel(
            "Masuk menggunakan akun Developer SIMPATI. Kredensial "
            "tidak disimpan di aplikasi."
        )
        description.setObjectName("subtleText")
        description.setWordWrap(True)
        layout.addWidget(description)

        form = QFormLayout()
        self.api_url = QLineEdit(
            settings_store().value("api/base_url", "")
        )
        self.api_url.setPlaceholderText("https://alamat-universal-api")
        self.username = QLineEdit()
        self.username.setPlaceholderText("Username Developer")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("URL dasar Universal API", self.api_url)
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        layout.addLayout(form)

        self.status = QLabel(
            initial_error or initial_message or "API belum diperiksa."
        )
        self.status.setObjectName("subtleText")
        self.status.setWordWrap(True)
        if initial_error:
            self.status.setStyleSheet("color:#A32323;")
        elif initial_message:
            self.status.setStyleSheet(f"color:{MUTED_GOLD};")
        layout.addWidget(self.status)

        buttons = QDialogButtonBox()
        self.login_button = buttons.addButton(
            "Masuk", QDialogButtonBox.ButtonRole.AcceptRole
        )
        cancel_button = buttons.addButton(
            "Keluar", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.login_button.clicked.connect(self.login)
        cancel_button.clicked.connect(self.reject)
        self.password.returnPressed.connect(self.login)
        layout.addWidget(buttons)

    def login(self):
        base_url = self.api_url.text().strip()
        try:
            base_url = ApiClient.validate_base_url(base_url)
            settings = settings_store()
            settings.setValue("api/base_url", base_url)
            settings.sync()
            if settings.status() != QSettings.Status.NoError:
                raise ApiError("URL API gagal disimpan ke pengaturan lokal.")

            self.api_client.set_base_url(base_url)
            self.login_button.setEnabled(False)
            self.status.setStyleSheet("")
            self.status.setText("Memeriksa koneksi Universal API...")
            QApplication.processEvents()
            self.api_client.check_connection()
            self.status.setText("API terhubung. Memverifikasi akun Developer...")
            QApplication.processEvents()
            self.user = self.api_client.developer_login(
                self.username.text().strip(), self.password.text()
            )
        except ApiError as exc:
            self.status.setText(str(exc))
            self.status.setStyleSheet("color:#A32323;")
            self.login_button.setEnabled(True)
            return

        self.password.clear()
        self.accept()


class PasswordChangeDialog(QDialog):
    MIN_PASSWORD_LENGTH = 12

    def __init__(self, api_client, user, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.setWindowTitle("Ganti Password Developer")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.addWidget(make_title("Ganti Password"))
        description = QLabel(
            f"Akun {user.get('username', 'Developer')} wajib mengganti "
            "password sebelum dapat membuka Dashboard."
        )
        description.setObjectName("subtleText")
        description.setWordWrap(True)
        layout.addWidget(description)

        form = QFormLayout()
        self.current_password = QLineEdit()
        self.new_password = QLineEdit()
        self.confirm_password = QLineEdit()
        for field in (
            self.current_password,
            self.new_password,
            self.confirm_password,
        ):
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setMaxLength(256)
        self.current_password.setPlaceholderText("Password saat ini")
        self.new_password.setPlaceholderText(
            f"Minimal {self.MIN_PASSWORD_LENGTH} karakter"
        )
        self.confirm_password.setPlaceholderText("Ulangi password baru")
        form.addRow("Password saat ini", self.current_password)
        form.addRow("Password baru", self.new_password)
        form.addRow("Konfirmasi password baru", self.confirm_password)
        layout.addLayout(form)

        self.status = QLabel(
            f"Password baru harus minimal {self.MIN_PASSWORD_LENGTH} karakter. "
            "Setelah berhasil, Anda harus login kembali."
        )
        self.status.setObjectName("subtleText")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox()
        self.change_button = buttons.addButton(
            "Ganti Password", QDialogButtonBox.ButtonRole.AcceptRole
        )
        cancel_button = buttons.addButton(
            "Keluar", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.change_button.clicked.connect(self.change_password)
        cancel_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

    def change_password(self):
        current_password = self.current_password.text()
        new_password = self.new_password.text()
        if not current_password:
            self._show_error("Password saat ini wajib diisi.")
            return
        if len(new_password) < self.MIN_PASSWORD_LENGTH:
            self._show_error(
                f"Password baru minimal {self.MIN_PASSWORD_LENGTH} karakter."
            )
            return
        if new_password != self.confirm_password.text():
            self._show_error("Konfirmasi password baru tidak cocok.")
            return

        self.change_button.setEnabled(False)
        try:
            self.api_client.change_password(
                current_password, new_password
            )
        except ApiError as exc:
            self._show_error(str(exc))
            self.change_button.setEnabled(True)
            return
        self.status.setText(
            "Password berhasil diganti. Silakan login kembali dengan password "
            "baru."
        )
        self.accept()

    def _show_error(self, message):
        self.status.setText(message)
        self.status.setStyleSheet("color:#A32323;")

    def done(self, result):
        self.current_password.clear()
        self.new_password.clear()
        self.confirm_password.clear()
        super().done(result)


def authenticate_user(
    api_client, initial_error=None, parent=None, initial_user=None
):
    user = initial_user
    initial_message = None
    while True:
        if user is None:
            login_dialog = LoginDialog(
                api_client,
                initial_error=initial_error,
                parent=parent,
                initial_message=initial_message,
            )
            if login_dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            user = login_dialog.user

        if user.get("must_change_password") is not True:
            return user

        password_dialog = PasswordChangeDialog(api_client, user, parent)
        if password_dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        user = None
        initial_error = None
        initial_message = (
            "Password berhasil diganti. Login kembali menggunakan password "
            "baru."
        )


class ConnectionCheckWorker(QThread):
    checked = Signal(bool, str)

    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client

    def run(self):
        try:
            self.api_client.check_connection()
        except ApiError as exc:
            self.checked.emit(False, str(exc))
        else:
            self.checked.emit(True, "API: TERHUBUNG")


class DashboardMonitoringWorker(QThread):
    checked = Signal(object)

    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client

    def run(self):
        started = time.perf_counter()
        try:
            self.api_client.check_connection()
        except ApiError as exc:
            connected = False
            message = str(exc)
        else:
            connected = True
            message = "API: TERHUBUNG"
        response_ms = round((time.perf_counter() - started) * 1000, 2)
        checked_at = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )

        database_started = time.perf_counter()
        try:
            self.api_client.check_database_readiness()
        except ApiError as exc:
            if exc.status_code == 503:
                database_status = "OFFLINE"
                database_message = (
                    "Universal API melaporkan readiness database gagal "
                    "(HTTP 503)."
                )
            elif exc.status_code == 404:
                database_status = "N/D"
                database_message = (
                    "Endpoint GET /health/ready tidak tersedia pada "
                    "Universal API ini (HTTP 404)."
                )
            else:
                database_status = "N/D"
                database_message = (
                    f"Status database tidak dapat dipastikan: {exc}"
                )
        else:
            database_status = "ONLINE"
            database_message = (
                "GET /health/ready mengonfirmasi status ONLINE/CONNECTED."
            )
        database_response_ms = round(
            (time.perf_counter() - database_started) * 1000, 2
        )
        database_checked_at = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        self.checked.emit(
            {
                "api": {
                    "connected": connected,
                    "message": message,
                    "response_ms": response_ms,
                    "checked_at": checked_at,
                },
                "database": {
                    "status": database_status,
                    "message": database_message,
                    "response_ms": database_response_ms,
                    "checked_at": database_checked_at,
                },
            }
        )


class DashboardLoadWorker(QThread):
    loaded = Signal(object)

    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client

    def run(self):
        counts = {
            "tenants": None,
            "installations": None,
            "modules": None,
        }
        timings = {}
        errors = {}
        tenants = None

        started = time.perf_counter()
        try:
            tenants = self.api_client.list_tenants()
            counts["tenants"] = sum(
                tenant["status"] == "ACTIVE" for tenant in tenants
            )
        except ApiError as exc:
            errors["tenants"] = str(exc)
        finally:
            timings["tenants"] = round(
                (time.perf_counter() - started) * 1000, 2
            )

        if tenants is None:
            errors["installations"] = (
                "Jumlah instalasi aktif tidak dapat dihitung karena daftar "
                "Tenant gagal dimuat."
            )
        else:
            started = time.perf_counter()
            try:
                counts["installations"] = sum(
                    sum(
                        installation["status"] == "ACTIVE"
                        for installation in
                        self.api_client.list_tenant_installations(
                            tenant["id"]
                        )
                    )
                    for tenant in tenants
                )
            except ApiError as exc:
                errors["installations"] = str(exc)
            finally:
                timings["installations"] = round(
                    (time.perf_counter() - started) * 1000, 2
                )

        started = time.perf_counter()
        try:
            counts["modules"] = sum(
                module["is_active"]
                for module in self.api_client.list_modules()
            )
        except ApiError as exc:
            errors["modules"] = str(exc)
        finally:
            timings["modules"] = round(
                (time.perf_counter() - started) * 1000, 2
            )

        started = time.perf_counter()
        try:
            activities = self.api_client.list_recent_audit_logs()
        except ApiError as exc:
            activities = []
            errors["activity"] = str(exc)
        finally:
            timings["activity"] = round(
                (time.perf_counter() - started) * 1000, 2
            )

        self.loaded.emit(
            {
                "counts": counts,
                "errors": errors,
                "activities": activities,
                "timings_ms": timings,
            }
        )


class DashboardPage(QWidget):
    health_check_requested = Signal()

    def __init__(self, api_client=None):
        super().__init__()
        self.api_client = api_client
        self.load_worker = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(18)

        heading = QHBoxLayout()
        heading.addWidget(make_title("Dashboard"))
        heading.addStretch()
        self.refresh_button = QPushButton("Periksa Ulang")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.clicked.connect(self.refresh_dashboard)
        heading.addWidget(self.refresh_button)
        developer_tag = QLabel("DEVELOPER")
        developer_tag.setObjectName("roleTag")
        heading.addWidget(developer_tag)
        layout.addLayout(heading)

        intro = QLabel(
            "Ringkasan diperoleh langsung dari Universal API. Data yang belum "
            "didukung API akan ditandai secara eksplisit."
        )
        intro.setObjectName("subtleText")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        stats = QGridLayout()
        stats.setSpacing(12)
        self.stat_values = {}
        for index, (key, title, detail) in enumerate(
            (
                ("tenants", "TENANT AKTIF", "Status ACTIVE dari Universal API"),
                (
                    "active_licenses",
                    "LISENSI AKTIF",
                    "Belum tersedia melalui Universal API",
                ),
                (
                    "restricted_licenses",
                    "RESTRICTED",
                    "Belum tersedia melalui Universal API",
                ),
                (
                    "expired_licenses",
                    "EXPIRED",
                    "Belum tersedia melalui Universal API",
                ),
                (
                    "installations",
                    "INSTALASI AKTIF",
                    "Status ACTIVE dari Universal API",
                ),
                (
                    "modules",
                    "MODUL TERSEDIA",
                    "Modul katalog berstatus aktif",
                ),
            )
        ):
            card = QFrame()
            card.setObjectName("statCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            name = QLabel(title)
            name.setObjectName("statLabel")
            value = QLabel("N/D" if "licenses" in key else "—")
            value.setObjectName("statValue")
            if "licenses" in key:
                value.setToolTip(
                    "Universal API saat ini tidak menyediakan endpoint data "
                    "lisensi."
                )
            caption = QLabel(detail)
            caption.setObjectName("subtleText")
            card_layout.addWidget(name)
            card_layout.addWidget(value)
            card_layout.addWidget(caption)
            stats.addWidget(card, index // 3, index % 3)
            self.stat_values[title] = value
        layout.addLayout(stats)

        connection_card = QFrame()
        connection_card.setObjectName("panel")
        connection_layout = QVBoxLayout(connection_card)
        connection_layout.setContentsMargins(18, 16, 18, 16)
        connection_layout.setSpacing(9)
        connection_layout.addWidget(QLabel("MONITORING UNIVERSAL API"))
        self.api_status = make_status_label(
            "UNIVERSAL API: BELUM DIPERIKSA"
        )
        connection_layout.addWidget(self.api_status)
        self.api_response_time = QLabel("Waktu respons: N/D")
        self.api_response_time.setObjectName("subtleText")
        connection_layout.addWidget(self.api_response_time)
        self.last_health_check = QLabel(
            "Pemeriksaan terakhir: belum diperiksa"
        )
        self.last_health_check.setObjectName("subtleText")
        connection_layout.addWidget(self.last_health_check)
        self.database_status = make_status_label("DATABASE: N/D")
        self.database_status.setToolTip(
            "Status database akan ditampilkan hanya dari pemeriksaan resmi "
            "GET /health/ready."
        )
        connection_layout.addWidget(self.database_status)
        self.database_response_time = QLabel("Waktu respons database: N/D")
        self.database_response_time.setObjectName("subtleText")
        connection_layout.addWidget(self.database_response_time)
        self.last_database_check = QLabel(
            "Pemeriksaan database terakhir: belum diperiksa"
        )
        self.last_database_check.setObjectName("subtleText")
        connection_layout.addWidget(self.last_database_check)
        connection_note = QLabel(
            "GET /health/live memeriksa layanan API; GET /health/ready "
            "memeriksa koneksi database. Status database tidak disimpulkan "
            "dari status liveness API."
        )
        connection_note.setObjectName("subtleText")
        connection_note.setWordWrap(True)
        connection_layout.addWidget(connection_note)
        layout.addWidget(connection_card)

        activity_card = QFrame()
        activity_card.setObjectName("panel")
        activity_layout = QVBoxLayout(activity_card)
        activity_layout.setContentsMargins(18, 16, 18, 16)
        activity_layout.addWidget(QLabel("AKTIVITAS TERBARU"))
        self.activity_label = QLabel("Aktivitas akan dimuat dari API.")
        self.activity_label.setObjectName("subtleText")
        self.activity_label.setWordWrap(True)
        self.activity_label.setTextFormat(Qt.TextFormat.PlainText)
        activity_layout.addWidget(self.activity_label)
        layout.addWidget(activity_card)
        self.data_status = make_status_label(
            "DATA DASHBOARD: BELUM DIMUAT"
        )
        layout.addWidget(self.data_status)
        layout.addStretch()

    def refresh_dashboard(self):
        self.load_dashboard()
        self.health_check_requested.emit()

    def load_dashboard(self):
        if self.api_client is None:
            self.data_status.setText(
                "DATA DASHBOARD: UNIVERSAL API BELUM TERHUBUNG"
            )
            self.data_status.setStyleSheet("color:#A32323;")
            self.show_api_health(
                False,
                "Alamat Universal API belum dikonfigurasi.",
                None,
                None,
                "N/D",
                "Universal API belum dikonfigurasi.",
                None,
                None,
            )
            return
        if self.load_worker and self.load_worker.isRunning():
            return

        self.refresh_button.setEnabled(False)
        self.data_status.setText("DATA DASHBOARD: MEMUAT DARI API...")
        self.data_status.setStyleSheet("")
        self.load_worker = DashboardLoadWorker(self.api_client)
        self.load_worker.loaded.connect(self.show_dashboard_data)
        self.load_worker.start()

    def show_api_health(
        self,
        connected,
        message,
        response_ms=None,
        checked_at=None,
        database_status="N/D",
        database_message="Status database belum diperiksa.",
        database_response_ms=None,
        database_checked_at=None,
    ):
        if connected:
            status = "UNIVERSAL API: ONLINE"
            color = MUTED_GOLD
        elif message == "Alamat Universal API belum dikonfigurasi.":
            status = "UNIVERSAL API: BELUM DIKONFIGURASI"
            color = "#A32323"
        else:
            status = "UNIVERSAL API: OFFLINE"
            color = "#A32323"
        self.api_status.setText(status)
        self.api_status.setToolTip(message)
        self.api_status.setStyleSheet(f"color:{color};")
        if isinstance(response_ms, (int, float)):
            self.api_response_time.setText(
                f"Waktu respons: {response_ms:.2f} ms"
            )
        else:
            self.api_response_time.setText("Waktu respons: N/D")
        self.last_health_check.setText(
            "Pemeriksaan terakhir: "
            + (checked_at if isinstance(checked_at, str) else "belum diperiksa")
        )
        self.show_database_readiness(
            database_status,
            database_message,
            database_response_ms,
            database_checked_at,
        )

    def show_database_readiness(
        self, status, message, response_ms=None, checked_at=None
    ):
        if status == "ONLINE":
            self.database_status.setText("DATABASE: ONLINE")
            self.database_status.setStyleSheet(f"color:{MUTED_GOLD};")
        elif status == "OFFLINE":
            self.database_status.setText("DATABASE: OFFLINE")
            self.database_status.setStyleSheet("color:#A32323;")
        else:
            self.database_status.setText("DATABASE: N/D")
            self.database_status.setStyleSheet("")
        self.database_status.setToolTip(message)
        if isinstance(response_ms, (int, float)):
            self.database_response_time.setText(
                f"Waktu respons database: {response_ms:.2f} ms"
            )
        else:
            self.database_response_time.setText(
                "Waktu respons database: N/D"
            )
        self.last_database_check.setText(
            "Pemeriksaan database terakhir: "
            + (
                checked_at
                if isinstance(checked_at, str)
                else "belum diperiksa"
            )
        )

    def show_api_checking(self):
        self.api_status.setText("UNIVERSAL API: MEMERIKSA...")
        self.api_status.setToolTip("Endpoint GET /health/live sedang diperiksa.")
        self.api_status.setStyleSheet("")
        self.api_response_time.setText("Waktu respons: sedang diperiksa")
        self.last_health_check.setText("Pemeriksaan terakhir: sedang berlangsung")
        self.database_status.setText("DATABASE: MEMERIKSA...")
        self.database_status.setToolTip(
            "Endpoint GET /health/ready sedang diperiksa."
        )
        self.database_status.setStyleSheet("")
        self.database_response_time.setText(
            "Waktu respons database: sedang diperiksa"
        )
        self.last_database_check.setText(
            "Pemeriksaan database terakhir: sedang berlangsung"
        )

    def show_dashboard_data(self, snapshot):
        counts = snapshot["counts"]
        errors = snapshot["errors"]
        metric_keys = {
            "TENANT AKTIF": "tenants",
            "INSTALASI AKTIF": "installations",
            "MODUL TERSEDIA": "modules",
        }
        timings = snapshot.get("timings_ms", {})
        for title, metric_key in metric_keys.items():
            value = counts[metric_key]
            error = errors.get(metric_key)
            self.stat_values[title].setText(
                "Gagal" if error else str(value)
            )
            response_ms = timings.get(metric_key)
            detail = error or "Data aktual dari Universal API."
            detail += (
                f"\nWaktu respons pemeriksaan: {response_ms:.2f} ms"
                if isinstance(response_ms, (int, float))
                else "\nWaktu respons pemeriksaan: N/D"
            )
            self.stat_values[title].setToolTip(detail)

        activities = snapshot["activities"]
        if "activity" in errors:
            self.activity_label.setText(
                "Aktivitas gagal dimuat dari Universal API: "
                + errors["activity"]
            )
        elif not activities:
            self.activity_label.setText("Belum ada aktivitas pada server.")
        else:
            self.activity_label.setText(
                "\n".join(
                    (
                        f"{log['created_at']} | {log.get('action', '—')} | "
                        f"{log.get('entity', '—')} "
                        f"(aktor {log.get('actor_type', '—')} "
                        f"{log.get('actor_id', '—')})"
                    )
                    for log in activities
                )
            )
        activity_response_ms = timings.get("activity")
        self.activity_label.setToolTip(
            errors.get("activity", "Aktivitas aktual dari Universal API.")
            + (
                f"\nWaktu respons pemeriksaan: {activity_response_ms:.2f} ms"
                if isinstance(activity_response_ms, (int, float))
                else "\nWaktu respons pemeriksaan: N/D"
            )
        )

        if errors:
            messages = [
                f"{name}: {message}" for name, message in errors.items()
            ]
            self.data_status.setText(
                "DATA DASHBOARD: SEBAGIAN GAGAL DIMUAT"
            )
            self.data_status.setToolTip("\n".join(messages))
            self.data_status.setStyleSheet("color:#A32323;")
        else:
            self.data_status.setText(
                "DATA DASHBOARD: DIPERBARUI DARI UNIVERSAL API"
            )
            self.data_status.setToolTip(
                "Data lisensi belum tersedia karena endpoint lisensi belum "
                "disediakan Universal API."
            )
            self.data_status.setStyleSheet(f"color:{MUTED_GOLD};")
        self.refresh_button.setEnabled(True)

    def wait_for_load(self):
        if self.load_worker and self.load_worker.isRunning():
            self.load_worker.wait()


class TenantModuleWorker(QThread):
    loaded = Signal(object, str)
    failed = Signal(str)

    def __init__(
        self, api_client, tenant_id, action=None, module_code=None
    ):
        super().__init__()
        self.api_client = api_client
        self.tenant_id = tenant_id
        self.action = action
        self.module_code = module_code

    def run(self):
        success_message = ""
        if self.action == "enable":
            try:
                self.api_client.enable_tenant_module(
                    self.tenant_id, self.module_code
                )
            except ApiError as exc:
                self.failed.emit(str(exc))
                return
            success_message = (
                f"Assignment modul {self.module_code} diaktifkan."
            )
        elif self.action == "disable":
            try:
                self.api_client.disable_tenant_module(
                    self.tenant_id, self.module_code
                )
            except ApiError as exc:
                self.failed.emit(str(exc))
                return
            success_message = (
                f"Assignment modul {self.module_code} dinonaktifkan."
            )

        try:
            modules = self.api_client.list_tenant_modules(self.tenant_id)
        except ApiError as exc:
            if success_message:
                self.loaded.emit(
                    None,
                    success_message
                    + " Namun daftar modul gagal dimuat ulang: "
                    + str(exc),
                )
            else:
                self.failed.emit(str(exc))
        else:
            self.loaded.emit(modules, success_message)


class LicenseRequestWorker(QThread):
    loaded = Signal(str, object)
    failed = Signal(str)

    def __init__(self, api_client, operation, **values):
        super().__init__()
        self.api_client = api_client
        self.operation = operation
        self.values = values

    def run(self):
        try:
            if self.operation == "tenants":
                result = self.api_client.list_tenants()
            elif self.operation == "licenses":
                result = self.api_client.list_tenant_licenses(
                    self.values["tenant_id"],
                    limit=self.values["limit"],
                    offset=self.values["offset"],
                )
            elif self.operation == "catalogs":
                packages = []
                offset = 0
                while True:
                    page = self.api_client.list_license_packages(
                        limit=100, offset=offset
                    )
                    items = page["items"]
                    packages.extend(items)
                    if len(items) < 100:
                        break
                    offset += len(items)
                result = {
                    "packages": packages,
                    "modules": self.api_client.list_license_modules(),
                }
            elif self.operation == "detail":
                result = self.api_client.get_tenant_license(
                    self.values["tenant_id"], self.values["license_id"]
                )
            elif self.operation == "history":
                result = self.api_client.list_license_history(
                    self.values["tenant_id"], self.values["license_id"]
                )
            elif self.operation == "create":
                result = self.api_client.create_tenant_license(
                    **self.values
                )
            elif self.operation == "extend":
                result = self.api_client.extend_tenant_license(
                    **self.values
                )
            elif self.operation == "validity":
                result = self.api_client.update_tenant_license_validity(
                    **self.values
                )
            elif self.operation == "status":
                result = self.api_client.update_tenant_license_status(
                    **self.values
                )
            else:
                self.failed.emit("Operasi lisensi tidak dikenal.")
                return
        except ApiError as exc:
            self.failed.emit(str(exc))
        else:
            self.loaded.emit(self.operation, result)


class LicensePackageWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, api_client, package_id, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.package_id = package_id

    def run(self):
        try:
            package = self.api_client.get_license_package(self.package_id)
        except ApiError as exc:
            self.failed.emit(str(exc))
        else:
            self.loaded.emit(package)


def _license_record_id(record):
    return record.get("id") or record.get("license_id")


def _sanitize_license_display(value):
    secret_fields = {
        "accesstoken",
        "apikey",
        "authorization",
        "clientsecret",
        "password",
        "refreshtoken",
        "secret",
        "serialkey",
        "licensekey",
        "snapshotentitlements",
        "token",
    }
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if (
                normalized in secret_fields
                or "token" in normalized
                or "secret" in normalized
                or "serialkey" in normalized
                or "licensekey" in normalized
                or "snapshotentitlements" in normalized
            ):
                continue
            sanitized[key] = _sanitize_license_display(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_license_display(item) for item in value]
    if isinstance(value, str):
        return re.sub(
            r"\bSMP-LIC-\d{4}-[A-F0-9]{16}-[A-F0-9]{16}\b",
            "[REDACTED]",
            value,
            flags=re.IGNORECASE,
        )
    return value


def _date_time_edit(value=None, default=None):
    edit = QDateTimeEdit()
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
    parsed = (
        QDateTime.fromString(value, Qt.DateFormat.ISODate)
        if isinstance(value, str)
        else QDateTime()
    )
    edit.setDateTime(
        parsed if parsed.isValid() else default or QDateTime.currentDateTime()
    )
    return edit


class LicenseIssueDialog(QDialog):
    def __init__(self, api_client, tenant_id, packages, modules, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.tenant_id = tenant_id
        self.modules = modules
        self.package_worker = None
        self.package_detail = None
        self.setWindowTitle("Terbitkan Lisensi")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.addWidget(make_title("Terbitkan Lisensi"))
        note = QLabel(
            "Paket, modul, dan batas kapasitas menjadi snapshot lisensi saat "
            "diterbitkan; API belum menyediakan perubahan setelah penerbitan."
        )
        note.setObjectName("subtleText")
        note.setWordWrap(True)
        layout.addWidget(note)

        form = QFormLayout()
        self.package_input = QComboBox()
        for package in packages:
            package_id = package["id"]
            label = package.get("name") or package.get("package_name")
            self.package_input.addItem(
                f"{label} ({package_id})" if label else package_id,
                package_id,
            )
        self.package_input.currentIndexChanged.connect(
            self.load_package_modules
        )
        form.addRow("Paket", self.package_input)
        self.valid_from = _date_time_edit(
            default=QDateTime.currentDateTime()
        )
        self.valid_until = _date_time_edit(
            default=QDateTime.currentDateTime().addYears(1)
        )
        form.addRow("Berlaku mulai", self.valid_from)
        form.addRow("Berlaku sampai", self.valid_until)
        self.grace_period = self._spin_box(0, 90, 7)
        integer_limit = 2147483647
        self.max_installations = self._spin_box(1, integer_limit, 1)
        self.max_members = self._spin_box(1, integer_limit, 50000)
        self.max_accounts = self._spin_box(1, integer_limit, 200)
        self.max_concurrent_users = self._spin_box(1, integer_limit, 25)
        self.max_storage_mb = self._spin_box(500, integer_limit, 20480)
        form.addRow("Masa tenggang (hari)", self.grace_period)
        form.addRow("Batas instalasi", self.max_installations)
        form.addRow("Batas anggota", self.max_members)
        form.addRow("Batas akun", self.max_accounts)
        form.addRow("Pengguna bersamaan", self.max_concurrent_users)
        form.addRow("Penyimpanan (MB)", self.max_storage_mb)
        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText("Opsional")
        form.addRow("Catatan", self.notes_input)
        layout.addLayout(form)

        module_label = QLabel("Modul yang disertakan")
        module_label.setObjectName("statLabel")
        layout.addWidget(module_label)
        self.module_list = QListWidget()
        self.module_list.setMaximumHeight(150)
        layout.addWidget(self.module_list)
        self.package_status = QLabel("Memuat modul paket...")
        self.package_status.setObjectName("subtleText")
        self.package_status.setWordWrap(True)
        layout.addWidget(self.package_status)
        self.validation_message = QLabel()
        self.validation_message.setStyleSheet("color:#A32323;")
        self.validation_message.setWordWrap(True)
        layout.addWidget(self.validation_message)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Terbitkan"
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.submit_button = buttons.button(
            QDialogButtonBox.StandardButton.Ok
        )
        self.package_input.setEnabled(bool(packages))
        self.submit_button.setEnabled(False)
        if packages:
            self.load_package_modules()
        else:
            self.package_status.setText("Tidak ada paket aktif dari API.")

    @staticmethod
    def _spin_box(minimum, maximum, value):
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    def load_package_modules(self, *_):
        package_id = self.package_input.currentData()
        if not package_id or self.package_worker and self.package_worker.isRunning():
            return
        self.package_detail = None
        self.module_list.clear()
        self.package_status.setText("Memuat modul paket dari Universal API...")
        self.submit_button.setEnabled(False)
        self.package_input.setEnabled(False)
        self.package_worker = LicensePackageWorker(
            self.api_client, package_id, self
        )
        self.package_worker.loaded.connect(self._show_package_modules)
        self.package_worker.failed.connect(self._package_load_failed)
        self.package_worker.finished.connect(self._package_load_finished)
        self.package_worker.start()

    def _show_package_modules(self, package):
        self.package_detail = package
        modules_by_code = {
            module["module_code"]: module for module in self.modules
        }
        selectable = 0
        mandatory_unavailable = False
        for package_module in package["package_modules"]:
            code = package_module["module_code"]
            module = modules_by_code.get(code)
            label = (
                module.get("name", code)
                if module is not None
                else code
            )
            mandatory = package_module.get("is_mandatory") is True
            active = module is not None and module.get("is_active") is True
            if mandatory and not active:
                mandatory_unavailable = True
            suffix = " — wajib" if mandatory else ""
            if not active:
                suffix += " — tidak aktif di katalog"
            item = QListWidgetItem(f"{label} ({code}){suffix}")
            item.setData(Qt.ItemDataRole.UserRole, code)
            flags = item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            if not active or mandatory:
                flags &= ~Qt.ItemFlag.ItemIsEnabled
            item.setFlags(flags)
            item.setCheckState(
                Qt.CheckState.Checked
                if mandatory
                else Qt.CheckState.Unchecked
            )
            self.module_list.addItem(item)
            if active:
                selectable += 1
        self.package_status.setText(
            "Modul wajib tidak dapat dilepas."
            if not mandatory_unavailable
            else "Paket memiliki modul wajib yang tidak aktif di katalog."
        )
        self.submit_button.setEnabled(
            bool(package["package_modules"])
            and selectable > 0
            and not mandatory_unavailable
            and self.valid_until.dateTime() > self.valid_from.dateTime()
        )

    def _package_load_failed(self, message):
        self.package_status.setText("Gagal memuat modul paket: " + message)
        self.validation_message.setText(message)
        self.validation_message.setVisible(True)

    def _package_load_finished(self):
        self.package_input.setEnabled(True)

    def _accept_if_valid(self):
        if self.package_detail is None:
            self.validation_message.setText(
                "Paket dan modul belum selesai dimuat."
            )
            return
        if self.valid_until.dateTime() <= self.valid_from.dateTime():
            self.validation_message.setText(
                "Tanggal akhir harus setelah tanggal mulai."
            )
            return
        selected = [
            self.module_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.module_list.count())
            if self.module_list.item(row).checkState()
            == Qt.CheckState.Checked
        ]
        if not selected:
            self.validation_message.setText(
                "Pilih sedikitnya satu modul untuk lisensi."
            )
            return
        self.accept()

    def values(self):
        modules = [
            self.module_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.module_list.count())
            if self.module_list.item(row).checkState()
            == Qt.CheckState.Checked
        ]
        return {
            "tenant_id": self.tenant_id,
            "package_id": self.package_input.currentData(),
            "valid_from": self.valid_from.dateTime().toString(
                Qt.DateFormat.ISODate
            ),
            "valid_until": self.valid_until.dateTime().toString(
                Qt.DateFormat.ISODate
            ),
            "modules": modules,
            "max_installations": self.max_installations.value(),
            "max_members": self.max_members.value(),
            "max_accounts": self.max_accounts.value(),
            "max_concurrent_users": self.max_concurrent_users.value(),
            "max_storage_mb": self.max_storage_mb.value(),
            "grace_period_days": self.grace_period.value(),
            "notes": self.notes_input.text().strip() or None,
        }

    def wait_for_load(self):
        if self.package_worker and self.package_worker.isRunning():
            self.package_worker.wait()


class LicenseMutationDialog(QDialog):
    def __init__(self, action, license_record, parent=None):
        super().__init__(parent)
        self.action = action
        self.license_record = license_record
        titles = {
            "extend": "Perpanjang Lisensi",
            "validity": "Ubah Masa Berlaku",
            "status": "Ubah Status Lisensi",
        }
        self.setWindowTitle(titles[action])
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.addWidget(make_title(titles[action]))
        form = QFormLayout()
        default_from = _date_time_edit().dateTime()
        default_until = default_from.addYears(1)
        if action in ("extend", "validity"):
            self.valid_until = _date_time_edit(
                license_record.get("valid_until"), default_until
            )
            form.addRow("Berlaku sampai", self.valid_until)
        if action == "validity":
            self.valid_from = _date_time_edit(
                license_record.get("valid_from"), default_from
            )
            form.insertRow(0, "Berlaku mulai", self.valid_from)
            self.grace_period = LicenseIssueDialog._spin_box(0, 90, 7)
            grace = license_record.get("grace_period_days")
            if type(grace) is int and 0 <= grace <= 90:
                self.grace_period.setValue(grace)
            form.addRow("Masa tenggang (hari)", self.grace_period)
        if action == "status":
            self.status_input = QComboBox()
            self.status_input.addItems(
                ["ACTIVE", "SUSPENDED", "REVOKED"]
            )
            current_status = license_record.get("status")
            if current_status in ("ACTIVE", "SUSPENDED", "REVOKED"):
                self.status_input.setCurrentText(current_status)
            form.addRow("Status", self.status_input)
        self.reason_input = QLineEdit()
        self.reason_input.setPlaceholderText("Minimal 3 karakter")
        form.addRow("Alasan", self.reason_input)
        layout.addLayout(form)
        self.validation_message = QLabel()
        self.validation_message.setStyleSheet("color:#A32323;")
        layout.addWidget(self.validation_message)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Simpan")
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_if_valid(self):
        if len(self.reason_input.text().strip()) < 3:
            self.validation_message.setText(
                "Alasan perubahan minimal 3 karakter."
            )
            return
        if self.action == "validity" and (
            self.valid_until.dateTime() <= self.valid_from.dateTime()
        ):
            self.validation_message.setText(
                "Tanggal akhir harus setelah tanggal mulai."
            )
            return
        self.accept()

    def values(self):
        reason = self.reason_input.text().strip()
        if self.action == "extend":
            return {
                "valid_until": self.valid_until.dateTime().toString(
                    Qt.DateFormat.ISODate
                ),
                "reason": reason,
            }
        if self.action == "validity":
            return {
                "valid_from": self.valid_from.dateTime().toString(
                    Qt.DateFormat.ISODate
                ),
                "valid_until": self.valid_until.dateTime().toString(
                    Qt.DateFormat.ISODate
                ),
                "grace_period_days": self.grace_period.value(),
                "reason": reason,
            }
        return {"status": self.status_input.currentText(), "reason": reason}


class LicenseDetailsDialog(QDialog):
    def __init__(self, title, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(680, 480)
        layout = QVBoxLayout(self)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText(
            json.dumps(
                _sanitize_license_display(data),
                ensure_ascii=False,
                indent=2,
            )
        )
        layout.addWidget(details)
        close_button = QPushButton("Tutup")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)


class LicenseIssuedDialog(QDialog):
    def __init__(self, license_id, serial_key, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lisensi Berhasil Diterbitkan")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.addWidget(make_title("Lisensi Berhasil Diterbitkan"))
        note = QLabel(
            f"ID lisensi: {license_id}\n"
            "Serial Key hanya tersedia pada respons penerbitan ini. Salin "
            "sekarang; Universal API tidak menyediakan pengambilan ulang."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.serial_key_input = QLineEdit(serial_key)
        self.serial_key_input.setReadOnly(True)
        self.serial_key_input.setClearButtonEnabled(False)
        layout.addWidget(self.serial_key_input)
        buttons = QHBoxLayout()
        copy_button = QPushButton("Salin Serial Key")
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(
                self.serial_key_input.text()
            )
        )
        close_button = QPushButton("Tutup")
        close_button.setObjectName("secondaryButton")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(copy_button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def clear_key(self):
        self.serial_key_input.clear()


class LicenseHistoryDialog(QDialog):
    def __init__(self, history, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Riwayat Lisensi")
        self.resize(820, 460)
        layout = QVBoxLayout(self)
        note = QLabel(
            "Riwayat berasal dari Audit Log Universal API dan difilter "
            "berdasarkan ID lisensi."
        )
        note.setObjectName("subtleText")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(len(history), 4)
        self.table.setHorizontalHeaderLabels(
            ["WAKTU", "AKTIVITAS", "AKTOR", "DETAIL"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        for row, log in enumerate(history):
            values = (
                log["created_at"],
                log["action"],
                f"{log['actor_type']} #{log['actor_id'] or '—'}",
                json.dumps(
                    _sanitize_license_display(log["details"]),
                    ensure_ascii=False,
                ),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(row, column, item)
        layout.addWidget(self.table, 1)
        if not history:
            empty = QLabel("Belum ada riwayat lisensi pada Audit Log.")
            empty.setObjectName("emptyState")
            layout.addWidget(empty)
        close_button = QPushButton("Tutup")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)


class LicensePage(QWidget):
    PAGE_SIZE = 50

    def __init__(self, api_client=None, user=None):
        super().__init__()
        self.api_client = api_client
        self.permissions = None
        self.set_user_permissions(user)
        self.worker = None
        self.issue_dialog = None
        self.request_pending = False
        self.pending_operation = None
        self.pending_result = None
        self.pending_error = None
        self.loaded_tenant_id = None
        self.tenant_id = None
        self.tenants = []
        self.tenants_by_id = {}
        self.offset = 0
        self.licenses = []
        self.license_by_id = {}
        self.catalogs = None
        self.mutation_succeeded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(14)
        layout.addWidget(make_title("Manajemen Lisensi"))

        self.license_note = QLabel(
            "Lisensi dan Serial Key dikelola License Manager melalui "
            "Universal API. Batas dan modul hanya dapat ditetapkan saat "
            "penerbitan; API belum menyediakan perubahan entitlements "
            "setelahnya atau endpoint riwayat khusus."
        )
        self.license_note.setObjectName("subtleText")
        self.license_note.setWordWrap(True)
        layout.addWidget(self.license_note)

        tenant_toolbar = QHBoxLayout()
        tenant_toolbar.addWidget(QLabel("Tenant"))
        self.tenant_selector = QComboBox()
        self.tenant_selector.addItem("Muat daftar Tenant", None)
        self.tenant_selector.currentIndexChanged.connect(
            self._tenant_changed
        )
        tenant_toolbar.addWidget(self.tenant_selector, 1)
        self.load_tenants_button = QPushButton("Muat Tenant")
        self.load_tenants_button.clicked.connect(self.load_tenants)
        tenant_toolbar.addWidget(self.load_tenants_button)
        self.load_button = QPushButton("Muat Lisensi")
        self.load_button.clicked.connect(self.load_licenses)
        tenant_toolbar.addWidget(self.load_button)
        self.issue_button = QPushButton("Terbitkan Lisensi")
        self.issue_button.setToolTip(
            "Memerlukan tenants.manage dan tenants.read untuk katalog."
        )
        self.issue_button.clicked.connect(self.open_issue_dialog)
        tenant_toolbar.addWidget(self.issue_button)
        tenant_toolbar.addStretch()
        layout.addLayout(tenant_toolbar)

        actions_toolbar = QHBoxLayout()
        self.detail_button = QPushButton("Detail")
        self.detail_button.setObjectName("secondaryButton")
        self.detail_button.clicked.connect(
            lambda: self._run_selected_operation("detail")
        )
        actions_toolbar.addWidget(self.detail_button)
        self.history_button = QPushButton("Riwayat")
        self.history_button.setObjectName("secondaryButton")
        self.history_button.clicked.connect(
            lambda: self._run_selected_operation("history")
        )
        actions_toolbar.addWidget(self.history_button)
        self.status_button = QPushButton("Ubah Status")
        self.status_button.setObjectName("secondaryButton")
        self.status_button.clicked.connect(
            lambda: self.open_mutation_dialog("status")
        )
        actions_toolbar.addWidget(self.status_button)
        self.validity_button = QPushButton("Ubah Masa Berlaku")
        self.validity_button.setObjectName("secondaryButton")
        self.validity_button.clicked.connect(
            lambda: self.open_mutation_dialog("validity")
        )
        actions_toolbar.addWidget(self.validity_button)
        self.extend_button = QPushButton("Perpanjang")
        self.extend_button.setObjectName("secondaryButton")
        self.extend_button.clicked.connect(
            lambda: self.open_mutation_dialog("extend")
        )
        actions_toolbar.addWidget(self.extend_button)
        actions_toolbar.addStretch()
        layout.addLayout(actions_toolbar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["ID LISENSI", "PAKET", "STATUS", "BERLAKU MULAI", "BERLAKU SAMPAI"]
        )
        self.table.setMinimumHeight(230)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.itemSelectionChanged.connect(self.update_action_buttons)
        layout.addWidget(self.table, 1)

        self.empty_label = QLabel(
            "Muat daftar Tenant dari Universal API, lalu pilih Tenant."
        )
        self.empty_label.setObjectName("emptyState")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.empty_label)
        pagination = QHBoxLayout()
        self.previous_button = QPushButton("Sebelumnya")
        self.previous_button.setObjectName("secondaryButton")
        self.previous_button.clicked.connect(self.previous_page)
        self.page_label = QLabel("Halaman belum dimuat")
        self.page_label.setObjectName("subtleText")
        self.next_button = QPushButton("Berikutnya")
        self.next_button.setObjectName("secondaryButton")
        self.next_button.clicked.connect(self.next_page)
        pagination.addWidget(self.previous_button)
        pagination.addWidget(self.page_label)
        pagination.addStretch()
        pagination.addWidget(self.next_button)
        layout.addLayout(pagination)
        self.data_status = make_status_label("LISENSI: BELUM DIMUAT")
        self.data_status.setWordWrap(True)
        layout.addWidget(self.data_status)
        self.update_action_buttons()

    def _has_permission(self, permission):
        return self.permissions is None or permission in self.permissions

    def set_user_permissions(self, user):
        user_permissions = (
            user.get("permissions") if isinstance(user, dict) else None
        )
        self.permissions = (
            set(user_permissions)
            if isinstance(user_permissions, list)
            else None
        )
        if hasattr(self, "load_button"):
            self.update_action_buttons()

    def _tenant_id(self):
        tenant_id = self.tenant_selector.currentData()
        return tenant_id if type(tenant_id) is int and tenant_id > 0 else None

    def load_tenants(self):
        if not self._has_permission("tenants.read"):
            self._show_error(
                "Daftar Tenant memerlukan permission tenants.read."
            )
            return
        if self.api_client is None:
            self._show_error("Client Universal API tidak tersedia.")
            return
        self.data_status.setText("TENANT: MEMUAT DARI UNIVERSAL API...")
        self._start_request("tenants")

    def _show_tenants(self, tenants):
        selected_tenant_id = self._tenant_id()
        self.tenants = tenants
        self.tenants_by_id = {
            tenant["id"]: tenant for tenant in tenants
        }
        self.tenant_selector.blockSignals(True)
        self.tenant_selector.clear()
        self.tenant_selector.addItem("Pilih Tenant", None)
        selected_index = 0
        for tenant in tenants:
            tenant_id = tenant["id"]
            label = (
                f"{tenant['code']} — {tenant['name']} "
                f"(ID {tenant_id}, {tenant['status']})"
            )
            self.tenant_selector.addItem(label, tenant_id)
            if tenant_id == selected_tenant_id:
                selected_index = self.tenant_selector.count() - 1
        if selected_index == 0 and tenants:
            selected_index = 1
        self.tenant_selector.setCurrentIndex(selected_index)
        self.tenant_selector.blockSignals(False)
        if tenants:
            self._tenant_changed()
        else:
            self.loaded_tenant_id = None
            self.tenant_id = None
            self.licenses = []
            self.license_by_id = {}
            self.table.setRowCount(0)
            self.empty_label.setText(
                "Belum ada Tenant terdaftar di Universal API."
            )
            self.empty_label.setVisible(True)
            self.data_status.setText("TENANT: 0 DIMUAT DARI UNIVERSAL API")
            self.update_action_buttons()

    def _tenant_changed(self, *_):
        tenant_id = self._tenant_id()
        self.tenant_id = tenant_id
        self.loaded_tenant_id = None
        self.offset = 0
        self.licenses = []
        self.license_by_id = {}
        self.table.setRowCount(0)
        self.page_label.setText("Halaman belum dimuat")
        if tenant_id is None:
            self.empty_label.setText(
                "Pilih Tenant terdaftar untuk memuat lisensi."
            )
            self.empty_label.setVisible(True)
            self.data_status.setText("LISENSI: PILIH TENANT")
            self.update_action_buttons()
            return
        tenant = self.tenants_by_id.get(tenant_id)
        if tenant is None:
            self._show_error(
                "Tenant tidak ditemukan pada daftar Universal API."
            )
            return
        self.empty_label.setText(
            "Tenant dipilih. Muat lisensi yang tersedia atau terbitkan "
            "lisensi baru."
        )
        self.empty_label.setVisible(True)
        self.data_status.setText(
            f"TENANT: {tenant['code']} DIPILIH"
        )
        self.update_action_buttons()

    def load_licenses(self, offset=0):
        tenant_id = self._tenant_id()
        if tenant_id is None:
            self._show_error("Pilih Tenant terlebih dahulu.")
            return
        tenant = self.tenants_by_id.get(tenant_id)
        if tenant is None:
            self._show_error(
                "Tenant tidak ditemukan pada daftar Universal API."
            )
            return
        if not self._has_permission("tenants.read"):
            self._show_error(
                "Daftar lisensi memerlukan permission tenants.read."
            )
            return
        if self.api_client is None:
            self._show_error("Client Universal API tidak tersedia.")
            return
        self.tenant_id = tenant_id
        self.offset = offset
        self.licenses = []
        self.license_by_id = {}
        self.table.setRowCount(0)
        self.empty_label.setText("Memuat lisensi dari Universal API...")
        self.empty_label.setVisible(True)
        self.data_status.setText("LISENSI: MEMUAT...")
        self.data_status.setToolTip("")
        self.data_status.setStyleSheet("")
        self._start_request(
            "licenses",
            tenant_id=tenant_id,
            limit=self.PAGE_SIZE,
            offset=offset,
        )

    def previous_page(self):
        if self.offset > 0:
            self.load_licenses(max(0, self.offset - self.PAGE_SIZE))

    def next_page(self):
        if len(self.licenses) == self.PAGE_SIZE:
            self.load_licenses(self.offset + self.PAGE_SIZE)

    def open_issue_dialog(self):
        tenant_id = self._tenant_id()
        if tenant_id is None:
            self._show_error("Pilih Tenant untuk penerbitan lisensi.")
            return
        tenant = self.tenants_by_id.get(tenant_id)
        if tenant is None:
            self._show_error(
                "Tenant tidak ditemukan pada daftar Universal API."
            )
            return
        if not self._has_permission("tenants.manage"):
            self._show_error(
                "Penerbitan lisensi memerlukan permission tenants.manage."
            )
            return
        if not self._has_permission("tenants.read"):
            self._show_error(
                "Pemilihan paket dan modul memerlukan permission tenants.read."
            )
            return
        if self.api_client is None:
            self._show_error("Client Universal API tidak tersedia.")
            return
        self.tenant_id = tenant_id
        if self.catalogs is not None:
            self._show_issue_dialog(self.catalogs)
            return
        self.data_status.setText("KATALOG LISENSI: MEMUAT DARI API...")
        self._start_request("catalogs")

    def _show_issue_dialog(self, catalogs):
        self.issue_dialog = LicenseIssueDialog(
            self.api_client,
            self.tenant_id,
            catalogs["packages"],
            catalogs["modules"],
            self,
        )
        if self.issue_dialog.exec() == QDialog.DialogCode.Accepted:
            values = self.issue_dialog.values()
            self.issue_dialog.wait_for_load()
            self._start_mutation("create", **values)
        else:
            self.issue_dialog.wait_for_load()
        self.issue_dialog = None

    def open_mutation_dialog(self, action):
        selected = self._selected_license()
        tenant_id = self._tenant_id()
        if selected is None or tenant_id != self.loaded_tenant_id:
            self._show_error(
                "Muat lisensi Tenant yang dipilih terlebih dahulu."
            )
            return
        if not self._has_permission("tenants.manage"):
            self._show_error(
                "Perubahan lisensi memerlukan permission tenants.manage."
            )
            return
        dialog = LicenseMutationDialog(action, selected, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = {
            "tenant_id": tenant_id,
            "license_id": _license_record_id(selected),
            **dialog.values(),
        }
        if action == "status" and values["status"] == "REVOKED":
            answer = QMessageBox.question(
                self,
                "Konfirmasi Pencabutan Lisensi",
                "Lisensi yang dicabut tidak dapat dipulihkan melalui API. "
                "Lanjutkan?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._start_mutation(action, **values)

    def _selected_license(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        license_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        return self.license_by_id.get(license_id)

    def _run_selected_operation(self, operation):
        selected = self._selected_license()
        tenant_id = self._tenant_id()
        if selected is None or tenant_id != self.loaded_tenant_id:
            self._show_error(
                "Muat lisensi Tenant yang dipilih terlebih dahulu."
            )
            return
        if operation == "history" and not self._has_permission(
            "auth.audit.read"
        ):
            self._show_error(
                "Riwayat lisensi memerlukan permission auth.audit.read."
            )
            return
        self._start_request(
            operation,
            tenant_id=tenant_id,
            license_id=_license_record_id(selected),
        )

    def _start_mutation(self, operation, **values):
        if operation != "create" and not self._has_permission(
            "tenants.manage"
        ):
            self._show_error(
                "Perubahan lisensi memerlukan permission tenants.manage."
            )
            return
        self.mutation_succeeded = False
        self.data_status.setText("LISENSI: MENYIMPAN KE UNIVERSAL API...")
        self._start_request(operation, **values)

    def _start_request(self, operation, **values):
        if self.request_pending:
            return
        self.request_pending = True
        self.pending_operation = operation
        self.pending_result = None
        self.pending_error = None
        self.worker = LicenseRequestWorker(
            self.api_client, operation, **values
        )
        self.worker.loaded.connect(self._request_loaded)
        self.worker.failed.connect(self._request_failed)
        self.worker.finished.connect(self._request_finished)
        self.update_action_buttons()
        self.worker.start()

    def _request_loaded(self, operation, result):
        self.pending_operation = operation
        self.pending_result = result

    def _request_failed(self, message):
        self.pending_error = message

    def _request_finished(self):
        operation = self.pending_operation
        result = self.pending_result
        error = self.pending_error
        self.request_pending = False
        self.pending_result = None
        self.pending_error = None
        if error is not None:
            self._show_error(error)
        elif operation == "tenants":
            self._show_tenants(result)
        elif operation == "licenses":
            self._show_licenses(result)
        elif operation == "catalogs":
            self.catalogs = result
            self._show_issue_dialog(result)
        elif operation == "detail":
            LicenseDetailsDialog("Detail Lisensi", result, self).exec()
            self._set_success("Detail lisensi dimuat dari Universal API.")
        elif operation == "history":
            LicenseHistoryDialog(result, self).exec()
            self._set_success(
                f"{len(result)} catatan riwayat lisensi dimuat dari Audit Log."
            )
        elif operation == "create":
            serial_key = result.get("license_key")
            license_id = result.get("license_id") or result.get("id")
            if isinstance(serial_key, str) and serial_key:
                issued_dialog = LicenseIssuedDialog(
                    license_id, serial_key, self
                )
                issued_dialog.exec()
                issued_dialog.clear_key()
                result["license_key"] = ""
            self.mutation_succeeded = True
            self._set_success(
                "Lisensi diterbitkan melalui Universal API. "
                "Serial Key tidak disimpan Desktop."
            )
        elif operation in ("extend", "validity", "status"):
            self.mutation_succeeded = True
            self._set_success("Perubahan lisensi tersimpan melalui API.")
        self.update_action_buttons()
        if self.mutation_succeeded and self.tenant_id is not None:
            self.load_licenses(self.offset)

    def _show_licenses(self, response):
        self.licenses = response["items"]
        self.license_by_id = {
            _license_record_id(record): record
            for record in self.licenses
        }
        self.loaded_tenant_id = self.tenant_id
        self.table.setRowCount(len(self.licenses))
        for row, record in enumerate(self.licenses):
            license_id = _license_record_id(record)
            package = record.get("package_name") or record.get("package_id")
            if package is None and isinstance(record.get("package"), dict):
                package = record["package"].get("name")
            values = (
                license_id,
                package or "—",
                record.get("status") or "—",
                record.get("valid_from") or "—",
                record.get("valid_until") or "—",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, license_id)
                self.table.setItem(row, column, item)
        self.empty_label.setText("Tidak ada lisensi pada halaman ini.")
        self.empty_label.setVisible(not self.licenses)
        self.page_label.setText(
            f"Halaman {self.offset // self.PAGE_SIZE + 1} — "
            f"{len(self.licenses)} lisensi; total tidak tersedia"
        )
        self.data_status.setText(
            f"LISENSI: {len(self.licenses)} DIMUAT DARI UNIVERSAL API"
        )
        self.data_status.setToolTip(
            "Lisensi dan Serial Key tetap dikelola License Manager."
        )
        self.data_status.setStyleSheet(f"color:{MUTED_GOLD};")

    def _set_success(self, message):
        self.data_status.setText("LISENSI: " + message)
        self.data_status.setToolTip("")
        self.data_status.setStyleSheet(f"color:{MUTED_GOLD};")

    def _show_error(self, message):
        self.data_status.setText("LISENSI: GAGAL — " + message)
        self.data_status.setToolTip(message)
        self.data_status.setStyleSheet("color:#A32323;")
        if self.table.rowCount() == 0:
            self.empty_label.setText(message)
            self.empty_label.setVisible(True)
        self.update_action_buttons()

    def update_action_buttons(self, *_):
        tenant_id = self._tenant_id()
        tenant = self.tenants_by_id.get(tenant_id)
        can_read = (
            tenant is not None
            and not self.request_pending
            and self._has_permission("tenants.read")
        )
        can_manage = (
            tenant is not None
            and not self.request_pending
            and self._has_permission("tenants.manage")
        )
        can_issue = (
            can_manage and self._has_permission("tenants.read")
        )
        selected = self._selected_license()
        can_use_selection = (
            selected is not None
            and tenant_id == self.loaded_tenant_id
            and not self.request_pending
        )
        self.tenant_selector.setEnabled(not self.request_pending)
        self.load_tenants_button.setEnabled(
            not self.request_pending
            and self._has_permission("tenants.read")
        )
        self.load_button.setEnabled(can_read)
        self.issue_button.setEnabled(can_issue)
        self.detail_button.setEnabled(can_use_selection and can_read)
        self.history_button.setEnabled(
            can_use_selection
            and self._has_permission("auth.audit.read")
        )
        self.status_button.setEnabled(can_use_selection and can_manage)
        self.validity_button.setEnabled(can_use_selection and can_manage)
        self.extend_button.setEnabled(can_use_selection and can_manage)
        self.previous_button.setEnabled(
            not self.request_pending and self.offset > 0
        )
        self.next_button.setEnabled(
            not self.request_pending and len(self.licenses) == self.PAGE_SIZE
        )

    def wait_for_load(self):
        if self.worker is not None:
            self.worker.wait()
        if self.issue_dialog is not None:
            self.issue_dialog.wait_for_load()


class DataPage(QWidget):
    def __init__(
        self,
        title,
        description,
        columns,
        form_fields=None,
        filter_column=None,
        filter_values=None,
        add_label="Tambah",
    ):
        super().__init__()
        self.title = title
        self.form_fields = form_fields or []
        self.filter_column = filter_column

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(14)
        layout.addWidget(make_title(title))

        description_label = QLabel(description)
        description_label.setObjectName("subtleText")
        description_label.setWordWrap(True)
        layout.addWidget(description_label)

        toolbar = QHBoxLayout()
        self.toolbar = toolbar
        self.search = QLineEdit()
        self.search.setPlaceholderText("Cari pada tabel...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_table)
        toolbar.addWidget(self.search, 1)

        self.status_filter = None
        if filter_values is not None:
            self.status_filter = QComboBox()
            self.status_filter.addItems(["Semua"] + list(filter_values))
            self.status_filter.currentTextChanged.connect(self.filter_table)
            toolbar.addWidget(self.status_filter)

        self.add_button = None
        self.edit_button = None
        if self.form_fields:
            self.add_button = QPushButton("+ " + add_label)
            self.add_button.clicked.connect(self.open_add_form)
            toolbar.addWidget(self.add_button)

            self.edit_button = QPushButton("Edit")
            self.edit_button.setObjectName("secondaryButton")
            self.edit_button.setEnabled(False)
            self.edit_button.clicked.connect(self.open_edit_form)
            toolbar.addWidget(self.edit_button)
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setMinimumHeight(230)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setMinimumSectionSize(75)
        self.table.itemSelectionChanged.connect(self.update_edit_button)
        if self.status_filter is not None:
            self.table.itemChanged.connect(self.refresh_filter_choices)
        self.table.cellDoubleClicked.connect(self.show_details)
        layout.addWidget(self.table, 1)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("emptyState")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)
        self.update_empty_state()

        self.data_status = make_status_label(
            "STATUS DATA: BELUM TERHUBUNG KE API"
        )
        self.data_status.setWordWrap(True)
        layout.addWidget(self.data_status)

    def update_edit_button(self):
        if self.edit_button:
            self.edit_button.setEnabled(self.table.currentRow() >= 0)

    def filter_table(self, *_):
        keyword = self.search.text().casefold().strip()
        selected_status = (
            self.status_filter.currentText()
            if self.status_filter is not None
            else "Semua"
        )
        visible_count = 0

        for row in range(self.table.rowCount()):
            matches_keyword = any(
                keyword in (
                    self.table.item(row, column).text().casefold()
                    if self.table.item(row, column)
                    else ""
                )
                for column in range(self.table.columnCount())
            )
            matches_status = (
                selected_status == "Semua"
                or self.filter_column is None
                or (
                    self.table.item(row, self.filter_column) is not None
                    and self.table.item(row, self.filter_column)
                    .text()
                    .casefold()
                    == selected_status.casefold()
                )
            )
            visible = matches_keyword and matches_status
            self.table.setRowHidden(row, not visible)
            visible_count += int(visible)

        self.update_empty_state(visible_count)

    def refresh_filter_choices(self, *_):
        if self.status_filter is None or self.filter_column is None:
            return
        selected = self.status_filter.currentText()
        values = sorted(
            {
                self.table.item(row, self.filter_column).text()
                for row in range(self.table.rowCount())
                if self.table.item(row, self.filter_column) is not None
            },
            key=str.casefold,
        )
        self.status_filter.blockSignals(True)
        self.status_filter.clear()
        self.status_filter.addItems(["Semua"] + values)
        if selected in values:
            self.status_filter.setCurrentText(selected)
        self.status_filter.blockSignals(False)
        self.filter_table()

    def update_empty_state(self, visible_count=None):
        if visible_count is None:
            visible_count = self.table.rowCount()
        if self.table.rowCount() == 0:
            message = (
                "Belum ada data untuk ditampilkan.\n"
                "Data produksi tidak dibuat sebagai contoh; endpoint data "
                "Universal API belum dihubungkan ke tabel ini."
            )
        elif visible_count == 0:
            message = "Tidak ada data yang cocok dengan pencarian atau filter."
        else:
            message = ""
        self.empty_label.setText(message)
        self.empty_label.setVisible(bool(message))

    def open_add_form(self):
        self.open_form("Tambah " + self.title)

    def open_edit_form(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self, "Edit data", "Pilih satu baris terlebih dahulu."
            )
            return
        values = {}
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)
            if item:
                values[self.table.horizontalHeaderItem(column).text()] = (
                    item.text()
                )
        self.open_form("Edit " + self.title, values)

    def open_form(self, title, initial_values=None):
        dialog = FormDialog(
            title, self.form_fields, initial_values, parent=self
        )
        dialog.exec()

    def show_details(self, row, column):
        self.table.setCurrentCell(row, column)
        details = []
        for column in range(self.table.columnCount()):
            header = self.table.horizontalHeaderItem(column).text()
            item = self.table.item(row, column)
            details.append(f"{header}: {item.text() if item else '—'}")
        QMessageBox.information(self, "Detail " + self.title, "\n".join(details))


class AuditLogLoadWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, api_client, limit, offset):
        super().__init__()
        self.api_client = api_client
        self.limit = limit
        self.offset = offset

    def run(self):
        try:
            page = self.api_client.list_audit_logs(
                limit=self.limit, offset=self.offset
            )
        except ApiError as exc:
            self.failed.emit(str(exc))
        else:
            self.loaded.emit(page)


class AuditLogPage(DataPage):
    PAGE_SIZE = 50

    def __init__(self, api_client):
        self.api_client = api_client
        self.offset = 0
        self.logs = []
        self.logs_by_id = {}
        self.request_pending = False
        self.worker = None
        super().__init__(
            "Audit Log",
            "Riwayat aktivitas dan perubahan yang tercatat di Universal API.",
            ["NO.", "WAKTU", "AKTOR", "AKTIVITAS", "OBJEK", "HASIL"],
            filter_column=3,
            filter_values=(),
        )
        self.search.setPlaceholderText("Cari pada halaman yang dimuat...")
        self.actor_filter = QComboBox()
        self.actor_filter.addItem("Semua aktor", None)
        self.actor_filter.currentTextChanged.connect(self.filter_table)
        self.toolbar.addWidget(self.actor_filter)
        self.date_from = QLineEdit()
        self.date_from.setPlaceholderText("Dari YYYY-MM-DD")
        self.date_from.setMaximumWidth(145)
        self.date_from.textChanged.connect(self.filter_table)
        self.toolbar.addWidget(self.date_from)
        self.date_to = QLineEdit()
        self.date_to.setPlaceholderText("Sampai YYYY-MM-DD")
        self.date_to.setMaximumWidth(145)
        self.date_to.textChanged.connect(self.filter_table)
        self.toolbar.addWidget(self.date_to)

        self.filter_limitation = QLabel(
            "API mendukung pagination, tetapi belum mendukung pencarian atau "
            "filter periode/aktor/aktivitas di server. Filter di sini hanya "
            "berlaku pada halaman yang sedang dimuat."
        )
        self.filter_limitation.setObjectName("subtleText")
        self.filter_limitation.setWordWrap(True)
        self.layout().insertWidget(3, self.filter_limitation)
        self.filter_error = QLabel()
        self.filter_error.setStyleSheet("color:#A32323;")
        self.filter_error.setVisible(False)
        self.layout().insertWidget(4, self.filter_error)

        self.refresh_button = QPushButton("Muat Ulang")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.clicked.connect(self.refresh)
        self.toolbar.addWidget(self.refresh_button)
        self.detail_button = QPushButton("Lihat Detail")
        self.detail_button.setObjectName("secondaryButton")
        self.detail_button.setEnabled(False)
        self.detail_button.clicked.connect(self.show_selected_details)
        self.toolbar.addWidget(self.detail_button)
        self.table.itemSelectionChanged.connect(self._update_detail_button)

        self.previous_button = QPushButton("Sebelumnya")
        self.previous_button.setObjectName("secondaryButton")
        self.previous_button.clicked.connect(self.previous_page)
        self.next_button = QPushButton("Berikutnya")
        self.next_button.setObjectName("secondaryButton")
        self.next_button.clicked.connect(self.next_page)
        self.page_label = QLabel("Halaman belum dimuat")
        self.page_label.setObjectName("subtleText")
        pagination = QHBoxLayout()
        pagination.addWidget(self.previous_button)
        pagination.addWidget(self.page_label)
        pagination.addStretch()
        pagination.addWidget(self.next_button)
        self.layout().insertLayout(self.layout().count() - 1, pagination)
        self.empty_label.setText(
            "Buka menu ini untuk memuat riwayat audit dari Universal API."
        )
        self._update_pagination_controls()

    def load_page(self, offset=0):
        if self.request_pending:
            return
        if self.api_client is None:
            self._show_load_error("Client Universal API tidak tersedia.")
            return
        if type(offset) is not int or offset < 0:
            self._show_load_error("Offset halaman audit tidak valid.")
            return
        self.offset = offset
        self.request_pending = True
        self.logs = []
        self.logs_by_id = {}
        self.table.setRowCount(0)
        self.empty_label.setText("Memuat riwayat audit...")
        self.empty_label.setVisible(True)
        self.data_status.setText("AUDIT LOG: MEMUAT DARI UNIVERSAL API...")
        self.data_status.setToolTip("")
        self.data_status.setStyleSheet("")
        self.refresh_button.setEnabled(False)
        self.filter_limitation.setEnabled(False)
        self._update_detail_button()
        self._update_pagination_controls()
        self.worker = AuditLogLoadWorker(
            self.api_client, self.PAGE_SIZE, self.offset
        )
        self.worker.loaded.connect(self._show_page)
        self.worker.failed.connect(self._show_load_error)
        self.worker.finished.connect(self._load_finished)
        self.worker.start()

    def refresh(self):
        self.load_page(0)

    def previous_page(self):
        if self.offset > 0:
            self.load_page(max(0, self.offset - self.PAGE_SIZE))

    def next_page(self):
        if len(self.logs) == self.PAGE_SIZE:
            self.load_page(self.offset + self.PAGE_SIZE)

    def _show_page(self, page):
        self.logs = page["items"]
        self.logs_by_id = {log["id"]: log for log in self.logs}
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self.logs))
            for index, log in enumerate(self.logs):
                values = (
                    self.offset + index + 1,
                    log["created_at"],
                    self._actor_label(log),
                    log["action"],
                    self._entity_label(log),
                    self._summary(log.get("details")),
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 0:
                        item.setData(Qt.ItemDataRole.UserRole, log["id"])
                    self.table.setItem(index, column, item)
        finally:
            self.table.blockSignals(False)
        self.refresh_filter_choices()
        self._refresh_actor_choices()
        self.filter_error.clear()
        self.filter_error.setVisible(False)
        self.data_status.setText(
            f"AUDIT LOG: {len(self.logs)} DIMUAT (OFFSET {self.offset}); "
            "TOTAL TIDAK DISEDIAKAN API"
        )
        self.data_status.setToolTip(
            "Universal API tidak mengembalikan total catatan audit."
        )
        self.data_status.setStyleSheet("")
        self.page_label.setText(
            f"Halaman {self.offset // self.PAGE_SIZE + 1} — "
            f"{len(self.logs)} catatan; total tidak tersedia"
        )
        self.filter_table()
        self._update_detail_button()
        self._update_pagination_controls()

    def _show_load_error(self, message):
        self.data_status.setText(f"AUDIT LOG: GAGAL DIMUAT — {message}")
        self.data_status.setToolTip(message)
        self.data_status.setStyleSheet("color:#A32323;")
        if self.table.rowCount() == 0:
            self.empty_label.setText(
                "Riwayat audit tidak dapat dimuat dari Universal API.\n"
                + message
            )
            self.empty_label.setVisible(True)

    def _load_finished(self):
        self.request_pending = False
        self.refresh_button.setEnabled(True)
        self.filter_limitation.setEnabled(True)
        self._update_pagination_controls()

    def _update_pagination_controls(self):
        self.previous_button.setEnabled(
            not self.request_pending and self.offset > 0
        )
        self.next_button.setEnabled(
            not self.request_pending and len(self.logs) == self.PAGE_SIZE
        )

    def _update_detail_button(self):
        row = self.table.currentRow()
        self.detail_button.setEnabled(
            row >= 0 and not self.request_pending
        )

    def _selected_log(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        log_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        return self.logs_by_id.get(log_id)

    def show_selected_details(self):
        row = self.table.currentRow()
        if row >= 0:
            self.show_details(row, 0)

    def show_details(self, row, column):
        self.table.setCurrentCell(row, column)
        log = self._selected_log()
        if log is None:
            self._show_load_error("Catatan audit yang dipilih tidak valid.")
            return
        details = log.get("details")
        rendered_details = (
            json.dumps(details, ensure_ascii=False, indent=2, sort_keys=True)
            if details is not None
            else "Tidak tersedia"
        )
        lines = [
            f"ID log: {log['id']}",
            f"Waktu: {log['created_at']}",
            f"Tenant ID: {log.get('tenant_id') or '—'}",
            f"Aktor: {self._actor_label(log)}",
            f"Aktivitas: {log['action']}",
            f"Objek: {self._entity_label(log)}",
            "Hasil/informasi aktivitas:",
            rendered_details,
        ]
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Detail Audit Log")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText("\n".join(lines))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.exec()

    def filter_table(self, *_):
        keyword = self.search.text().casefold().strip()
        selected_action = (
            self.status_filter.currentText()
            if self.status_filter is not None
            else "Semua"
        )
        selected_actor = self.actor_filter.currentData()
        start_text = self.date_from.text().strip()
        end_text = self.date_to.text().strip()
        filter_message = ""
        try:
            start_date = date.fromisoformat(start_text) if start_text else None
            end_date = date.fromisoformat(end_text) if end_text else None
            if start_date and end_date and start_date > end_date:
                filter_message = "Tanggal awal harus sebelum tanggal akhir."
        except ValueError:
            start_date = None
            end_date = None
            filter_message = "Gunakan format tanggal YYYY-MM-DD."
        self.filter_error.setText(filter_message)
        self.filter_error.setVisible(bool(filter_message))

        visible_count = 0
        for row, log in enumerate(self.logs):
            values = (
                self.table.item(row, column).text().casefold()
                if self.table.item(row, column)
                else ""
                for column in range(self.table.columnCount())
            )
            matches_keyword = not keyword or any(
                keyword in value for value in values
            )
            matches_action = (
                selected_action == "Semua"
                or log["action"].casefold() == selected_action.casefold()
            )
            matches_actor = (
                selected_actor is None
                or self._actor_value(log) == selected_actor
            )
            try:
                log_date = datetime.fromisoformat(
                    log["created_at"].replace("Z", "+00:00")
                ).date()
            except ValueError:
                log_date = None
            matches_period = (
                (
                    start_date is None
                    or (
                        log_date is not None
                        and log_date >= start_date
                    )
                )
                and (
                    end_date is None
                    or (log_date is not None and log_date <= end_date)
                )
            )
            visible = (
                not filter_message
                and matches_keyword
                and matches_action
                and matches_actor
                and matches_period
            )
            self.table.setRowHidden(row, not visible)
            visible_count += int(visible)
        self.update_empty_state(visible_count)

    def refresh_filter_choices(self, *_):
        if self.status_filter is None:
            return
        selected = self.status_filter.currentText()
        actions = sorted({log["action"] for log in self.logs}, key=str.casefold)
        self.status_filter.blockSignals(True)
        self.status_filter.clear()
        self.status_filter.addItems(["Semua"] + actions)
        if selected in actions:
            self.status_filter.setCurrentText(selected)
        self.status_filter.blockSignals(False)

    def _refresh_actor_choices(self):
        selected = self.actor_filter.currentData()
        actors = sorted(
            {self._actor_value(log) for log in self.logs},
            key=str.casefold,
        )
        self.actor_filter.blockSignals(True)
        self.actor_filter.clear()
        self.actor_filter.addItem("Semua aktor", None)
        for actor in actors:
            self.actor_filter.addItem(actor, actor)
        if selected in actors:
            self.actor_filter.setCurrentIndex(
                self.actor_filter.findData(selected)
            )
        self.actor_filter.blockSignals(False)

    @staticmethod
    def _actor_value(log):
        actor_id = log.get("actor_id")
        return f"{log['actor_type']} #{actor_id if actor_id is not None else '—'}"

    @classmethod
    def _actor_label(cls, log):
        return cls._actor_value(log)

    @staticmethod
    def _entity_label(log):
        entity_id = log.get("entity_id")
        return (
            f"{log['entity']} #{entity_id}"
            if entity_id is not None
            else log["entity"]
        )

    @staticmethod
    def _summary(details):
        if not details:
            return "—"
        value = details.get("result", details.get("summary", details))
        if isinstance(value, str):
            summary = value
        else:
            summary = json.dumps(
                value, ensure_ascii=False, sort_keys=True, default=str
            )
        return summary if len(summary) <= 160 else summary[:157] + "..."

    def update_empty_state(self, visible_count=None):
        if self.table.rowCount() == 0:
            if self.request_pending:
                message = "Memuat riwayat audit..."
            elif (
                hasattr(self, "data_status")
                and self.data_status.text().startswith("AUDIT LOG: GAGAL")
            ):
                message = "Riwayat audit belum dapat dimuat."
            elif self.offset > 0:
                message = (
                    "Tidak ada catatan pada offset ini. API tidak "
                    "menyediakan jumlah total untuk membatasi pagination."
                )
            elif self.logs:
                message = "Tidak ada catatan audit yang cocok dengan filter."
            else:
                message = "Belum ada catatan audit pada halaman ini."
        elif visible_count == 0:
            message = "Tidak ada catatan audit yang cocok dengan filter."
        else:
            message = ""
        self.empty_label.setText(message)
        self.empty_label.setVisible(bool(message))

    def wait_for_load(self):
        if self.worker and self.worker.isRunning():
            self.worker.wait()


class DeveloperAccountDialog(QDialog):
    def __init__(self, account=None, roles=None, parent=None):
        super().__init__(parent)
        self.account = account
        self.is_create = account is None
        self.setWindowTitle(
            "Tambah Akun Developer"
            if self.is_create
            else "Edit Akun Developer"
        )
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.username = QLineEdit(
            "" if self.is_create else account["username"]
        )
        self.username.setReadOnly(not self.is_create)
        form.addRow("Username", self.username)
        self.full_name = QLineEdit(
            "" if self.is_create else account["full_name"]
        )
        self.full_name.setMaxLength(200)
        form.addRow("Nama lengkap", self.full_name)
        if self.is_create:
            self.password = QLineEdit()
            self.password.setEchoMode(QLineEdit.EchoMode.Password)
            self.password.setMaxLength(256)
            self.confirm_password = QLineEdit()
            self.confirm_password.setEchoMode(QLineEdit.EchoMode.Password)
            self.confirm_password.setMaxLength(256)
            form.addRow("Password awal", self.password)
            form.addRow("Konfirmasi password", self.confirm_password)
        layout.addLayout(form)
        self.role_list = None
        self.role_note = None
        if self.is_create:
            if roles is None:
                self.role_note = QLabel(
                    "Katalog role tidak tersedia. Akun dibuat tanpa role "
                    "dan tidak menerima hak akses otomatis."
                )
                self.role_note.setObjectName("subtleText")
                self.role_note.setWordWrap(True)
                layout.addWidget(self.role_note)
            else:
                self.role_list = QListWidget()
                for role in roles:
                    if not role["is_active"]:
                        continue
                    item = QListWidgetItem(
                        f"{role['code']} — {role['name']}"
                    )
                    item.setData(Qt.ItemDataRole.UserRole, role["code"])
                    item.setFlags(
                        item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                    )
                    item.setCheckState(Qt.CheckState.Unchecked)
                    self.role_list.addItem(item)
                layout.addWidget(QLabel("Role yang diberikan (opsional)"))
                layout.addWidget(self.role_list)
                self.role_note = QLabel(
                    "Tidak ada role yang dipilih secara otomatis. "
                    "developer_admin memberikan hak istimewa tinggi."
                )
                self.role_note.setObjectName("subtleText")
                self.role_note.setWordWrap(True)
                layout.addWidget(self.role_note)
        self.validation_message = QLabel(
            "Password minimal 12 karakter dan tidak akan ditampilkan."
            if self.is_create
            else "Username tidak dapat diubah melalui Universal API."
        )
        self.validation_message.setObjectName("subtleText")
        self.validation_message.setWordWrap(True)
        layout.addWidget(self.validation_message)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.submit_form)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def submit_form(self):
        if not self.full_name.text().strip():
            self.validation_message.setText("Nama lengkap wajib diisi.")
            return False
        if self.is_create:
            if not self.username.text().strip():
                self.validation_message.setText("Username wajib diisi.")
                return False
            if not 12 <= len(self.password.text()) <= 256:
                self.validation_message.setText(
                    "Password harus terdiri dari 12–256 karakter."
                )
                return False
            if self.password.text() != self.confirm_password.text():
                self.validation_message.setText(
                    "Konfirmasi password tidak cocok."
                )
                return False
        self.accept()
        return True

    def values(self):
        values = {"full_name": self.full_name.text().strip()}
        if self.is_create:
            values.update(
                {
                    "username": self.username.text().strip(),
                    "password": self.password.text(),
                    "role_codes": self.selected_role_codes(),
                }
            )
        return values

    def selected_role_codes(self):
        if self.role_list is None:
            return []
        return [
            self.role_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.role_list.count())
            if self.role_list.item(index).checkState()
            == Qt.CheckState.Checked
        ]

    def clear_sensitive_inputs(self):
        if self.is_create:
            self.password.clear()
            self.confirm_password.clear()


class DeveloperPasswordDialog(QDialog):
    def __init__(self, username, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reset Password Developer")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Akun: {username}"))
        form = QFormLayout()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setMaxLength(256)
        self.confirm_password = QLineEdit()
        self.confirm_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_password.setMaxLength(256)
        form.addRow("Password baru", self.password)
        form.addRow("Konfirmasi password", self.confirm_password)
        layout.addLayout(form)
        self.validation_message = QLabel(
            "Password minimal 12 karakter. Universal API akan mencabut "
            "sesi aktif akun setelah reset."
        )
        self.validation_message.setObjectName("subtleText")
        self.validation_message.setWordWrap(True)
        layout.addWidget(self.validation_message)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.submit_form)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def submit_form(self):
        if not 12 <= len(self.password.text()) <= 256:
            self.validation_message.setText(
                "Password harus terdiri dari 12–256 karakter."
            )
            return False
        if self.password.text() != self.confirm_password.text():
            self.validation_message.setText(
                "Konfirmasi password tidak cocok."
            )
            return False
        self.accept()
        return True

    def value(self):
        return self.password.text()

    def clear_passwords(self):
        self.password.clear()
        self.confirm_password.clear()


class DeveloperSelectionDialog(QDialog):
    def __init__(
        self,
        title,
        choices,
        selected_codes=(),
        note="Pilihan akan diterapkan persis seperti yang dicentang.",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        self.items = QListWidget()
        selected_codes = set(selected_codes)
        for choice in choices:
            code = choice["code"]
            description = choice.get("name", "")
            module = choice.get("module")
            label = f"{code} — {description}" if description else code
            if module:
                label += f" ({module})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, code)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if code in selected_codes
                else Qt.CheckState.Unchecked
            )
            self.items.addItem(item)
        layout.addWidget(self.items)
        self.note = QLabel(note)
        self.note.setObjectName("subtleText")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_codes(self):
        return [
            self.items.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.items.count())
            if self.items.item(index).checkState() == Qt.CheckState.Checked
        ]


class DeveloperAccountsLoadWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, api_client, limit, offset):
        super().__init__()
        self.api_client = api_client
        self.limit = limit
        self.offset = offset

    def run(self):
        try:
            accounts = self.api_client.list_developer_accounts(
                limit=self.limit, offset=self.offset
            )
        except ApiError as exc:
            self.failed.emit(str(exc))
            return
        roles = None
        permissions = None
        role_error = None
        permission_error = None
        try:
            roles = self.api_client.list_developer_roles()
        except ApiError as exc:
            role_error = str(exc)
        try:
            permissions = self.api_client.list_developer_permissions()
        except ApiError as exc:
            permission_error = str(exc)
        self.loaded.emit(
            {
                "accounts": accounts,
                "roles": roles,
                "permissions": permissions,
                "role_error": role_error,
                "permission_error": permission_error,
            }
        )


class DeveloperMutationWorker(QThread):
    saved = Signal(object, object)
    failed = Signal(str)

    def __init__(self, api_client, operation, **values):
        super().__init__()
        self.api_client = api_client
        self.operation = operation
        self.values = values

    def run(self):
        try:
            if self.operation == "create":
                result = self.api_client.create_developer_account(
                    self.values["username"],
                    self.values["password"],
                    self.values["full_name"],
                    self.values["role_codes"],
                )
            elif self.operation == "update":
                result = self.api_client.update_developer_account(
                    self.values["user_id"], self.values["full_name"]
                )
            elif self.operation == "status":
                result = self.api_client.set_developer_account_active(
                    self.values["user_id"], self.values["is_active"]
                )
            elif self.operation == "password":
                result = self.api_client.reset_developer_password(
                    self.values["user_id"], self.values["password"]
                )
            else:
                result = self.api_client.assign_developer_roles(
                    self.values["user_id"], self.values["role_codes"]
                )
        except ApiError as exc:
            self.failed.emit(str(exc))
        else:
            self.saved.emit(self.operation, result)


class DeveloperRoleMutationWorker(QThread):
    saved = Signal(object, object, object)
    failed = Signal(str)

    def __init__(self, api_client, operation, **values):
        super().__init__()
        self.api_client = api_client
        self.operation = operation
        self.values = values

    def run(self):
        try:
            if self.operation == "create":
                result = self.api_client.create_developer_role(
                    self.values["code"],
                    self.values["name"],
                    self.values["description"],
                    self.values["permission_codes"],
                )
            elif self.operation == "update":
                result = self.api_client.update_developer_role(
                    self.values["role_id"],
                    self.values["name"],
                    self.values["description"],
                    self.values["is_active"],
                )
            else:
                result = self.api_client.set_developer_role_permissions(
                    self.values["role_id"],
                    self.values["permission_codes"],
                )
        except ApiError as exc:
            self.failed.emit(str(exc))
        else:
            self.saved.emit(self.operation, result, self.values)


class DeveloperRoleManagerDialog(QDialog):
    def __init__(self, api_client, roles, permissions, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.roles = list(roles)
        self.permissions = list(permissions)
        self.role_by_id = {role["id"]: role for role in self.roles}
        self.worker = None
        self.mutation_pending = False
        self.did_change = False
        self.setWindowTitle("Role dan Permission Developer")
        self.resize(800, 520)
        layout = QVBoxLayout(self)
        note = QLabel(
            "Hak akses hanya berubah setelah dipilih dan disimpan. Role "
            "developer_admin dikelola sistem dan tidak dapat dinonaktifkan "
            "atau diubah permission-nya."
        )
        note.setObjectName("subtleText")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["ID", "KODE", "NAMA", "STATUS", "PERMISSION"]
        )
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.itemSelectionChanged.connect(self._update_actions)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.create_button = QPushButton("Tambah Role")
        self.create_button.clicked.connect(self.open_create)
        self.edit_button = QPushButton("Edit Role")
        self.edit_button.setObjectName("secondaryButton")
        self.edit_button.clicked.connect(self.open_edit)
        self.permissions_button = QPushButton("Atur Permission")
        self.permissions_button.setObjectName("secondaryButton")
        self.permissions_button.clicked.connect(self.open_permissions)
        actions.addWidget(self.create_button)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.permissions_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.status = QLabel("Role dan permission dimuat dari Universal API.")
        self.status.setObjectName("subtleText")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self._show_roles()

    def _show_roles(self, selected_id=None):
        self.role_by_id = {role["id"]: role for role in self.roles}
        self.table.setRowCount(len(self.roles))
        selected_row = None
        for row, role in enumerate(self.roles):
            values = (
                role["id"],
                role["code"],
                role["name"],
                "ACTIVE" if role["is_active"] else "INACTIVE",
                ", ".join(role["permissions"]) or "—",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, role["id"])
                self.table.setItem(row, column, item)
            if role["id"] == selected_id:
                selected_row = row
        if selected_row is not None:
            self.table.selectRow(selected_row)
        self._update_actions()

    def _selected_role(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        role_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        return self.role_by_id.get(role_id)

    def _update_actions(self):
        role = self._selected_role()
        busy = self.mutation_pending
        self.create_button.setEnabled(not busy)
        self.edit_button.setEnabled(not busy and role is not None)
        self.permissions_button.setEnabled(
            not busy
            and role is not None
            and role["code"] != "developer_admin"
        )

    def open_create(self):
        dialog = FormDialog(
            "Tambah Role Developer",
            [("KODE ROLE", True), ("NAMA ROLE", True), ("DESKRIPSI", False)],
            parent=self,
            submit_handler=lambda form: form.accept(),
        )
        dialog.inputs["KODE ROLE"].setMaxLength(50)
        dialog.inputs["NAMA ROLE"].setMaxLength(100)
        dialog.inputs["DESKRIPSI"].setMaxLength(2000)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self._start_mutation(
            "create",
            code=values["KODE ROLE"],
            name=values["NAMA ROLE"],
            description=values["DESKRIPSI"] or None,
            permission_codes=[],
        )

    def open_edit(self):
        role = self._selected_role()
        if role is None:
            return
        dialog = FormDialog(
            "Edit Role Developer",
            [
                ("NAMA ROLE", True),
                ("DESKRIPSI", False),
                ("STATUS", True, ("ACTIVE", "INACTIVE")),
            ],
            {
                "NAMA ROLE": role["name"],
                "DESKRIPSI": role.get("description") or "",
                "STATUS": "ACTIVE" if role["is_active"] else "INACTIVE",
            },
            parent=self,
            submit_handler=lambda form: form.accept(),
        )
        dialog.inputs["NAMA ROLE"].setMaxLength(100)
        dialog.inputs["DESKRIPSI"].setMaxLength(2000)
        if role["code"] == "developer_admin":
            dialog.inputs["STATUS"].setEnabled(False)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self._start_mutation(
            "update",
            role_id=role["id"],
            name=values["NAMA ROLE"],
            description=values["DESKRIPSI"] or None,
            is_active=values["STATUS"] == "ACTIVE",
        )

    def open_permissions(self):
        role = self._selected_role()
        if role is None or role["code"] == "developer_admin":
            return
        dialog = DeveloperSelectionDialog(
            "Permission Role: " + role["code"],
            self.permissions,
            role["permissions"],
            "Permission yang dicentang akan menggantikan seluruh permission "
            "role ini. Tidak ada permission yang ditambahkan otomatis.",
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._start_mutation(
            "permissions",
            role_id=role["id"],
            permission_codes=dialog.selected_codes(),
        )

    def _start_mutation(self, operation, **values):
        if self.mutation_pending:
            return
        self.mutation_pending = True
        self._update_actions()
        self.status.setText("Menyimpan perubahan role ke Universal API...")
        self.status.setStyleSheet("")
        self.worker = DeveloperRoleMutationWorker(
            self.api_client, operation, **values
        )
        self.worker.saved.connect(self._mutation_saved)
        self.worker.failed.connect(self._mutation_failed)
        self.worker.finished.connect(self._mutation_finished)
        self.worker.start()

    def _mutation_saved(self, operation, result, values):
        if operation == "create":
            role = {
                "id": result["id"],
                "code": result["code"],
                "name": result["name"],
                "description": values["description"],
                "is_active": True,
                "permissions": result["permissions"],
            }
            self.roles.append(role)
        elif operation == "update":
            role = self.role_by_id[result["id"]]
            role.update(result)
        else:
            role = self.role_by_id[result["role_id"]]
            role["permissions"] = result["permissions"]
        self.did_change = True
        self.status.setText("Perubahan role tersimpan melalui Universal API.")
        self.status.setStyleSheet(f"color:{MUTED_GOLD};")
        self._show_roles(role["id"])

    def _mutation_failed(self, message):
        self.status.setText("Gagal menyimpan role: " + message)
        self.status.setToolTip(message)
        self.status.setStyleSheet("color:#A32323;")

    def _mutation_finished(self):
        self.mutation_pending = False
        self._update_actions()

    def wait_for_mutation(self):
        if self.worker and self.worker.isRunning():
            self.worker.wait()

    def closeEvent(self, event):
        self.wait_for_mutation()
        super().closeEvent(event)


class DeveloperPage(DataPage):
    PAGE_SIZE = 50

    def __init__(self, api_client):
        self.api_client = api_client
        self.offset = 0
        self.accounts = []
        self.account_by_id = {}
        self.roles = []
        self.permissions = []
        self.roles_available = False
        self.permissions_available = False
        self.role_error = None
        self.permission_error = None
        self.accounts_loaded = False
        self.request_pending = False
        self.mutation_pending = False
        self.mutation_succeeded = False
        self.worker = None
        self.mutation_worker = None
        super().__init__(
            "Pengguna Developer",
            "Akun pengelola SIMPATI Developer Desktop. Akun Tenant tidak "
            "ditampilkan pada halaman ini.",
            [
                "NO.",
                "USER ID",
                "USERNAME",
                "NAMA LENGKAP",
                "ROLE",
                "STATUS",
                "DIBUAT",
                "DIPERBARUI",
            ],
            filter_column=5,
            filter_values=("ACTIVE", "INACTIVE"),
        )
        self.capability_note = QLabel(
            "Daftar dan perubahan akun memerlukan auth.developers.manage. "
            "Katalog role/permission memerlukan auth.roles.manage. Akun baru "
            "tidak memperoleh role otomatis."
        )
        self.capability_note.setObjectName("subtleText")
        self.capability_note.setWordWrap(True)
        self.layout().insertWidget(3, self.capability_note)
        self.refresh_button = QPushButton("Muat Ulang")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.clicked.connect(self.refresh)
        self.toolbar.addWidget(self.refresh_button)
        self.create_button = QPushButton("+ Tambah Akun")
        self.create_button.clicked.connect(self.open_create)
        self.toolbar.addWidget(self.create_button)
        self.edit_account_button = QPushButton("Edit Informasi")
        self.edit_account_button.setObjectName("secondaryButton")
        self.edit_account_button.clicked.connect(self.open_edit)
        self.toolbar.addWidget(self.edit_account_button)
        self.status_button = QPushButton("Ubah Status")
        self.status_button.setObjectName("secondaryButton")
        self.status_button.clicked.connect(self.toggle_status)
        self.toolbar.addWidget(self.status_button)
        self.assign_roles_button = QPushButton("Atur Role")
        self.assign_roles_button.setObjectName("secondaryButton")
        self.assign_roles_button.clicked.connect(self.open_assign_roles)
        self.toolbar.addWidget(self.assign_roles_button)
        self.reset_password_button = QPushButton("Reset Password")
        self.reset_password_button.setObjectName("secondaryButton")
        self.reset_password_button.clicked.connect(self.open_password_reset)
        self.toolbar.addWidget(self.reset_password_button)
        self.detail_button = QPushButton("Detail")
        self.detail_button.setObjectName("secondaryButton")
        self.detail_button.clicked.connect(self.show_selected_details)
        self.toolbar.addWidget(self.detail_button)
        self.manage_roles_button = QPushButton("Kelola Role/Permission")
        self.manage_roles_button.setObjectName("secondaryButton")
        self.manage_roles_button.clicked.connect(self.open_role_manager)
        self.toolbar.addWidget(self.manage_roles_button)
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.previous_button = QPushButton("Sebelumnya")
        self.previous_button.setObjectName("secondaryButton")
        self.previous_button.clicked.connect(self.previous_page)
        self.next_button = QPushButton("Berikutnya")
        self.next_button.setObjectName("secondaryButton")
        self.next_button.clicked.connect(self.next_page)
        self.page_label = QLabel("Halaman belum dimuat")
        self.page_label.setObjectName("subtleText")
        pagination = QHBoxLayout()
        pagination.addWidget(self.previous_button)
        pagination.addWidget(self.page_label)
        pagination.addStretch()
        pagination.addWidget(self.next_button)
        self.layout().insertLayout(self.layout().count() - 1, pagination)
        self.empty_label.setText(
            "Buka menu ini untuk memuat akun Developer dari Universal API."
        )
        self._update_actions()
        self._update_pagination_controls()

    def load_page(self, offset=0):
        if self.request_pending or self.mutation_pending:
            return
        if self.api_client is None:
            self._show_load_error("Client Universal API tidak tersedia.")
            return
        if (
            type(offset) is not int
            or offset < 0
            or offset % self.PAGE_SIZE != 0
        ):
            self._show_load_error("Offset halaman Developer tidak valid.")
            return
        self.offset = offset
        self.request_pending = True
        self.accounts_loaded = False
        self.accounts = []
        self.account_by_id = {}
        self.roles = []
        self.permissions = []
        self.roles_available = False
        self.permissions_available = False
        self.table.setRowCount(0)
        self.empty_label.setText("Memuat akun Developer...")
        self.empty_label.setVisible(True)
        self.data_status.setText(
            "PENGGUNA DEVELOPER: MEMUAT DARI UNIVERSAL API..."
        )
        self.data_status.setToolTip("")
        self.data_status.setStyleSheet("")
        self._update_actions()
        self._update_pagination_controls()
        self.worker = DeveloperAccountsLoadWorker(
            self.api_client, self.PAGE_SIZE, self.offset
        )
        self.worker.loaded.connect(self._show_page)
        self.worker.failed.connect(self._show_load_error)
        self.worker.finished.connect(self._load_finished)
        self.worker.start()

    def refresh(self):
        self.load_page(0)

    def previous_page(self):
        if self.offset > 0:
            self.load_page(max(0, self.offset - self.PAGE_SIZE))

    def next_page(self):
        if len(self.accounts) == self.PAGE_SIZE:
            self.load_page(self.offset + self.PAGE_SIZE)

    def _show_page(self, data):
        response = data["accounts"]
        self.accounts = response["items"]
        self.accounts_loaded = True
        self.account_by_id = {
            account["id"]: account for account in self.accounts
        }
        self.roles = data["roles"] or []
        self.permissions = data["permissions"] or []
        self.roles_available = data["roles"] is not None
        self.permissions_available = data["permissions"] is not None
        self.role_error = data["role_error"]
        self.permission_error = data["permission_error"]
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self.accounts))
            for index, account in enumerate(self.accounts):
                values = (
                    self.offset + index + 1,
                    account["id"],
                    account["username"],
                    account["full_name"],
                    ", ".join(account["roles"]) or "—",
                    "ACTIVE" if account["is_active"] else "INACTIVE",
                    account["created_at"],
                    account["updated_at"],
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 1:
                        item.setData(
                            Qt.ItemDataRole.UserRole, account["id"]
                        )
                    self.table.setItem(index, column, item)
        finally:
            self.table.blockSignals(False)
        self.capability_note.setText(self._capability_text())
        self.data_status.setText(
            f"PENGGUNA DEVELOPER: {len(self.accounts)} DIMUAT "
            f"(OFFSET {self.offset}); TOTAL TIDAK DISEDIAKAN API"
        )
        self.data_status.setToolTip(
            "Endpoint akun Developer tidak mengembalikan total data."
        )
        self.data_status.setStyleSheet("")
        self.page_label.setText(
            f"Halaman {self.offset // self.PAGE_SIZE + 1} — "
            f"{len(self.accounts)} akun; total tidak tersedia"
        )
        self.refresh_filter_choices()
        self.filter_table()
        self._update_actions()
        self._update_pagination_controls()

    def _capability_text(self):
        text = (
            "Daftar dan perubahan akun memerlukan auth.developers.manage. "
            "Katalog role/permission memerlukan auth.roles.manage. "
            "Role tidak diberikan otomatis."
        )
        if self.role_error:
            text += " Katalog role tidak tersedia: " + self.role_error
        if self.permission_error:
            text += " Katalog permission tidak tersedia: " + self.permission_error
        return text

    def _show_load_error(self, message):
        self.data_status.setText(
            f"PENGGUNA DEVELOPER: GAGAL DIMUAT — {message}"
        )
        self.data_status.setToolTip(message)
        self.data_status.setStyleSheet("color:#A32323;")
        if self.table.rowCount() == 0:
            self.empty_label.setText(
                "Akun Developer tidak dapat dimuat dari Universal API.\n"
                + message
            )
            self.empty_label.setVisible(True)

    def _load_finished(self):
        self.request_pending = False
        self._update_actions()
        self._update_pagination_controls()
        self.refresh_button.setEnabled(not self.mutation_pending)

    def _update_pagination_controls(self):
        self.previous_button.setEnabled(
            not self.request_pending
            and not self.mutation_pending
            and self.offset > 0
        )
        self.next_button.setEnabled(
            not self.request_pending
            and not self.mutation_pending
            and len(self.accounts) == self.PAGE_SIZE
        )

    def _selected_account(self):
        row = self.table.currentRow()
        item = self.table.item(row, 1) if row >= 0 else None
        user_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        return self.account_by_id.get(user_id)

    def _update_actions(self):
        account = self._selected_account()
        busy = self.request_pending or self.mutation_pending
        self.refresh_button.setEnabled(not busy)
        self.create_button.setEnabled(self.accounts_loaded and not busy)
        has_selected_account = self.accounts_loaded and account is not None
        self.edit_account_button.setEnabled(has_selected_account and not busy)
        self.reset_password_button.setEnabled(
            has_selected_account and not busy
        )
        self.detail_button.setEnabled(has_selected_account and not busy)
        if has_selected_account:
            self.status_button.setText(
                "Nonaktifkan Akun"
                if account["is_active"]
                else "Aktifkan Akun"
            )
        else:
            self.status_button.setText("Ubah Status")
        self.status_button.setEnabled(has_selected_account and not busy)
        self.assign_roles_button.setEnabled(
            has_selected_account and self.roles_available and not busy
        )
        self.manage_roles_button.setEnabled(
            self.roles_available and self.permissions_available and not busy
        )
        self._update_pagination_controls()

    def open_create(self):
        dialog = DeveloperAccountDialog(
            roles=self.roles if self.roles_available else None,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            dialog.clear_sensitive_inputs()
            return
        values = dialog.values()
        dialog.clear_sensitive_inputs()
        self._start_mutation("create", **values)

    def open_edit(self):
        account = self._selected_account()
        if account is None:
            return
        dialog = DeveloperAccountDialog(account=account, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._start_mutation(
            "update",
            user_id=account["id"],
            full_name=dialog.values()["full_name"],
        )

    def toggle_status(self):
        account = self._selected_account()
        if account is None:
            return
        is_active = not account["is_active"]
        action = "mengaktifkan" if is_active else "menonaktifkan"
        answer = QMessageBox.question(
            self,
            "Konfirmasi Status Akun",
            f"Apakah Anda yakin ingin {action} akun {account['username']}? "
            "API dapat menolak penonaktifan Developer Admin terakhir.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_mutation(
            "status", user_id=account["id"], is_active=is_active
        )

    def open_assign_roles(self):
        account = self._selected_account()
        if account is None or not self.roles_available:
            return
        active_roles = [
            role for role in self.roles if role["is_active"]
        ]
        dialog = DeveloperSelectionDialog(
            "Role Akun " + account["username"],
            active_roles,
            account["roles"],
            "Role yang dicentang akan menggantikan role akun. Tidak ada role "
            "yang ditambahkan otomatis; developer_admin memberikan hak tinggi.",
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._start_mutation(
            "roles",
            user_id=account["id"],
            role_codes=dialog.selected_codes(),
        )

    def open_password_reset(self):
        account = self._selected_account()
        if account is None:
            return
        dialog = DeveloperPasswordDialog(account["username"], self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            dialog.clear_passwords()
            return
        password = dialog.value()
        dialog.clear_passwords()
        self._start_mutation(
            "password", user_id=account["id"], password=password
        )

    def open_role_manager(self):
        if not self.roles_available or not self.permissions_available:
            self._show_load_error(
                "Pengelolaan role dan permission memerlukan permission "
                "auth.roles.manage."
            )
            return
        dialog = DeveloperRoleManagerDialog(
            self.api_client, self.roles, self.permissions, self
        )
        dialog.exec()
        if dialog.did_change:
            self.load_page(self.offset)

    def show_selected_details(self):
        row = self.table.currentRow()
        if row >= 0:
            self.show_details(row, 0)

    def show_details(self, row, column):
        self.table.setCurrentCell(row, column)
        account = self._selected_account()
        if account is None:
            self._show_load_error("Akun Developer yang dipilih tidak valid.")
            return
        lines = [
            f"ID: {account['id']}",
            f"Username: {account['username']}",
            f"Nama lengkap: {account['full_name']}",
            "Status: " + ("ACTIVE" if account["is_active"] else "INACTIVE"),
            "Role: " + (", ".join(account["roles"]) or "—"),
            f"Dibuat: {account['created_at']}",
            f"Diperbarui: {account['updated_at']}",
            "",
            "Detail berasal dari endpoint daftar; API tidak menyediakan "
            "endpoint detail akun tersendiri.",
        ]
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Detail Akun Developer")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText("\n".join(lines))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.exec()

    def _start_mutation(self, operation, **values):
        if self.request_pending or self.mutation_pending:
            return
        self.mutation_pending = True
        self.mutation_succeeded = False
        self._update_actions()
        self.data_status.setText(
            "PENGGUNA DEVELOPER: MENYIMPAN KE UNIVERSAL API..."
        )
        self.data_status.setToolTip("")
        self.data_status.setStyleSheet("")
        self.mutation_worker = DeveloperMutationWorker(
            self.api_client, operation, **values
        )
        self.mutation_worker.saved.connect(self._mutation_saved)
        self.mutation_worker.failed.connect(self._mutation_failed)
        self.mutation_worker.finished.connect(self._mutation_finished)
        self.mutation_worker.start()

    def _mutation_saved(self, operation, result):
        self.mutation_succeeded = True
        if operation == "password":
            message = (
                "Password direset melalui Universal API. Sesi akun dicabut "
                "oleh API; password tidak ditampilkan atau disimpan."
            )
        else:
            message = "Perubahan akun tersimpan melalui Universal API."
        self.data_status.setText("PENGGUNA DEVELOPER: " + message)
        self.data_status.setToolTip(
            "Respons API tidak menampilkan password atau token."
        )
        self.data_status.setStyleSheet(f"color:{MUTED_GOLD};")

    def _mutation_failed(self, message):
        self.data_status.setText(
            "PENGGUNA DEVELOPER: GAGAL MENYIMPAN — " + message
        )
        self.data_status.setToolTip(message)
        self.data_status.setStyleSheet("color:#A32323;")

    def _mutation_finished(self):
        if self.mutation_worker and "password" in self.mutation_worker.values:
            self.mutation_worker.values["password"] = ""
        self.mutation_pending = False
        if self.mutation_succeeded:
            self.load_page(self.offset)
        else:
            self._update_actions()
            self.refresh_button.setEnabled(True)

    def update_empty_state(self, visible_count=None):
        if self.table.rowCount() == 0:
            if self.request_pending:
                message = "Memuat akun Developer..."
            elif (
                hasattr(self, "data_status")
                and self.data_status.text().startswith(
                    "PENGGUNA DEVELOPER: GAGAL"
                )
            ):
                message = "Akun Developer belum dapat dimuat."
            elif self.accounts:
                message = "Tidak ada akun yang cocok dengan pencarian/filter."
            else:
                message = "Belum ada akun pada halaman ini."
        elif visible_count == 0:
            message = "Tidak ada akun yang cocok dengan pencarian/filter."
        else:
            message = ""
        self.empty_label.setText(message)
        self.empty_label.setVisible(bool(message))

    def wait_for_load(self):
        for worker in (self.worker, self.mutation_worker):
            if worker and worker.isRunning():
                worker.wait()


class TenantListWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client

    def run(self):
        try:
            tenants = self.api_client.list_tenants()
        except ApiError as exc:
            self.failed.emit(str(exc))
        else:
            self.loaded.emit(tenants)


class PartialTenantSaveError(Exception):
    pass


class TenantSaveWorker(QThread):
    saved = Signal()
    failed = Signal(str, bool)

    def __init__(
        self,
        api_client,
        tenant_id,
        code,
        name,
        organization_name,
        status,
        original_status,
        reason,
        original_identity=None,
    ):
        super().__init__()
        self.api_client = api_client
        self.tenant_id = tenant_id
        self.code = code
        self.name = name
        self.organization_name = organization_name
        self.status = status
        self.original_status = original_status
        self.reason = reason
        self.original_identity = original_identity or {}

    def run(self):
        try:
            if self.tenant_id is None:
                tenant = self.api_client.create_tenant(
                    self.code, self.name, self.organization_name
                )
                tenant_id = tenant["id"]
                if self.status != "ACTIVE":
                    try:
                        self.api_client.change_tenant_status(
                            tenant_id, self.status, self.reason
                        )
                    except ApiError as exc:
                        raise PartialTenantSaveError(
                            "Tenant berhasil dibuat dengan status ACTIVE, "
                            f"tetapi status {self.status} gagal diterapkan: "
                            f"{exc}"
                        ) from exc
            else:
                identity_changed = (
                    self.code != self.original_identity.get("code")
                    or self.name != self.original_identity.get("name")
                    or self.organization_name
                    != self.original_identity.get("organization_name")
                )
                if identity_changed:
                    self.api_client.update_tenant(
                        self.tenant_id,
                        self.code,
                        self.name,
                        self.organization_name,
                    )
                if self.status != self.original_status:
                    try:
                        self.api_client.change_tenant_status(
                            self.tenant_id, self.status, self.reason
                        )
                    except ApiError as exc:
                        raise PartialTenantSaveError(
                            "Data Tenant berhasil diperbarui, tetapi "
                            f"perubahan status ke {self.status} gagal: {exc}"
                        ) from exc
        except PartialTenantSaveError as exc:
            self.failed.emit(str(exc), True)
        except ApiError as exc:
            self.failed.emit(str(exc), False)
        else:
            self.saved.emit()


class TenantPage(DataPage):
    TENANT_STATUSES = ("ACTIVE", "INACTIVE", "RESTRICTED")

    def __init__(self, api_client):
        self.loaded_from_api = False
        self.load_error = None
        super().__init__(
            "Tenant / Client",
            "Identitas dan status organisasi client SIMPATI.",
            [
                "NO.",
                "TENANT ID",
                "NAMA TENANT",
                "ORGANISASI",
                "STATUS",
                "TANGGAL DAFTAR",
            ],
            [
                ("TENANT ID", True),
                ("NAMA TENANT", True),
                ("ORGANISASI", False),
                ("EMAIL KONTAK", False),
                ("STATUS", True, self.TENANT_STATUSES),
            ],
            filter_column=4,
            filter_values=self.TENANT_STATUSES,
            add_label="Tambah Tenant",
        )
        self.api_client = api_client
        self.tenant_worker = None
        self.refresh_button = QPushButton("Muat Ulang")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.clicked.connect(self.load_tenants)
        self.toolbar.addWidget(self.refresh_button)
        self.empty_label.setText(
            "Buka menu ini untuk memuat daftar Tenant dari Universal API."
        )

    def open_edit_form(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self, "Edit data", "Pilih satu baris terlebih dahulu."
            )
            return
        values = {}
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)
            if item:
                values[self.table.horizontalHeaderItem(column).text()] = (
                    item.text()
                )
        if values.get("ORGANISASI") == "—":
            values["ORGANISASI"] = ""
        tenant_id_item = self.table.item(row, 1)
        tenant_id = (
            tenant_id_item.data(Qt.ItemDataRole.UserRole)
            if tenant_id_item
            else None
        )
        if type(tenant_id) is not int:
            QMessageBox.warning(
                self, "Edit Tenant", "ID Tenant dari server tidak valid."
            )
            return
        original_identity = {
            "code": values["TENANT ID"],
            "name": values["NAMA TENANT"],
            "organization_name": values["ORGANISASI"] or None,
        }
        self.open_form(
            "Edit " + self.title,
            values,
            tenant_id,
            original_identity,
        )

    def open_form(
        self, title, initial_values=None, tenant_id=None, original_identity=None
    ):
        initial_values = initial_values or {}
        original_status = initial_values.get("STATUS", "ACTIVE")
        fields = self.form_fields + [
            ("ALASAN PERUBAHAN STATUS", False)
        ]
        dialog = FormDialog(
            title,
            fields,
            initial_values,
            parent=self,
            submit_handler=lambda form: self._submit_tenant(
                form, tenant_id, original_status, original_identity
            ),
        )
        reason_field = dialog.inputs["ALASAN PERUBAHAN STATUS"]
        reason_field.setMaxLength(1000)
        reason_label = dialog.form_layout.labelForField(reason_field)
        status_field = dialog.inputs["STATUS"]

        def update_reason_visibility(_status=None):
            visible = dialog.value("STATUS") != original_status
            reason_field.setVisible(visible)
            if reason_label:
                reason_label.setVisible(visible)

        status_field.currentTextChanged.connect(update_reason_visibility)
        update_reason_visibility()
        dialog.exec()

    def _submit_tenant(
        self, dialog, tenant_id, original_status, original_identity=None
    ):
        values = dialog.values()
        if values["EMAIL KONTAK"].strip():
            dialog.show_error(
                "Universal API belum mendukung field EMAIL KONTAK Tenant. "
                "Kosongkan field tersebut untuk menyimpan."
            )
            return

        status = values["STATUS"]
        reason = values["ALASAN PERUBAHAN STATUS"].strip()
        if status != original_status and len(reason) < 3:
            dialog.show_error(
                "Alasan perubahan status wajib diisi minimal 3 karakter."
            )
            return

        if self.api_client is None:
            dialog.show_error("Client Universal API tidak tersedia.")
            return

        organization_name = values["ORGANISASI"].strip() or None
        dialog.set_busy(True)
        dialog.validation_message.setText("Menyimpan perubahan Tenant...")
        self.save_worker = TenantSaveWorker(
            self.api_client,
            tenant_id,
            values["TENANT ID"].strip(),
            values["NAMA TENANT"].strip(),
            organization_name,
            status,
            original_status,
            reason,
            original_identity,
        )
        self.save_worker.saved.connect(
            lambda: self._tenant_save_succeeded(dialog)
        )
        self.save_worker.failed.connect(
            lambda message, partial: self._tenant_save_failed(
                dialog, message, partial
            )
        )
        self.save_worker.start()

    def _tenant_save_succeeded(self, dialog):
        dialog.accept()
        self.load_tenants()

    def _tenant_save_failed(self, dialog, message, partial):
        dialog.set_busy(False)
        dialog.show_error(message)
        if partial:
            self.load_tenants()

    def load_tenants(self):
        if self.api_client is None:
            self._show_load_error("Client Universal API tidak tersedia.")
            return
        if self.tenant_worker and self.tenant_worker.isRunning():
            return

        self.load_error = None
        self.data_status.setText("DATA TENANT: MEMUAT...")
        self.data_status.setToolTip("")
        self.data_status.setStyleSheet("")
        if self.table.rowCount() == 0:
            self.empty_label.setText("Memuat daftar Tenant dari server...")
            self.empty_label.setVisible(True)
        self.refresh_button.setEnabled(False)
        self.tenant_worker = TenantListWorker(self.api_client)
        self.tenant_worker.loaded.connect(self._show_tenants)
        self.tenant_worker.failed.connect(self._show_load_error)
        self.tenant_worker.start()

    def _show_tenants(self, tenants):
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(tenants))
            for row, tenant in enumerate(tenants):
                values = (
                    row + 1,
                    tenant["code"],
                    tenant["name"],
                    tenant.get("organization_name") or "—",
                    tenant["status"],
                    tenant["created_at"],
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 1:
                        item.setData(Qt.ItemDataRole.UserRole, tenant["id"])
                    self.table.setItem(row, column, item)
        finally:
            self.table.blockSignals(False)

        self.loaded_from_api = True
        self.load_error = None
        self.refresh_button.setEnabled(True)
        self.data_status.setText(
            f"DATA TENANT: {len(tenants)} DIMUAT DARI API"
        )
        self.data_status.setToolTip("Daftar Tenant berhasil dimuat dari server.")
        self.data_status.setStyleSheet("")
        self.refresh_filter_choices()
        self.update_edit_button()
        self.filter_table()

    def _show_load_error(self, message):
        self.load_error = message
        self.refresh_button.setEnabled(True)
        self.data_status.setText(f"DATA TENANT: GAGAL DIMUAT — {message}")
        self.data_status.setToolTip(message)
        self.data_status.setStyleSheet("color:#A32323;")
        if self.table.rowCount() == 0:
            self.empty_label.setText(
                "Tidak dapat memuat daftar Tenant dari Universal API.\n"
                + message
            )
            self.empty_label.setVisible(True)

    def update_empty_state(self, visible_count=None):
        if self.load_error and self.table.rowCount() == 0:
            self.empty_label.setText(
                "Tidak dapat memuat daftar Tenant dari Universal API.\n"
                + self.load_error
            )
            self.empty_label.setVisible(True)
            return
        if self.loaded_from_api and self.table.rowCount() == 0:
            self.empty_label.setText("Belum ada Tenant pada server.")
            self.empty_label.setVisible(True)
            return
        super().update_empty_state(visible_count)

    def wait_for_load(self):
        if self.tenant_worker and self.tenant_worker.isRunning():
            self.tenant_worker.wait()


class InstallationsListWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, api_client, include_deleted=False):
        super().__init__()
        self.api_client = api_client
        self.include_deleted = include_deleted

    def run(self):
        try:
            installations = self.api_client.list_installations(
                self.include_deleted
            )
        except ApiError as exc:
            self.failed.emit(str(exc))
        else:
            self.loaded.emit(installations)


class InstallationDetailWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, api_client, tenant_id, installation_id):
        super().__init__()
        self.api_client = api_client
        self.tenant_id = tenant_id
        self.installation_id = installation_id

    def run(self):
        try:
            installation = self.api_client.get_tenant_installation(
                self.tenant_id, self.installation_id
            )
        except ApiError as exc:
            self.failed.emit(str(exc))
        else:
            self.loaded.emit(installation)


class InstallationPage(DataPage):
    def __init__(self, api_client):
        self.api_client = api_client
        self.installations_worker = None
        self.detail_worker = None
        self.list_request_pending = False
        self.tenants_by_id = {}
        self.load_error = None
        super().__init__(
            "Manajemen Instalasi",
            "Daftar instalasi aktif Tenant dan informasi perangkat dari "
            "Universal API. Klik dua kali untuk memuat detail dari server.",
            [
                "NO.",
                "INSTALLATION ID",
                "TENANT",
                "DEVICE ID",
                "NAMA PERANGKAT",
                "PLATFORM",
                "VERSI APLIKASI",
                "STATUS",
                "TERAKHIR AKTIF",
            ],
            filter_column=7,
            filter_values=("ACTIVE", "REVOKED"),
        )
        self.refresh_button = QPushButton("Muat Ulang")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.clicked.connect(self.load_installations)
        self.toolbar.addWidget(self.refresh_button)
        self.include_revoked = QCheckBox(
            "Sertakan instalasi dicabut"
        )
        self.include_revoked.stateChanged.connect(
            lambda *_: self.load_installations()
        )
        self.toolbar.addWidget(self.include_revoked)
        self.empty_label.setText(
            "Buka menu ini untuk memuat instalasi dari Universal API."
        )

    def load_installations(self):
        if self.api_client is None:
            self._show_load_error("Client Universal API tidak tersedia.")
            return
        if self.list_request_pending:
            return
        if self.detail_worker and self.detail_worker.isRunning():
            return
        self.list_request_pending = True
        self.load_error = None
        self.table.setRowCount(0)
        self.empty_label.setText("Memuat daftar instalasi dari API...")
        self.empty_label.setVisible(True)
        self.data_status.setText("DATA INSTALASI: MEMUAT...")
        self.data_status.setToolTip("")
        self.data_status.setStyleSheet("")
        self.refresh_button.setEnabled(False)
        self.include_revoked.setEnabled(False)
        self.installations_worker = InstallationsListWorker(
            self.api_client, self.include_revoked.isChecked()
        )
        self.installations_worker.loaded.connect(self._show_installations)
        self.installations_worker.failed.connect(self._show_load_error)
        self.installations_worker.finished.connect(
            self._installations_finished
        )
        self.installations_worker.start()

    def _show_installations(self, installations):
        self.tenants_by_id = {}
        self.installations_by_identity = {}
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(installations))
            for row, installation in enumerate(installations):
                tenant_id = installation["tenant_id"]
                identity = (tenant_id, installation["id"])
                self.installations_by_identity[identity] = installation
                tenant = {
                    "id": tenant_id,
                    "code": installation["tenant_code"],
                    "name": installation["tenant_name"],
                }
                self.tenants_by_id[tenant_id] = tenant
                device = installation["device"]
                tenant_label = (
                    f"{tenant['code']} — {tenant['name']}"
                )
                values = (
                    row + 1,
                    installation["id"],
                    tenant_label,
                    device["id"],
                    device.get("name") or "—",
                    device["platform"],
                    device.get("app_version") or "—",
                    installation["status"],
                    installation.get("last_seen_at") or "—",
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 1:
                        item.setData(
                            Qt.ItemDataRole.UserRole,
                            {
                                "tenant_id": tenant_id,
                                "installation_id": installation["id"],
                            },
                        )
                    elif column == 2:
                        item.setData(
                            Qt.ItemDataRole.UserRole, tenant_id
                        )
                    self.table.setItem(row, column, item)
        finally:
            self.table.blockSignals(False)

        self.load_error = None
        self.data_status.setText(
            f"DATA INSTALASI: {len(installations)} DIMUAT DARI API"
        )
        self.data_status.setToolTip(
            "Data digabung dari daftar Tenant dan endpoint instalasi per Tenant."
        )
        self.data_status.setStyleSheet("")
        self.refresh_filter_choices()
        self.filter_table()

    def _show_load_error(self, message):
        self.load_error = message
        self.data_status.setText(
            f"DATA INSTALASI: GAGAL DIMUAT — {message}"
        )
        self.data_status.setToolTip(message)
        self.data_status.setStyleSheet("color:#A32323;")
        if self.table.rowCount() == 0:
            self.empty_label.setText(
                "Tidak dapat memuat instalasi dari Universal API.\n" + message
            )
            self.empty_label.setVisible(True)

    def _installations_finished(self):
        self.list_request_pending = False
        self.refresh_button.setEnabled(True)
        self.include_revoked.setEnabled(True)

    def update_empty_state(self, visible_count=None):
        if self.load_error and self.table.rowCount() == 0:
            self.empty_label.setText(
                "Tidak dapat memuat instalasi dari Universal API.\n"
                + self.load_error
            )
            self.empty_label.setVisible(True)
            return
        if self.table.rowCount() == 0:
            include_revoked = getattr(self, "include_revoked", None)
            message = (
                "Belum ada instalasi pada server."
                if include_revoked and include_revoked.isChecked()
                else "Belum ada instalasi aktif pada server."
            )
            self.empty_label.setText(message)
            self.empty_label.setVisible(True)
            return
        super().update_empty_state(visible_count)

    def show_details(self, row, column):
        self.table.setCurrentCell(row, column)
        item = self.table.item(row, 1)
        identity = (
            item.data(Qt.ItemDataRole.UserRole) if item else None
        )
        if (
            not isinstance(identity, dict)
            or type(identity.get("tenant_id")) is not int
            or type(identity.get("installation_id")) is not int
        ):
            self._show_detail_error(
                "Identitas instalasi pada daftar tidak valid."
            )
            return
        installation = self.installations_by_identity.get(
            (identity["tenant_id"], identity["installation_id"])
        )
        if installation and installation.get("deleted_at") is not None:
            self._show_installation_detail(installation)
            return
        if self.api_client is None:
            self._show_detail_error("Client Universal API tidak tersedia.")
            return
        if self.detail_worker and self.detail_worker.isRunning():
            return
        self.data_status.setText("DETAIL INSTALASI: MEMUAT DARI API...")
        self.refresh_button.setEnabled(False)
        self.include_revoked.setEnabled(False)
        self.detail_worker = InstallationDetailWorker(
            self.api_client,
            identity["tenant_id"],
            identity["installation_id"],
        )
        self.detail_worker.loaded.connect(self._show_installation_detail)
        self.detail_worker.failed.connect(self._show_detail_error)
        self.detail_worker.finished.connect(self._detail_finished)
        self.detail_worker.start()

    def _show_installation_detail(self, installation):
        tenant = self.tenants_by_id.get(installation["tenant_id"])
        tenant_name = tenant["name"] if tenant else "—"
        tenant_code = tenant["code"] if tenant else "—"
        device = installation["device"]
        details = device.get("details") or {}
        lines = [
            f"Tenant ID: {installation['tenant_id']}",
            f"Tenant: {tenant_code} — {tenant_name}",
            f"Installation ID: {installation['id']}",
            f"Status: {installation['status']}",
            f"Device ID: {device['id']}",
            f"Nama perangkat: {device.get('name') or '—'}",
            f"Platform: {device['platform']}",
            f"Versi aplikasi: {device.get('app_version') or '—'}",
            "Informasi perangkat:",
        ]
        lines.extend(
            f"  {name}: {value}"
            for name, value in sorted(details.items())
        )
        lines.extend(
            (
                f"Pertama terlihat: {installation['first_seen_at']}",
                "Terakhir aktif: "
                + (installation.get("last_seen_at") or "—"),
                f"Dibuat: {installation['created_at']}",
                f"Diperbarui: {installation['updated_at']}",
                "Dihapus: " + (installation.get("deleted_at") or "—"),
            )
        )
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Detail Instalasi")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText("\n".join(lines))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.exec()
        self.data_status.setText(
            "DETAIL INSTALASI: DIMUAT DARI UNIVERSAL API"
        )
        self.data_status.setStyleSheet(f"color:{MUTED_GOLD};")

    def _show_detail_error(self, message):
        self.data_status.setText(
            f"DETAIL INSTALASI: GAGAL DIMUAT — {message}"
        )
        self.data_status.setToolTip(message)
        self.data_status.setStyleSheet("color:#A32323;")

    def _detail_finished(self):
        self.refresh_button.setEnabled(True)
        self.include_revoked.setEnabled(True)

    def wait_for_load(self):
        for worker in (
            self.installations_worker,
            self.detail_worker,
        ):
            if worker and worker.isRunning():
                worker.wait()


class ModuleCatalogWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client

    def run(self):
        try:
            modules = self.api_client.list_modules()
        except ApiError as exc:
            self.failed.emit(str(exc))
        else:
            self.loaded.emit(modules)


class ModuleDetailWorker(QThread):
    loaded = Signal(object, object, str)
    failed = Signal(str)

    def __init__(self, api_client, module_id):
        super().__init__()
        self.api_client = api_client
        self.module_id = module_id

    def run(self):
        try:
            module = self.api_client.get_module(self.module_id)
        except ApiError as exc:
            self.failed.emit(str(exc))
            return
        try:
            usage = self.api_client.list_module_tenant_usage(
                module["code"]
            )
        except ApiError as exc:
            self.loaded.emit(module, None, str(exc))
        else:
            self.loaded.emit(module, usage, "")


class ModuleMutationWorker(QThread):
    saved = Signal(object)
    failed = Signal(str)

    def __init__(self, api_client, operation, **values):
        super().__init__()
        self.api_client = api_client
        self.operation = operation
        self.values = values

    def run(self):
        try:
            if self.operation == "create":
                module = self.api_client.create_module(
                    self.values["code"],
                    self.values["name"],
                    self.values["description"],
                )
            elif self.operation == "update":
                module = self.api_client.update_module(
                    self.values["module_id"],
                    self.values["name"],
                    self.values["description"],
                )
            else:
                module = self.api_client.set_module_active(
                    self.values["module_id"],
                    self.values["is_active"],
                )
        except ApiError as exc:
            self.failed.emit(str(exc))
        else:
            self.saved.emit(module)


class ModulePage(DataPage):
    def __init__(self, api_client):
        self.api_client = api_client
        self.catalog_loaded = False
        self.load_error = None
        self.catalog_pending = False
        self.mutation_pending = False
        self.pending_dialog = None
        self.modules_by_id = {}
        self.catalog_worker = None
        self.detail_worker = None
        self.mutation_worker = None
        super().__init__(
            "Modul Sistem",
            "Katalog, status katalog, dan data penggunaan per Tenant dari "
            "Universal API.",
            [
                "NO.",
                "MODULE ID",
                "KODE MODUL",
                "NAMA MODUL",
                "DESKRIPSI",
                "STATUS KATALOG",
            ],
            filter_column=5,
            filter_values=("ACTIVE", "INACTIVE"),
        )
        self.distinction_note = QLabel(
            "Status katalog tidak sama dengan assignment Tenant; keduanya "
            "juga bukan lisensi. Penggunaan per Tenant ditampilkan pada detail."
        )
        self.distinction_note.setObjectName("subtleText")
        self.distinction_note.setWordWrap(True)
        self.layout().insertWidget(2, self.distinction_note)
        self.refresh_button = QPushButton("Muat Ulang")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.clicked.connect(self.load_modules)
        self.toolbar.addWidget(self.refresh_button)
        self.create_button = QPushButton("+ Tambah Modul")
        self.create_button.clicked.connect(self.open_create_form)
        self.toolbar.addWidget(self.create_button)
        self.edit_module_button = QPushButton("Edit Detail")
        self.edit_module_button.setObjectName("secondaryButton")
        self.edit_module_button.setEnabled(False)
        self.edit_module_button.clicked.connect(self.open_edit_form)
        self.toolbar.addWidget(self.edit_module_button)
        self.status_button = QPushButton("Ubah Status")
        self.status_button.setObjectName("secondaryButton")
        self.status_button.setEnabled(False)
        self.status_button.clicked.connect(self.toggle_module_status)
        self.toolbar.addWidget(self.status_button)
        self.table.itemSelectionChanged.connect(self.update_module_buttons)
        self.distinction_note.setTextFormat(Qt.TextFormat.PlainText)
        self.empty_label.setText(
            "Buka menu ini untuk memuat katalog modul dari Universal API."
        )

    def load_modules(self):
        if self.api_client is None:
            self._show_catalog_error("Client Universal API tidak tersedia.")
            return
        if self.catalog_pending or self.mutation_pending:
            return
        self.catalog_pending = True
        self.table.setRowCount(0)
        self.modules_by_id = {}
        self.load_error = None
        self.empty_label.setText("Memuat katalog modul dari API...")
        self.empty_label.setVisible(True)
        self.data_status.setText("KATALOG MODUL: MEMUAT...")
        self.data_status.setToolTip("")
        self.data_status.setStyleSheet("")
        self.update_module_buttons()
        self.catalog_worker = ModuleCatalogWorker(self.api_client)
        self.catalog_worker.loaded.connect(self._show_modules)
        self.catalog_worker.failed.connect(self._show_catalog_error)
        self.catalog_worker.finished.connect(self._catalog_finished)
        self.catalog_worker.start()

    def _catalog_finished(self):
        self.catalog_pending = False
        self.refresh_button.setEnabled(True)
        self.update_module_buttons()

    def _show_modules(self, modules):
        self.modules_by_id = {
            module["id"]: module for module in modules
        }
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(modules))
            for row, module in enumerate(modules):
                values = (
                    row + 1,
                    module["id"],
                    module["code"],
                    module["name"],
                    module.get("description") or "—",
                    "ACTIVE" if module["is_active"] else "INACTIVE",
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 1:
                        item.setData(
                            Qt.ItemDataRole.UserRole, module["id"]
                        )
                    self.table.setItem(row, column, item)
        finally:
            self.table.blockSignals(False)
        self.catalog_loaded = True
        self.load_error = None
        self.data_status.setText(
            f"KATALOG MODUL: {len(modules)} DIMUAT DARI API"
        )
        self.data_status.setToolTip(
            "Status ACTIVE/INACTIVE adalah status katalog dari Universal API."
        )
        self.data_status.setStyleSheet("")
        self.refresh_filter_choices()
        self.filter_table()
        self.update_module_buttons()

    def _show_catalog_error(self, message):
        self.load_error = message
        self.data_status.setText(f"KATALOG MODUL: GAGAL DIMUAT — {message}")
        self.data_status.setToolTip(message)
        self.data_status.setStyleSheet("color:#A32323;")
        if self.table.rowCount() == 0:
            self.empty_label.setText(
                "Tidak dapat memuat katalog dari Universal API.\n" + message
            )
            self.empty_label.setVisible(True)

    def update_empty_state(self, visible_count=None):
        if self.load_error and self.table.rowCount() == 0:
            self.empty_label.setText(
                "Tidak dapat memuat katalog dari Universal API.\n"
                + self.load_error
            )
            self.empty_label.setVisible(True)
            return
        if self.table.rowCount() == 0 and self.catalog_loaded:
            self.empty_label.setText("Belum ada data katalog modul.")
            self.empty_label.setVisible(True)
            return
        if self.table.rowCount() == 0 and not self.catalog_loaded:
            if not self.load_error:
                self.empty_label.setText(
                    "Buka menu ini untuk memuat katalog modul dari "
                    "Universal API."
                )
                self.empty_label.setVisible(True)
            return
        super().update_empty_state(visible_count)

    def _selected_module(self):
        row = self.table.currentRow()
        item = self.table.item(row, 1) if row >= 0 else None
        module_id = (
            item.data(Qt.ItemDataRole.UserRole) if item else None
        )
        return self.modules_by_id.get(module_id)

    def update_module_buttons(self):
        module = self._selected_module()
        busy = self.catalog_pending or self.mutation_pending
        self.refresh_button.setEnabled(not busy)
        self.create_button.setEnabled(not busy)
        self.edit_module_button.setEnabled(not busy and module is not None)
        if module is None:
            self.status_button.setText("Ubah Status")
        else:
            self.status_button.setText(
                "Nonaktifkan Modul"
                if module["is_active"]
                else "Aktifkan Modul"
            )
        can_change_status = (
            not busy
            and module is not None
            and not (module["code"] == "CORE" and module["is_active"])
        )
        self.status_button.setEnabled(can_change_status)

    def open_create_form(self):
        if self.api_client is None:
            self._show_catalog_error("Client Universal API tidak tersedia.")
            return
        dialog = FormDialog(
            "Tambah Modul",
            [("KODE MODUL", True), ("NAMA MODUL", True), ("DESKRIPSI", False)],
            parent=self,
            submit_handler=self._submit_create,
        )
        dialog.inputs["KODE MODUL"].setMaxLength(50)
        dialog.inputs["NAMA MODUL"].setMaxLength(150)
        dialog.inputs["DESKRIPSI"].setMaxLength(4000)
        dialog.exec()

    def _submit_create(self, dialog):
        values = dialog.values()
        self._start_mutation(
            dialog,
            "create",
            code=values["KODE MODUL"],
            name=values["NAMA MODUL"],
            description=values["DESKRIPSI"] or None,
        )

    def open_edit_form(self):
        module = self._selected_module()
        if module is None:
            return
        dialog = FormDialog(
            "Edit Modul",
            [("NAMA MODUL", True), ("DESKRIPSI", False)],
            {
                "NAMA MODUL": module["name"],
                "DESKRIPSI": module.get("description") or "",
            },
            parent=self,
            submit_handler=lambda form: self._submit_edit(
                form, module["id"]
            ),
        )
        dialog.inputs["NAMA MODUL"].setMaxLength(150)
        dialog.inputs["DESKRIPSI"].setMaxLength(4000)
        dialog.exec()

    def _submit_edit(self, dialog, module_id):
        values = dialog.values()
        self._start_mutation(
            dialog,
            "update",
            module_id=module_id,
            name=values["NAMA MODUL"],
            description=values["DESKRIPSI"] or None,
        )

    def toggle_module_status(self):
        module = self._selected_module()
        if module is None:
            return
        self._start_mutation(
            None,
            "status",
            module_id=module["id"],
            is_active=not module["is_active"],
        )

    def _start_mutation(self, dialog, operation, **values):
        if self.api_client is None:
            if dialog:
                dialog.show_error("Client Universal API tidak tersedia.")
            else:
                self._show_catalog_error(
                    "Client Universal API tidak tersedia."
                )
            return
        if self.catalog_pending or self.mutation_pending:
            return
        self.mutation_pending = True
        self.pending_dialog = dialog
        if dialog:
            dialog.set_busy(True)
            dialog.validation_message.setText(
                "Menyimpan ke Universal API..."
            )
        self.data_status.setText("PERUBAHAN MODUL: MENYIMPAN...")
        self.data_status.setStyleSheet("")
        self.update_module_buttons()
        self.mutation_worker = ModuleMutationWorker(
            self.api_client, operation, **values
        )
        self.mutation_worker.saved.connect(self._module_saved)
        self.mutation_worker.failed.connect(self._module_mutation_failed)
        self.mutation_worker.finished.connect(self._mutation_finished)
        self.mutation_worker.start()

    def _module_saved(self, module):
        dialog = self.pending_dialog
        self._upsert_module(module)
        if dialog:
            dialog.accept()
        self.data_status.setText(
            f"MODUL {module['code']}: PERUBAHAN TERSIMPAN DI API"
        )
        self.data_status.setToolTip(
            "Data modul diperbarui melalui Universal API."
        )
        self.data_status.setStyleSheet(f"color:{MUTED_GOLD};")

    def _module_mutation_failed(self, message):
        if self.pending_dialog:
            self.pending_dialog.set_busy(False)
            self.pending_dialog.show_error(message)
        self.data_status.setText("PERUBAHAN MODUL: GAGAL")
        self.data_status.setToolTip(message)
        self.data_status.setStyleSheet("color:#A32323;")

    def _mutation_finished(self):
        self.mutation_pending = False
        self.pending_dialog = None
        self.update_module_buttons()

    def _upsert_module(self, module):
        module_id = module["id"]
        row = next(
            (
                index
                for index in range(self.table.rowCount())
                if self.table.item(index, 1).data(
                    Qt.ItemDataRole.UserRole
                )
                == module_id
            ),
            None,
        )
        if row is None:
            row = self.table.rowCount()
            self.table.insertRow(row)
        self.modules_by_id[module_id] = module
        values = (
            row + 1,
            module["id"],
            module["code"],
            module["name"],
            module.get("description") or "—",
            "ACTIVE" if module["is_active"] else "INACTIVE",
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            if column == 1:
                item.setData(Qt.ItemDataRole.UserRole, module_id)
            self.table.setItem(row, column, item)
        self.refresh_filter_choices()
        self.filter_table()
        self.update_module_buttons()

    def show_details(self, row, column):
        self.table.setCurrentCell(row, column)
        module = self._selected_module()
        if module is None:
            self._show_catalog_error("ID modul pada tabel tidak valid.")
            return
        if self.api_client is None:
            self._show_catalog_error("Client Universal API tidak tersedia.")
            return
        if self.detail_worker and self.detail_worker.isRunning():
            return
        self.data_status.setText("DETAIL MODUL: MEMUAT DARI API...")
        self.detail_worker = ModuleDetailWorker(
            self.api_client, module["id"]
        )
        self.detail_worker.loaded.connect(self._show_module_detail)
        self.detail_worker.failed.connect(self._show_module_detail_error)
        self.detail_worker.start()

    def _show_module_detail(self, module, usage, usage_error):
        lines = [
            f"Module ID: {module['id']}",
            f"Kode: {module['code']}",
            f"Nama: {module['name']}",
            f"Deskripsi: {module.get('description') or '—'}",
            "Status katalog: "
            + ("ACTIVE" if module["is_active"] else "INACTIVE"),
            f"Dibuat: {module['created_at']}",
            f"Diperbarui: {module['updated_at']}",
            "",
            "PENGGUNAAN PER TENANT",
        ]
        if usage_error:
            lines.append(
                "Data penggunaan gagal dimuat dari Universal API: "
                + usage_error
            )
        elif not usage:
            lines.append("Tidak ada Tenant pada server.")
        else:
            enabled = sum(item["is_enabled"] for item in usage)
            assigned_but_disabled = sum(
                item["is_assigned"] and not item["is_enabled"]
                for item in usage
            )
            lines.extend(
                (
                    f"Assignment aktif: {enabled}",
                    f"Assignment nonaktif: {assigned_but_disabled}",
                    "",
                )
            )
            assigned_tenants = [
                item for item in usage if item["is_assigned"]
            ]
            if not assigned_tenants:
                lines.append("Belum ada assignment modul pada Tenant.")
            else:
                lines.extend(
                    f"{item['tenant_code']} — {item['tenant_name']}: "
                    f"{item['status']}"
                    for item in assigned_tenants
                )
        lines.extend(
            (
                "",
                "Status katalog, assignment modul, dan lisensi adalah data "
                "yang berbeda.",
            )
        )
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Detail Modul")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText("\n".join(lines))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.exec()
        self.data_status.setText("DETAIL MODUL: DIMUAT DARI UNIVERSAL API")
        self.data_status.setToolTip(
            usage_error or "Detail katalog dan penggunaan dari Universal API."
        )
        self.data_status.setStyleSheet(
            "color:#A32323;" if usage_error else f"color:{MUTED_GOLD};"
        )

    def _show_module_detail_error(self, message):
        self.data_status.setText(
            f"DETAIL MODUL: GAGAL DIMUAT — {message}"
        )
        self.data_status.setToolTip(message)
        self.data_status.setStyleSheet("color:#A32323;")

    def wait_for_load(self):
        for worker in (
            self.catalog_worker,
            self.detail_worker,
            self.mutation_worker,
        ):
            if worker and worker.isRunning():
                worker.wait()


class ConfigurationPage(QWidget):
    def __init__(self):
        super().__init__()
        self.connection_worker = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(16)
        layout.addWidget(make_title("Konfigurasi"))

        description = QLabel(
            "Pengaturan lokal aplikasi. Tidak ada secret key atau "
            "kredensial database yang diminta atau disimpan."
        )
        description.setObjectName("subtleText")
        description.setWordWrap(True)
        layout.addWidget(description)

        settings = settings_store()
        self.sections_scroll = QScrollArea()
        self.sections_scroll.setWidgetResizable(True)
        self.sections_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sections = QWidget()
        self.sections_layout = QVBoxLayout(sections)
        self.sections_layout.setContentsMargins(0, 0, 8, 0)
        self.sections_layout.setSpacing(12)
        self.sections_scroll.setWidget(sections)
        layout.addWidget(self.sections_scroll, 1)

        _, identity_form = self._add_section("Identitas Aplikasi")
        self.app_name = QLineEdit(
            settings.value("branding/app_name", APP_NAME)
        )
        self.version_value = QLabel(APP_VERSION)
        self.developer_value = QLabel(APP_DEVELOPER)
        identity_form.addRow("Nama aplikasi", self.app_name)
        identity_form.addRow("Versi aplikasi", self.version_value)
        identity_form.addRow("Developer", self.developer_value)

        _, connection_form = self._add_section("Koneksi Universal API")
        self.api_url = QLineEdit(settings.value("api/base_url", ""))
        self.api_url.setPlaceholderText("https://api.example.com")
        connection_form.addRow("Alamat API", self.api_url)
        self.test_connection_button = QPushButton("Uji Koneksi")
        self.test_connection_button.setObjectName("secondaryButton")
        self.test_connection_button.clicked.connect(self.test_connection)
        self.connection_status = make_status_label(
            "Koneksi Universal API: BELUM DIUJI"
        )
        self.connection_status.setWordWrap(True)
        connection_form.addRow(self.test_connection_button)
        connection_form.addRow(self.connection_status)

        _, appearance_form = self._add_section("Tampilan")
        self.theme = QComboBox()
        self.theme.addItem("Terang", "light")
        self.theme.addItem("Gelap", "dark")
        saved_theme = settings.value("appearance/theme", "light")
        theme_index = self.theme.findData(saved_theme)
        self.theme.setCurrentIndex(theme_index if theme_index >= 0 else 0)
        self.primary_color = QLineEdit(
            settings.value("branding/primary_color", MAROON)
        )
        self.accent_color = QLineEdit(
            settings.value("branding/accent_color", GOLD)
        )
        self.primary_color.setMaxLength(7)
        self.accent_color.setMaxLength(7)
        appearance_form.addRow("Tema", self.theme)
        appearance_form.addRow("Warna utama (#RRGGBB)", self.primary_color)
        appearance_form.addRow("Warna aksen (#RRGGBB)", self.accent_color)

        _, operation_form = self._add_section("Pengaturan Operasional")
        self.window_size = QComboBox()
        self.window_size.addItem("Ringkas — 1024 × 680", "1024x680")
        self.window_size.addItem("Standar — 1280 × 780", "1280x780")
        self.window_size.addItem("Besar — 1440 × 900", "1440x900")
        saved_size = settings.value(
            "operational/window_size", "1280x780"
        )
        size_index = self.window_size.findData(saved_size)
        self.window_size.setCurrentIndex(size_index if size_index >= 0 else 1)
        operation_form.addRow("Ukuran jendela", self.window_size)

        _, security_form = self._add_section("Keamanan")
        security_info = QLabel(
            "Token akses dan refresh disimpan melalui keyring sistem operasi. "
            "Password tidak disimpan. Masa berlaku sesi ditentukan Universal "
            "API; Desktop tidak mengatur timeout sesi lokal."
        )
        security_info.setWordWrap(True)
        security_info.setStyleSheet("font-weight: normal;")
        security_form.addRow(security_info)

        self.settings_notice = QLabel(
            "Pengaturan aplikasi disimpan lokal melalui QSettings. Alamat API "
            "tidak berisi kredensial; pengaturan lokal tidak mengubah "
            "konfigurasi pusat Universal API."
        )
        self.settings_notice.setObjectName("subtleText")
        self.settings_notice.setWordWrap(True)
        self.sections_layout.addWidget(self.settings_notice)
        self.sections_layout.addStretch()

        save_button = QPushButton("Simpan pengaturan lokal")
        save_button.clicked.connect(self.save_settings)
        layout.addWidget(save_button, alignment=Qt.AlignmentFlag.AlignLeft)

    def _add_section(self, title):
        panel = QFrame()
        panel.setObjectName("panel")
        section_layout = QVBoxLayout(panel)
        section_layout.setContentsMargins(20, 16, 20, 18)
        section_layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("configSectionTitle")
        section_layout.addWidget(heading)
        form = QFormLayout()
        form.setSpacing(12)
        section_layout.addLayout(form)
        self.sections_layout.addWidget(panel)
        return panel, form

    def test_connection(self):
        if self.connection_worker and self.connection_worker.isRunning():
            return
        try:
            api_url = ApiClient.validate_base_url(self.api_url.text())
            probe_client = ApiClient(api_url)
        except ApiError as exc:
            self._show_connection_result(False, str(exc))
            return

        self.connection_status.setText(
            "Koneksi Universal API: SEDANG DIUJI..."
        )
        self.connection_status.setToolTip("")
        self.connection_status.setStyleSheet("")
        self.test_connection_button.setEnabled(False)
        self.connection_worker = ConnectionCheckWorker(probe_client)
        self.connection_worker.checked.connect(
            self._show_connection_result
        )
        self.connection_worker.finished.connect(
            self._connection_test_finished
        )
        self.connection_worker.start()

    def _show_connection_result(self, connected, message):
        if connected:
            self.connection_status.setText(
                "Koneksi Universal API: TERHUBUNG"
            )
            self.connection_status.setStyleSheet(
                f"color:{MUTED_GOLD};"
            )
        else:
            self.connection_status.setText(
                "Koneksi Universal API: GAGAL — " + message
            )
            self.connection_status.setStyleSheet("color:#A32323;")
        self.connection_status.setToolTip(message)

    def _connection_test_finished(self):
        self.test_connection_button.setEnabled(True)

    def wait_for_connection_test(self):
        if self.connection_worker and self.connection_worker.isRunning():
            self.connection_worker.wait()

    def save_settings(self):
        if not self.app_name.text().strip():
            self.settings_notice.setText("Nama aplikasi wajib diisi.")
            self.settings_notice.setStyleSheet("color:#A32323;")
            return False

        api_url = self.api_url.text().strip()
        if api_url:
            try:
                api_url = ApiClient.validate_base_url(api_url)
            except ApiError:
                self.settings_notice.setText(
                    "URL API harus berupa URL lengkap dengan skema "
                    "http:// atau https://."
                )
                self.settings_notice.setStyleSheet("color:#A32323;")
                return False

        primary_text = self.primary_color.text().strip()
        accent_text = self.accent_color.text().strip()
        color_pattern = r"#[0-9A-Fa-f]{6}"
        if not re.fullmatch(color_pattern, primary_text) or not re.fullmatch(
            color_pattern, accent_text
        ):
            self.settings_notice.setText(
                "Format warna tidak valid. Gunakan format warna, misalnya "
                "#420D18."
            )
            self.settings_notice.setStyleSheet("color:#A32323;")
            return False
        primary = QColor(primary_text)
        accent = QColor(accent_text)
        window_size = self.window_size.currentData()
        if window_size not in WINDOW_SIZES:
            self.settings_notice.setText(
                "Ukuran jendela yang dipilih tidak valid."
            )
            self.settings_notice.setStyleSheet("color:#A32323;")
            return False

        settings = settings_store()
        settings.setValue("branding/app_name", self.app_name.text().strip())
        settings.setValue("api/base_url", api_url)
        settings.setValue("branding/primary_color", primary.name())
        settings.setValue("branding/accent_color", accent.name())
        settings.setValue("appearance/theme", self.theme.currentData())
        settings.setValue("operational/window_size", window_size)
        settings.sync()
        if settings.status() != QSettings.Status.NoError:
            self.settings_notice.setText(
                "Pengaturan gagal disimpan ke penyimpanan lokal."
            )
            self.settings_notice.setStyleSheet("color:#A32323;")
            return False

        apply_saved_branding()
        window = self.window()
        if isinstance(window, MainWindow):
            window.apply_local_configuration()
        self.settings_notice.setText(
            "Pengaturan lokal berhasil disimpan. Tampilan dan ukuran "
            "diterapkan sekarang; alamat API digunakan pada login berikutnya."
        )
        self.settings_notice.setStyleSheet(f"color:{MUTED_GOLD};")
        return True


class BackupRecoveryPage(QWidget):
    OPERATIONS = (
        (
            "Membuat backup database",
            "BELUM TERSEDIA",
            "Universal API belum menyediakan operasi backup database.",
        ),
        (
            "Melihat daftar backup",
            "BELUM TERSEDIA",
            "Belum ada model arsip atau endpoint daftar backup.",
        ),
        (
            "Mengunduh backup",
            "BELUM TERSEDIA",
            "Belum ada endpoint unduh arsip backup yang aman.",
        ),
        (
            "Memulihkan database",
            "BELUM TERSEDIA",
            "Belum ada mekanisme restore atau konfirmasi restore resmi.",
        ),
        (
            "Menghapus arsip backup",
            "BELUM TERSEDIA",
            "Belum ada penghapusan arsip atau mekanisme perlindungannya.",
        ),
        (
            "Status dan riwayat proses",
            "BELUM TERSEDIA",
            "Belum ada status pekerjaan maupun riwayat backup/restore.",
        ),
    )

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(14)
        layout.addWidget(make_title("Manajemen Backup dan Pemulihan"))

        self.readiness_status = make_status_label(
            "BACKUP DATABASE: BELUM DIDUKUNG UNIVERSAL API"
        )
        self.readiness_status.setStyleSheet("color:#A32323;")
        layout.addWidget(self.readiness_status)

        supported_note = QLabel(
            "Yang tersedia: GET /health/ready (alias GET /health) hanya "
            "memeriksa kesiapan koneksi database. Pemeriksaan ini bukan "
            "backup, ekspor data, atau pemulihan database."
        )
        supported_note.setObjectName("subtleText")
        supported_note.setWordWrap(True)
        layout.addWidget(supported_note)

        self.operation_table = QTableWidget(
            len(self.OPERATIONS), 3
        )
        self.operation_table.setHorizontalHeaderLabels(
            ["KEMAMPUAN", "STATUS", "KETERANGAN"]
        )
        self.operation_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.operation_table.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection
        )
        self.operation_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.operation_table.horizontalHeader().setStretchLastSection(True)
        for row, values in enumerate(self.OPERATIONS):
            for column, value in enumerate(values):
                self.operation_table.setItem(
                    row, column, QTableWidgetItem(value)
                )
        layout.addWidget(self.operation_table, 1)

        security_note = QLabel(
            "Operasi backup dan restore belum diaktifkan. Desktop tidak "
            "mengakses database, menjalankan ekspor sebagai pengganti "
            "backup, atau menyediakan kontrol hapus/restore yang belum "
            "didukung backend. Pemulihan Tenant dari recycle bin tidak "
            "memulihkan database."
        )
        security_note.setObjectName("subtleText")
        security_note.setWordWrap(True)
        layout.addWidget(security_note)


class DeveloperNotificationsPage(QWidget):
    CAPABILITIES = (
        (
            "Daftar notifikasi Developer",
            "BELUM TERSEDIA",
            "Universal API belum menyediakan model atau endpoint feed "
            "notifikasi Developer.",
        ),
        (
            "Aktivitas audit sistem",
            "TERSEDIA TERPISAH",
            "GET /auth/audit-logs tersedia di menu Audit Log; catatan audit "
            "bukan notifikasi.",
        ),
        (
            "Tenant dan waktu kejadian notifikasi",
            "BELUM TERSEDIA",
            "API tidak menyediakan objek notifikasi dengan metadata ini.",
        ),
        (
            "Kategori dan tingkat kepentingan",
            "BELUM TERSEDIA",
            "Kategori dan severity notifikasi belum dimodelkan.",
        ),
        (
            "Status sudah/belum dibaca",
            "BELUM TERSEDIA",
            "API tidak menyediakan status baca notifikasi.",
        ),
        (
            "Filter dan pencarian notifikasi",
            "BELUM TERSEDIA",
            "Tidak ada endpoint feed atau parameter filter notifikasi.",
        ),
        (
            "Event dan webhook",
            "BELUM TERSEDIA",
            "API tidak menyediakan endpoint event subscription, webhook, "
            "atau delivery history.",
        ),
        (
            "Muat ulang feed notifikasi",
            "BELUM TERSEDIA",
            "Tidak ada sumber notifikasi backend untuk dimuat ulang.",
        ),
    )

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(14)
        layout.addWidget(make_title("Manajemen Notifikasi Developer"))

        self.readiness_status = make_status_label(
            "NOTIFIKASI DEVELOPER: BELUM DIDUKUNG UNIVERSAL API"
        )
        self.readiness_status.setStyleSheet("color:#A32323;")
        layout.addWidget(self.readiness_status)

        note = QLabel(
            "Halaman ini menjelaskan kesiapan backend, bukan feed notifikasi. "
            "Tidak ada data contoh atau penyimpanan notifikasi lokal."
        )
        note.setObjectName("subtleText")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.capability_table = QTableWidget(
            len(self.CAPABILITIES), 3
        )
        self.capability_table.setHorizontalHeaderLabels(
            ["KEMAMPUAN", "STATUS", "KETERANGAN"]
        )
        self.capability_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.capability_table.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection
        )
        self.capability_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.capability_table.horizontalHeader().setStretchLastSection(True)
        for row, values in enumerate(self.CAPABILITIES):
            for column, value in enumerate(values):
                self.capability_table.setItem(
                    row, column, QTableWidgetItem(value)
                )
        layout.addWidget(self.capability_table, 1)

        separation_note = QLabel(
            "Audit Log tetap tersedia secara terpisah dan tidak menyediakan "
            "kategori, prioritas, status baca, atau pengiriman notifikasi. "
            "Halaman ini tidak mengubah atau menghapus catatan audit."
        )
        separation_note.setObjectName("subtleText")
        separation_note.setWordWrap(True)
        layout.addWidget(separation_note)


class MainWindow(QMainWindow):
    MENU = (
        ("Dashboard", "dashboard"),
        ("Tenant / Client", "tenants"),
        ("Lisensi", "licenses"),
        ("Instalasi", "installations"),
        ("Modul Sistem", "modules"),
        ("Konfigurasi", "configuration"),
        ("Pengguna Developer", "developers"),
        ("Audit Log", "audit"),
        ("Notifikasi Developer", "notifications"),
        ("Backup & Pemulihan", "backup_recovery"),
    )

    def __init__(self, api_client=None, user=None):
        super().__init__()
        self.api_client = api_client
        self.user = user or {}
        self.connection_worker = None
        self.setMinimumSize(900, 600)
        self.menu_buttons = {}
        self.page_by_key = {}

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 22, 16, 18)
        sidebar_layout.setSpacing(7)

        logo = QLabel("SIMPATI")
        logo.setObjectName("brandLogo")
        subtitle = QLabel("DEVELOPER CONSOLE")
        subtitle.setObjectName("brandSubtitle")
        sidebar_layout.addWidget(logo)
        sidebar_layout.addWidget(subtitle)
        sidebar_layout.addSpacing(20)

        self.pages = QStackedWidget()
        self.pages.setObjectName("pageStack")
        self.build_pages()

        for label, key in self.MENU:
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(self.navigation_handler(key))
            sidebar_layout.addWidget(button)
            self.menu_buttons[key] = button

        sidebar_layout.addStretch()
        sidebar_layout.addWidget(
            QLabel("SIMPATI UNIVERSAL\nDeveloper Desktop")
        )

        content = QWidget()
        content.setObjectName("content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        connection_bar = QHBoxLayout()
        connection_bar.setContentsMargins(20, 10, 20, 10)
        self.api_status = make_status_label(
            "API: BELUM DIPERIKSA" if api_client else "API: BELUM TERHUBUNG"
        )
        connection_bar.addWidget(self.api_status)
        connection_bar.addStretch()
        self.account_label = QLabel(
            self.user.get("full_name") or self.user.get("username", "")
        )
        self.account_label.setObjectName("subtleText")
        connection_bar.addWidget(self.account_label)
        self.logout_button = QPushButton("Keluar")
        self.logout_button.setObjectName("secondaryButton")
        self.logout_button.setVisible(api_client is not None)
        self.logout_button.clicked.connect(self.logout)
        connection_bar.addWidget(self.logout_button)
        content_layout.addLayout(connection_bar)
        content_layout.addWidget(self.pages, 1)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(content, 1)
        self.apply_local_configuration()
        self.navigate("dashboard")
        if self.api_client:
            self.dashboard_page = self.page_by_key["dashboard"]
            self.connection_timer = QTimer(self)
            self.connection_timer.timeout.connect(
                self.start_connection_check
            )
            self.connection_timer.start(30000)
            self.start_connection_check()

    def navigation_handler(self, page_key):
        def navigate_from_button():
            self.navigate(page_key)

        return navigate_from_button

    def build_pages(self):
        pages = {
            "dashboard": DashboardPage(self.api_client),
            "tenants": TenantPage(self.api_client),
            "licenses": LicensePage(self.api_client, self.user),
            "installations": InstallationPage(self.api_client),
            "modules": ModulePage(self.api_client),
            "developers": DeveloperPage(self.api_client),
            "audit": AuditLogPage(self.api_client),
            "notifications": DeveloperNotificationsPage(),
            "backup_recovery": BackupRecoveryPage(),
            "configuration": ConfigurationPage(),
        }
        for menu_item in self.MENU:
            key = menu_item[1]
            page = pages[key]
            self.page_by_key[key] = page
            self.pages.addWidget(page)
        self.dashboard_page = pages["dashboard"]
        self.dashboard_page.health_check_requested.connect(
            self.start_connection_check
        )

    def start_connection_check(self):
        if not self.api_client or not self.api_client.base_url:
            self._set_api_status(
                {
                    "api": {
                        "connected": False,
                        "message": "Alamat Universal API belum dikonfigurasi.",
                        "response_ms": None,
                        "checked_at": None,
                    },
                    "database": {
                        "status": "N/D",
                        "message": "Universal API belum dikonfigurasi.",
                        "response_ms": None,
                        "checked_at": None,
                    },
                }
            )
            return
        if self.connection_worker and self.connection_worker.isRunning():
            return
        self.dashboard_page.show_api_checking()
        self.api_status.setText("API: MEMERIKSA...")
        self.api_status.setToolTip("Endpoint GET /health/live sedang diperiksa.")
        self.connection_worker = DashboardMonitoringWorker(self.api_client)
        self.connection_worker.checked.connect(self._set_api_status)
        self.connection_worker.start()

    def _set_api_status(self, result):
        api = result["api"]
        database = result["database"]
        connected = api["connected"]
        message = api["message"]
        state = "TERHUBUNG" if connected else "TERPUTUS"
        self.api_status.setText(f"API: {state}")
        self.api_status.setToolTip(message)
        color = MUTED_GOLD if connected else "#A32323"
        self.api_status.setStyleSheet(f"color:{color};")
        self.dashboard_page.show_api_health(
            connected=connected,
            message=message,
            response_ms=api["response_ms"],
            checked_at=api["checked_at"],
            database_status=database["status"],
            database_message=database["message"],
            database_response_ms=database["response_ms"],
            database_checked_at=database["checked_at"],
        )

    def logout(self):
        if not self.api_client:
            return
        try:
            self.api_client.logout()
        except ApiError as exc:
            error = (
                "Sesi lokal sudah dihapus, tetapi server tidak dapat "
                f"dikonfirmasi logout: {exc}"
            )
            QMessageBox.warning(self, "Logout", error)
        user = authenticate_user(self.api_client, parent=self)
        if user is not None:
            self.user = user
            self.account_label.setText(
                self.user.get("full_name")
                or self.user.get("username", "")
            )
            license_page = self.page_by_key.get("licenses")
            if license_page is not None:
                license_page.set_user_permissions(self.user)
            self.navigate("dashboard")
            self.start_connection_check()
            return
        self.close()

    def closeEvent(self, event):
        configuration_page = self.page_by_key.get("configuration")
        if configuration_page is not None:
            configuration_page.wait_for_connection_test()
        tenant_page = self.page_by_key.get("tenants")
        if tenant_page is not None:
            tenant_page.wait_for_load()
        installation_page = self.page_by_key.get("installations")
        if installation_page is not None:
            installation_page.wait_for_load()
        module_page = self.page_by_key.get("modules")
        if module_page is not None:
            module_page.wait_for_load()
        audit_page = self.page_by_key.get("audit")
        if audit_page is not None:
            audit_page.wait_for_load()
        developer_page = self.page_by_key.get("developers")
        if developer_page is not None:
            developer_page.wait_for_load()
        license_page = self.page_by_key.get("licenses")
        if license_page is not None:
            license_page.wait_for_load()
        if self.dashboard_page is not None:
            self.dashboard_page.wait_for_load()
        if (
            self.connection_worker
            and self.connection_worker.isRunning()
        ):
            self.connection_worker.wait()
        super().closeEvent(event)

    def apply_local_configuration(self):
        settings = settings_store()
        app_name = settings.value("branding/app_name", APP_NAME)
        self.setWindowTitle(app_name)
        size_key = settings.value(
            "operational/window_size", "1280x780"
        )
        self.resize(*WINDOW_SIZES.get(size_key, WINDOW_SIZES["1280x780"]))
        self.setStyleSheet(
            self.stylesheet(settings.value("appearance/theme", "light"))
        )
        app = QApplication.instance()
        if app is not None:
            app.setApplicationName(app_name)

    def navigate(self, page_key):
        page = self.page_by_key.get(page_key)
        if page is None:
            return
        self.pages.setCurrentWidget(page)
        if page_key == "tenants" and self.api_client:
            page.load_tenants()
        if page_key == "licenses" and self.api_client:
            page.load_tenants()
        if page_key == "installations" and self.api_client:
            page.load_installations()
        if page_key == "modules" and self.api_client:
            page.load_modules()
        if page_key == "dashboard" and self.api_client:
            page.load_dashboard()
            if getattr(self, "connection_timer", None) is not None:
                self.start_connection_check()
        if page_key == "audit" and self.api_client:
            page.load_page(0)
        if page_key == "developers" and self.api_client:
            page.load_page(0)
        for key, button in self.menu_buttons.items():
            button.setProperty("active", key == page_key)
            button.style().unpolish(button)
            button.style().polish(button)

    @staticmethod
    def stylesheet(theme="light"):
        if theme == "dark":
            background = "#1E1E1E"
            surface = "#292929"
            text = "#E8E6E3"
            muted_text = "#B8B3AD"
            border = "#49443E"
            alternate = "#323232"
            header = "#38332D"
            selected = "#56431D"
            secondary = "#3B3230"
            heading_color = GOLD
            accent_text = "#E8C968"
        else:
            background = BACKGROUND
            surface = "white"
            text = "#333333"
            muted_text = "#666666"
            border = "#E5DED5"
            alternate = "#F8F6F2"
            header = "#EEE9E1"
            selected = "#E9DFD0"
            secondary = "#E8E1D8"
            heading_color = MAROON
            accent_text = MUTED_GOLD
        return f"""
            QMainWindow, QWidget#content {{
                background-color: {background};
            }}
            QWidget#sidebar {{
                background-color: {DARK};
            }}
            QLabel#brandLogo {{
                color: {GOLD};
                font-size: 27px;
                font-weight: bold;
            }}
            QLabel#brandSubtitle {{
                color: white;
                font-size: 10px;
                letter-spacing: 2px;
            }}
            QLabel#pageTitle {{
                color: {heading_color};
                font-size: 26px;
                font-weight: bold;
            }}
            QLabel#configSectionTitle {{
                color: {MAROON};
                font-size: 15px;
                font-weight: bold;
            }}
            QLabel#roleTag, QLabel#connectionStatus {{
                color: {accent_text};
                font-size: 11px;
                font-weight: bold;
                padding: 3px;
            }}
            QLabel#subtleText {{
                color: {muted_text};
                font-size: 12px;
            }}
            QLabel#emptyState {{
                color: {muted_text};
                background: {surface};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 14px;
            }}
            QLabel#statLabel {{
                color: {muted_text};
                font-size: 10px;
                font-weight: bold;
            }}
            QLabel#statValue {{
                color: {heading_color};
                font-size: 28px;
                font-weight: bold;
            }}
            QFrame#statCard, QFrame#panel {{
                background: {surface};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            QFrame#panel QLabel {{
                color: {text};
                font-weight: bold;
            }}
            QLineEdit, QComboBox {{
                background: {surface};
                color: {text};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 9px;
                min-height: 20px;
            }}
            QLineEdit:focus, QComboBox:focus {{
                border: 1px solid {GOLD};
            }}
            QPushButton {{
                color: white;
                background: {MAROON};
                border: none;
                border-radius: 6px;
                padding: 10px 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: #5B1724;
            }}
            QPushButton:disabled {{
                background: #D7D0C0;
                color: #888888;
            }}
            QPushButton#secondaryButton {{
                color: {text if theme == "dark" else MAROON};
                background: {secondary};
            }}
            QPushButton#navButton {{
                color: white;
                background: transparent;
                text-align: left;
                padding: 12px;
            }}
            QPushButton#navButton:hover, QPushButton#navButton[active="true"] {{
                color: {GOLD};
                background: {MAROON};
            }}
            QTableWidget {{
                background: {surface};
                alternate-background-color: {alternate};
                color: {text};
                border: 1px solid {border};
                border-radius: 7px;
                selection-background-color: {selected};
                selection-color: {text if theme == "dark" else MAROON};
            }}
            QHeaderView::section {{
                color: {text if theme == "dark" else MAROON};
                background: {header};
                border: none;
                padding: 9px 5px;
                font-weight: bold;
                font-size: 10px;
            }}
            QDialog {{
                background: {background};
            }}
        """


if __name__ == "__main__":
    apply_saved_branding()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("SIMPATI")
    api_client = ApiClient()
    user = None
    initial_error = None
    try:
        api_client.set_base_url(settings_store().value("api/base_url", ""))
        user = api_client.current_user()
    except ApiError as exc:
        initial_error = str(exc)
    if user is None or user.get("must_change_password") is True:
        user = authenticate_user(
            api_client,
            initial_error=initial_error,
            initial_user=user,
        )
        if user is None:
            sys.exit(0)
    window = MainWindow(api_client, user)
    window.show()
    sys.exit(app.exec())
