import re
import sys

from api_client import ApiClient, ApiError
from PySide6.QtCore import Qt, QSettings, QThread, QTimer, Signal
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
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QVBoxLayout,
    QWidget,
)


MAROON = "#420D18"
DARK = "#2B0910"
GOLD = "#D4AF37"
BACKGROUND = "#F4F1EC"
MUTED_GOLD = "#A16C19"


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
        errors = {}
        tenants = None

        try:
            tenants = self.api_client.list_tenants()
            counts["tenants"] = len(tenants)
        except ApiError as exc:
            errors["tenants"] = str(exc)

        if tenants is None:
            errors["installations"] = (
                "Jumlah instalasi tidak dapat dihitung karena daftar Tenant "
                "gagal dimuat."
            )
        else:
            try:
                counts["installations"] = sum(
                    self.api_client.count_tenant_installations(
                        tenant["id"]
                    )
                    for tenant in tenants
                )
            except ApiError as exc:
                errors["installations"] = str(exc)

        try:
            counts["modules"] = len(self.api_client.list_modules())
        except ApiError as exc:
            errors["modules"] = str(exc)

        try:
            activities = self.api_client.list_recent_audit_logs()
        except ApiError as exc:
            activities = []
            errors["activity"] = str(exc)

        self.loaded.emit(
            {"counts": counts, "errors": errors, "activities": activities}
        )


class DashboardPage(QWidget):
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
        self.refresh_button = QPushButton("Muat Ulang")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.clicked.connect(self.load_dashboard)
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
                ("tenants", "TOTAL TENANT", "Tenant terdaftar"),
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
                ("installations", "INSTALASI", "Perangkat terdaftar"),
                ("modules", "MODUL SISTEM", "Katalog modul"),
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
        connection_layout.addWidget(QLabel("STATUS KONEKSI"))
        self.api_status = make_status_label("API: BELUM DIPERIKSA")
        connection_layout.addWidget(self.api_status)
        connection_layout.addWidget(
            make_status_label("DATABASE: DIKELOLA MELALUI UNIVERSAL API")
        )
        connection_note = QLabel(
            "Aplikasi tidak terhubung langsung ke database. "
            "Operasi data dan License Manager tetap menjadi tanggung jawab "
            "backend Universal API."
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

    def load_dashboard(self):
        if self.api_client is None:
            self.data_status.setText(
                "DATA DASHBOARD: UNIVERSAL API BELUM TERHUBUNG"
            )
            self.data_status.setStyleSheet("color:#A32323;")
            return
        if self.load_worker and self.load_worker.isRunning():
            return

        self.refresh_button.setEnabled(False)
        self.data_status.setText("DATA DASHBOARD: MEMUAT DARI API...")
        self.data_status.setStyleSheet("")
        self.load_worker = DashboardLoadWorker(self.api_client)
        self.load_worker.loaded.connect(self.show_dashboard_data)
        self.load_worker.start()

    def show_dashboard_data(self, snapshot):
        counts = snapshot["counts"]
        errors = snapshot["errors"]
        metric_keys = {
            "TOTAL TENANT": "tenants",
            "INSTALASI": "installations",
            "MODUL SISTEM": "modules",
        }
        for title, metric_key in metric_keys.items():
            value = counts[metric_key]
            error = errors.get(metric_key)
            self.stat_values[title].setText(
                "Gagal" if error else str(value)
            )
            self.stat_values[title].setToolTip(error or "Data dari Universal API.")

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


class LicensePage(QWidget):
    def __init__(self, api_client=None):
        super().__init__()
        self.api_client = api_client
        self.worker = None
        self.request_pending = False
        self.loaded_tenant_id = None
        self.pending_tenant_id = None
        self.modules_by_code = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(14)
        layout.addWidget(make_title("Manajemen Lisensi"))

        self.license_note = QLabel(
            "Universal API saat ini belum menyediakan model atau endpoint "
            "lisensi. Daftar dan pembuatan lisensi, masa berlaku, paket, "
            "batas penggunaan, serta status lisensi belum dapat dikelola "
            "melalui Desktop."
        )
        self.license_note.setObjectName("subtleText")
        self.license_note.setWordWrap(True)
        layout.addWidget(self.license_note)

        module_title = QLabel("OTORISASI MODUL TENANT")
        module_title.setObjectName("statLabel")
        layout.addWidget(module_title)
        module_note = QLabel(
            "Bagian ini mengelola assignment modul yang tersedia di API; "
            "assignment bukan lisensi dan tidak memberikan hak validasi "
            "lisensi."
        )
        module_note.setObjectName("subtleText")
        module_note.setWordWrap(True)
        layout.addWidget(module_note)

        toolbar = QHBoxLayout()
        self.tenant_id_input = QLineEdit()
        self.tenant_id_input.setPlaceholderText("ID Tenant")
        self.tenant_id_input.setMaximumWidth(180)
        self.tenant_id_input.textChanged.connect(
            self.update_action_buttons
        )
        toolbar.addWidget(QLabel("Tenant ID"))
        toolbar.addWidget(self.tenant_id_input)
        self.load_button = QPushButton("Muat Modul")
        self.load_button.clicked.connect(self.load_modules)
        toolbar.addWidget(self.load_button)
        self.enable_button = QPushButton("Aktifkan Assignment")
        self.enable_button.setEnabled(False)
        self.enable_button.clicked.connect(
            lambda: self.change_selected_module("enable")
        )
        toolbar.addWidget(self.enable_button)
        self.disable_button = QPushButton("Nonaktifkan Assignment")
        self.disable_button.setObjectName("secondaryButton")
        self.disable_button.setEnabled(False)
        self.disable_button.clicked.connect(
            lambda: self.change_selected_module("disable")
        )
        toolbar.addWidget(self.disable_button)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            ["KODE MODUL", "NAMA MODUL", "STATUS ASSIGNMENT"]
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
        self.table.itemSelectionChanged.connect(
            self.update_action_buttons
        )
        layout.addWidget(self.table, 1)

        self.empty_label = QLabel(
            "Masukkan ID Tenant lalu muat daftar assignment modul dari API."
        )
        self.empty_label.setObjectName("emptyState")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.empty_label)
        self.data_status = make_status_label(
            "STATUS MODUL: BELUM DIMUAT"
        )
        self.data_status.setWordWrap(True)
        layout.addWidget(self.data_status)

    def load_modules(self):
        tenant_id = self._tenant_id()
        if tenant_id is None:
            self._show_error("Masukkan ID Tenant berupa bilangan positif.")
            return
        if self.api_client is None:
            self._show_error("Client Universal API tidak tersedia.")
            return
        self._start_request(tenant_id)

    def change_selected_module(self, action):
        row = self.table.currentRow()
        if row < 0:
            self._show_error("Pilih satu modul terlebih dahulu.")
            return
        item = self.table.item(row, 0)
        module_code = (
            item.data(Qt.ItemDataRole.UserRole) if item else None
        )
        tenant_id = self._tenant_id()
        if (
            tenant_id is None
            or tenant_id != self.loaded_tenant_id
            or not isinstance(module_code, str)
        ):
            self._show_error(
                "Muat daftar modul untuk Tenant yang dipilih terlebih dahulu."
            )
            return
        if self.api_client is None:
            self._show_error("Client Universal API tidak tersedia.")
            return
        self._start_request(tenant_id, action, module_code)

    def _tenant_id(self):
        value = self.tenant_id_input.text().strip()
        if not value.isdecimal():
            return None
        tenant_id = int(value)
        return tenant_id if tenant_id > 0 else None

    def _start_request(self, tenant_id, action=None, module_code=None):
        if self.request_pending:
            return
        self.request_pending = True
        self.loaded_tenant_id = None
        self.pending_tenant_id = tenant_id
        self.modules_by_code = {}
        self.table.setRowCount(0)
        self.empty_label.setText("Memuat assignment modul dari API...")
        self.empty_label.setVisible(True)
        self.data_status.setText("STATUS MODUL: MEMUAT...")
        self.data_status.setStyleSheet("")
        self.load_button.setEnabled(False)
        self.update_action_buttons()
        self.worker = TenantModuleWorker(
            self.api_client, tenant_id, action, module_code
        )
        self.worker.loaded.connect(self._show_modules)
        self.worker.failed.connect(self._show_error)
        self.worker.finished.connect(self._request_finished)
        self.worker.start()

    def _show_modules(self, modules, message):
        if modules is None:
            self._show_error(message)
            return
        self.table.setRowCount(len(modules))
        self.modules_by_code = {
            module["code"]: module for module in modules
        }
        for row, module in enumerate(modules):
            code_item = QTableWidgetItem(module["code"])
            code_item.setData(
                Qt.ItemDataRole.UserRole, module["code"]
            )
            self.table.setItem(row, 0, code_item)
            self.table.setItem(
                row, 1, QTableWidgetItem(module["name"])
            )
            self.table.setItem(
                row, 2, QTableWidgetItem(module["status"])
            )

        self.loaded_tenant_id = self.pending_tenant_id
        self.empty_label.setText(
            "Tidak ada data modul dari Universal API."
        )
        self.empty_label.setVisible(not modules)
        self.data_status.setText(
            message or f"DATA MODUL: {len(modules)} DIMUAT DARI API"
        )
        self.data_status.setToolTip(
            "Assignment modul bukan lisensi dan tidak menggantikan "
            "License Manager."
        )
        self.data_status.setStyleSheet(f"color:{MUTED_GOLD};")
        self.update_action_buttons()

    def _show_error(self, message):
        self.data_status.setText("DATA MODUL: GAGAL")
        self.data_status.setToolTip(message)
        self.data_status.setStyleSheet("color:#A32323;")
        self.empty_label.setText(message)
        self.empty_label.setVisible(True)
        self.update_action_buttons()

    def update_action_buttons(self, *_):
        row = self.table.currentRow()
        selected = self.table.item(row, 0) if row >= 0 else None
        module_code = (
            selected.data(Qt.ItemDataRole.UserRole)
            if selected
            else None
        )
        module = self.modules_by_code.get(module_code)
        can_change = (
            not self.request_pending
            and self._tenant_id() == self.loaded_tenant_id
            and module is not None
        )
        self.load_button.setEnabled(not self.request_pending)
        self.enable_button.setEnabled(
            can_change
            and module["is_active"]
            and module["status"] in ("DISABLED", "UNASSIGNED")
        )
        self.disable_button.setEnabled(
            can_change
            and module["status"] == "ENABLED"
            and module["code"] != "CORE"
        )

    def _request_finished(self):
        self.request_pending = False
        self.update_action_buttons()

    def wait_for_load(self):
        if self.worker and self.worker.isRunning():
            self.worker.wait()


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

        panel = QFrame()
        panel.setObjectName("panel")
        form = QFormLayout(panel)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(14)

        settings = settings_store()
        self.app_name = QLineEdit(
            settings.value("branding/app_name", "SIMPATI Developer Desktop")
        )
        self.api_url = QLineEdit(settings.value("api/base_url", ""))
        self.api_url.setPlaceholderText("https://api.example.com")
        self.primary_color = QLineEdit(
            settings.value("branding/primary_color", MAROON)
        )
        self.accent_color = QLineEdit(
            settings.value("branding/accent_color", GOLD)
        )
        self.primary_color.setMaxLength(7)
        self.accent_color.setMaxLength(7)
        form.addRow("Nama aplikasi", self.app_name)
        form.addRow("URL dasar API", self.api_url)
        form.addRow("Warna maroon (#RRGGBB)", self.primary_color)
        form.addRow("Warna gold (#RRGGBB)", self.accent_color)
        layout.addWidget(panel)

        notice = QLabel(
            "URL hanya disimpan sebagai konfigurasi lokal. Menyimpan URL "
            "tidak menyimpan secret atau kredensial. URL baru digunakan "
            "saat login berikutnya; koneksi diperiksa melalui Universal API."
        )
        notice.setObjectName("subtleText")
        notice.setWordWrap(True)
        layout.addWidget(notice)

        self.result = QLabel()
        self.result.setWordWrap(True)
        layout.addWidget(self.result)
        save_button = QPushButton("Simpan pengaturan lokal")
        save_button.clicked.connect(self.save_settings)
        layout.addWidget(save_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()

    def save_settings(self):
        if not self.app_name.text().strip():
            self.result.setText("Nama aplikasi wajib diisi.")
            self.result.setStyleSheet("color:#A32323;")
            return False

        api_url = self.api_url.text().strip()
        if api_url:
            try:
                api_url = ApiClient.validate_base_url(api_url)
            except ApiError:
                self.result.setText(
                    "URL API harus berupa URL lengkap dengan skema "
                    "http:// atau https://."
                )
                self.result.setStyleSheet("color:#A32323;")
                return False

        primary_text = self.primary_color.text().strip()
        accent_text = self.accent_color.text().strip()
        color_pattern = r"#[0-9A-Fa-f]{6}"
        if not re.fullmatch(color_pattern, primary_text) or not re.fullmatch(
            color_pattern, accent_text
        ):
            self.result.setText(
                "Format warna tidak valid. Gunakan format warna, misalnya "
                "#420D18."
            )
            self.result.setStyleSheet("color:#A32323;")
            return False
        primary = QColor(primary_text)
        accent = QColor(accent_text)

        settings = settings_store()
        settings.setValue("branding/app_name", self.app_name.text().strip())
        settings.setValue("api/base_url", api_url)
        settings.setValue("branding/primary_color", primary.name())
        settings.setValue("branding/accent_color", accent.name())
        settings.sync()
        if settings.status() != QSettings.Status.NoError:
            self.result.setText("Pengaturan gagal disimpan ke penyimpanan lokal.")
            self.result.setStyleSheet("color:#A32323;")
            return False

        self.result.setText(
            "Pengaturan lokal berhasil disimpan. Perubahan branding "
            "diterapkan setelah aplikasi dijalankan ulang; URL API "
            "digunakan pada login berikutnya."
        )
        self.result.setStyleSheet(f"color:{MUTED_GOLD};")
        return True


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
    )

    def __init__(self, api_client=None, user=None):
        super().__init__()
        self.api_client = api_client
        self.user = user or {}
        self.connection_worker = None
        self.setWindowTitle(
            settings_store().value(
                "branding/app_name", "SIMPATI Developer Desktop"
            )
        )
        self.setMinimumSize(900, 600)
        self.resize(1280, 780)
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
        self.setStyleSheet(self.stylesheet())
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
            "licenses": LicensePage(self.api_client),
            "installations": InstallationPage(self.api_client),
            "modules": ModulePage(self.api_client),
            "developers": DataPage(
                "Pengguna Developer",
                "Akun, peran, status, dan akses developer.",
                [
                    "NO.",
                    "USER ID",
                    "USERNAME",
                    "NAMA",
                    "PERAN",
                    "STATUS",
                    "TERAKHIR LOGIN",
                ],
                [
                    ("USER ID", True),
                    ("USERNAME", True),
                    ("NAMA", True),
                    ("PERAN", True),
                    ("STATUS", True),
                ],
                filter_column=5,
                filter_values=("ACTIVE", "INACTIVE", "LOCKED"),
                add_label="Tambah Pengguna",
            ),
            "audit": DataPage(
                "Audit Log",
                "Riwayat aktivitas dan perubahan yang tercatat di sistem.",
                [
                    "NO.",
                    "WAKTU",
                    "PENGGUNA",
                    "TINDAKAN",
                    "OBJEK",
                    "RINGKASAN",
                ],
                filter_column=3,
                filter_values=(),
            ),
            "configuration": ConfigurationPage(),
        }
        for menu_item in self.MENU:
            key = menu_item[1]
            page = pages[key]
            self.page_by_key[key] = page
            self.pages.addWidget(page)
        self.dashboard_page = pages["dashboard"]

    def start_connection_check(self):
        if not self.api_client or not self.api_client.base_url:
            self._set_api_status(False, "API: BELUM DIKONFIGURASI")
            return
        if self.connection_worker and self.connection_worker.isRunning():
            return
        self.connection_worker = ConnectionCheckWorker(self.api_client)
        self.connection_worker.checked.connect(self._set_api_status)
        self.connection_worker.start()

    def _set_api_status(self, connected, message):
        state = "TERHUBUNG" if connected else "TERPUTUS"
        self.api_status.setText(f"API: {state}")
        self.api_status.setToolTip(message)
        self.dashboard_page.api_status.setText(f"API: {state}")
        self.dashboard_page.api_status.setToolTip(message)
        color = MUTED_GOLD if connected else "#A32323"
        self.api_status.setStyleSheet(f"color:{color};")
        self.dashboard_page.api_status.setStyleSheet(f"color:{color};")

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
            self.navigate("dashboard")
            self._set_api_status(True, "API: TERHUBUNG")
            return
        self.close()

    def closeEvent(self, event):
        tenant_page = self.page_by_key.get("tenants")
        if tenant_page is not None:
            tenant_page.wait_for_load()
        installation_page = self.page_by_key.get("installations")
        if installation_page is not None:
            installation_page.wait_for_load()
        module_page = self.page_by_key.get("modules")
        if module_page is not None:
            module_page.wait_for_load()
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

    def navigate(self, page_key):
        page = self.page_by_key.get(page_key)
        if page is None:
            return
        self.pages.setCurrentWidget(page)
        if page_key == "tenants" and self.api_client:
            page.load_tenants()
        if page_key == "installations" and self.api_client:
            page.load_installations()
        if page_key == "modules" and self.api_client:
            page.load_modules()
        if page_key == "dashboard" and self.api_client:
            page.load_dashboard()
        for key, button in self.menu_buttons.items():
            button.setProperty("active", key == page_key)
            button.style().unpolish(button)
            button.style().polish(button)

    @staticmethod
    def stylesheet():
        return f"""
            QMainWindow, QWidget#content {{
                background-color: {BACKGROUND};
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
                color: {MAROON};
                font-size: 26px;
                font-weight: bold;
            }}
            QLabel#roleTag, QLabel#connectionStatus {{
                color: {MUTED_GOLD};
                font-size: 11px;
                font-weight: bold;
                padding: 3px;
            }}
            QLabel#subtleText {{
                color: #666666;
                font-size: 12px;
            }}
            QLabel#emptyState {{
                color: #777777;
                background: white;
                border: 1px solid #E5DED5;
                border-radius: 8px;
                padding: 14px;
            }}
            QLabel#statLabel {{
                color: #777777;
                font-size: 10px;
                font-weight: bold;
            }}
            QLabel#statValue {{
                color: {MAROON};
                font-size: 28px;
                font-weight: bold;
            }}
            QFrame#statCard, QFrame#panel {{
                background: white;
                border: 1px solid #E5DED5;
                border-radius: 8px;
            }}
            QFrame#panel QLabel {{
                color: {MAROON};
                font-weight: bold;
            }}
            QLineEdit, QComboBox {{
                background: white;
                color: #333333;
                border: 1px solid #D6CEC3;
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
                color: {MAROON};
                background: #E8E1D8;
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
                background: white;
                alternate-background-color: #F8F6F2;
                color: #333333;
                border: 1px solid #E5DED5;
                border-radius: 7px;
                selection-background-color: #E9DFD0;
                selection-color: {MAROON};
            }}
            QHeaderView::section {{
                color: {MAROON};
                background: #EEE9E1;
                border: none;
                padding: 9px 5px;
                font-weight: bold;
                font-size: 10px;
            }}
            QDialog {{
                background: {BACKGROUND};
            }}
        """


if __name__ == "__main__":
    apply_saved_branding()
    app = QApplication(sys.argv)
    app.setApplicationName("SIMPATI Developer Desktop")
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
