import os
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault("SESSION_SECRET", "test-session-secret")
os.environ.setdefault("DEVELOPER_USERNAME", "developer")
os.environ.setdefault("DEVELOPER_PASSWORD", "test-password")

from starlette.requests import Request

import app


TENANTS = [{"id": 42, "name": "Tenant Uji", "code": "UJI"}]
PACKAGE_ID = "81a98f72-9d76-40b1-a3df-81521bc01efb"
PACKAGES = [{"id": PACKAGE_ID, "package_name": "Paket Uji"}]
MODULES = [{"code": "CORE", "name": "Core"}]


def authenticated_request():
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/licenses",
        "headers": [],
        "session": {
            "developer_authenticated": True,
            "csrf_token": "csrf-test-token",
        },
    })


class LicenseValidationTests(unittest.TestCase):
    def test_rejects_end_date_before_start_date(self):
        with self.assertRaisesRegex(ValueError, "setelah tanggal mulai"):
            app.validate_license_dates(
                "2026-02-01T00:00",
                "2026-01-31T23:59",
            )

    def test_issue_validation_matches_universal_api_catalog(self):
        data = {
            "tenant_id": "42",
            "package_id": PACKAGE_ID,
            "valid_from": "2026-01-01T00:00",
            "valid_until": "2027-01-01T00:00",
            "modules": ["CORE"],
            "grace_period_days": "7",
            "max_installations": "1",
            "max_members": "50000",
            "max_accounts": "200",
            "max_concurrent_users": "25",
            "max_storage_mb": "20480",
        }

        errors, normalized = app.validate_license_issue(
            data,
            TENANTS,
            PACKAGES,
            MODULES,
        )

        self.assertEqual(errors, [])
        self.assertEqual(normalized["tenant_id"], 42)
        self.assertEqual(normalized["modules"], ["CORE"])
        self.assertEqual(normalized["values"]["max_storage_mb"], 20480)

    def test_rejects_unknown_module_and_storage_below_api_minimum(self):
        data = {
            "tenant_id": "42",
            "package_id": PACKAGE_ID,
            "valid_from": "2026-01-01T00:00",
            "valid_until": "2027-01-01T00:00",
            "modules": ["NOT_IN_CATALOG"],
            "grace_period_days": "7",
            "max_installations": "1",
            "max_members": "50000",
            "max_accounts": "200",
            "max_concurrent_users": "25",
            "max_storage_mb": "499",
        }

        errors, _ = app.validate_license_issue(
            data,
            TENANTS,
            PACKAGES,
            MODULES,
        )

        self.assertTrue(any("modul tidak valid" in error for error in errors))
        self.assertTrue(any("minimal 500" in error for error in errors))


class LicenseRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_universal_api_refreshes_rotating_tokens_before_request(self):
        request = authenticated_request()
        session_key = "api-session-test"
        request.session["universal_api_session"] = session_key
        app.UNIVERSAL_API_SESSIONS[session_key] = {
            "access_token": "expired-access",
            "refresh_token": "old-refresh",
            "expires_at": 0,
            "session_expires_at": app.time.monotonic() + 60,
        }
        try:
            with patch.object(
                app,
                "universal_http_request",
                new=AsyncMock(side_effect=[
                    {
                        "access_token": "fresh-access",
                        "refresh_token": "new-refresh",
                        "expires_in": 300,
                    },
                    [{"id": 42}],
                ]),
            ) as http_request:
                result = await app.universal_api_request(
                    request,
                    "GET",
                    "/tenants",
                )
        finally:
            app.UNIVERSAL_API_SESSIONS.pop(session_key, None)

        self.assertEqual(result, [{"id": 42}])
        self.assertEqual(http_request.await_args_list[0].args[:2], (
            "POST",
            "/auth/refresh",
        ))
        self.assertEqual(
            http_request.await_args_list[1].kwargs["access_token"],
            "fresh-access",
        )

    async def test_list_loads_licenses_for_each_tenant(self):
        request = authenticated_request()

        async def api_response(_request, _method, path, params=None, data=None):
            if path == "/tenants":
                return [{"id": 42, "name": "Tenant A"}, {"id": 73, "name": "Tenant B"}]
            if params["tenant_id"] == 42:
                return [{"id": "license-a", "license_key": "KEY-A"}]
            return [{"id": "license-b", "license_key": "KEY-B"}]

        with patch.object(
            app,
            "universal_api_request",
            new=AsyncMock(side_effect=api_response),
        ) as api_request:
            tenants, licenses = await app.get_all_tenant_licenses(request)

        self.assertEqual(len(tenants), 2)
        self.assertEqual(
            [(item["tenant_id"], item["tenant_name"]) for item in licenses],
            [(42, "Tenant A"), (73, "Tenant B")],
        )
        self.assertEqual(api_request.await_count, 3)

    async def test_new_license_page_displays_api_catalog_choices(self):
        request = authenticated_request()
        with patch.object(
            app,
            "license_form_catalog",
            new=AsyncMock(return_value=(TENANTS, PACKAGES, MODULES)),
        ):
            response = await app.license_new_page(request)

        page = response.body.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Tenant Uji", page)
        self.assertIn("Paket Uji", page)
        self.assertIn('value="CORE"', page)
        self.assertIn('name="max_concurrent_users"', page)
        self.assertIn('name="max_storage_mb"', page)

    async def test_issue_posts_license_manager_contract_through_universal_api(self):
        request = authenticated_request()
        created_id = str(uuid4())
        with (
            patch.object(
                app,
                "license_form_catalog",
                new=AsyncMock(return_value=(TENANTS, PACKAGES, MODULES)),
            ),
            patch.object(
                app,
                "universal_api_request",
                new=AsyncMock(return_value={"id": created_id}),
            ) as api_request,
        ):
            response = await app.license_create(
                request,
                csrf_token="csrf-test-token",
                tenant_id="42",
                package_id=PACKAGE_ID,
                valid_from="2026-01-01T00:00",
                valid_until="2027-01-01T00:00",
                grace_period_days="7",
                max_installations="1",
                modules=["CORE"],
                max_members="50",
                max_accounts="20",
                max_concurrent_users="5",
                max_storage_mb="1000",
                notes="Uji penerbitan",
            )

        self.assertEqual(response.status_code, 303)
        self.assertIn(created_id, response.headers["location"])
        self.assertEqual(api_request.await_args.args[1:3], ("POST", "/licenses"))
        payload = api_request.await_args.kwargs["data"]
        self.assertEqual(payload["tenant_id"], 42)
        self.assertEqual(payload["package_id"], PACKAGE_ID)
        self.assertEqual(payload["modules"], ["CORE"])
        self.assertNotIn("levels", payload)
        self.assertEqual(
            payload["capacity"],
            {
                "max_members": 50,
                "max_accounts": 20,
                "max_concurrent_users": 5,
                "max_storage_mb": 1000,
            },
        )
        self.assertEqual(payload["notes"], "Uji penerbitan")

    async def test_status_change_sends_reasoned_universal_api_request(self):
        request = authenticated_request()
        license_id = str(uuid4())
        with patch.object(
            app,
            "universal_api_request",
            new=AsyncMock(return_value={}),
        ) as api_request:
            response = await app.license_change_status(
                request,
                license_id,
                tenant_id=42,
                new_status="SUSPENDED",
                reason="Permintaan pemilik Tenant",
                csrf_token="csrf-test-token",
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(api_request.await_args.args[1:3], (
            "PATCH",
            f"/licenses/{license_id}/status",
        ))
        self.assertEqual(
            api_request.await_args.kwargs["data"],
            {"status": "SUSPENDED", "reason": "Permintaan pemilik Tenant"},
        )

    async def test_renewal_must_extend_beyond_current_expiration(self):
        request = authenticated_request()
        license_id = str(uuid4())
        with (
            patch.object(
                app,
                "get_license_detail",
                new=AsyncMock(return_value={
                    "valid_until": "2027-01-01T00:00:00+00:00",
                }),
            ),
            patch.object(
                app,
                "universal_api_request",
                new=AsyncMock(),
            ) as api_request,
        ):
            response = await app.license_extend(
                request,
                license_id,
                tenant_id=42,
                valid_until="2026-12-31T23:59",
                reason="Perpanjangan tahunan",
                csrf_token="csrf-test-token",
            )

        self.assertEqual(response.status_code, 303)
        self.assertIn(
            "Tanggal%20perpanjangan%20harus%20setelah",
            response.headers["location"],
        )
        api_request.assert_not_awaited()

    async def test_detail_renders_serial_key_and_license_history(self):
        request = authenticated_request()
        license_id = str(uuid4())
        license_data = {
            "id": license_id,
            "license_key": "SIMPATI-ACTIVATION-KEY",
            "status": "ACTIVE",
            "computed_status": "ACTIVE",
            "customer_name": "Tenant Uji",
            "package_name": "Paket Uji",
            "valid_from": "2026-01-01T00:00:00+00:00",
            "valid_until": "2027-01-01T00:00:00+00:00",
            "modules": ["CORE"],
            "capacity": {"max_members": 50},
            "history": [{
                "action": "ISSUED",
                "created_at": "2026-01-01T00:00:00+00:00",
                "remarks": "Uji",
            }],
        }
        with patch.object(
            app,
            "get_license_detail",
            new=AsyncMock(return_value=license_data),
        ):
            response = await app.license_detail_page(
                request,
                license_id,
                tenant_id=42,
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("SIMPATI-ACTIVATION-KEY", response.body.decode())
        self.assertIn("ISSUED", response.body.decode())
