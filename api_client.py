import hashlib
import ipaddress
import json
import re
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
    USER_AGENT = "SIMPATI-Developer-Desktop"
    API_SERVICE_PATH = "/health/live"
    TENANT_PAGE_SIZE = 100
    INSTALLATION_PAGE_SIZE = 100

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
        headers = {
            "Accept": "application/json",
            "User-Agent": self.USER_AGENT,
        }
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

    def check_database_readiness(self):
        result = self._send("GET", "/health/ready")
        if (
            result.get("status") != "ONLINE"
            or result.get("database") != "CONNECTED"
        ):
            raise ApiError(
                "Universal API tidak mengonfirmasi kesiapan database."
            )
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
    def _validate_installation(installation, tenant_id):
        device = (
            installation.get("device")
            if isinstance(installation, dict)
            else None
        )
        if (
            not isinstance(installation, dict)
            or type(installation.get("id")) is not int
            or type(installation.get("tenant_id")) is not int
            or installation.get("tenant_id") != tenant_id
            or not isinstance(installation.get("installation_key"), str)
            or not isinstance(device, dict)
            or not isinstance(device.get("id"), str)
            or (
                device.get("name") is not None
                and not isinstance(device.get("name"), str)
            )
            or not isinstance(device.get("platform"), str)
            or (
                device.get("app_version") is not None
                and not isinstance(device.get("app_version"), str)
            )
            or not isinstance(device.get("details"), dict)
            or installation.get("status") not in ("ACTIVE", "REVOKED")
            or not isinstance(installation.get("first_seen_at"), str)
            or (
                installation.get("last_seen_at") is not None
                and not isinstance(installation.get("last_seen_at"), str)
            )
            or not isinstance(installation.get("created_at"), str)
            or not isinstance(installation.get("updated_at"), str)
            or (
                installation.get("deleted_at") is not None
                and not isinstance(installation.get("deleted_at"), str)
            )
        ):
            raise ApiError(
                "Respons instalasi dari Universal API tidak valid."
            )
        return installation

    def list_tenant_installations(self, tenant_id, include_deleted=False):
        if type(tenant_id) is not int or tenant_id < 1:
            raise ApiError("ID Tenant tidak valid.")
        if type(include_deleted) is not bool:
            raise ApiError("Pilihan instalasi dicabut tidak valid.")
        installations = []
        offset = 0
        total = None
        while total is None or offset < total:
            limit = self.INSTALLATION_PAGE_SIZE
            query = urlencode({"limit": limit, "offset": offset})
            endpoint = (
                f"/tenants/{tenant_id}/installations/recycle-bin"
                if include_deleted
                else f"/tenants/{tenant_id}/installations"
            )
            page = self.request(
                "GET",
                f"{endpoint}?{query}",
                authenticated=True,
            )
            items = page.get("items")
            page_total = page.get("total")
            if (
                not isinstance(items, list)
                or type(page_total) is not int
                or page_total < 0
                or len(items) > limit
                or offset + len(items) > page_total
                or any(
                    not isinstance(installation, dict)
                    for installation in items
                )
            ):
                raise ApiError(
                    "Respons daftar instalasi dari Universal API tidak valid."
                )
            if (
                page.get("limit") != limit
                or page.get("offset") != offset
                or any(
                    installation.get("tenant_id") != tenant_id
                    for installation in items
                )
            ):
                raise ApiError(
                    "Metadata daftar instalasi dari Universal API tidak valid."
                )
            if total is not None and page_total != total:
                raise ApiError(
                    "Jumlah instalasi Tenant berubah saat data sedang dimuat. "
                    "Muat ulang daftar instalasi."
                )
            total = page_total
            if not items:
                if offset < total:
                    raise ApiError(
                        "Universal API mengembalikan halaman instalasi kosong "
                        "sebelum seluruh data termuat."
                    )
                break
            validated_items = [
                self._validate_installation(installation, tenant_id)
                for installation in items
            ]
            if include_deleted and any(
                item["status"] != "REVOKED" or item["deleted_at"] is None
                for item in validated_items
            ):
                raise ApiError(
                    "Respons recycle bin instalasi dari Universal API "
                    "tidak valid."
                )
            installations.extend(validated_items)
            offset += len(items)
        return installations

    def list_installations(self, include_deleted=False):
        if type(include_deleted) is not bool:
            raise ApiError("Pilihan instalasi dicabut tidak valid.")
        installations = []
        for tenant in self.list_tenants():
            tenant_installations = self.list_tenant_installations(
                tenant["id"]
            )
            installations.extend(
                {
                    **installation,
                    "tenant_code": tenant["code"],
                    "tenant_name": tenant["name"],
                }
                for installation in tenant_installations
            )
            if include_deleted:
                deleted_installations = self.list_tenant_installations(
                    tenant["id"], include_deleted=True
                )
                installations.extend(
                    {
                        **installation,
                        "tenant_code": tenant["code"],
                        "tenant_name": tenant["name"],
                    }
                    for installation in deleted_installations
                )
        return installations

    def get_tenant_installation(self, tenant_id, installation_id):
        if type(tenant_id) is not int or tenant_id < 1:
            raise ApiError("ID Tenant tidak valid.")
        if type(installation_id) is not int or installation_id < 1:
            raise ApiError("ID instalasi tidak valid.")
        installation = self.request(
            "GET",
            f"/tenants/{tenant_id}/installations/{installation_id}",
            authenticated=True,
        )
        installation = self._validate_installation(
            installation, tenant_id
        )
        if installation["id"] != installation_id:
            raise ApiError(
                "Respons detail instalasi dari Universal API tidak valid."
            )
        return installation

    def list_modules(self):
        response = self.request(
            "GET", "/modules?include_inactive=true", authenticated=True
        )
        modules = response.get("items")
        if not isinstance(modules, list):
            raise ApiError(
                "Respons daftar modul dari Universal API tidak valid."
            )
        return [self._validate_module(module) for module in modules]

    @staticmethod
    def _validate_module(module):
        if (
            not isinstance(module, dict)
            or type(module.get("id")) is not int
            or not isinstance(module.get("code"), str)
            or not isinstance(module.get("name"), str)
            or (
                module.get("description") is not None
                and not isinstance(module.get("description"), str)
            )
            or type(module.get("is_active")) is not bool
            or not isinstance(module.get("created_at"), str)
            or not isinstance(module.get("updated_at"), str)
        ):
            raise ApiError(
                "Respons detail modul dari Universal API tidak valid."
            )
        return module

    def get_module(self, module_id):
        if type(module_id) is not int or module_id < 1:
            raise ApiError("ID modul tidak valid.")
        module = self._validate_module(
            self.request(
                "GET", f"/modules/{module_id}", authenticated=True
            )
        )
        if module["id"] != module_id:
            raise ApiError(
                "Respons detail modul dari Universal API tidak valid."
            )
        return module

    @staticmethod
    def _validate_module_code(module_code):
        if not isinstance(module_code, str):
            raise ApiError("Kode modul tidak valid.")
        module_code = module_code.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,49}", module_code):
            raise ApiError("Kode modul harus terdiri dari 2–50 huruf, "
                           "angka, atau garis bawah dan diawali huruf.")
        return module_code

    def create_module(self, module_code, name, description=None):
        module_code = self._validate_module_code(module_code)
        if module_code == "CORE":
            raise ApiError("CORE dikelola oleh sistem dan tidak dapat dibuat.")
        if not isinstance(name, str) or not name.strip():
            raise ApiError("Nama modul wajib diisi.")
        if len(name.strip()) > 150:
            raise ApiError("Nama modul maksimal 150 karakter.")
        if description is not None and not isinstance(description, str):
            raise ApiError("Deskripsi modul tidak valid.")
        description = description.strip() if description else None
        if description and len(description) > 4000:
            raise ApiError("Deskripsi modul maksimal 4000 karakter.")
        response = self.request(
            "POST",
            "/modules",
            {
                "code": module_code,
                "name": name.strip(),
                "description": description or None,
                "is_active": True,
            },
            authenticated=True,
        )
        module = self._validate_module(response)
        if module["code"] != module_code:
            raise ApiError(
                "Respons pembuatan modul dari Universal API tidak valid."
            )
        return module

    def set_module_active(self, module_id, is_active):
        if type(module_id) is not int or module_id < 1:
            raise ApiError("ID modul tidak valid.")
        if type(is_active) is not bool:
            raise ApiError("Status modul tidak valid.")
        module = self._validate_module(
            self.request(
                "PATCH",
                f"/modules/{module_id}",
                {"is_active": is_active},
                authenticated=True,
            )
        )
        if module["id"] != module_id or module["is_active"] != is_active:
            raise ApiError(
                "Respons perubahan status modul dari Universal API tidak "
                "valid."
            )
        return module

    def update_module(self, module_id, name, description=None):
        if type(module_id) is not int or module_id < 1:
            raise ApiError("ID modul tidak valid.")
        if not isinstance(name, str) or not name.strip():
            raise ApiError("Nama modul wajib diisi.")
        if len(name.strip()) > 150:
            raise ApiError("Nama modul maksimal 150 karakter.")
        if description is not None and not isinstance(description, str):
            raise ApiError("Deskripsi modul tidak valid.")
        description = description.strip() if description else None
        if description and len(description) > 4000:
            raise ApiError("Deskripsi modul maksimal 4000 karakter.")
        module = self._validate_module(
            self.request(
                "PATCH",
                f"/modules/{module_id}",
                {
                    "name": name.strip(),
                    "description": description or None,
                },
                authenticated=True,
            )
        )
        if (
            module["id"] != module_id
            or module["name"] != name.strip()
            or module["description"] != (description or None)
        ):
            raise ApiError(
                "Respons perubahan modul dari Universal API tidak valid."
            )
        return module

    def count_tenant_installations(self, tenant_id):
        if type(tenant_id) is not int or tenant_id < 1:
            raise ApiError("ID Tenant tidak valid.")
        query = urlencode({"limit": 1, "offset": 0})
        response = self.request(
            "GET",
            f"/tenants/{tenant_id}/installations?{query}",
            authenticated=True,
        )
        items = response.get("items")
        total = response.get("total")
        if (
            not isinstance(items, list)
            or any(not isinstance(item, dict) for item in items)
            or type(total) is not int
            or total < 0
            or len(items) > 1
            or len(items) > total
            or (total > 0 and len(items) != 1)
            or response.get("limit") != 1
            or response.get("offset") != 0
        ):
            raise ApiError(
                "Respons jumlah instalasi Tenant dari Universal API tidak "
                "valid."
            )
        return total

    def list_audit_logs(self, limit=50, offset=0, tenant_id=None):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ApiError("Jumlah audit log yang diminta tidak valid.")
        if type(offset) is not int or offset < 0:
            raise ApiError("Offset audit log tidak valid.")
        if tenant_id is not None and (
            type(tenant_id) is not int or tenant_id < 1
        ):
            raise ApiError("ID Tenant untuk audit log tidak valid.")
        params = {"limit": limit, "offset": offset}
        if tenant_id is not None:
            params["tenant_id"] = tenant_id
        query = urlencode(params)
        response = self.request(
            "GET", f"/auth/audit-logs?{query}", authenticated=True
        )
        logs = response.get("items")
        if (
            not isinstance(logs, list)
            or len(logs) > limit
            or any(
                not isinstance(log, dict)
                or any(
                    key not in log
                    for key in (
                        "id",
                        "tenant_id",
                        "actor_type",
                        "actor_id",
                        "action",
                        "entity",
                        "entity_id",
                        "details",
                        "created_at",
                    )
                )
                or type(log.get("id")) is not int
                or (
                    log.get("tenant_id") is not None
                    and type(log.get("tenant_id")) is not int
                )
                or log.get("actor_type")
                not in {"DEVELOPER", "TENANT", "SYSTEM"}
                or (
                    log.get("actor_id") is not None
                    and type(log.get("actor_id")) is not int
                )
                or not isinstance(log.get("action"), str)
                or not isinstance(log.get("entity"), str)
                or (
                    log.get("entity_id") is not None
                    and not isinstance(log.get("entity_id"), str)
                )
                or (
                    log.get("details") is not None
                    and not isinstance(log.get("details"), dict)
                )
                or not isinstance(log.get("created_at"), str)
                for log in logs
            )
            or type(response.get("limit")) is not int
            or response.get("limit") != limit
            or type(response.get("offset")) is not int
            or response.get("offset") != offset
        ):
            raise ApiError(
                "Respons audit log dari Universal API tidak valid."
            )
        return response

    def list_recent_audit_logs(self, limit=5):
        return self.list_audit_logs(limit=limit, offset=0)["items"]

    @staticmethod
    def _validate_developer_id(user_id):
        if type(user_id) is not int or user_id < 1:
            raise ApiError("ID akun Developer tidak valid.")

    @staticmethod
    def _validate_developer_account(account):
        sensitive_fields = {
            "password",
            "password_hash",
            "access_token",
            "refresh_token",
        }
        if (
            not isinstance(account, dict)
            or sensitive_fields.intersection(account)
            or type(account.get("id")) is not int
            or not isinstance(account.get("username"), str)
            or not isinstance(account.get("full_name"), str)
            or type(account.get("is_active")) is not bool
        ):
            raise ApiError(
                "Respons akun Developer dari Universal API tidak valid."
            )
        return account

    @staticmethod
    def _validate_role_codes(role_codes):
        if (
            not isinstance(role_codes, list)
            or any(
                not isinstance(code, str)
                or not re.fullmatch(r"[a-z0-9._-]{2,50}", code)
                for code in role_codes
            )
            or len(role_codes) != len(set(role_codes))
        ):
            raise ApiError("Daftar role Developer tidak valid.")
        return role_codes

    @staticmethod
    def _validate_permission_codes(permission_codes):
        if (
            not isinstance(permission_codes, list)
            or any(
                not isinstance(code, str)
                or not re.fullmatch(r"[a-z][a-z0-9._-]{1,99}", code)
                for code in permission_codes
            )
            or len(permission_codes) != len(set(permission_codes))
        ):
            raise ApiError("Daftar permission Developer tidak valid.")
        return permission_codes

    def list_developer_accounts(self, limit=50, offset=0):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ApiError("Jumlah akun Developer yang diminta tidak valid.")
        if type(offset) is not int or offset < 0:
            raise ApiError("Offset akun Developer tidak valid.")
        query = urlencode({"limit": limit, "offset": offset})
        response = self.request(
            "GET", f"/auth/developers?{query}", authenticated=True
        )
        accounts = response.get("items") if isinstance(response, dict) else None
        if (
            not isinstance(accounts, list)
            or len(accounts) > limit
            or any(
                not isinstance(account, dict)
                or "roles" not in account
                or not isinstance(account.get("roles"), list)
                or any(not isinstance(role, str) for role in account["roles"])
                or not isinstance(account.get("created_at"), str)
                or not isinstance(account.get("updated_at"), str)
                for account in accounts
            )
            or response.get("limit") != limit
            or response.get("offset") != offset
        ):
            raise ApiError(
                "Respons daftar akun Developer dari Universal API tidak valid."
            )
        for account in accounts:
            self._validate_developer_account(account)
        return response

    def create_developer_account(
        self, username, password, full_name, role_codes=None
    ):
        if not isinstance(username, str):
            raise ApiError("Username Developer tidak valid.")
        username = username.strip().lower()
        if not re.fullmatch(r"[a-zA-Z0-9._-]{3,100}", username):
            raise ApiError("Username Developer harus terdiri dari 3–100 karakter.")
        if not isinstance(full_name, str) or not full_name.strip():
            raise ApiError("Nama lengkap Developer wajib diisi.")
        full_name = full_name.strip()
        if len(full_name) > 200:
            raise ApiError("Nama lengkap Developer maksimal 200 karakter.")
        if not isinstance(password, str) or not 12 <= len(password) <= 256:
            raise ApiError("Password harus terdiri dari 12–256 karakter.")
        if role_codes is None:
            role_codes = []
        role_codes = self._validate_role_codes(role_codes)
        response = self.request(
            "POST",
            "/auth/developer/register",
            {
                "username": username,
                "password": password,
                "full_name": full_name,
                "role_codes": role_codes,
            },
            authenticated=True,
        )
        account = self._validate_developer_account(response)
        if (
            account["username"] != username
            or account["full_name"] != full_name
            or account.get("role_codes") != sorted(role_codes)
        ):
            raise ApiError(
                "Respons pembuatan akun Developer dari Universal API tidak "
                "valid."
            )
        return account

    def update_developer_account(self, user_id, full_name):
        self._validate_developer_id(user_id)
        if not isinstance(full_name, str) or not full_name.strip():
            raise ApiError("Nama lengkap Developer wajib diisi.")
        full_name = full_name.strip()
        if len(full_name) > 200:
            raise ApiError("Nama lengkap Developer maksimal 200 karakter.")
        response = self.request(
            "PATCH",
            f"/auth/developers/{user_id}",
            {"full_name": full_name},
            authenticated=True,
        )
        account = self._validate_developer_account(response)
        if account["id"] != user_id or account["full_name"] != full_name:
            raise ApiError(
                "Respons perubahan akun Developer dari Universal API tidak "
                "valid."
            )
        return account

    def set_developer_account_active(self, user_id, is_active):
        self._validate_developer_id(user_id)
        if type(is_active) is not bool:
            raise ApiError("Status akun Developer tidak valid.")
        response = self.request(
            "PATCH",
            f"/auth/developers/{user_id}",
            {"is_active": is_active},
            authenticated=True,
        )
        account = self._validate_developer_account(response)
        if account["id"] != user_id or account["is_active"] != is_active:
            raise ApiError(
                "Respons perubahan status akun Developer dari Universal API "
                "tidak valid."
            )
        return account

    def reset_developer_password(self, user_id, password):
        self._validate_developer_id(user_id)
        if not isinstance(password, str) or not 12 <= len(password) <= 256:
            raise ApiError("Password harus terdiri dari 12–256 karakter.")
        response = self.request(
            "PATCH",
            f"/auth/developers/{user_id}",
            {"password": password},
            authenticated=True,
        )
        account = self._validate_developer_account(response)
        if account["id"] != user_id:
            raise ApiError(
                "Respons reset password Developer dari Universal API tidak "
                "valid."
            )
        return account

    def assign_developer_roles(self, user_id, role_codes):
        self._validate_developer_id(user_id)
        role_codes = self._validate_role_codes(role_codes)
        response = self.request(
            "PUT",
            f"/auth/developers/{user_id}/roles",
            {"role_codes": role_codes},
            authenticated=True,
        )
        if (
            not isinstance(response, dict)
            or response.get("user_id") != user_id
            or response.get("role_codes") != sorted(role_codes)
        ):
            raise ApiError(
                "Respons assignment role Developer dari Universal API tidak "
                "valid."
            )
        return response

    def list_developer_roles(self):
        roles = self.request(
            "GET", "/auth/developer-roles", authenticated=True
        )
        if not isinstance(roles, list) or any(
            not isinstance(role, dict)
            or type(role.get("id")) is not int
            or not isinstance(role.get("code"), str)
            or not isinstance(role.get("name"), str)
            or (
                role.get("description") is not None
                and not isinstance(role.get("description"), str)
            )
            or type(role.get("is_active")) is not bool
            or not isinstance(role.get("permissions"), list)
            or any(
                not isinstance(permission, str)
                for permission in role["permissions"]
            )
            for role in roles
        ):
            raise ApiError(
                "Respons daftar role Developer dari Universal API tidak valid."
            )
        return roles

    def list_developer_permissions(self):
        permissions = self.request(
            "GET", "/auth/permissions", authenticated=True
        )
        if not isinstance(permissions, list) or any(
            not isinstance(permission, dict)
            or not isinstance(permission.get("code"), str)
            or not isinstance(permission.get("name"), str)
            or not isinstance(permission.get("module"), str)
            for permission in permissions
        ):
            raise ApiError(
                "Respons katalog permission Developer dari Universal API "
                "tidak valid."
            )
        return permissions

    def create_developer_role(
        self, code, name, description=None, permission_codes=None
    ):
        if not isinstance(code, str):
            raise ApiError("Kode role Developer tidak valid.")
        code = code.strip().lower()
        if not re.fullmatch(r"[a-z0-9._-]{2,50}", code):
            raise ApiError("Kode role Developer tidak valid.")
        if code == "developer_admin":
            raise ApiError("Role developer_admin dikelola oleh sistem.")
        if not isinstance(name, str) or not name.strip():
            raise ApiError("Nama role Developer wajib diisi.")
        name = name.strip()
        if len(name) > 100:
            raise ApiError("Nama role Developer maksimal 100 karakter.")
        if description is not None and not isinstance(description, str):
            raise ApiError("Deskripsi role Developer tidak valid.")
        description = description.strip() if description else None
        if description and len(description) > 2000:
            raise ApiError("Deskripsi role Developer maksimal 2000 karakter.")
        if permission_codes is None:
            permission_codes = []
        permission_codes = self._validate_permission_codes(permission_codes)
        response = self.request(
            "POST",
            "/auth/developer-roles",
            {
                "code": code,
                "name": name,
                "description": description,
                "permission_codes": permission_codes,
            },
            authenticated=True,
        )
        if (
            not isinstance(response, dict)
            or type(response.get("id")) is not int
            or response.get("code") != code
            or response.get("name") != name
            or response.get("permissions") != sorted(permission_codes)
        ):
            raise ApiError(
                "Respons pembuatan role Developer dari Universal API tidak "
                "valid."
            )
        return response

    def update_developer_role(
        self, role_id, name, description, is_active
    ):
        if type(role_id) is not int or role_id < 1:
            raise ApiError("ID role Developer tidak valid.")
        if not isinstance(name, str) or not name.strip():
            raise ApiError("Nama role Developer wajib diisi.")
        name = name.strip()
        if len(name) > 100:
            raise ApiError("Nama role Developer maksimal 100 karakter.")
        if description is not None and not isinstance(description, str):
            raise ApiError("Deskripsi role Developer tidak valid.")
        description = description.strip() if description else None
        if description and len(description) > 2000:
            raise ApiError("Deskripsi role Developer maksimal 2000 karakter.")
        if type(is_active) is not bool:
            raise ApiError("Status role Developer tidak valid.")
        response = self.request(
            "PATCH",
            f"/auth/developer-roles/{role_id}",
            {
                "name": name,
                "description": description,
                "is_active": is_active,
            },
            authenticated=True,
        )
        if (
            not isinstance(response, dict)
            or response.get("id") != role_id
            or response.get("name") != name
            or response.get("description") != description
            or response.get("is_active") is not is_active
            or not isinstance(response.get("code"), str)
        ):
            raise ApiError(
                "Respons perubahan role Developer dari Universal API tidak "
                "valid."
            )
        return response

    def set_developer_role_permissions(self, role_id, permission_codes):
        if type(role_id) is not int or role_id < 1:
            raise ApiError("ID role Developer tidak valid.")
        permission_codes = self._validate_permission_codes(permission_codes)
        response = self.request(
            "PUT",
            f"/auth/developer-roles/{role_id}/permissions",
            {"permission_codes": permission_codes},
            authenticated=True,
        )
        if (
            not isinstance(response, dict)
            or response.get("role_id") != role_id
            or response.get("permissions") != sorted(permission_codes)
        ):
            raise ApiError(
                "Respons perubahan permission role Developer dari Universal "
                "API tidak valid."
            )
        return response

    @staticmethod
    def _validate_module_request(tenant_id, module_code):
        if type(tenant_id) is not int or tenant_id < 1:
            raise ApiError("ID Tenant tidak valid.")
        if not isinstance(module_code, str):
            raise ApiError("Kode modul tidak valid.")
        module_code = module_code.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,49}", module_code):
            raise ApiError("Kode modul tidak valid.")
        return module_code

    def list_tenant_modules(self, tenant_id):
        if type(tenant_id) is not int or tenant_id < 1:
            raise ApiError("ID Tenant tidak valid.")
        response = self.request(
            "GET",
            f"/tenants/{tenant_id}/modules",
            authenticated=True,
        )
        modules = response.get("items")
        allowed_statuses = {
            "ENABLED",
            "DISABLED",
            "UNASSIGNED",
            "CATALOG_INACTIVE",
        }
        if (
            response.get("tenant_id") != tenant_id
            or not isinstance(modules, list)
            or any(
                not isinstance(module, dict)
                or type(module.get("id")) is not int
                or not isinstance(module.get("code"), str)
                or not isinstance(module.get("name"), str)
                or type(module.get("is_active")) is not bool
                or type(module.get("is_assigned")) is not bool
                or type(module.get("is_enabled")) is not bool
                or module.get("status") not in allowed_statuses
                for module in modules
            )
        ):
            raise ApiError(
                "Respons otorisasi modul Tenant dari Universal API tidak "
                "valid."
            )
        return modules

    def list_module_tenant_usage(self, module_code):
        module_code = self._validate_module_code(module_code)
        usage = []
        for tenant in self.list_tenants():
            tenant_modules = self.list_tenant_modules(tenant["id"])
            matches = [
                module
                for module in tenant_modules
                if module["code"] == module_code
            ]
            if len(matches) != 1:
                raise ApiError(
                    "Data katalog modul untuk Tenant tidak konsisten dengan "
                    "Universal API."
                )
            module = matches[0]
            usage.append(
                {
                    "tenant_id": tenant["id"],
                    "tenant_code": tenant["code"],
                    "tenant_name": tenant["name"],
                    "is_assigned": module["is_assigned"],
                    "is_enabled": module["is_enabled"],
                    "status": module["status"],
                }
            )
        return usage

    def enable_tenant_module(self, tenant_id, module_code):
        module_code = self._validate_module_request(tenant_id, module_code)
        response = self.request(
            "POST",
            f"/tenants/{tenant_id}/modules",
            {"module_code": module_code},
            authenticated=True,
        )
        module = response.get("module")
        if (
            response.get("tenant_id") != tenant_id
            or not isinstance(module, dict)
            or module.get("code") != module_code
            or response.get("is_assigned") is not True
            or response.get("is_enabled") is not True
            or response.get("status") != "ENABLED"
        ):
            raise ApiError(
                "Respons aktivasi modul Tenant dari Universal API tidak "
                "valid."
            )
        return response

    def disable_tenant_module(self, tenant_id, module_code):
        module_code = self._validate_module_request(tenant_id, module_code)
        response = self.request(
            "DELETE",
            f"/tenants/{tenant_id}/modules/{module_code}",
            authenticated=True,
        )
        if (
            response.get("tenant_id") != tenant_id
            or response.get("module_code") != module_code
            or response.get("is_assigned") is not True
            or response.get("is_enabled") is not False
            or response.get("status") != "DISABLED"
        ):
            raise ApiError(
                "Respons penonaktifan modul Tenant dari Universal API tidak "
                "valid."
            )
        return response

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
