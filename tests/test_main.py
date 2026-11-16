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
    QTableWidgetItem,
)

from main import (
    ConfigurationPage,
    DataPage,
    FormDialog,
    MainWindow,
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
