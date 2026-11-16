import hashlib
import ipaddress
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import keyring
from keyring.errors import KeyringError


class ApiError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class SecureTokenStore:
    SERVICE_NAME = "SIMPATI Developer Desktop"

    @classmethod
    def _account(cls, base_url):
        return hashlib.sha256(base_url.rstrip("/").encode("utf-8")).hexdigest()

    def load(self, base_url):
        try:
            serialized = keyring.get_password(
                self.SERVICE_NAME, self._account(base_url)
            )
        except KeyringError as exc:
            raise ApiError(
                "Penyimpanan kredensial aman tidak tersedia: "
                f"{type(exc).__name__}."
            ) from exc
        if serialized is None:
            return None
        try:
            tokens = json.loads(serialized)
        except json.JSONDecodeError as exc:
            raise ApiError(
                "Token tersimpan tidak dapat dibaca. Hapus kredensial "
                "aplikasi dari pengelola kredensial sistem."
            ) from exc
        if not isinstance(tokens, dict) or not all(
            isinstance(tokens.get(name), str) and tokens[name]
            for name in ("access_token", "refresh_token")
        ):
            raise ApiError(
                "Format token tersimpan tidak valid. Hapus kredensial "
                "aplikasi dari pengelola kredensial sistem."
            )
        return tokens

    def save(self, base_url, tokens):
        if not all(
            isinstance(tokens.get(name), str) and tokens[name]
            for name in ("access_token", "refresh_token")
        ):
            raise ApiError("Respons autentikasi tidak berisi token yang valid.")
        try:
            keyring.set_password(
                self.SERVICE_NAME,
                self._account(base_url),
                json.dumps(
                    {
                        "access_token": tokens["access_token"],
                        "refresh_token": tokens["refresh_token"],
                    }
                ),
            )
        except KeyringError as exc:
            raise ApiError(
                "Token tidak dapat disimpan ke penyimpanan kredensial aman: "
                f"{type(exc).__name__}."
            ) from exc

    def clear(self, base_url):
        try:
            keyring.delete_password(
                self.SERVICE_NAME, self._account(base_url)
            )
        except keyring.errors.PasswordDeleteError:
            return
        except KeyringError as exc:
            raise ApiError(
                "Token tidak dapat dihapus dari penyimpanan kredensial aman: "
                f"{type(exc).__name__}."
            ) from exc


class ApiClient:
    TIMEOUT_SECONDS = 8
    API_SERVICE_PATH = "/health/live"
    TENANT_PAGE_SIZE = 100

    def __init__(self, base_url="", token_store=None):
        self.token_store = token_store or SecureTokenStore()
        self.set_base_url(base_url)

    @staticmethod
    def validate_base_url(base_url):
        try:
            parsed_url = urlsplit(base_url.strip())
            parsed_url.port
        except ValueError as exc:
            raise ApiError("URL API tidak valid.") from exc
        if (
            parsed_url.scheme not in ("http", "https")
            or not parsed_url.netloc
            or not parsed_url.hostname
            or parsed_url.username
            or parsed_url.password
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ApiError(
                "URL API harus berupa alamat http:// atau https:// yang valid."
            )
        if any(character.isspace() for character in base_url):
            raise ApiError("URL API tidak boleh berisi spasi.")
        if parsed_url.scheme == "http":
            try:
                loopback = ipaddress.ip_address(parsed_url.hostname).is_loopback
            except ValueError:
                loopback = parsed_url.hostname.casefold() == "localhost"
            if not loopback:
                raise ApiError(
                    "Gunakan HTTPS untuk API jaringan; HTTP hanya "
                    "diizinkan untuk localhost."
                )
        return base_url.strip().rstrip("/")

    def set_base_url(self, base_url):
        if base_url.strip():
            self.base_url = self.validate_base_url(base_url)
        else:
            self.base_url = ""

    def _require_base_url(self):
        if not self.base_url:
            raise ApiError("Alamat Universal API belum dikonfigurasi.")

    def _send(self, method, path, payload=None, access_token=None):
        self._require_base_url()
        body = (
            json.dumps(payload).encode("utf-8")
            if payload is not None
            else None
        )
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        request = Request(
            self.base_url + "/" + path.lstrip("/"),
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.TIMEOUT_SECONDS) as response:
                raw_response = response.read()
                status_code = response.status
        except HTTPError as exc:
            raw_response = exc.read()
            status_code = exc.code
        except (URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", None)
            description = (
                str(reason) if reason else type(exc).__name__
            )
            raise ApiError(
                f"Tidak dapat terhubung ke Universal API: {description}."
            ) from exc

        if not raw_response:
            response_data = {}
        else:
            try:
                response_data = json.loads(raw_response.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ApiError(
                    "Universal API mengirim respons yang bukan JSON valid.",
                    status_code,
                ) from exc

        if status_code < 200 or status_code >= 300:
            detail = (
                response_data.get("detail")
                if isinstance(response_data, dict)
                else None
            )
            if not isinstance(detail, str) or not detail.strip():
                detail = f"Permintaan API gagal (HTTP {status_code})."
            raise ApiError(detail, status_code)
        if not isinstance(response_data, dict):
            raise ApiError(
                "Universal API mengirim objek respons yang tidak valid.",
                status_code,
            )
        return response_data

    def check_connection(self):
        result = self._send("GET", self.API_SERVICE_PATH)
        if result.get("status") != "RUNNING":
            raise ApiError("Universal API merespons, tetapi belum berstatus aktif.")
        return result

    def list_tenants(self):
        tenants = []
        offset = 0
        total = None
        while total is None or offset < total:
            limit = self.TENANT_PAGE_SIZE
            query = urlencode({"limit": limit, "offset": offset})
            page = self.request(
                "GET", f"/tenants?{query}", authenticated=True
            )
            items = page.get("items")
            page_total = page.get("total")
            if (
                not isinstance(items, list)
                or type(page_total) is not int
                or page_total < 0
                or len(items) > limit
                or offset + len(items) > page_total
                or any(not isinstance(tenant, dict) for tenant in items)
                or any(
                    type(tenant.get("id")) is not int
                    or not isinstance(tenant.get("code"), str)
                    or not isinstance(tenant.get("name"), str)
                    or not isinstance(tenant.get("status"), str)
                    or not isinstance(tenant.get("created_at"), str)
                    or (
                        tenant.get("organization_name") is not None
                        and not isinstance(
                            tenant.get("organization_name"), str
                        )
                    )
                    for tenant in items
                )
            ):
                raise ApiError(
                    "Respons daftar Tenant dari Universal API tidak valid."
                )
            if page.get("limit") != limit or page.get("offset") != offset:
                raise ApiError(
                    "Metadata pagination daftar Tenant dari API tidak valid."
                )
            if total is not None and page_total != total:
                raise ApiError(
                    "Jumlah Tenant berubah saat data sedang dimuat. "
                    "Muat ulang daftar Tenant."
                )
            total = page_total
            if not items:
                if offset < total:
                    raise ApiError(
                        "Universal API mengembalikan halaman Tenant kosong "
                        "sebelum seluruh data termuat."
                    )
                break
            tenants.extend(items)
            offset += len(items)
        return tenants

    @staticmethod
    def _tenant_identity_payload(code, name, organization_name):
        payload = {"code": code, "name": name}
        if organization_name:
            payload["organization_name"] = organization_name
        return payload

    def create_tenant(self, code, name, organization_name=None):
        payload = self._tenant_identity_payload(
            code, name, organization_name
        )
        response = self.request(
            "POST", "/tenants", payload, authenticated=True
        )
        if not isinstance(response, dict) or type(response.get("id")) is not int:
            raise ApiError(
                "Respons pembuatan Tenant dari Universal API tidak valid."
            )
        return response

    def update_tenant(self, tenant_id, code, name, organization_name=None):
        if type(tenant_id) is not int or tenant_id < 1:
            raise ApiError("ID Tenant tidak valid.")
        payload = self._tenant_identity_payload(
            code, name, organization_name
        )
        response = self.request(
            "PATCH",
            f"/tenants/{tenant_id}",
            payload,
            authenticated=True,
        )
        if (
            not isinstance(response, dict)
            or type(response.get("id")) is not int
            or response["id"] != tenant_id
        ):
            raise ApiError(
                "Respons perubahan Tenant dari Universal API tidak valid."
            )
        return response

    def change_tenant_status(self, tenant_id, status, reason):
        if type(tenant_id) is not int or tenant_id < 1:
            raise ApiError("ID Tenant tidak valid.")
        if status not in ("ACTIVE", "INACTIVE", "RESTRICTED"):
            raise ApiError("Kode status Tenant tidak valid.")
        if not isinstance(reason, str):
            raise ApiError("Alasan perubahan status tidak valid.")
        reason = reason.strip()
        if not 3 <= len(reason) <= 1000:
            raise ApiError(
                "Alasan perubahan status harus terdiri dari 3–1000 karakter."
            )
        response = self.request(
            "PATCH",
            f"/tenants/{tenant_id}/status",
            {"status": status, "reason": reason},
            authenticated=True,
        )
        if (
            not isinstance(response, dict)
            or type(response.get("id")) is not int
            or response["id"] != tenant_id
            or response.get("status") != status
        ):
            raise ApiError(
                "Respons perubahan status Tenant dari Universal API tidak valid."
            )
        return response

    def _load_tokens(self):
        self._require_base_url()
        return self.token_store.load(self.base_url)

    def _save_tokens(self, response):
        self.token_store.save(self.base_url, response)

    def _refresh_tokens(self, refresh_token):
        try:
            response = self._send(
                "POST",
                "/auth/refresh",
                {"refresh_token": refresh_token},
            )
        except ApiError as exc:
            if exc.status_code == 401:
                self.token_store.clear(self.base_url)
                raise ApiError(
                    "Sesi telah kedaluwarsa. Silakan login kembali.", 401
                ) from exc
            raise
        self._save_tokens(response)
        return response["access_token"]

    def request(self, method, path, payload=None, authenticated=False):
        tokens = self._load_tokens() if authenticated else None
        try:
            return self._send(
                method,
                path,
                payload,
                tokens["access_token"] if tokens else None,
            )
        except ApiError as exc:
            if not authenticated or exc.status_code != 401 or not tokens:
                raise
        access_token = self._refresh_tokens(tokens["refresh_token"])
        return self._send(method, path, payload, access_token)

    def developer_login(self, username, password):
        response = self._send(
            "POST",
            "/auth/developer/login",
            {"username": username, "password": password},
        )
        user = response.get("user")
        if (
            not isinstance(user, dict)
            or str(user.get("actor_type", "")).casefold() != "developer"
        ):
            raise ApiError(
                "Endpoint login tidak mengembalikan akun Developer yang valid."
            )
        self._save_tokens(response)
        return user

    def current_user(self):
        tokens = self._load_tokens()
        if tokens is None:
            return None
        user = self.request("GET", "/auth/me", authenticated=True)
        if str(user.get("actor_type", "")).casefold() != "developer":
            self.token_store.clear(self.base_url)
            raise ApiError("Akun yang tersimpan bukan akun Developer.")
        return user

    def change_password(self, current_password, new_password):
        response = self.request(
            "POST",
            "/auth/password",
            {
                "current_password": current_password,
                "new_password": new_password,
            },
            authenticated=True,
        )
        self.token_store.clear(self.base_url)
        if response.get("status") != "password_changed":
            raise ApiError(
                "Respons perubahan password dari Universal API tidak valid."
            )

    def logout(self):
        tokens = self._load_tokens()
        if tokens is None:
            return
        try:
            self._send(
                "POST",
                "/auth/logout",
                {"refresh_token": tokens["refresh_token"]},
            )
        finally:
            self.token_store.clear(self.base_url)
