import os
import threading
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QMessageBox,
    QTableWidgetItem,
)

from main import (
    ConfigurationPage,
    DashboardLoadWorker,
    DashboardPage,
    DataPage,
    FormDialog,
    InstallationPage,
    LicensePage,
    MainWindow,
    ModulePage,
    PasswordChangeDialog,
    TenantPage,
    TenantSaveWorker,
    authenticate_user,
)
from api_client import ApiError


class DesktopApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_builds_and_all_sidebar_pages_navigate(self):
        window = MainWindow()
        self.addCleanup(window.close)

        self.assertEqual(window.pages.count(), len(MainWindow.MENU))
        for menu_item in MainWindow.MENU:
            page_key = menu_item[1]
            window.menu_buttons[page_key].click()
            self.assertIs(
                window.pages.currentWidget(), window.page_by_key[page_key]
            )
        self.assertEqual(len(window.menu_buttons), len(MainWindow.MENU))

    def test_dashboard_displays_live_api_counts_and_latest_activity(self):
        class FakeApiClient:
            def list_tenants(self):
                return [{"id": 31}, {"id": 32}]

            def count_tenant_installations(self, tenant_id):
                return {31: 4, 32: 7}[tenant_id]

            def list_modules(self):
                return [{"id": 1}, {"id": 2}, {"id": 3}]

            def list_recent_audit_logs(self):
                return [
                    {
                        "created_at": "2026-11-17T00:00:00+00:00",
                        "action": "TENANT_CREATED",
                        "entity": "Tenant",
                        "actor_type": "DEVELOPER",
                        "actor_id": 1,
                    }
                ]

        results = []
        worker = DashboardLoadWorker(FakeApiClient())
        worker.loaded.connect(results.append)
        worker.run()

        page = DashboardPage()
        self.addCleanup(page.close)
        page.show_dashboard_data(results[0])

        self.assertEqual(page.stat_values["TOTAL TENANT"].text(), "2")
        self.assertEqual(page.stat_values["INSTALASI"].text(), "11")
        self.assertEqual(page.stat_values["MODUL SISTEM"].text(), "3")
        self.assertEqual(page.stat_values["LISENSI AKTIF"].text(), "N/D")
        self.assertIn("TENANT_CREATED", page.activity_label.text())
        self.assertEqual(
            page.data_status.text(),
            "DATA DASHBOARD: DIPERBARUI DARI UNIVERSAL API",
        )

    def test_dashboard_surfaces_api_errors_instead_of_showing_zero(self):
        page = DashboardPage()
        self.addCleanup(page.close)

        page.show_dashboard_data(
            {
                "counts": {
                    "tenants": None,
                    "installations": None,
                    "modules": 2,
                },
                "errors": {
                    "tenants": "Akses ditolak.",
                    "installations": "Tenant gagal dimuat.",
                },
                "activities": [],
            }
        )

        self.assertEqual(page.stat_values["TOTAL TENANT"].text(), "Gagal")
        self.assertEqual(page.stat_values["INSTALASI"].text(), "Gagal")
        self.assertEqual(page.stat_values["MODUL SISTEM"].text(), "2")
        self.assertIn("Akses ditolak", page.data_status.toolTip())

    def test_license_page_uses_api_module_assignment_without_fake_licenses(self):
        class FakeApiClient:
            def __init__(self):
                self.enabled = False
                self.enable_calls = []
                self.list_calls = []

            def list_tenant_modules(self, tenant_id):
                self.list_calls.append(tenant_id)
                return [
                    {
                        "id": 1,
                        "code": "CORE",
                        "name": "Core",
                        "is_active": True,
                        "is_assigned": True,
                        "is_enabled": True,
                        "status": "ENABLED",
                    },
                    {
                        "id": 2,
                        "code": "SURVEI_GPS",
                        "name": "Survei GPS",
                        "is_active": True,
                        "is_assigned": self.enabled,
                        "is_enabled": self.enabled,
                        "status": "ENABLED" if self.enabled else "UNASSIGNED",
                    },
                ]

            def enable_tenant_module(self, tenant_id, module_code):
                self.enable_calls.append((tenant_id, module_code))
                self.enabled = True

            def disable_tenant_module(self, tenant_id, module_code):
                self.enabled = False

        api_client = FakeApiClient()
        page = LicensePage(api_client)
        self.addCleanup(page.close)
        self.assertIn(
            "belum menyediakan model atau endpoint lisensi",
            page.license_note.text(),
        )

        page.tenant_id_input.setText("31")
        page.load_button.click()
        page.wait_for_load()
        self.app.processEvents()

        self.assertEqual(page.table.rowCount(), 2)
        self.assertEqual(api_client.list_calls, [31])
        survei_row = next(
            row
            for row in range(page.table.rowCount())
            if page.table.item(row, 0).text() == "SURVEI_GPS"
        )
        page.table.selectRow(survei_row)
        self.assertTrue(page.enable_button.isEnabled())
        self.assertFalse(page.disable_button.isEnabled())

        page.enable_button.click()
        page.wait_for_load()
        self.app.processEvents()

        self.assertEqual(api_client.enable_calls, [(31, "SURVEI_GPS")])
        self.assertEqual(page.table.item(survei_row, 2).text(), "ENABLED")

    def test_installation_page_shows_server_list_and_tenant_scoped_detail(self):
        installation = {
            "id": 8,
            "tenant_id": 31,
            "tenant_code": "TEN-31",
            "tenant_name": "Tenant One",
            "installation_key": "do-not-display-key",
            "device": {
                "id": "device-8",
                "name": "Field Laptop",
                "platform": "windows",
                "app_version": "1.2.3",
                "details": {
                    "os_version": "Windows 11",
                    "locale": "id-ID",
                },
            },
            "status": "ACTIVE",
            "first_seen_at": "2026-11-17T00:00:00+00:00",
            "last_seen_at": "2026-11-17T01:00:00+00:00",
            "created_at": "2026-11-17T00:00:00+00:00",
            "updated_at": "2026-11-17T01:00:00+00:00",
            "deleted_at": None,
        }
        revoked_installation = {
            **installation,
            "id": 9,
            "tenant_id": 31,
            "device": {
                **installation["device"],
                "id": "device-9",
                "name": "Revoked Device",
            },
            "status": "REVOKED",
            "deleted_at": "2026-11-17T02:00:00+00:00",
        }

        class FakeApiClient:
            def __init__(self):
                self.detail_requests = []
                self.list_requests = []

            def list_installations(self, include_deleted=False):
                self.list_requests.append(include_deleted)
                return (
                    [installation, revoked_installation]
                    if include_deleted
                    else [installation]
                )

            def get_tenant_installation(self, tenant_id, installation_id):
                self.detail_requests.append((tenant_id, installation_id))
                return installation

        api_client = FakeApiClient()
        page = InstallationPage(api_client)
        self.addCleanup(page.close)
        self.addCleanup(page.wait_for_load)
        self.assertIsNone(page.add_button)
        self.assertIsNone(page.edit_button)

        page.load_installations()
        page.wait_for_load()
        self.app.processEvents()

        self.assertEqual(page.table.rowCount(), 1)
        self.assertEqual(page.table.item(0, 1).text(), "8")
        self.assertEqual(page.table.item(0, 2).text(), "TEN-31 — Tenant One")
        self.assertEqual(page.table.item(0, 3).text(), "device-8")
        self.assertEqual(page.table.item(0, 7).text(), "ACTIVE")

        with patch("main.QMessageBox.exec") as show_detail:
            page.show_details(0, 0)
            page.wait_for_load()
            self.app.processEvents()

        self.assertEqual(api_client.detail_requests, [(31, 8)])
        self.assertTrue(show_detail.called)
        detail_dialog = page.findChild(QMessageBox)
        detail_text = detail_dialog.text()
        self.assertIn("Tenant: TEN-31 — Tenant One", detail_text)
        self.assertIn("Platform: windows", detail_text)
        self.assertIn("os_version: Windows 11", detail_text)
        self.assertNotIn("do-not-display-key", detail_text)

        page.include_revoked.setChecked(True)
        page.wait_for_load()
        self.app.processEvents()
        self.assertEqual(api_client.list_requests, [False, True])
        self.assertEqual(page.table.rowCount(), 2)
        revoked_row = next(
            row
            for row in range(page.table.rowCount())
            if page.table.item(row, 1).text() == "9"
        )
        with patch("main.QMessageBox.exec"):
            page.show_details(revoked_row, 0)
        detail_dialog = page.findChildren(QMessageBox)[-1]
        self.assertIn("Status: REVOKED", detail_dialog.text())
        self.assertIn("Dihapus: 2026-11-17T02:00:00+00:00", detail_dialog.text())
        self.assertEqual(api_client.detail_requests, [(31, 8)])

    def test_module_page_loads_catalog_and_tenant_usage_from_api(self):
        module = {
            "id": 5,
            "code": "UMKM",
            "name": "UMKM",
            "description": "Business module",
            "is_active": True,
            "created_at": "2026-11-17T00:00:00+00:00",
            "updated_at": "2026-11-17T01:00:00+00:00",
        }

        class FakeApiClient:
            def __init__(self):
                self.detail_requests = []
                self.usage_requests = []

            def list_modules(self):
                return [module]

            def get_module(self, module_id):
                self.detail_requests.append(module_id)
                return module

            def list_module_tenant_usage(self, module_code):
                self.usage_requests.append(module_code)
                return [
                    {
                        "tenant_id": 31,
                        "tenant_code": "TEN-31",
                        "tenant_name": "Tenant One",
                        "is_assigned": True,
                        "is_enabled": True,
                        "status": "ENABLED",
                    },
                    {
                        "tenant_id": 32,
                        "tenant_code": "TEN-32",
                        "tenant_name": "Tenant Two",
                        "is_assigned": False,
                        "is_enabled": False,
                        "status": "UNASSIGNED",
                    },
                ]

        api_client = FakeApiClient()
        page = ModulePage(api_client)
        self.addCleanup(page.close)
        self.addCleanup(page.wait_for_load)

        page.load_modules()
        page.wait_for_load()
        self.app.processEvents()

        self.assertEqual(page.table.rowCount(), 1)
        self.assertEqual(page.table.item(0, 2).text(), "UMKM")
        self.assertEqual(page.table.item(0, 5).text(), "ACTIVE")

        with patch("main.QMessageBox.exec"):
            page.show_details(0, 0)
            page.wait_for_load()
            self.app.processEvents()

        self.assertEqual(api_client.detail_requests, [5])
        self.assertEqual(api_client.usage_requests, ["UMKM"])
        detail_dialog = page.findChildren(QMessageBox)[-1]
        self.assertIn("Status katalog: ACTIVE", detail_dialog.text())
        self.assertIn("Assignment aktif: 1", detail_dialog.text())
        self.assertIn("TEN-31 — Tenant One: ENABLED", detail_dialog.text())
        self.assertIn(
            "Status katalog, assignment modul, dan lisensi",
            detail_dialog.text(),
        )

    def test_module_page_creates_edits_and_changes_catalog_status_via_api(self):
        class FakeApiClient:
            def __init__(self):
                self.modules = []
                self.calls = []

            def list_modules(self):
                return list(self.modules)

            def create_module(self, code, name, description):
                self.calls.append(("create", code, name, description))
                module = {
                    "id": 7,
                    "code": code.upper(),
                    "name": name,
                    "description": description,
                    "is_active": True,
                    "created_at": "2026-11-17T00:00:00+00:00",
                    "updated_at": "2026-11-17T00:00:00+00:00",
                }
                self.modules.append(module)
                return module

            def update_module(self, module_id, name, description):
                self.calls.append(
                    ("update", module_id, name, description)
                )
                module = {
                    **self.modules[0],
                    "name": name,
                    "description": description,
                }
                self.modules[0] = module
                return module

            def set_module_active(self, module_id, is_active):
                self.calls.append(("status", module_id, is_active))
                module = {
                    **self.modules[0],
                    "is_active": is_active,
                }
                self.modules[0] = module
                return module

        api_client = FakeApiClient()
        page = ModulePage(api_client)
        self.addCleanup(page.close)
        self.addCleanup(page.wait_for_load)
        dialogs = []

        with patch.object(
            FormDialog,
            "exec",
            new=lambda dialog: dialogs.append(dialog)
            or QDialog.DialogCode.Rejected,
        ):
            page.open_create_form()

        create_dialog = dialogs.pop()
        self.addCleanup(create_dialog.close)
        create_dialog.inputs["KODE MODUL"].setText("custom")
        create_dialog.inputs["NAMA MODUL"].setText("Custom Module")
        create_dialog.inputs["DESKRIPSI"].setText("Initial description")
        self.assertTrue(create_dialog.submit_form())
        page.wait_for_load()
        self.app.processEvents()
        self.assertEqual(
            api_client.calls[0],
            ("create", "custom", "Custom Module", "Initial description"),
        )

        page.table.selectRow(0)
        self.assertTrue(page.status_button.isEnabled())
        page.toggle_module_status()
        page.wait_for_load()
        self.app.processEvents()
        self.assertEqual(api_client.calls[1], ("status", 7, False))
        self.assertEqual(page.table.item(0, 5).text(), "INACTIVE")

        with patch.object(
            FormDialog,
            "exec",
            new=lambda dialog: dialogs.append(dialog)
            or QDialog.DialogCode.Rejected,
        ):
            page.open_edit_form()

        edit_dialog = dialogs.pop()
        self.addCleanup(edit_dialog.close)
        edit_dialog.inputs["NAMA MODUL"].setText("Custom Suite")
        edit_dialog.inputs["DESKRIPSI"].setText("Updated description")
        self.assertTrue(edit_dialog.submit_form())
        page.wait_for_load()
        self.app.processEvents()
        self.assertEqual(
            api_client.calls[2],
            ("update", 7, "Custom Suite", "Updated description"),
        )
        self.assertEqual(page.table.item(0, 3).text(), "Custom Suite")

    def test_search_filter_and_empty_state_follow_table_contents(self):
        page = DataPage(
            "Tenant",
            "Pengujian tabel",
            ["ID", "NAMA", "STATUS"],
            filter_column=2,
            filter_values=("ACTIVE", "INACTIVE"),
        )
        self.addCleanup(page.close)

        self.assertFalse(page.empty_label.isHidden())
        page.table.setRowCount(2)
        values = (
            ("T-01", "Alpha", "ACTIVE"),
            ("T-02", "Beta", "INACTIVE"),
        )
        for row, row_values in enumerate(values):
            for column, value in enumerate(row_values):
                page.table.setItem(row, column, QTableWidgetItem(value))

        page.search.setText("alpha")
        self.assertFalse(page.table.isRowHidden(0))
        self.assertTrue(page.table.isRowHidden(1))
        self.assertTrue(page.empty_label.isHidden())

        page.search.clear()
        page.status_filter.setCurrentText("INACTIVE")
        self.assertTrue(page.table.isRowHidden(0))
        self.assertFalse(page.table.isRowHidden(1))

        page.search.setText("tidak ditemukan")
        self.assertFalse(page.empty_label.isHidden())
        self.assertIn("Tidak ada data", page.empty_label.text())

    def test_form_validation_requires_mandatory_fields_without_saving(self):
        dialog = FormDialog(
            "Tambah tenant",
            [("TENANT ID", True), ("CATATAN", False)],
        )
        self.addCleanup(dialog.close)

        self.assertFalse(dialog.validate_form())
        self.assertIn("TENANT ID", dialog.validation_message.text())

        dialog.inputs["TENANT ID"].setText("TEN-001")
        self.assertTrue(dialog.validate_form())
        self.assertIn("belum disimpan", dialog.validation_message.text())

    def test_audit_filter_options_are_derived_from_log_rows(self):
        page = DataPage(
            "Audit Log",
            "Pengujian filter tindakan",
            ["WAKTU", "PENGGUNA", "TINDAKAN"],
            filter_column=2,
            filter_values=(),
        )
        self.addCleanup(page.close)
        page.table.setRowCount(2)
        page.table.setItem(0, 0, QTableWidgetItem("2026-01-01"))
        page.table.setItem(0, 1, QTableWidgetItem("dev-a"))
        page.table.setItem(0, 2, QTableWidgetItem("CREATE"))
        page.table.setItem(1, 0, QTableWidgetItem("2026-01-02"))
        page.table.setItem(1, 1, QTableWidgetItem("dev-b"))
        page.table.setItem(1, 2, QTableWidgetItem("DELETE"))

        page.status_filter.setCurrentText("DELETE")
        self.assertTrue(page.table.isRowHidden(0))
        self.assertFalse(page.table.isRowHidden(1))

    def test_configuration_rejects_malformed_api_url(self):
        page = ConfigurationPage()
        self.addCleanup(page.close)
        page.api_url.setText("not-a-url")

        self.assertFalse(page.save_settings())
        self.assertIn("URL API", page.result.text())

    def test_login_without_password_change_requirement_skips_change_page(self):
        user = {"username": "developer", "must_change_password": False}
        login_dialog = Mock()
        login_dialog.exec.return_value = QDialog.DialogCode.Accepted
        login_dialog.user = user

        with patch("main.LoginDialog", return_value=login_dialog), patch(
            "main.PasswordChangeDialog"
        ) as password_dialog:
            result = authenticate_user(object())

        self.assertIs(result, user)
        password_dialog.assert_not_called()

    def test_required_password_change_relogs_in_before_returning_user(self):
        first_user = {"username": "developer", "must_change_password": True}
        authenticated_user = {
            "username": "developer",
            "must_change_password": False,
        }
        first_login = Mock()
        first_login.exec.return_value = QDialog.DialogCode.Accepted
        first_login.user = first_user
        second_login = Mock()
        second_login.exec.return_value = QDialog.DialogCode.Accepted
        second_login.user = authenticated_user
        password_dialog = Mock()
        password_dialog.exec.return_value = QDialog.DialogCode.Accepted

        with patch(
            "main.LoginDialog", side_effect=[first_login, second_login]
        ) as login_dialog, patch(
            "main.PasswordChangeDialog", return_value=password_dialog
        ) as change_page:
            result = authenticate_user(object())

        self.assertIs(result, authenticated_user)
        self.assertEqual(login_dialog.call_count, 2)
        change_page.assert_called_once_with(
            login_dialog.call_args.args[0], first_user, None
        )

    def test_password_change_form_submits_values_and_clears_password_fields(self):
        api_client = Mock()
        dialog = PasswordChangeDialog(
            api_client, {"username": "developer"}
        )
        self.addCleanup(dialog.close)
        dialog.current_password.setText("current-password")
        dialog.new_password.setText("new-password-123")
        dialog.confirm_password.setText("new-password-123")

        dialog.change_password()

        api_client.change_password.assert_called_once_with(
            "current-password", "new-password-123"
        )
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.current_password.text(), "")
        self.assertEqual(dialog.new_password.text(), "")
        self.assertEqual(dialog.confirm_password.text(), "")

    def test_tenant_page_loads_server_records_into_existing_table(self):
        tenant = {
            "id": 31,
            "code": "TEN-31",
            "name": "Tenant Test",
            "organization_name": "Org Test",
            "status": "ACTIVE",
            "created_at": "2026-11-17T00:00:00+00:00",
        }

        class FakeApiClient:
            def list_tenants(self):
                return [tenant]

        page = TenantPage(FakeApiClient())
        self.addCleanup(page.close)
        self.addCleanup(page.wait_for_load)
        page.load_tenants()
        page.wait_for_load()
        self.app.processEvents()

        self.assertEqual(page.table.rowCount(), 1)
        self.assertEqual(page.table.item(0, 1).text(), "TEN-31")
        self.assertEqual(page.table.item(0, 2).text(), "Tenant Test")
        self.assertEqual(page.table.item(0, 3).text(), "Org Test")
        self.assertEqual(page.table.item(0, 4).text(), "ACTIVE")
        self.assertEqual(
            page.data_status.text(), "DATA TENANT: 1 DIMUAT DARI API"
        )
        self.assertEqual(
            page.table.item(0, 1).data(Qt.ItemDataRole.UserRole), 31
        )

    def test_tenant_forms_offer_api_status_codes_and_active_default(self):
        page = TenantPage(Mock())
        self.addCleanup(page.close)
        dialogs = []
        with patch.object(
            FormDialog,
            "exec",
            new=lambda dialog: dialogs.append(dialog)
            or QDialog.DialogCode.Rejected,
        ):
            page.open_form("Tambah Tenant")

        dialog = dialogs[0]
        self.addCleanup(dialog.close)
        status = dialog.inputs["STATUS"]
        self.assertIsInstance(status, QComboBox)
        self.assertEqual(
            [status.itemText(index) for index in range(status.count())],
            ["ACTIVE", "INACTIVE", "RESTRICTED"],
        )
        self.assertEqual(status.currentText(), "ACTIVE")

    def test_tenant_edit_form_preserves_server_id_and_status(self):
        page = TenantPage(Mock())
        self.addCleanup(page.close)
        page._show_tenants(
            [
                {
                    "id": 42,
                    "code": "TEN-42",
                    "name": "Tenant Test",
                    "organization_name": None,
                    "status": "RESTRICTED",
                    "created_at": "2026-11-17T00:00:00+00:00",
                }
            ]
        )
        page.table.selectRow(0)
        dialogs = []
        with patch.object(
            FormDialog,
            "exec",
            new=lambda dialog: dialogs.append(dialog)
            or QDialog.DialogCode.Rejected,
        ):
            page.open_edit_form()

        dialog = dialogs[0]
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.inputs["STATUS"].currentText(), "RESTRICTED")
        self.assertEqual(
            page.table.item(0, 1).data(Qt.ItemDataRole.UserRole),
            42,
        )

    def test_tenant_form_submit_routes_to_api_save_worker(self):
        api_client = Mock()
        page = TenantPage(api_client)
        self.addCleanup(page.close)
        dialogs = []
        with patch.object(
            FormDialog,
            "exec",
            new=lambda dialog: dialogs.append(dialog)
            or QDialog.DialogCode.Rejected,
        ):
            page.open_form("Tambah Tenant")
        dialog = dialogs[0]
        self.addCleanup(dialog.close)
        dialog.inputs["TENANT ID"].setText("TEN-55")
        dialog.inputs["NAMA TENANT"].setText("Tenant Baru")
        dialog.inputs["ORGANISASI"].setText("Org Baru")
        dialog.inputs["STATUS"].setCurrentText("INACTIVE")
        dialog.inputs["ALASAN PERUBAHAN STATUS"].setText("Permintaan admin")

        with patch("main.TenantSaveWorker") as worker:
            self.assertTrue(dialog.submit_form())

        worker.assert_called_once_with(
            api_client,
            None,
            "TEN-55",
            "Tenant Baru",
            "Org Baru",
            "INACTIVE",
            "ACTIVE",
            "Permintaan admin",
            None,
        )
        worker.return_value.start.assert_called_once_with()

    def test_tenant_form_requires_reason_for_status_change(self):
        page = TenantPage(Mock())
        self.addCleanup(page.close)
        dialogs = []
        with patch.object(
            FormDialog,
            "exec",
            new=lambda dialog: dialogs.append(dialog)
            or QDialog.DialogCode.Rejected,
        ):
            page.open_form("Tambah Tenant")
        dialog = dialogs[0]
        self.addCleanup(dialog.close)
        dialog.inputs["TENANT ID"].setText("TEN-55")
        dialog.inputs["NAMA TENANT"].setText("Tenant Baru")
        dialog.inputs["STATUS"].setCurrentText("INACTIVE")

        with patch("main.TenantSaveWorker") as worker:
            dialog.submit_form()

        worker.assert_not_called()
        self.assertIn("alasan", dialog.validation_message.text().lower())

    def test_tenant_create_worker_sets_status_after_create(self):
        api_client = Mock()
        api_client.create_tenant.return_value = {"id": 55}
        worker = TenantSaveWorker(
            api_client,
            None,
            "TEN-55",
            "Tenant Baru",
            "Org Baru",
            "INACTIVE",
            "ACTIVE",
            "Permintaan admin",
        )
        saved = []
        worker.saved.connect(lambda: saved.append(True))

        worker.run()

        api_client.create_tenant.assert_called_once_with(
            "TEN-55", "Tenant Baru", "Org Baru"
        )
        api_client.change_tenant_status.assert_called_once_with(
            55, "INACTIVE", "Permintaan admin"
        )
        self.assertEqual(saved, [True])

    def test_tenant_status_only_edit_skips_identity_update(self):
        api_client = Mock()
        worker = TenantSaveWorker(
            api_client,
            42,
            "TEN-42",
            "Tenant Test",
            None,
            "INACTIVE",
            "ACTIVE",
            "Permintaan admin",
            {
                "code": "TEN-42",
                "name": "Tenant Test",
                "organization_name": None,
            },
        )

        worker.run()

        api_client.update_tenant.assert_not_called()
        api_client.change_tenant_status.assert_called_once_with(
            42, "INACTIVE", "Permintaan admin"
        )

    def test_tenant_worker_reports_partial_create_if_status_fails(self):
        api_client = Mock()
        api_client.create_tenant.return_value = {"id": 55}
        api_client.change_tenant_status.side_effect = ApiError(
            "Akses ditolak (HTTP 403)."
        )
        worker = TenantSaveWorker(
            api_client,
            None,
            "TEN-55",
            "Tenant Baru",
            None,
            "INACTIVE",
            "ACTIVE",
            "Permintaan admin",
        )
        failures = []
        worker.failed.connect(
            lambda message, partial: failures.append((message, partial))
        )

        worker.run()

        self.assertEqual(len(failures), 1)
        self.assertTrue(failures[0][1])
        self.assertIn("berhasil dibuat dengan status ACTIVE", failures[0][0])

    def test_tenant_page_reports_empty_and_api_error_states(self):
        page = TenantPage(None)
        self.addCleanup(page.close)

        page._show_tenants([])
        self.assertEqual(page.table.rowCount(), 0)
        self.assertEqual(page.empty_label.text(), "Belum ada Tenant pada server.")

        page._show_load_error("Akses ditolak (HTTP 403).")
        self.assertTrue(
            page.data_status.text().startswith("DATA TENANT: GAGAL DIMUAT")
        )
        self.assertIn("Akses ditolak", page.empty_label.text())

    def test_tenant_page_shows_loading_status_while_request_is_pending(self):
        release_request = threading.Event()
        self.addCleanup(release_request.set)

        class BlockingApiClient:
            def list_tenants(self):
                release_request.wait(timeout=2)
                return []

        page = TenantPage(BlockingApiClient())
        self.addCleanup(page.close)
        self.addCleanup(page.wait_for_load)

        page.load_tenants()

        self.assertEqual(page.data_status.text(), "DATA TENANT: MEMUAT...")
        release_request.set()
        page.wait_for_load()
        self.app.processEvents()
        self.assertEqual(page.data_status.text(), "DATA TENANT: 0 DIMUAT DARI API")


if __name__ == "__main__":
    unittest.main()
