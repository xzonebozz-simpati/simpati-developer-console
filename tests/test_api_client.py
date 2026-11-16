import io
import json
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import patch

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
