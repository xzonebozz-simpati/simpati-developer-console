import io
import json
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import call, patch

from api_client import ApiClient, ApiError


class MemoryTokenStore:
    def __init__(self):
        self.tokens = {}

    def load(self, base_url):
        return self.tokens.get(base_url)

    def save(self, base_url, tokens):
        self.tokens[base_url] = {
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
        }

    def clear(self, base_url):
        self.tokens.pop(base_url, None)


class FakeResponse:
    status = 200

    def __init__(self, value):
        self.body = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.body


class ApiClientTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryTokenStore()
        self.client = ApiClient("https://api.example.test", self.store)

    def test_base_url_allows_local_http_but_rejects_remote_http(self):
        self.assertEqual(
            ApiClient.validate_base_url("http://127.0.0.1:8000"),
            "http://127.0.0.1:8000",
        )
        with self.assertRaisesRegex(ApiError, "Gunakan HTTPS"):
            ApiClient.validate_base_url("http://api.example.test")
        with self.assertRaisesRegex(ApiError, "URL API tidak valid"):
            ApiClient.validate_base_url("https://[")

    @patch("api_client.urlopen")
    def test_developer_login_uses_contract_and_saves_tokens(self, urlopen):
        urlopen.return_value = FakeResponse(
            {
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "token_type": "bearer",
                "expires_in": 900,
                "user": {
                    "actor_type": "developer",
                    "username": "dev",
                },
            }
        )

        user = self.client.developer_login("dev", "password")

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://api.example.test/auth/developer/login",
        )
        self.assertEqual(
            json.loads(request.data),
            {"username": "dev", "password": "password"},
        )
        self.assertEqual(user["username"], "dev")
        self.assertEqual(
            self.store.load(self.client.base_url),
            {"access_token": "access-1", "refresh_token": "refresh-1"},
        )

    @patch("api_client.urlopen")
    def test_unauthorized_request_rotates_tokens_and_retries_once(self, urlopen):
        urlopen.side_effect = [
            HTTPError(
                "https://api.example.test/auth/me",
                401,
                "Unauthorized",
                {},
                io.BytesIO(b'{"detail":"Invalid or expired access token."}'),
            ),
            FakeResponse(
                {
                    "access_token": "access-2",
                    "refresh_token": "refresh-2",
                    "user": {"actor_type": "developer"},
                }
            ),
            FakeResponse({"actor_type": "developer", "username": "dev"}),
        ]
        self.store.save(
            self.client.base_url,
            {"access_token": "access-1", "refresh_token": "refresh-1"},
        )

        user = self.client.current_user()

        refresh_request = urlopen.call_args_list[1].args[0]
        self.assertEqual(
            refresh_request.full_url,
            "https://api.example.test/auth/refresh",
        )
        self.assertEqual(
            json.loads(refresh_request.data),
            {"refresh_token": "refresh-1"},
        )
        retried_request = urlopen.call_args_list[2].args[0]
        self.assertEqual(
            retried_request.get_header("Authorization"), "Bearer access-2"
        )
        self.assertEqual(user["username"], "dev")
        self.assertEqual(
            self.store.load(self.client.base_url)["refresh_token"],
            "refresh-2",
        )

    @patch("api_client.urlopen")
    def test_logout_revokes_server_session_and_clears_local_tokens(self, urlopen):
        self.store.save(
            self.client.base_url,
            {"access_token": "access-1", "refresh_token": "refresh-1"},
        )
        urlopen.return_value = FakeResponse({"status": "logged_out"})

        self.client.logout()

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://api.example.test/auth/logout",
        )
        self.assertEqual(
            json.loads(request.data), {"refresh_token": "refresh-1"}
        )
        self.assertIsNone(self.store.load(self.client.base_url))

    @patch("api_client.urlopen")
    def test_password_change_uses_authenticated_contract_and_clears_tokens(
        self, urlopen
    ):
        self.store.save(
            self.client.base_url,
            {"access_token": "access-1", "refresh_token": "refresh-1"},
        )
        urlopen.return_value = FakeResponse({"status": "password_changed"})

        self.client.change_password("current-password", "new-password-123")

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url, "https://api.example.test/auth/password"
        )
        self.assertEqual(
            json.loads(request.data),
            {
                "current_password": "current-password",
                "new_password": "new-password-123",
            },
        )
        self.assertEqual(
            request.get_header("Authorization"), "Bearer access-1"
        )
        self.assertIsNone(self.store.load(self.client.base_url))

    def test_list_tenants_uses_paginated_tenant_contract(self):
        def tenant_record(item_id):
            return {
                "id": item_id,
                "code": f"TEN-{item_id}",
                "name": f"Tenant {item_id}",
                "organization_name": None,
                "status": "ACTIVE",
                "created_at": "2026-11-17T00:00:00+00:00",
            }

        first_page = {
            "items": [tenant_record(item_id) for item_id in range(100)],
            "total": 101,
            "limit": 100,
            "offset": 0,
        }
        second_page = {
            "items": [tenant_record(100)],
            "total": 101,
            "limit": 100,
            "offset": 100,
        }
        with patch.object(
            self.client, "request", side_effect=[first_page, second_page]
        ) as request:
            tenants = self.client.list_tenants()

        self.assertEqual(len(tenants), 101)
        request.assert_any_call(
            "GET", "/tenants?limit=100&offset=0", authenticated=True
        )
        request.assert_any_call(
            "GET", "/tenants?limit=100&offset=100", authenticated=True
        )

    def test_list_tenants_rejects_malformed_pagination_response(self):
        with patch.object(
            self.client,
            "request",
            return_value={"items": [], "total": 0, "offset": 0},
        ):
            with self.assertRaisesRegex(ApiError, "Metadata pagination"):
                self.client.list_tenants()

    def test_tenant_installations_validate_and_load_all_pages(self):
        def installation(item_id):
            return {
                "id": item_id,
                "tenant_id": 31,
                "installation_key": f"install-key-{item_id}",
                "device": {
                    "id": f"device-{item_id}",
                    "name": f"Device {item_id}",
                    "platform": "windows",
                    "app_version": "1.2.3",
                    "details": {"os_version": "Windows 11"},
                },
                "status": "ACTIVE",
                "first_seen_at": "2026-11-17T00:00:00+00:00",
                "last_seen_at": None,
                "created_at": "2026-11-17T00:00:00+00:00",
                "updated_at": "2026-11-17T00:00:00+00:00",
                "deleted_at": None,
            }

        pages = [
            {
                "items": [installation(1), installation(2)],
                "total": 3,
                "limit": 2,
                "offset": 0,
            },
            {
                "items": [installation(3)],
                "total": 3,
                "limit": 2,
                "offset": 2,
            },
        ]
        with patch.object(self.client, "INSTALLATION_PAGE_SIZE", 2), patch.object(
            self.client, "request", side_effect=pages
        ) as request:
            results = self.client.list_tenant_installations(31)

        self.assertEqual([item["id"] for item in results], [1, 2, 3])
        request.assert_any_call(
            "GET",
            "/tenants/31/installations?limit=2&offset=0",
            authenticated=True,
        )
        request.assert_any_call(
            "GET",
            "/tenants/31/installations?limit=2&offset=2",
            authenticated=True,
        )

    def test_global_installation_list_enriches_records_from_tenant_api(self):
        installation = {
            "id": 8,
            "tenant_id": 31,
            "device": {"id": "device-8"},
        }
        with patch.object(
            self.client,
            "list_tenants",
            return_value=[
                {"id": 31, "code": "TEN-31", "name": "Tenant One"}
            ],
        ), patch.object(
            self.client,
            "list_tenant_installations",
            return_value=[installation],
        ) as list_for_tenant:
            results = self.client.list_installations()

        list_for_tenant.assert_called_once_with(31)
        self.assertEqual(
            results,
            [
                {
                    **installation,
                    "tenant_code": "TEN-31",
                    "tenant_name": "Tenant One",
                }
            ],
        )

    def test_recycle_bin_installation_list_uses_backend_recycle_bin_route(self):
        installation = {
            "id": 9,
            "tenant_id": 31,
            "installation_key": "install-key-9",
            "device": {
                "id": "device-9",
                "name": None,
                "platform": "android",
                "app_version": None,
                "details": {},
            },
            "status": "REVOKED",
            "first_seen_at": "2026-11-17T00:00:00+00:00",
            "last_seen_at": None,
            "created_at": "2026-11-17T00:00:00+00:00",
            "updated_at": "2026-11-17T00:00:00+00:00",
            "deleted_at": "2026-11-17T01:00:00+00:00",
        }
        with patch.object(
            self.client,
            "request",
            return_value={
                "items": [installation],
                "total": 1,
                "limit": 100,
                "offset": 0,
            },
        ) as request:
            results = self.client.list_tenant_installations(
                31, include_deleted=True
            )

        self.assertEqual(results, [installation])
        request.assert_called_once_with(
            "GET",
            "/tenants/31/installations/recycle-bin?limit=100&offset=0",
            authenticated=True,
        )

    def test_all_installation_list_only_reads_recycle_bin_when_requested(self):
        tenants = [{"id": 31, "code": "TEN-31", "name": "Tenant One"}]
        with patch.object(
            self.client, "list_tenants", return_value=tenants
        ), patch.object(
            self.client,
            "list_tenant_installations",
            side_effect=[[], [{"id": 9, "tenant_id": 31}]],
        ) as list_for_tenant:
            results = self.client.list_installations(include_deleted=True)

        self.assertEqual(
            results,
            [
                {
                    "id": 9,
                    "tenant_id": 31,
                    "tenant_code": "TEN-31",
                    "tenant_name": "Tenant One",
                }
            ],
        )
        self.assertEqual(
            list_for_tenant.call_args_list,
            [call(31), call(31, include_deleted=True)],
        )

    def test_installation_detail_uses_tenant_scoped_endpoint(self):
        installation = {
            "id": 8,
            "tenant_id": 31,
            "installation_key": "do-not-display-key",
            "device": {
                "id": "device-8",
                "name": "Device",
                "platform": "windows",
                "app_version": None,
                "details": {},
            },
            "status": "ACTIVE",
            "first_seen_at": "2026-11-17T00:00:00+00:00",
            "last_seen_at": None,
            "created_at": "2026-11-17T00:00:00+00:00",
            "updated_at": "2026-11-17T00:00:00+00:00",
            "deleted_at": None,
        }
        with patch.object(
            self.client, "request", return_value=installation
        ) as request:
            result = self.client.get_tenant_installation(31, 8)

        request.assert_called_once_with(
            "GET",
            "/tenants/31/installations/8",
            authenticated=True,
        )
        self.assertEqual(result, installation)

    def test_list_modules_uses_catalog_endpoint_and_validates_records(self):
        modules = [
            {
                "id": 1,
                "code": "CORE",
                "name": "Core",
                "description": "Core platform",
                "is_active": True,
                "created_at": "2026-11-17T00:00:00+00:00",
                "updated_at": "2026-11-17T00:00:00+00:00",
            }
        ]
        with patch.object(
            self.client,
            "request",
            return_value={"items": modules},
        ) as request:
            self.assertEqual(self.client.list_modules(), modules)

        request.assert_called_once_with(
            "GET", "/modules?include_inactive=true", authenticated=True
        )

        with patch.object(
            self.client, "request", return_value={"items": [{"id": "bad"}]}
        ):
            with self.assertRaisesRegex(ApiError, "detail modul"):
                self.client.list_modules()

    def test_module_detail_uses_catalog_detail_endpoint(self):
        module = {
            "id": 5,
            "code": "UMKM",
            "name": "UMKM",
            "description": None,
            "is_active": False,
            "created_at": "2026-11-17T00:00:00+00:00",
            "updated_at": "2026-11-17T01:00:00+00:00",
        }
        with patch.object(
            self.client, "request", return_value=module
        ) as request:
            result = self.client.get_module(5)

        request.assert_called_once_with(
            "GET", "/modules/5", authenticated=True
        )
        self.assertEqual(result, module)

    def test_module_creation_uses_catalog_contract(self):
        module = {
            "id": 42,
            "code": "CUSTOM",
            "name": "Custom Module",
            "description": "Description",
            "is_active": True,
            "created_at": "2026-11-17T00:00:00+00:00",
            "updated_at": "2026-11-17T00:00:00+00:00",
        }
        with patch.object(
            self.client, "request", return_value=module
        ) as request:
            result = self.client.create_module(
                "custom", " Custom Module ", " Description "
            )

        request.assert_called_once_with(
            "POST",
            "/modules",
            {
                "code": "CUSTOM",
                "name": "Custom Module",
                "description": "Description",
                "is_active": True,
            },
            authenticated=True,
        )
        self.assertEqual(result, module)

    def test_module_status_and_metadata_use_patch_contracts(self):
        active_module = {
            "id": 4,
            "code": "UMKM",
            "name": "UMKM",
            "description": None,
            "is_active": True,
            "created_at": "2026-11-17T00:00:00+00:00",
            "updated_at": "2026-11-17T01:00:00+00:00",
        }
        with patch.object(
            self.client, "request", return_value=active_module
        ) as request:
            self.client.set_module_active(4, True)

        request.assert_called_once_with(
            "PATCH",
            "/modules/4",
            {"is_active": True},
            authenticated=True,
        )

        updated_module = {
            **active_module,
            "name": "UMKM Suite",
            "description": "Updated",
        }
        with patch.object(
            self.client, "request", return_value=updated_module
        ) as request:
            self.client.update_module(4, "UMKM Suite", "Updated")

        request.assert_called_once_with(
            "PATCH",
            "/modules/4",
            {"name": "UMKM Suite", "description": "Updated"},
            authenticated=True,
        )

    def test_module_catalog_rejects_reserved_core_creation(self):
        with patch.object(self.client, "request") as request:
            with self.assertRaisesRegex(ApiError, "CORE"):
                self.client.create_module("core", "Core")

        request.assert_not_called()

    def test_module_usage_is_combined_from_tenant_module_endpoints(self):
        tenants = [
            {"id": 31, "code": "TEN-31", "name": "Tenant One"},
            {"id": 32, "code": "TEN-32", "name": "Tenant Two"},
        ]
        module_assignment = {
            "code": "UMKM",
            "is_assigned": True,
            "is_enabled": True,
            "status": "ENABLED",
        }
        with patch.object(
            self.client, "list_tenants", return_value=tenants
        ), patch.object(
            self.client,
            "list_tenant_modules",
            side_effect=[
                [module_assignment],
                [
                    {
                        **module_assignment,
                        "is_enabled": False,
                        "status": "DISABLED",
                    }
                ],
            ],
        ) as list_for_tenant:
            usage = self.client.list_module_tenant_usage("umkm")

        self.assertEqual(
            usage,
            [
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
                    "is_assigned": True,
                    "is_enabled": False,
                    "status": "DISABLED",
                },
            ],
        )
        self.assertEqual(
            list_for_tenant.call_args_list,
            [call(31), call(32)],
        )

    def test_installation_count_uses_paged_collection_total(self):
        with patch.object(
            self.client,
            "request",
            return_value={
                "items": [{"id": 8}],
                "total": 17,
                "limit": 1,
                "offset": 0,
            },
        ) as request:
            total = self.client.count_tenant_installations(31)

        self.assertEqual(total, 17)
        request.assert_called_once_with(
            "GET",
            "/tenants/31/installations?limit=1&offset=0",
            authenticated=True,
        )

    def test_recent_audit_logs_use_latest_page_and_validate_metadata(self):
        logs = [
            {
                "action": "TENANT_CREATED",
                "entity": "Tenant",
                "created_at": "2026-11-17T00:00:00+00:00",
            }
        ]
        with patch.object(
            self.client,
            "request",
            return_value={"items": logs, "limit": 5, "offset": 0},
        ) as request:
            self.assertEqual(self.client.list_recent_audit_logs(), logs)

        request.assert_called_once_with(
            "GET", "/auth/audit-logs?limit=5&offset=0", authenticated=True
        )

        with patch.object(
            self.client,
            "request",
            return_value={"items": logs, "limit": 10, "offset": 0},
        ):
            with self.assertRaisesRegex(ApiError, "audit log"):
                self.client.list_recent_audit_logs()

    def test_tenant_module_listing_uses_supported_assignment_endpoint(self):
        module = {
            "id": 2,
            "code": "SURVEI_GPS",
            "name": "Survei GPS",
            "is_active": True,
            "is_assigned": False,
            "is_enabled": False,
            "status": "UNASSIGNED",
        }
        with patch.object(
            self.client,
            "request",
            return_value={"tenant_id": 31, "items": [module]},
        ) as request:
            self.assertEqual(self.client.list_tenant_modules(31), [module])

        request.assert_called_once_with(
            "GET", "/tenants/31/modules", authenticated=True
        )

    def test_tenant_module_assignment_uses_supported_mutation_contracts(self):
        with patch.object(
            self.client,
            "request",
            return_value={
                "tenant_id": 31,
                "module": {"code": "SURVEI_GPS"},
                "is_assigned": True,
                "is_enabled": True,
                "status": "ENABLED",
            },
        ) as request:
            self.client.enable_tenant_module(31, "survei_gps")

        request.assert_called_once_with(
            "POST",
            "/tenants/31/modules",
            {"module_code": "SURVEI_GPS"},
            authenticated=True,
        )

        with patch.object(
            self.client,
            "request",
            return_value={
                "tenant_id": 31,
                "module_code": "SURVEI_GPS",
                "is_assigned": True,
                "is_enabled": False,
                "status": "DISABLED",
            },
        ) as request:
            self.client.disable_tenant_module(31, "SURVEI_GPS")

        request.assert_called_once_with(
            "DELETE",
            "/tenants/31/modules/SURVEI_GPS",
            authenticated=True,
        )

    def test_tenant_module_mutation_rejects_invalid_code_before_request(self):
        with patch.object(self.client, "request") as request:
            with self.assertRaisesRegex(ApiError, "Kode modul"):
                self.client.enable_tenant_module(31, "../bad")

        request.assert_not_called()

    def test_create_tenant_uses_contract_without_status_field(self):
        response = {
            "id": 31,
            "code": "TEN-31",
            "name": "Tenant Test",
            "organization_name": "Org Test",
            "status": "ACTIVE",
        }
        with patch.object(self.client, "request", return_value=response) as request:
            tenant = self.client.create_tenant(
                "TEN-31", "Tenant Test", "Org Test"
            )

        request.assert_called_once_with(
            "POST",
            "/tenants",
            {
                "code": "TEN-31",
                "name": "Tenant Test",
                "organization_name": "Org Test",
            },
            authenticated=True,
        )
        self.assertEqual(tenant, response)

    def test_update_tenant_uses_identity_patch_contract(self):
        response = {"id": 31}
        with patch.object(self.client, "request", return_value=response) as request:
            self.client.update_tenant(31, "TEN-31", "Tenant Test", "Org Test")

        request.assert_called_once_with(
            "PATCH",
            "/tenants/31",
            {
                "code": "TEN-31",
                "name": "Tenant Test",
                "organization_name": "Org Test",
            },
            authenticated=True,
        )

    def test_status_change_uses_status_and_reason_contract(self):
        response = {"id": 31, "status": "RESTRICTED"}
        with patch.object(self.client, "request", return_value=response) as request:
            self.client.change_tenant_status(
                31, "RESTRICTED", "Compliance request"
            )

        request.assert_called_once_with(
            "PATCH",
            "/tenants/31/status",
            {
                "status": "RESTRICTED",
                "reason": "Compliance request",
            },
            authenticated=True,
        )

    def test_status_change_rejects_unsupported_status_and_short_reason(self):
        with patch.object(self.client, "request") as request:
            with self.assertRaisesRegex(ApiError, "Kode status"):
                self.client.change_tenant_status(31, "SUSPENDED", "Valid reason")
            with self.assertRaisesRegex(ApiError, "3–1000 karakter"):
                self.client.change_tenant_status(31, "INACTIVE", "No")

        request.assert_not_called()

    @patch("api_client.urlopen", side_effect=URLError("network unavailable"))
    def test_connection_failure_is_reported(self, _urlopen):
        with self.assertRaisesRegex(ApiError, "Tidak dapat terhubung"):
            self.client.check_connection()

    @patch("api_client.urlopen")
    def test_expired_refresh_token_clears_session(self, urlopen):
        urlopen.side_effect = [
            HTTPError(
                "https://api.example.test/auth/me",
                401,
                "Unauthorized",
                {},
                io.BytesIO(b'{"detail":"Invalid or expired access token."}'),
            ),
            HTTPError(
                "https://api.example.test/auth/refresh",
                401,
                "Unauthorized",
                {},
                io.BytesIO(b'{"detail":"Invalid or expired refresh token."}'),
            ),
        ]
        self.store.save(
            self.client.base_url,
            {"access_token": "access-1", "refresh_token": "refresh-1"},
        )

        with self.assertRaisesRegex(ApiError, "Sesi telah kedaluwarsa"):
            self.client.current_user()

        self.assertIsNone(self.store.load(self.client.base_url))

    @patch("api_client.urlopen", side_effect=URLError("network unavailable"))
    def test_connection_loss_does_not_delete_saved_tokens(self, _urlopen):
        tokens = {"access_token": "access-1", "refresh_token": "refresh-1"}
        self.store.save(self.client.base_url, tokens)

        with self.assertRaises(ApiError):
            self.client.current_user()

        self.assertEqual(self.store.load(self.client.base_url), tokens)


if __name__ == "__main__":
    unittest.main()
