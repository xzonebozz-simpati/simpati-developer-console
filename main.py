import re
import sys
from urllib.parse import urlsplit

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
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
    def __init__(self, title, fields, initial_values=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self.fields = fields
        self.inputs = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(12)
        initial_values = initial_values or {}

        for field_name, required in fields:
            field = QLineEdit()
            field.setText(initial_values.get(field_name, ""))
            field.setPlaceholderText("Wajib diisi" if required else "Opsional")
            self.inputs[field_name] = field
            form.addRow(field_name, field)

        layout.addLayout(form)
        self.validation_message = QLabel(
            "Validasi formulir tidak akan mengirim atau menyimpan data."
        )
        self.validation_message.setWordWrap(True)
        self.validation_message.setObjectName("subtleText")
        layout.addWidget(self.validation_message)

        buttons = QHBoxLayout()
        validate_button = QPushButton("Validasi")
        validate_button.clicked.connect(self.validate_form)
        close_button = QPushButton("Tutup")
        close_button.setObjectName("secondaryButton")
        close_button.clicked.connect(self.close)
        buttons.addStretch()
        buttons.addWidget(validate_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def validate_form(self):
        missing = [
            field_name
            for field_name, required in self.fields
            if required and not self.inputs[field_name].text().strip()
        ]
        if missing:
            self.validation_message.setText(
                "Lengkapi kolom wajib: " + ", ".join(missing) + "."
            )
            self.validation_message.setStyleSheet("color:#A32323;")
            return False

        self.validation_message.setText(
            "Input valid. Data belum disimpan karena API belum terhubung."
        )
        self.validation_message.setStyleSheet(f"color:{MUTED_GOLD};")
        return True


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
            "Pusat pemantauan SIMPATI Universal. Data akan tersedia "
            "setelah API resmi terintegrasi."
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
        connection_layout.addWidget(
            make_status_label("API: BELUM TERHUBUNG")
        )
        connection_layout.addWidget(
            make_status_label("DATABASE: BELUM TERHUBUNG MELALUI API")
        )
        connection_note = QLabel(
            "Aplikasi tidak terhubung langsung ke database. "
            "Belum ada endpoint SIMPATI Universal API yang tersedia "
            "di dokumentasi proyek ini."
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
            "Belum ada aktivitas. Log akan ditampilkan setelah "
            "integrasi API tersedia."
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

        layout.addWidget(
            make_status_label("STATUS DATA: BELUM TERHUBUNG KE API")
        )

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
                "Data produksi tidak dibuat sebagai contoh; "
                "hubungkan aplikasi ke API resmi untuk memuat data."
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
            "tidak menguji atau mengaktifkan koneksi; integrasi menunggu "
            "dokumentasi API resmi."
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
            parsed_url = urlsplit(api_url)
            if (
                parsed_url.scheme not in ("http", "https")
                or not parsed_url.netloc
                or not parsed_url.hostname
            ):
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
            "diterapkan setelah aplikasi dijalankan ulang; API tetap "
            "BELUM TERHUBUNG."
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

    def __init__(self):
        super().__init__()
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
        connection_bar.addStretch()
        connection_bar.addWidget(make_status_label("API: BELUM TERHUBUNG"))
        connection_bar.addWidget(
            make_status_label("DATABASE: BELUM TERHUBUNG")
        )
        content_layout.addLayout(connection_bar)
        content_layout.addWidget(self.pages, 1)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(content, 1)
        self.setStyleSheet(self.stylesheet())
        self.navigate("dashboard")

    def navigation_handler(self, page_key):
        def navigate_from_button():
            self.navigate(page_key)

        return navigate_from_button

    def build_pages(self):
        pages = {
            "dashboard": DashboardPage(),
            "tenants": DataPage(
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
                    ("STATUS", True),
                ],
                filter_column=4,
                filter_values=("ACTIVE", "INACTIVE", "SUSPENDED"),
                add_label="Tambah Tenant",
            ),
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

    def navigate(self, page_key):
        page = self.page_by_key.get(page_key)
        if page is None:
            return
        self.pages.setCurrentWidget(page)
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
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
