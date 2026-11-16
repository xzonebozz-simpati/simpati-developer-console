import re
import sys

from api_client import ApiClient, ApiError
from PySide6.QtCore import Qt, QSettings, QThread, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
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


class DashboardPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(18)

        heading = QHBoxLayout()
        heading.addWidget(make_title("Dashboard"))
        heading.addStretch()
        developer_tag = QLabel("DEVELOPER")
        developer_tag.setObjectName("roleTag")
        heading.addWidget(developer_tag)
        layout.addLayout(heading)

        intro = QLabel(
            "Pusat pemantauan SIMPATI Universal. Data ringkasan akan tersedia "
            "setelah endpoint Dashboard dihubungkan."
        )
        intro.setObjectName("subtleText")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        stats = QGridLayout()
        stats.setSpacing(12)
        for index, (title, detail) in enumerate(
            (
                ("TOTAL TENANT", "Tenant terdaftar"),
                ("LISENSI AKTIF", "Status active"),
                ("RESTRICTED", "Lisensi dibatasi"),
                ("EXPIRED", "Lisensi berakhir"),
                ("INSTALASI", "Perangkat terdaftar"),
                ("MODUL SISTEM", "Data modul tersedia"),
            )
        ):
            card = QFrame()
            card.setObjectName("statCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            name = QLabel(title)
            name.setObjectName("statLabel")
            value = QLabel("—")
            value.setObjectName("statValue")
            value.setToolTip("Belum ada data dari API.")
            caption = QLabel(detail)
            caption.setObjectName("subtleText")
            card_layout.addWidget(name)
            card_layout.addWidget(value)
            card_layout.addWidget(caption)
            stats.addWidget(card, index // 3, index % 3)
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
        activity = QLabel(
            "Belum ada aktivitas. Log akan ditampilkan setelah endpoint "
            "audit dihubungkan."
        )
        activity.setObjectName("subtleText")
        activity.setWordWrap(True)
        activity_layout.addWidget(activity)
        layout.addWidget(activity_card)
        layout.addStretch()


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
            "dashboard": DashboardPage(),
            "tenants": TenantPage(self.api_client),
            "licenses": DataPage(
                "Manajemen Lisensi",
                "Paket, periode aktivasi, dan status lisensi tenant.",
                [
                    "NO.",
                    "LICENSE ID",
                    "TENANT",
                    "PAKET",
                    "STATUS",
                    "TANGGAL AKTIVASI",
                    "TANGGAL BERAKHIR",
                ],
                [
                    ("LICENSE ID", True),
                    ("TENANT ID", True),
                    ("PAKET", True),
                    ("STATUS", True),
                    ("TANGGAL AKTIVASI", False),
                    ("TANGGAL BERAKHIR", False),
                ],
                filter_column=4,
                filter_values=("ACTIVE", "RESTRICTED", "EXPIRED"),
                add_label="Buat Lisensi",
            ),
            "installations": DataPage(
                "Manajemen Instalasi",
                "Installation ID, perangkat, OS, dan waktu aktif terakhir.",
                [
                    "NO.",
                    "INSTALLATION ID",
                    "TENANT",
                    "NAMA PERANGKAT",
                    "SISTEM OPERASI",
                    "STATUS",
                    "TERAKHIR AKTIF",
                ],
                [
                    ("INSTALLATION ID", True),
                    ("TENANT ID", True),
                    ("NAMA PERANGKAT", True),
                    ("SISTEM OPERASI", False),
                    ("STATUS", True),
                ],
                filter_column=5,
                filter_values=("ACTIVE", "INACTIVE", "REVOKED"),
                add_label="Tambah Instalasi",
            ),
            "modules": DataPage(
                "Modul Sistem",
                "Daftar modul tersedia dan modul yang memerlukan lisensi.",
                [
                    "NO.",
                    "KODE MODUL",
                    "NAMA MODUL",
                    "DESKRIPSI",
                    "KATEGORI",
                    "STATUS",
                ],
                [
                    ("KODE MODUL", True),
                    ("NAMA MODUL", True),
                    ("DESKRIPSI", False),
                    ("KATEGORI LISENSI", False),
                    ("STATUS", True),
                ],
                filter_column=5,
                filter_values=("AVAILABLE", "LICENSED", "INACTIVE"),
                add_label="Kelola Modul",
            ),
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
