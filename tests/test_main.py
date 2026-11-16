import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTableWidgetItem

from main import ConfigurationPage, DataPage, FormDialog, MainWindow


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


if __name__ == "__main__":
    unittest.main()
