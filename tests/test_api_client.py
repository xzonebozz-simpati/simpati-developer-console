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

    @patch("api_client.urlopen")
    def test_requests_identify_the_desktop_client(self, urlopen):
        urlopen.return_value = FakeResponse({"status": "RUNNING"})

        self.client.check_connection()

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.get_header("User-agent"), ApiClient.USER_AGENT
        )
        self.assertEqual(
            request.get_header("Accept"), "application/json"
        )

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
                "id": 18,
                "tenant_id": None,
                "actor_type": "DEVELOPER",
                "actor_id": 4,
                "action": "TENANT_CREATED",
                "entity": "Tenant",
                "entity_id": "31",
                "details": {"result": "success"},
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

    def test_developer_accounts_use_supported_list_endpoint_and_pagination(self):
        account = {
            "id": 8,
            "username": "developer.ops",
            "full_name": "Developer Ops",
            "is_active": True,
            "roles": ["developer_ops"],
            "created_at": "2026-11-17T00:00:00+00:00",
            "updated_at": "2026-11-17T01:00:00+00:00",
        }
        response = {"items": [account], "limit": 50, "offset": 100}
        with patch.object(
            self.client, "request", return_value=response
        ) as request:
            result = self.client.list_developer_accounts(50, 100)

        self.assertEqual(result, response)
        request.assert_called_once_with(
            "GET",
            "/auth/developers?limit=50&offset=100",
            authenticated=True,
        )

        with patch.object(
            self.client,
            "request",
            return_value={
                "items": [{**account, "password_hash": "never-return-this"}],
                "limit": 50,
                "offset": 0,
            },
        ):
            with self.assertRaisesRegex(ApiError, "akun Developer"):
                self.client.list_developer_accounts()

    def test_developer_creation_uses_empty_roles_by_default(self):
        response = {
            "id": 12,
            "username": "new.developer",
            "full_name": "New Developer",
            "is_active": True,
            "role_codes": [],
        }
        with patch.object(
            self.client, "request", return_value=response
        ) as request:
            result = self.client.create_developer_account(
                "New.Developer", "secure-initial-password", " New Developer "
            )

        request.assert_called_once_with(
            "POST",
            "/auth/developer/register",
            {
                "username": "new.developer",
                "password": "secure-initial-password",
                "full_name": "New Developer",
                "role_codes": [],
            },
            authenticated=True,
        )
        self.assertNotIn("password", result)

        with patch.object(self.client, "request") as request:
            with self.assertRaisesRegex(ApiError, "12–256"):
                self.client.create_developer_account(
                    "new.developer", "short", "New Developer"
                )
        request.assert_not_called()

    def test_developer_edit_status_password_reset_and_role_assignment_routes(self):
        account = {
            "id": 12,
            "username": "new.developer",
            "full_name": "Updated Developer",
            "is_active": True,
        }
        with patch.object(
            self.client, "request", return_value=account
        ) as request:
            self.client.update_developer_account(12, "Updated Developer")
        request.assert_called_once_with(
            "PATCH",
            "/auth/developers/12",
            {"full_name": "Updated Developer"},
            authenticated=True,
        )

        inactive_account = {**account, "is_active": False}
        with patch.object(
            self.client, "request", return_value=inactive_account
        ) as request:
            self.client.set_developer_account_active(12, False)
        request.assert_called_once_with(
            "PATCH",
            "/auth/developers/12",
            {"is_active": False},
            authenticated=True,
        )

        with patch.object(
            self.client, "request", return_value=account
        ) as request:
            result = self.client.reset_developer_password(
                12, "replacement-password"
            )
        request.assert_called_once_with(
            "PATCH",
            "/auth/developers/12",
            {"password": "replacement-password"},
            authenticated=True,
        )
        self.assertNotIn("password", result)

        with patch.object(
            self.client,
            "request",
            return_value={"user_id": 12, "role_codes": ["developer_ops"]},
        ) as request:
            self.client.assign_developer_roles(12, ["developer_ops"])
        request.assert_called_once_with(
            "PUT",
            "/auth/developers/12/roles",
            {"role_codes": ["developer_ops"]},
            authenticated=True,
        )

    def test_developer_role_and_permission_catalogs_use_role_permission_routes(self):
        roles = [
            {
                "id": 3,
                "code": "developer_ops",
                "name": "Operations",
                "description": None,
                "is_active": True,
                "permissions": ["tenants.read"],
            }
        ]
        permissions = [
            {
                "code": "tenants.read",
                "name": "Read tenants",
                "module": "tenants",
            }
        ]
        with patch.object(
            self.client, "request", return_value=roles
        ) as request:
            self.assertEqual(self.client.list_developer_roles(), roles)
        request.assert_called_once_with(
            "GET", "/auth/developer-roles", authenticated=True
        )

        with patch.object(
            self.client, "request", return_value=permissions
        ) as request:
            self.assertEqual(
                self.client.list_developer_permissions(), permissions
            )
        request.assert_called_once_with(
            "GET", "/auth/permissions", authenticated=True
        )

        created_role = {
            "id": 4,
            "code": "developer_viewer",
            "name": "Viewer",
            "permissions": ["tenants.read"],
        }
        with patch.object(
            self.client, "request", return_value=created_role
        ) as request:
            self.client.create_developer_role(
                "Developer_Viewer",
                "Viewer",
                permission_codes=["tenants.read"],
            )
        request.assert_called_once_with(
            "POST",
            "/auth/developer-roles",
            {
                "code": "developer_viewer",
                "name": "Viewer",
                "description": None,
                "permission_codes": ["tenants.read"],
            },
            authenticated=True,
        )

        updated_role = {
            "id": 4,
            "code": "developer_viewer",
            "name": "Auditor",
            "description": "Read only",
            "is_active": False,
        }
        with patch.object(
            self.client, "request", return_value=updated_role
        ) as request:
            self.client.update_developer_role(
                4, "Auditor", "Read only", False
            )
        request.assert_called_once_with(
            "PATCH",
            "/auth/developer-roles/4",
            {
                "name": "Auditor",
                "description": "Read only",
                "is_active": False,
            },
            authenticated=True,
        )

        with patch.object(
            self.client,
            "request",
            return_value={"role_id": 4, "permissions": []},
        ) as request:
            self.client.set_developer_role_permissions(4, [])
        request.assert_called_once_with(
            "PUT",
            "/auth/developer-roles/4/permissions",
            {"permission_codes": []},
            authenticated=True,
        )

    def test_reserved_developer_admin_role_cannot_be_created(self):
        with patch.object(self.client, "request") as request:
            with self.assertRaisesRegex(ApiError, "developer_admin"):
                self.client.create_developer_role(
                    "developer_admin", "Developer Admin"
                )
        request.assert_not_called()

    def test_audit_log_list_uses_api_pagination_and_optional_tenant_filter(self):
        log = {
            "id": 28,
            "tenant_id": 31,
            "actor_type": "TENANT",
            "actor_id": 9,
            "action": "MEMBER_UPDATED",
            "entity": "Member",
            "entity_id": "12",
            "details": {"result": "success"},
            "created_at": "2026-11-17T00:00:00+00:00",
        }
        response = {"items": [log], "limit": 50, "offset": 100}
        with patch.object(
            self.client, "request", return_value=response
        ) as request:
            result = self.client.list_audit_logs(limit=50, offset=100)

        self.assertEqual(result, response)
        request.assert_called_once_with(
            "GET",
            "/auth/audit-logs?limit=50&offset=100",
            authenticated=True,
        )

        with patch.object(
            self.client, "request", return_value=response
        ) as request:
            self.client.list_audit_logs(
                limit=50, offset=100, tenant_id=31
            )

        request.assert_called_once_with(
            "GET",
            "/auth/audit-logs?limit=50&offset=100&tenant_id=31",
            authenticated=True,
        )

    def test_audit_log_list_validates_pagination_and_record_shape(self):
        with patch.object(self.client, "request") as request:
            with self.assertRaisesRegex(ApiError, "Offset"):
                self.client.list_audit_logs(limit=50, offset=-1)
            with self.assertRaisesRegex(ApiError, "ID Tenant"):
                self.client.list_audit_logs(tenant_id=0)

        request.assert_not_called()
        with patch.object(
            self.client,
            "request",
            return_value={
                "items": [
                    {
                        "id": 1,
                        "tenant_id": None,
                        "actor_type": "INVALID",
                        "actor_id": None,
                        "action": "LOGIN",
                        "entity": "Session",
                        "entity_id": None,
                        "details": None,
                        "created_at": "2026-11-17T00:00:00+00:00",
                    }
                ],
                "limit": 50,
                "offset": 0,
            },
        ):
            with self.assertRaisesRegex(ApiError, "audit log"):
                self.client.list_audit_logs()

    def test_license_list_uses_tenant_filter_and_pagination_contract(self):
        license_id = "e536cdd2-9952-4c33-9caf-789df6477bbb"
        response = {
            "items": [{"id": license_id, "status": "ACTIVE"}],
            "limit": 50,
            "offset": 100,
        }
        with patch.object(
            self.client, "request", return_value=response
        ) as request:
            result = self.client.list_tenant_licenses(
                31, limit=50, offset=100, status_filter="ACTIVE"
            )

        self.assertEqual(result, response)
        request.assert_called_once_with(
            "GET",
            "/licenses?tenant_id=31&limit=50&offset=100&status_filter=ACTIVE",
            authenticated=True,
        )

    def test_license_catalog_methods_use_universal_api_contract(self):
        package_id = "58dd22e7-35a2-43c2-9d8c-e34c480d5908"
        package = {
            "id": package_id,
            "is_active": True,
            "package_modules": [
                {"module_code": "CORE", "is_mandatory": True}
            ],
        }
        with patch.object(
            self.client,
            "request",
            side_effect=[
                {
                    "items": [{"id": package_id}],
                    "limit": 100,
                    "offset": 0,
                },
                {"items": [{"module_code": "CORE", "is_active": True}]},
                package,
            ],
        ) as request:
            packages = self.client.list_license_packages()
            modules = self.client.list_license_modules()
            detail = self.client.get_license_package(package_id)

        self.assertEqual(packages["items"][0]["id"], package_id)
        self.assertEqual(modules[0]["module_code"], "CORE")
        self.assertEqual(detail, package)
        self.assertEqual(
            [item.args[1] for item in request.call_args_list],
            [
                "/licenses/packages?limit=100&offset=0",
                "/licenses/modules",
                f"/licenses/packages/{package_id}",
            ],
        )

    def test_license_creation_sends_capacity_and_returns_one_time_key(self):
        package_id = "58dd22e7-35a2-43c2-9d8c-e34c480d5908"
        license_id = "e536cdd2-9952-4c33-9caf-789df6477bbb"
        serial_key = "SMP-LIC-2026-0123456789ABCDEF-FEDCBA9876543210"
        response = {"license_id": license_id, "license_key": serial_key}
        with patch.object(
            self.client, "request", return_value=response
        ) as request:
            result = self.client.create_tenant_license(
                31,
                package_id,
                "2026-01-01T00:00:00Z",
                "2027-01-01T00:00:00Z",
                ["CORE", "SURVEI_GPS"],
                3,
                1000,
                25,
                12,
                10240,
            )

        self.assertEqual(result, response)
        request.assert_called_once_with(
            "POST",
            "/licenses",
            {
                "tenant_id": 31,
                "package_id": package_id,
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_until": "2027-01-01T00:00:00Z",
                "modules": ["CORE", "SURVEI_GPS"],
                "max_installations": 3,
                "grace_period_days": 7,
                "capacity": {
                    "max_members": 1000,
                    "max_accounts": 25,
                    "max_concurrent_users": 12,
                    "max_storage_mb": 10240,
                },
            },
            authenticated=True,
        )

    def test_license_mutations_use_tenant_scoped_endpoints(self):
        license_id = "e536cdd2-9952-4c33-9caf-789df6477bbb"
        with patch.object(
            self.client,
            "request",
            return_value={"status": "ACTIVE"},
        ) as request:
            self.client.extend_tenant_license(
                31, license_id, "2028-01-01T00:00:00Z", "Renewed"
            )
            self.client.update_tenant_license_validity(
                31,
                license_id,
                "2026-01-01T00:00:00Z",
                "2028-01-01T00:00:00Z",
                "Corrected dates",
                14,
            )
            self.client.update_tenant_license_status(
                31, license_id, "SUSPENDED", "Compliance review"
            )

        self.assertEqual(
            [
                (call.args[0], call.args[1], call.args[2])
                for call in request.call_args_list
            ],
            [
                (
                    "POST",
                    f"/licenses/{license_id}/extend?tenant_id=31",
                    {
                        "valid_until": "2028-01-01T00:00:00Z",
                        "reason": "Renewed",
                    },
                ),
                (
                    "PATCH",
                    f"/licenses/{license_id}/validity?tenant_id=31",
                    {
                        "valid_from": "2026-01-01T00:00:00Z",
                        "valid_until": "2028-01-01T00:00:00Z",
                        "reason": "Corrected dates",
                        "grace_period_days": 14,
                    },
                ),
                (
                    "PATCH",
                    f"/licenses/{license_id}/status?tenant_id=31",
                    {"status": "SUSPENDED", "reason": "Compliance review"},
                ),
            ],
        )

    def test_license_history_filters_all_tenant_audit_pages_by_license(self):
        license_id = "e536cdd2-9952-4c33-9caf-789df6477bbb"
        matching = {
            "entity": "License",
            "entity_id": license_id,
            "action": "LICENSE_STATUS_UPDATED",
        }
        unrelated = {
            "entity": "Tenant",
            "entity_id": "31",
            "action": "TENANT_UPDATED",
        }
        with patch.object(
            self.client,
            "list_audit_logs",
            side_effect=[
                {
                    "items": [dict(unrelated) for _ in range(100)],
                    "limit": 100,
                    "offset": 0,
                },
                {
                    "items": [dict(matching)],
                    "limit": 100,
                    "offset": 100,
                },
            ],
        ) as list_logs:
            result = self.client.list_license_history(31, license_id)

        self.assertEqual(result, [matching])
        self.assertEqual(
            list_logs.call_args_list,
            [
                call(limit=100, offset=0, tenant_id=31),
                call(limit=100, offset=100, tenant_id=31),
            ],
        )

    def test_license_inputs_reject_invalid_bounds_and_status(self):
        with patch.object(self.client, "request") as request:
            with self.assertRaisesRegex(ApiError, "ID Tenant"):
                self.client.list_tenant_licenses(0)
            with self.assertRaisesRegex(ApiError, "berakhir"):
                self.client.create_tenant_license(
                    31,
                    "58dd22e7-35a2-43c2-9d8c-e34c480d5908",
                    "2027-01-01T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                    ["CORE"],
                    1,
                    1,
                    1,
                    1,
                    500,
                )
            with self.assertRaisesRegex(ApiError, "Status lisensi"):
                self.client.update_tenant_license_status(
                    31,
                    "e536cdd2-9952-4c33-9caf-789df6477bbb",
                    "INACTIVE",
                    "Reason",
                )
        request.assert_not_called()

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

    def test_database_readiness_uses_official_public_endpoint(self):
        response = {"status": "ONLINE", "database": "CONNECTED"}
        with patch.object(self.client, "_send", return_value=response) as send:
            result = self.client.check_database_readiness()

        self.assertEqual(result, response)
        send.assert_called_once_with("GET", "/health/ready")

    def test_database_readiness_rejects_unconfirmed_database_status(self):
        with patch.object(
            self.client,
            "_send",
            return_value={"status": "ONLINE", "database": "DISCONNECTED"},
        ):
            with self.assertRaisesRegex(ApiError, "tidak mengonfirmasi"):
                self.client.check_database_readiness()

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
