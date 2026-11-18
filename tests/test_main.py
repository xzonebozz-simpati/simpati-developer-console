import os
import threading
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
)

from main import (
    AuditLogPage,
    BackupRecoveryPage,
    ConfigurationPage,
    DashboardLoadWorker,
    DashboardMonitoringWorker,
    DashboardPage,
    DataPage,
    DeveloperAccountDialog,
    DeveloperPage,
    DeveloperPasswordDialog,
    DeveloperRoleManagerDialog,
    DeveloperSelectionDialog,
    DeveloperNotificationsPage,
    FormDialog,
    InstallationPage,
    LicensePage,
    LicenseIssueDialog,
    LicenseIssuedDialog,
    LicenseMutationDialog,
    LicenseDetailsDialog,
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

    def test_backup_recovery_page_only_lists_unsupported_operations(self):
        page = BackupRecoveryPage()
        self.addCleanup(page.close)

        self.assertEqual(page.operation_table.rowCount(), 6)
        self.assertTrue(
            all(
                page.operation_table.item(row, 1).text()
                == "BELUM TERSEDIA"
                for row in range(page.operation_table.rowCount())
            )
        )
        self.assertEqual(page.findChildren(QPushButton), [])
        labels = [label.text() for label in page.findChildren(QLabel)]
        self.assertTrue(
            any("/health/ready" in label for label in labels)
        )
        self.assertIn(
            "BACKUP DATABASE: BELUM DIDUKUNG UNIVERSAL API",
            page.readiness_status.text(),
        )

    def test_developer_notifications_page_does_not_relabel_audit_as_notifications(self):
        page = DeveloperNotificationsPage()
        self.addCleanup(page.close)

        self.assertEqual(page.capability_table.rowCount(), 8)
        statuses = [
            page.capability_table.item(row, 1).text()
            for row in range(page.capability_table.rowCount())
        ]
        self.assertEqual(statuses[0], "BELUM TERSEDIA")
        self.assertEqual(statuses[1], "TERSEDIA TERPISAH")
        self.assertTrue(
            all(status == "BELUM TERSEDIA" for status in statuses[2:])
        )
        self.assertIn(
            "bukan notifikasi",
            page.capability_table.item(1, 2).text().lower(),
        )
        self.assertEqual(page.findChildren(QPushButton), [])
        self.assertIn("BELUM DIDUKUNG", page.readiness_status.text())

    def test_dashboard_displays_live_api_counts_and_latest_activity(self):
        class FakeApiClient:
            def list_tenants(self):
                return [
                    {"id": 31, "status": "ACTIVE"},
                    {"id": 32, "status": "INACTIVE"},
                ]

            def list_tenant_installations(self, tenant_id):
                return [
                    {"status": "ACTIVE"} for _ in range({31: 4, 32: 7}[tenant_id])
                ] + [{"status": "REVOKED"}]

            def list_modules(self):
                return [
                    {"id": 1, "is_active": True},
                    {"id": 2, "is_active": True},
                    {"id": 3, "is_active": False},
                ]

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

        self.assertEqual(page.stat_values["TENANT AKTIF"].text(), "1")
        self.assertEqual(page.stat_values["INSTALASI AKTIF"].text(), "11")
        self.assertEqual(page.stat_values["MODUL TERSEDIA"].text(), "2")
        self.assertEqual(page.stat_values["LISENSI AKTIF"].text(), "N/D")
        self.assertIn("TENANT_CREATED", page.activity_label.text())
        self.assertIn("Waktu respons", page.stat_values["TENANT AKTIF"].toolTip())
        self.assertEqual(page.database_status.text(), "DATABASE: N/D")
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
                    "modules": None,
                },
                "errors": {
                    "tenants": "Akses ditolak.",
                    "installations": "Tenant gagal dimuat.",
                    "modules": "Timeout.",
                },
                "activities": [],
                "timings_ms": {
                    "tenants": 12.5,
                    "installations": 0.0,
                    "modules": 8000.0,
                    "activity": 1.0,
                },
            }
        )

        self.assertEqual(page.stat_values["TENANT AKTIF"].text(), "Gagal")
        self.assertEqual(page.stat_values["INSTALASI AKTIF"].text(), "Gagal")
        self.assertEqual(page.stat_values["MODUL TERSEDIA"].text(), "Gagal")
        self.assertIn("Akses ditolak", page.data_status.toolTip())
        self.assertIn("8000.00 ms", page.stat_values["MODUL TERSEDIA"].toolTip())

    def test_connection_check_reports_healthy_status_and_response_time(self):
        class FakeApiClient:
            def check_connection(self):
                return {"status": "RUNNING"}

            def check_database_readiness(self):
                return {"status": "ONLINE", "database": "CONNECTED"}

        results = []
        worker = DashboardMonitoringWorker(FakeApiClient())
        worker.checked.connect(results.append)
        worker.run()

        api = results[0]["api"]
        database = results[0]["database"]
        self.assertTrue(api["connected"])
        self.assertEqual(api["message"], "API: TERHUBUNG")
        self.assertGreaterEqual(api["response_ms"], 0)
        self.assertTrue(api["checked_at"])
        self.assertEqual(database["status"], "ONLINE")
        self.assertGreaterEqual(database["response_ms"], 0)
        self.assertTrue(database["checked_at"])

    def test_connection_check_reports_failed_health_endpoint_as_offline(self):
        class FakeApiClient:
            def check_connection(self):
                raise ApiError("Health endpoint returned HTTP 503.")

            def check_database_readiness(self):
                return {"status": "ONLINE", "database": "CONNECTED"}

        results = []
        worker = DashboardMonitoringWorker(FakeApiClient())
        worker.checked.connect(results.append)
        worker.run()

        api = results[0]["api"]
        self.assertFalse(api["connected"])
        self.assertIn("HTTP 503", api["message"])
        self.assertGreaterEqual(api["response_ms"], 0)
        self.assertTrue(api["checked_at"])

    def test_connection_check_reports_database_readiness_503_as_offline(self):
        class FakeApiClient:
            def check_connection(self):
                return {"status": "RUNNING"}

            def check_database_readiness(self):
                raise ApiError(
                    "Permintaan API gagal (HTTP 503).",
                    status_code=503,
                )

        results = []
        worker = DashboardMonitoringWorker(FakeApiClient())
        worker.checked.connect(results.append)
        worker.run()

        self.assertTrue(results[0]["api"]["connected"])
        self.assertEqual(results[0]["database"]["status"], "OFFLINE")
        self.assertIn("HTTP 503", results[0]["database"]["message"])

    def test_connection_check_shows_database_not_determined_if_endpoint_missing(self):
        class FakeApiClient:
            def check_connection(self):
                return {"status": "RUNNING"}

            def check_database_readiness(self):
                raise ApiError(
                    "Permintaan API gagal (HTTP 404).",
                    status_code=404,
                )

        results = []
        worker = DashboardMonitoringWorker(FakeApiClient())
        worker.checked.connect(results.append)
        worker.run()

        self.assertTrue(results[0]["api"]["connected"])
        self.assertEqual(results[0]["database"]["status"], "N/D")
        self.assertIn("tidak tersedia", results[0]["database"]["message"])

    def test_connection_check_reports_timeout_as_offline_with_elapsed_time(self):
        class FakeApiClient:
            def check_connection(self):
                raise ApiError("Request timed out.")

            def check_database_readiness(self):
                return {"status": "ONLINE", "database": "CONNECTED"}

        results = []
        worker = DashboardMonitoringWorker(FakeApiClient())
        worker.checked.connect(results.append)
        with patch(
            "main.time.perf_counter",
            side_effect=[2.0, 10.0, 10.0, 10.05],
        ):
            worker.run()

        api = results[0]["api"]
        self.assertFalse(api["connected"])
        self.assertIn("timed out", api["message"])
        self.assertEqual(api["response_ms"], 8000.0)

    def test_dashboard_shows_monitoring_data_unavailable_as_not_determined(self):
        page = DashboardPage()
        self.addCleanup(page.close)

        self.assertEqual(page.database_status.text(), "DATABASE: N/D")
        self.assertIn("GET /health/ready", page.database_status.toolTip())
        page.show_api_health(
            False,
            "Tidak dapat terhubung ke Universal API.",
            8000.0,
            "2026-11-17T11:00:00+07:00",
            "N/D",
            "Endpoint readiness tidak tersedia.",
            12.0,
            "2026-11-17T11:00:00+07:00",
        )

        self.assertEqual(page.api_status.text(), "UNIVERSAL API: OFFLINE")
        self.assertEqual(page.api_response_time.text(), "Waktu respons: 8000.00 ms")
        self.assertEqual(
            page.last_health_check.text(),
            "Pemeriksaan terakhir: 2026-11-17T11:00:00+07:00",
        )
        self.assertEqual(page.database_status.text(), "DATABASE: N/D")
        self.assertEqual(
            page.database_response_time.text(),
            "Waktu respons database: 12.00 ms",
        )

    def test_dashboard_marks_database_online_only_after_readiness_success(self):
        page = DashboardPage()
        self.addCleanup(page.close)

        page.show_api_health(
            True,
            "API: TERHUBUNG",
            5.0,
            "2026-11-17T11:00:00+07:00",
            "ONLINE",
            "Database readiness succeeded.",
            8.0,
            "2026-11-17T11:00:00+07:00",
        )
        self.assertEqual(page.database_status.text(), "DATABASE: ONLINE")

        page.show_database_readiness(
            "OFFLINE",
            "Database readiness returned HTTP 503.",
            9.0,
            "2026-11-17T11:00:30+07:00",
        )
        self.assertEqual(page.database_status.text(), "DATABASE: OFFLINE")

    def test_dashboard_manual_refresh_requests_monitoring_check(self):
        page = DashboardPage(Mock())
        self.addCleanup(page.close)
        checks = []
        page.health_check_requested.connect(lambda: checks.append(True))

        with patch.object(page, "load_dashboard") as load_dashboard:
            page.refresh_button.click()

        load_dashboard.assert_called_once_with()
        self.assertEqual(checks, [True])

    def test_license_page_loads_license_records_from_universal_api(self):
        class FakeApiClient:
            def __init__(self):
                self.list_calls = []

            def list_tenants(self):
                return [
                    {
                        "id": 31,
                        "code": "TENANT-31",
                        "name": "Tenant 31",
                        "status": "ACTIVE",
                    }
                ]

            def list_tenant_licenses(self, tenant_id, limit, offset):
                self.list_calls.append((tenant_id, limit, offset))
                return {
                    "items": [
                        {
                            "id": (
                                "e536cdd2-9952-4c33-9caf-789df6477bbb"
                            ),
                            "package_id": (
                                "58dd22e7-35a2-43c2-9d8c-e34c480d5908"
                            ),
                            "status": "ACTIVE",
                            "valid_from": "2026-01-01T00:00:00Z",
                            "valid_until": "2027-01-01T00:00:00Z",
                        }
                    ],
                    "limit": limit,
                    "offset": offset,
                }

        api_client = FakeApiClient()
        page = LicensePage(
            api_client,
            {
                "permissions": [
                    "tenants.read",
                    "tenants.manage",
                    "auth.audit.read",
                ]
            },
        )
        self.addCleanup(page.close)
        self.assertIn("License Manager", page.license_note.text())

        page.load_tenants()
        page.wait_for_load()
        self.app.processEvents()
        self.assertEqual(page.tenant_selector.currentData(), 31)
        page.load_button.click()
        page.wait_for_load()
        self.app.processEvents()

        self.assertEqual(page.table.rowCount(), 1)
        self.assertEqual(api_client.list_calls, [(31, 50, 0)])
        self.assertEqual(
            page.table.item(0, 0).text(),
            "e536cdd2-9952-4c33-9caf-789df6477bbb",
        )
        self.assertEqual(page.table.item(0, 2).text(), "ACTIVE")
        page.table.selectRow(0)
        self.assertTrue(page.detail_button.isEnabled())
        self.assertTrue(page.history_button.isEnabled())
        self.assertFalse(hasattr(page, "enable_button"))

    def test_license_page_respects_license_permissions(self):
        class FakeApiClient:
            def list_tenants(self):
                return [
                    {
                        "id": 31,
                        "code": "TENANT-31",
                        "name": "Tenant 31",
                        "status": "ACTIVE",
                    }
                ]

        page = LicensePage(
            FakeApiClient(),
            {"permissions": ["tenants.read"]},
        )
        self.addCleanup(page.close)
        page.load_tenants()
        page.wait_for_load()
        self.app.processEvents()

        self.assertTrue(page.load_button.isEnabled())
        self.assertFalse(page.issue_button.isEnabled())
        self.assertFalse(page.history_button.isEnabled())

    def test_license_page_lists_tenants_without_licenses_for_issuance(self):
        class FakeApiClient:
            def __init__(self):
                self.license_calls = []

            def list_tenants(self):
                return [
                    {
                        "id": 31,
                        "code": "TENANT-31",
                        "name": "Tenant With Licenses",
                        "status": "ACTIVE",
                    },
                    {
                        "id": 32,
                        "code": "TENANT-32",
                        "name": "Tenant Without Licenses",
                        "status": "ACTIVE",
                    },
                    {
                        "id": 33,
                        "code": "TENANT-33",
                        "name": "Registered Inactive Tenant",
                        "status": "INACTIVE",
                    },
                ]

            def list_tenant_licenses(self, tenant_id, limit, offset):
                self.license_calls.append((tenant_id, limit, offset))
                return {"items": [], "limit": limit, "offset": offset}

        api_client = FakeApiClient()
        page = LicensePage(
            api_client,
            {
                "permissions": [
                    "tenants.read",
                    "tenants.manage",
                ]
            },
        )
        self.addCleanup(page.close)

        page.load_tenants()
        page.wait_for_load()
        self.app.processEvents()

        self.assertEqual(page.tenant_selector.count(), 4)
        self.assertEqual(page.tenant_selector.itemData(1), 31)
        self.assertEqual(page.tenant_selector.itemData(2), 32)
        self.assertEqual(page.tenant_selector.itemData(3), 33)
        self.assertIn(
            "Tenant Without Licenses",
            page.tenant_selector.itemText(2),
        )
        page.tenant_selector.setCurrentIndex(3)
        self.assertTrue(page.load_button.isEnabled())
        self.assertTrue(page.issue_button.isEnabled())
        page.tenant_selector.setCurrentIndex(2)
        self.assertTrue(page.issue_button.isEnabled())
        page.load_button.click()
        page.wait_for_load()
        self.app.processEvents()

        self.assertEqual(api_client.license_calls, [(32, 50, 0)])
        self.assertEqual(page.table.rowCount(), 0)
        self.assertTrue(page.issue_button.isEnabled())
        page.catalogs = {"packages": [], "modules": []}
        with patch.object(page, "_show_issue_dialog") as show_dialog:
            page.issue_button.click()

        self.assertEqual(page.tenant_id, 32)
        show_dialog.assert_called_once_with(page.catalogs)

    def test_license_issue_dialog_loads_package_modules_from_api(self):
        package_id = "58dd22e7-35a2-43c2-9d8c-e34c480d5908"

        class FakeApiClient:
            def get_license_package(self, selected_id):
                self.selected_package = selected_id
                return {
                    "id": package_id,
                    "is_active": True,
                    "package_modules": [
                        {"module_code": "CORE", "is_mandatory": True},
                        {
                            "module_code": "SURVEI_GPS",
                            "is_mandatory": False,
                        },
                    ],
                }

        dialog = LicenseIssueDialog(
            FakeApiClient(),
            31,
            [{"id": package_id, "name": "Professional"}],
            [
                {
                    "module_code": "CORE",
                    "name": "Core",
                    "is_active": True,
                },
                {
                    "module_code": "SURVEI_GPS",
                    "name": "Survei GPS",
                    "is_active": True,
                },
            ],
        )
        self.addCleanup(dialog.close)
        dialog.package_worker.wait()
        self.app.processEvents()

        values = dialog.values()
        self.assertEqual(values["tenant_id"], 31)
        self.assertEqual(values["package_id"], package_id)
        self.assertEqual(values["modules"], ["CORE"])
        self.assertEqual(values["max_installations"], 1)
        self.assertEqual(values["max_members"], 50000)
        self.assertEqual(values["max_accounts"], 200)
        self.assertEqual(values["max_concurrent_users"], 25)
        self.assertEqual(values["max_storage_mb"], 20480)
        self.assertTrue(dialog.submit_button.isEnabled())
        dialog.module_list.item(1).setCheckState(Qt.CheckState.Checked)
        self.assertEqual(
            dialog.values()["modules"], ["CORE", "SURVEI_GPS"]
        )

    def test_license_mutation_dialogs_collect_api_required_values(self):
        license_record = {
            "status": "ACTIVE",
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_until": "2027-01-01T00:00:00Z",
            "grace_period_days": 7,
        }
        status_dialog = LicenseMutationDialog("status", license_record)
        self.addCleanup(status_dialog.close)
        status_dialog.status_input.setCurrentText("SUSPENDED")
        status_dialog.reason_input.setText("Compliance review")
        self.assertEqual(
            status_dialog.values(),
            {"status": "SUSPENDED", "reason": "Compliance review"},
        )

        validity_dialog = LicenseMutationDialog(
            "validity", license_record
        )
        self.addCleanup(validity_dialog.close)
        validity_dialog.reason_input.setText("Corrected dates")
        self.assertEqual(
            validity_dialog.values()["grace_period_days"], 7
        )
        self.assertEqual(
            validity_dialog.values()["reason"], "Corrected dates"
        )

        extension_dialog = LicenseMutationDialog(
            "extend", license_record
        )
        self.addCleanup(extension_dialog.close)
        extension_dialog.reason_input.setText("Renewed")
        self.assertEqual(
            extension_dialog.values()["reason"], "Renewed"
        )

    def test_issued_serial_key_can_be_cleared_after_one_time_display(self):
        serial_key = "SMP-LIC-2026-0123456789ABCDEF-FEDCBA9876543210"
        dialog = LicenseIssuedDialog("license-id", serial_key)
        self.addCleanup(dialog.close)

        self.assertTrue(dialog.serial_key_input.isReadOnly())
        self.assertEqual(dialog.serial_key_input.text(), serial_key)
        dialog.clear_key()
        self.assertEqual(dialog.serial_key_input.text(), "")

    def test_license_details_never_display_serial_key_or_credentials(self):
        serial_key = "SMP-LIC-2026-0123456789ABCDEF-FEDCBA9876543210"
        dialog = LicenseDetailsDialog(
            "Detail Lisensi",
            {
                "id": "license-id",
                "license_key": serial_key,
                "notes": f"legacy {serial_key}",
                "access_token": "private-token",
                "status": "ACTIVE",
            },
        )
        self.addCleanup(dialog.close)

        text = dialog.findChild(QPlainTextEdit).toPlainText()
        self.assertNotIn(serial_key, text)
        self.assertNotIn("private-token", text)
        self.assertIn("[REDACTED]", text)
        self.assertIn("ACTIVE", text)

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

    def test_audit_log_page_displays_details_filters_and_paginates_api_data(self):
        logs = [
            {
                "id": 101,
                "tenant_id": 31,
                "actor_type": "DEVELOPER",
                "actor_id": 7,
                "action": "TENANT_CREATED",
                "entity": "Tenant",
                "entity_id": "31",
                "details": {
                    "result": "success",
                    "summary": "Tenant created",
                },
                "created_at": "2026-11-16T08:30:00+00:00",
            },
            {
                "id": 102,
                "tenant_id": 31,
                "actor_type": "TENANT",
                "actor_id": 9,
                "action": "MEMBER_UPDATED",
                "entity": "Member",
                "entity_id": "12",
                "details": {"result": "updated"},
                "created_at": "2026-11-17T09:30:00+00:00",
            },
            {
                "id": 103,
                "tenant_id": None,
                "actor_type": "SYSTEM",
                "actor_id": None,
                "action": "LOGIN_FAILED",
                "entity": "DeveloperSession",
                "entity_id": None,
                "details": None,
                "created_at": "2026-11-18T10:30:00+00:00",
            },
        ]

        class FakeApiClient:
            def __init__(self):
                self.calls = []

            def list_audit_logs(self, limit, offset):
                self.calls.append((limit, offset))
                items = logs[offset : offset + limit]
                return {"items": items, "limit": limit, "offset": offset}

        api_client = FakeApiClient()
        page = AuditLogPage(api_client)
        page.PAGE_SIZE = 2
        self.addCleanup(page.close)
        self.addCleanup(page.wait_for_load)

        page.load_page()
        page.wait_for_load()
        self.app.processEvents()

        self.assertEqual(api_client.calls, [(2, 0)])
        self.assertEqual(page.table.rowCount(), 2)
        self.assertEqual(page.table.item(0, 2).text(), "DEVELOPER #7")
        self.assertEqual(page.table.item(0, 3).text(), "TENANT_CREATED")
        self.assertEqual(page.table.item(0, 4).text(), "Tenant #31")
        self.assertIn("success", page.table.item(0, 5).text())
        self.assertEqual(
            page.data_status.text(),
            "AUDIT LOG: 2 DIMUAT (OFFSET 0); TOTAL TIDAK DISEDIAKAN API",
        )
        self.assertIn("halaman yang sedang dimuat", page.filter_limitation.text())
        self.assertTrue(page.next_button.isEnabled())
        self.assertIsNone(page.add_button)
        self.assertIsNone(page.edit_button)

        page.actor_filter.setCurrentIndex(
            page.actor_filter.findData("TENANT #9")
        )
        self.assertTrue(page.table.isRowHidden(0))
        self.assertFalse(page.table.isRowHidden(1))
        page.actor_filter.setCurrentIndex(0)
        page.date_from.setText("2026-11-17")
        self.assertTrue(page.table.isRowHidden(0))
        self.assertFalse(page.table.isRowHidden(1))
        page.date_from.clear()
        page.status_filter.setCurrentText("MEMBER_UPDATED")
        self.assertTrue(page.table.isRowHidden(0))
        self.assertFalse(page.table.isRowHidden(1))
        page.status_filter.setCurrentText("Semua")
        page.search.setText("DEVELOPER #7")
        self.assertFalse(page.table.isRowHidden(0))
        self.assertTrue(page.table.isRowHidden(1))
        page.search.clear()
        page.table.selectRow(0)
        self.assertTrue(page.detail_button.isEnabled())

        with patch("main.QMessageBox.exec"):
            page.show_selected_details()
        detail_dialog = page.findChildren(QMessageBox)[-1]
        self.assertIn("ID log: 101", detail_dialog.text())
        self.assertIn("Aktivitas: TENANT_CREATED", detail_dialog.text())
        self.assertIn('"summary": "Tenant created"', detail_dialog.text())

        page.next_button.click()
        page.wait_for_load()
        self.app.processEvents()
        self.assertEqual(api_client.calls, [(2, 0), (2, 2)])
        self.assertEqual(page.table.rowCount(), 1)
        self.assertEqual(page.table.item(0, 3).text(), "LOGIN_FAILED")
        self.assertFalse(page.next_button.isEnabled())
        self.assertTrue(page.previous_button.isEnabled())

        page.previous_button.click()
        page.wait_for_load()
        self.app.processEvents()
        self.assertEqual(api_client.calls[-1], (2, 0))

    def test_audit_log_page_surfaces_api_permission_errors(self):
        class FakeApiClient:
            def __init__(self):
                self.requested_page = None

            def list_audit_logs(self, limit, offset):
                self.requested_page = (limit, offset)
                raise ApiError("Akses ditolak: auth.audit.read.")

        api_client = FakeApiClient()
        page = AuditLogPage(api_client)
        self.addCleanup(page.close)
        self.addCleanup(page.wait_for_load)

        page.load_page()
        page.wait_for_load()
        self.app.processEvents()

        self.assertIn("GAGAL DIMUAT", page.data_status.text())
        self.assertIn("auth.audit.read", page.data_status.text())
        self.assertIn("tidak dapat dimuat", page.empty_label.text())
        self.assertEqual(api_client.requested_page, (50, 0))

    def test_configuration_rejects_malformed_api_url(self):
        page = ConfigurationPage()
        self.addCleanup(page.close)
        page.api_url.setText("not-a-url")

        self.assertFalse(page.save_settings())
        self.assertIn("URL API", page.settings_notice.text())

    def test_configuration_saves_local_identity_appearance_and_window_size(self):
        stored_values = {}
        settings = Mock()
        settings.value.side_effect = lambda key, default=None: stored_values.get(
            key, default
        )
        settings.setValue.side_effect = (
            lambda key, value: stored_values.__setitem__(key, value)
        )
        settings.status.return_value = QSettings.Status.NoError
        with patch("main.settings_store", return_value=settings):
            window = MainWindow()
            self.addCleanup(window.close)
            page = window.page_by_key["configuration"]
            page.app_name.setText("Desktop Test")
            page.api_url.setText("https://api.example.test")
            page.theme.setCurrentIndex(page.theme.findData("dark"))
            page.window_size.setCurrentIndex(
                page.window_size.findData("1440x900")
            )
            page.primary_color.setText("#521020")
            page.accent_color.setText("#DDBB44")

            self.assertTrue(page.save_settings())

        self.assertEqual(stored_values["branding/app_name"], "Desktop Test")
        self.assertEqual(
            stored_values["api/base_url"], "https://api.example.test"
        )
        self.assertEqual(stored_values["appearance/theme"], "dark")
        self.assertEqual(
            stored_values["operational/window_size"], "1440x900"
        )
        self.assertEqual(stored_values["branding/primary_color"], "#521020")
        self.assertEqual(stored_values["branding/accent_color"], "#ddbb44")
        self.assertIn("berhasil disimpan", page.settings_notice.text())
        self.assertEqual(window.windowTitle(), "Desktop Test")
        self.assertEqual((window.width(), window.height()), (1440, 900))
        self.assertIn("#1E1E1E", window.styleSheet())

    def test_configuration_connection_probe_uses_unauthed_health_endpoint(self):
        page = ConfigurationPage()
        self.addCleanup(page.close)
        self.addCleanup(page.wait_for_connection_test)
        page.api_url.setText("https://api.example.test")

        with patch(
            "main.ApiClient._send",
            autospec=True,
            return_value={"status": "RUNNING"},
        ) as send:
            page.test_connection()
            page.wait_for_connection_test()
            self.app.processEvents()

        api_client = send.call_args.args[0]
        self.assertEqual(api_client.base_url, "https://api.example.test")
        self.assertEqual(send.call_args.args[1:], ("GET", "/health/live"))
        self.assertNotIn("access_token", send.call_args.kwargs)
        self.assertEqual(
            page.connection_status.text(),
            "Koneksi Universal API: TERHUBUNG",
        )

    def test_configuration_connection_failure_is_visible(self):
        page = ConfigurationPage()
        self.addCleanup(page.close)
        self.addCleanup(page.wait_for_connection_test)
        page.api_url.setText("https://api.example.test")

        with patch(
            "main.ApiClient._send",
            autospec=True,
            side_effect=ApiError("API tidak tersedia."),
        ):
            page.test_connection()
            page.wait_for_connection_test()
            self.app.processEvents()

        self.assertIn("GAGAL", page.connection_status.text())
        self.assertIn("API tidak tersedia", page.connection_status.text())

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


    def test_developer_dialogs_mask_password_and_do_not_assign_roles_implicitly(self):
        roles = [
            {
                "id": 1,
                "code": "developer_admin",
                "name": "Developer Admin",
                "is_active": True,
            },
            {
                "id": 2,
                "code": "developer_support",
                "name": "Developer Support",
                "is_active": True,
            },
        ]
        account_dialog = DeveloperAccountDialog(roles=roles)
        self.addCleanup(account_dialog.close)
        self.assertEqual(
            account_dialog.password.echoMode(),
            QLineEdit.EchoMode.Password,
        )
        self.assertEqual(account_dialog.selected_role_codes(), [])
        account_dialog.username.setText("new.developer")
        account_dialog.full_name.setText("New Developer")
        account_dialog.password.setText("initial-secure-password")
        account_dialog.confirm_password.setText("initial-secure-password")
        self.assertTrue(account_dialog.submit_form())
        self.assertEqual(account_dialog.values()["role_codes"], [])
        account_dialog.clear_sensitive_inputs()
        self.assertEqual(account_dialog.password.text(), "")
        self.assertEqual(account_dialog.confirm_password.text(), "")

        password_dialog = DeveloperPasswordDialog("new.developer")
        self.addCleanup(password_dialog.close)
        self.assertEqual(
            password_dialog.password.echoMode(),
            QLineEdit.EchoMode.Password,
        )
        password_dialog.password.setText("replacement-password")
        password_dialog.confirm_password.setText("replacement-password")
        self.assertTrue(password_dialog.submit_form())
        password_dialog.clear_passwords()
        self.assertEqual(password_dialog.password.text(), "")
        self.assertEqual(password_dialog.confirm_password.text(), "")

        selection = DeveloperSelectionDialog(
            "Role akun", roles, selected_codes=[]
        )
        self.addCleanup(selection.close)
        self.assertEqual(selection.selected_codes(), [])

    def test_developer_page_shows_api_accounts_and_updates_status(self):
        account = {
            "id": 17,
            "username": "developer.one",
            "full_name": "Developer One",
            "is_active": True,
            "roles": [],
            "created_at": "2026-11-17T00:00:00+00:00",
            "updated_at": "2026-11-17T00:00:00+00:00",
        }

        class FakeApiClient:
            def __init__(self):
                self.account = dict(account)
                self.status_calls = []

            def list_developer_accounts(self, limit, offset):
                return {
                    "items": [dict(self.account)],
                    "limit": limit,
                    "offset": offset,
                }

            def list_developer_roles(self):
                return [
                    {
                        "id": 1,
                        "code": "developer_admin",
                        "name": "Developer Admin",
                        "is_active": True,
                        "permissions": ["auth.developers.manage"],
                    },
                    {
                        "id": 2,
                        "code": "developer_support",
                        "name": "Developer Support",
                        "is_active": True,
                        "permissions": ["auth.audit.read"],
                    },
                ]

            def list_developer_permissions(self):
                return [
                    {
                        "code": "auth.developers.manage",
                        "name": "Manage developers",
                        "module": "auth",
                    }
                ]

            def set_developer_account_active(self, user_id, is_active):
                self.status_calls.append((user_id, is_active))
                self.account["is_active"] = is_active
                return dict(self.account)

        api_client = FakeApiClient()
        page = DeveloperPage(api_client)
        self.addCleanup(page.close)
        self.addCleanup(page.wait_for_load)

        page.load_page()
        page.wait_for_load()
        self.app.processEvents()

        self.assertEqual(page.table.rowCount(), 1)
        self.assertEqual(page.table.item(0, 2).text(), "developer.one")
        self.assertEqual(page.table.item(0, 4).text(), "—")
        self.assertEqual(page.table.item(0, 5).text(), "ACTIVE")
        self.assertIn("auth.developers.manage", page.capability_note.text())

        detail_text = []
        with patch.object(
            QMessageBox,
            "setText",
            new=lambda _dialog, text: detail_text.append(text),
        ), patch("main.QMessageBox.exec"):
            page.show_details(0, 0)
        self.assertIn("Username: developer.one", detail_text[0])
        self.assertNotIn("password", detail_text[0].lower())
        self.assertNotIn("token", detail_text[0].lower())

        page.table.selectRow(0)
        self.assertTrue(page.status_button.isEnabled())
        with patch(
            "main.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            page.toggle_status()
        page.wait_for_load()
        self.app.processEvents()
        page.wait_for_load()
        self.app.processEvents()

        self.assertEqual(api_client.status_calls, [(17, False)])
        self.assertEqual(page.table.item(0, 5).text(), "INACTIVE")

    def test_developer_role_manager_protects_system_admin_permissions(self):
        roles = [
            {
                "id": 1,
                "code": "developer_admin",
                "name": "Developer Admin",
                "is_active": True,
                "permissions": ["auth.roles.manage"],
            },
            {
                "id": 2,
                "code": "developer_support",
                "name": "Developer Support",
                "is_active": True,
                "permissions": ["auth.audit.read"],
            },
        ]
        dialog = DeveloperRoleManagerDialog(
            object(),
            roles,
            [
                {
                    "code": "auth.audit.read",
                    "name": "Read audit",
                    "module": "auth",
                }
            ],
        )
        self.addCleanup(dialog.close)

        dialog.table.selectRow(0)
        self.assertFalse(dialog.permissions_button.isEnabled())
        dialog.table.selectRow(1)
        self.assertTrue(dialog.permissions_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
