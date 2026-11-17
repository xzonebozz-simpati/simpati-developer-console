import hmac
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

from fastapi import FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware


BASE_DIR = Path(__file__).resolve().parent
APP_VERSION = "0.4.0"

app = FastAPI(
    title="SIMPATI Developer Console",
    description="Pusat kendali ekosistem SIMPATI Universal.",
    version=APP_VERSION,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ["SESSION_SECRET"],
    session_cookie="simpati_developer_session",
    max_age=60 * 60 * 8,
    same_site="lax",
    https_only=os.getenv("COOKIE_SECURE", "true").lower() == "true",
)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

templates = Jinja2Templates(directory=BASE_DIR / "templates")


MENU_ITEMS = [
    {
        "label": "Dashboard",
        "description": "Ringkasan ekosistem SIMPATI",
        "path": "/dashboard",
        "slug": "dashboard",
    },
    {
        "label": "Manajemen Klien",
        "description": "Data organisasi pelanggan",
        "path": "/clients",
        "slug": "clients",
    },
    {
        "label": "Manajemen Instalasi",
        "description": "Daftar instalasi aplikasi pelanggan",
        "path": "/installations",
        "slug": "installations",
    },
    {
        "label": "Manajemen Lisensi",
        "description": "Akses layanan License Manager",
        "path": "/licenses",
        "slug": "licenses",
    },
    {
        "label": "Manajemen Paket",
        "description": "Paket dan pilihan modul",
        "path": "/packages",
        "slug": "packages",
    },
    {
        "label": "Manajemen Tenant",
        "description": "Identitas dan branding pelanggan",
        "path": "/tenants",
        "slug": "tenants",
    },
    {
        "label": "Manajemen Akun",
        "description": "Akun Superadmin pelanggan",
        "path": "/accounts",
        "slug": "accounts",
    },
    {
        "label": "Manajemen Modul",
        "description": "Ketersediaan modul aplikasi",
        "path": "/modules",
        "slug": "modules",
    },
    {
        "label": "Monitoring Sistem",
        "description": "Kondisi aplikasi dan layanan",
        "path": "/monitoring",
        "slug": "monitoring",
    },
    {
        "label": "Pengaturan Global",
        "description": "Konfigurasi ekosistem",
        "path": "/settings",
        "slug": "settings",
    },
    {
        "label": "Audit Log",
        "description": "Riwayat aktivitas pengembang",
        "path": "/audit-logs",
        "slug": "audit-logs",
    },
]


# =========================================================
# KONFIGURASI
# =========================================================

def is_configured() -> bool:
    return bool(
        os.getenv("DEVELOPER_USERNAME")
        and os.getenv("DEVELOPER_PASSWORD")
        and os.getenv("SESSION_SECRET")
    )


def supabase_configured() -> bool:
    return bool(
        os.getenv("SUPABASE_URL")
        and os.getenv("SUPABASE_SECRET_KEY")
    )


def authenticated(request: Request) -> bool:
    return request.session.get("developer_authenticated") is True


def ensure_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")

    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token

    return token


def verify_csrf(request: Request, token: str) -> bool:
    expected = request.session.get("csrf_token", "")

    if not expected or not token:
        return False

    return hmac.compare_digest(expected, token)


def render_page(request: Request, template: str, **context):
    return templates.TemplateResponse(
        request=request,
        name=template,
        context={
            **context,
            "menu_items": MENU_ITEMS,
            "username": os.getenv(
                "DEVELOPER_USERNAME",
                "Developer",
            ),
            "csrf_token": ensure_csrf_token(request),
        },
    )


# =========================================================
# SUPABASE REST API
# =========================================================

class SupabaseError(Exception):
    pass


async def supabase_request(
    method: str,
    endpoint: str,
    params=None,
    data=None,
):
    if not supabase_configured():
        raise SupabaseError(
            "Konfigurasi koneksi Supabase belum lengkap."
        )

    base_url = os.environ["SUPABASE_URL"].rstrip("/")
    secret_key = os.environ["SUPABASE_SECRET_KEY"]

    headers = {
        "apikey": secret_key,
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
    }

    url = f"{base_url}/rest/v1/{endpoint}"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=data,
            )

        if response.is_error:
            raise SupabaseError(
                f"Supabase menolak permintaan (HTTP {response.status_code})."
            )

        if not response.content:
            return None

        return response.json()

    except httpx.TimeoutException:
        raise SupabaseError(
            "Koneksi Supabase mengalami timeout."
        )

    except httpx.RequestError:
        raise SupabaseError(
            "Tidak dapat menghubungi server Supabase."
        )


# =========================================================
# SIMPATI UNIVERSAL API
# =========================================================

UNIVERSAL_API_BASE_URL = os.getenv(
    "UNIVERSAL_API_BASE_URL",
    "https://simpatiuniapi.hostless.app",
).rstrip("/")
UNIVERSAL_API_SESSIONS = {}


class UniversalAPIError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def api_error_detail(response):
    try:
        payload = response.json()
    except ValueError:
        payload = response.text

    if isinstance(payload, dict):
        detail = payload.get("detail", payload)
        if isinstance(detail, list):
            return "; ".join(
                str(item.get("msg", item))
                if isinstance(item, dict)
                else str(item)
                for item in detail
            )
        return str(detail)

    return str(payload or response.reason_phrase)


async def universal_http_request(
    method,
    path,
    params=None,
    data=None,
    access_token=None,
):
    headers = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.request(
                method=method,
                url=f"{UNIVERSAL_API_BASE_URL}/{path.lstrip('/')}",
                headers=headers,
                params=params,
                json=data,
            )
    except httpx.TimeoutException as exc:
        raise UniversalAPIError(
            "Koneksi ke SIMPATI Universal API mengalami timeout."
        ) from exc
    except httpx.RequestError as exc:
        raise UniversalAPIError(
            "Tidak dapat menghubungi SIMPATI Universal API."
        ) from exc

    if response.is_error:
        detail = api_error_detail(response)
        raise UniversalAPIError(
            f"Universal API menolak permintaan (HTTP {response.status_code}): "
            f"{detail[:500]}",
            status_code=response.status_code,
        )

    if not response.content:
        return None

    try:
        return response.json()
    except ValueError as exc:
        raise UniversalAPIError(
            "Universal API mengembalikan respons yang bukan JSON."
        ) from exc


async def universal_api_login(username, password):
    token_response = await universal_http_request(
        "POST",
        "/auth/developer/login",
        data={"username": username, "password": password},
    )
    if not isinstance(token_response, dict):
        raise UniversalAPIError(
            "Respons login Universal API tidak sesuai kontrak."
        )

    user = token_response.get("user")
    if not isinstance(user, dict) or user.get("actor_type") != "developer":
        raise UniversalAPIError(
            "Akun Universal API bukan akun Developer."
        )

    access_token = token_response.get("access_token")
    refresh_token = token_response.get("refresh_token")
    if not access_token or not refresh_token:
        raise UniversalAPIError(
            "Universal API tidak memberikan token akses dan refresh."
        )

    now = time.monotonic()
    for existing_key, existing_session in list(UNIVERSAL_API_SESSIONS.items()):
        if existing_session.get("session_expires_at", 0) <= now:
            UNIVERSAL_API_SESSIONS.pop(existing_key, None)

    session_key = secrets.token_urlsafe(32)
    UNIVERSAL_API_SESSIONS[session_key] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": now + max(0, int(token_response.get("expires_in", 0))),
        "session_expires_at": now + 60 * 60 * 8,
    }
    return session_key


async def universal_api_request(
    request,
    method,
    path,
    params=None,
    data=None,
):
    session_key = request.session.get("universal_api_session")
    token_state = UNIVERSAL_API_SESSIONS.get(session_key)
    if not token_state:
        message = request.session.get("universal_api_error")
        if message:
            raise UniversalAPIError(message)
        if not authenticated(request) or not is_configured():
            raise UniversalAPIError(
                "Sesi Universal API tidak tersedia. Keluar lalu masuk kembali "
                "menggunakan akun Developer Universal API."
            )
        try:
            session_key = await universal_api_login(
                os.environ["DEVELOPER_USERNAME"],
                os.environ["DEVELOPER_PASSWORD"],
            )
        except UniversalAPIError as exc:
            request.session["universal_api_error"] = str(exc)
            raise
        request.session["universal_api_session"] = session_key
        request.session.pop("universal_api_error", None)
        token_state = UNIVERSAL_API_SESSIONS[session_key]

    if token_state.get("session_expires_at", 0) <= time.monotonic():
        UNIVERSAL_API_SESSIONS.pop(session_key, None)
        raise UniversalAPIError(
            "Sesi Developer kedaluwarsa. Keluar lalu masuk kembali."
        )

    async def refresh_tokens():
        try:
            refreshed = await universal_http_request(
                "POST",
                "/auth/refresh",
                data={"refresh_token": token_state["refresh_token"]},
            )
        except UniversalAPIError:
            UNIVERSAL_API_SESSIONS.pop(session_key, None)
            raise

        if not isinstance(refreshed, dict):
            UNIVERSAL_API_SESSIONS.pop(session_key, None)
            raise UniversalAPIError(
                "Respons perpanjangan sesi Universal API tidak sesuai kontrak."
            )

        access_token = refreshed.get("access_token")
        refresh_token = refreshed.get("refresh_token")
        if not access_token or not refresh_token:
            UNIVERSAL_API_SESSIONS.pop(session_key, None)
            raise UniversalAPIError(
                "Sesi Universal API kedaluwarsa. Keluar lalu masuk kembali."
            )

        token_state["access_token"] = access_token
        token_state["refresh_token"] = refresh_token
        token_state["expires_at"] = time.monotonic() + max(
            0,
            int(refreshed.get("expires_in", 0)),
        )

    if token_state.get("expires_at", 0) <= time.monotonic() + 5:
        await refresh_tokens()

    try:
        return await universal_http_request(
            method,
            path,
            params=params,
            data=data,
            access_token=token_state["access_token"],
        )
    except UniversalAPIError as exc:
        if exc.status_code != 401:
            raise

    await refresh_tokens()

    return await universal_http_request(
        method,
        path,
        params=params,
        data=data,
        access_token=token_state["access_token"],
    )


def response_records(payload, collection_names):
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        for key in collection_names:
            if isinstance(payload.get(key), list):
                return payload[key]

    raise UniversalAPIError(
        "Bentuk respons daftar dari Universal API tidak sesuai kontrak."
    )


async def universal_api_collection(
    request,
    path,
    params,
    collection_names,
):
    records = []
    offset = int(params.get("offset", 0))
    limit = int(params.get("limit", 100))

    while True:
        page_params = {**params, "offset": offset, "limit": limit}
        payload = await universal_api_request(
            request,
            "GET",
            path,
            params=page_params,
        )
        page = response_records(payload, collection_names)
        records.extend(page)
        if len(page) < limit:
            return records
        offset += limit


async def get_universal_tenants(request):
    tenants = await universal_api_collection(
        request,
        "/tenants",
        {"limit": 100, "offset": 0},
        ("items", "tenants", "data", "results"),
    )
    for tenant in tenants:
        if not isinstance(tenant, dict):
            raise UniversalAPIError(
                "Data Tenant Universal API tidak sesuai kontrak."
            )
        if tenant.get("id") is None and tenant.get("tenant_id") is None:
            raise UniversalAPIError(
                "Respons Tenant Universal API tidak memiliki ID."
            )
    return tenants


def tenant_identifier(tenant):
    return tenant.get("id", tenant.get("tenant_id"))


def tenant_label(tenant):
    return (
        tenant.get("name")
        or tenant.get("tenant_name")
        or tenant.get("organization_name")
        or str(tenant_identifier(tenant))
    )


def normalize_module_catalog(payload):
    modules = response_records(
        payload,
        ("items", "modules", "available_modules", "data", "results"),
    )
    normalized = []
    for module in modules:
        if isinstance(module, str):
            code = module
            name = module
            description = ""
        elif isinstance(module, dict):
            code = (
                module.get("code")
                or module.get("module_code")
                or module.get("key")
            )
            name = (
                module.get("name")
                or module.get("module_name")
                or code
            )
            description = module.get("description", "")
        else:
            raise UniversalAPIError(
                "Data modul Universal API tidak sesuai kontrak."
            )

        if not code:
            raise UniversalAPIError(
                "Respons modul Universal API tidak memiliki kode."
            )
        normalized.append({
            "code": str(code),
            "name": str(name),
            "description": str(description or ""),
        })
    return normalized


async def get_license_catalog(request):
    packages = await universal_api_collection(
        request,
        "/licenses/packages",
        {"limit": 100, "offset": 0},
        ("items", "packages", "data", "results"),
    )
    packages = [
        item for item in packages
        if isinstance(item, dict) and item.get("is_active", True)
    ]

    module_payload = await universal_api_request(
        request,
        "GET",
        "/licenses/modules",
    )
    modules = normalize_module_catalog(module_payload)
    return packages, modules


def validate_positive_integer(value, label, minimum=1):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} harus berupa bilangan bulat.")
    if parsed < minimum:
        raise ValueError(f"{label} minimal {minimum}.")
    return parsed


def parse_license_datetime(value, label):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} tidak valid.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_license_dates(valid_from, valid_until):
    start = parse_license_datetime(valid_from, "Tanggal mulai")
    end = parse_license_datetime(valid_until, "Tanggal berakhir")
    if end <= start:
        raise ValueError(
            "Tanggal berakhir harus setelah tanggal mulai."
        )
    return start, end


def normalize_license_detail(payload):
    if not isinstance(payload, dict):
        raise UniversalAPIError(
            "Respons detail lisensi Universal API tidak sesuai kontrak."
        )
    if isinstance(payload.get("license"), dict):
        return {**payload["license"], **{
            key: value for key, value in payload.items()
            if key != "license"
        }}
    return payload


# =========================================================
# DATA KLIEN
# =========================================================

async def get_clients():
    result = await supabase_request(
        "GET",
        "clients",
        params={
            "select": "*",
            "order": "created_at.desc",
            "limit": "500",
        },
    )

    return result or []


async def get_client(client_id: str):
    try:
        parsed_id = str(uuid.UUID(client_id))
    except ValueError:
        return None

    result = await supabase_request(
        "GET",
        "clients",
        params={
            "select": "*",
            "id": f"eq.{parsed_id}",
            "limit": "1",
        },
    )

    if not result:
        return None

    return result[0]


def validate_client(client_code, client_name):
    errors = []

    client_code = client_code.strip().upper()
    client_name = client_name.strip()

    if not client_code:
        errors.append("Kode klien wajib diisi.")
    elif len(client_code) > 50:
        errors.append("Kode klien maksimal 50 karakter.")
    elif not all(
        char.isalnum() or char in "-_"
        for char in client_code
    ):
        errors.append(
            "Kode klien hanya boleh menggunakan huruf, angka, "
            "tanda hubung, dan garis bawah."
        )

    if not client_name:
        errors.append("Nama klien wajib diisi.")
    elif len(client_name) > 150:
        errors.append("Nama klien maksimal 150 karakter.")

    return errors


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "simpati-developer-console",
        "version": APP_VERSION,
        "database_configured": supabase_configured(),
    }


# =========================================================
# LOGIN
# =========================================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    destination = (
        "/dashboard"
        if authenticated(request)
        else "/login"
    )

    return RedirectResponse(
        destination,
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if authenticated(request):
        return RedirectResponse(
            "/dashboard",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "error": None,
            "configured": is_configured(),
            "csrf_token": ensure_csrf_token(request),
        },
    )


@app.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
):
    if not verify_csrf(request, csrf_token):
        return HTMLResponse(
            "Permintaan tidak valid. Silakan muat ulang halaman login.",
            status_code=403,
        )

    if not is_configured():
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Konfigurasi akun Developer belum lengkap.",
                "configured": False,
                "csrf_token": ensure_csrf_token(request),
            },
            status_code=503,
        )

    expected_user = os.environ["DEVELOPER_USERNAME"]
    expected_password = os.environ["DEVELOPER_PASSWORD"]

    valid_user = hmac.compare_digest(
        username.encode(),
        expected_user.encode(),
    )

    valid_password = hmac.compare_digest(
        password.encode(),
        expected_password.encode(),
    )

    if not (valid_user and valid_password):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Nama pengguna atau kata sandi tidak sesuai.",
                "configured": True,
                "csrf_token": ensure_csrf_token(request),
            },
            status_code=401,
        )

    request.session.clear()
    request.session["developer_authenticated"] = True
    request.session["csrf_token"] = secrets.token_urlsafe(32)
    try:
        request.session["universal_api_session"] = await universal_api_login(
            username,
            password,
        )
    except UniversalAPIError as exc:
        request.session["universal_api_error"] = str(exc)

    return RedirectResponse(
        "/dashboard",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# =========================================================
# DASHBOARD
# =========================================================

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not authenticated(request):
        return RedirectResponse(
            "/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return render_page(
        request,
        "dashboard.html",
        active_slug="dashboard",
    )


# =========================================================
# MANAJEMEN LISENSI
# =========================================================

LICENSE_STATUSES = ("ACTIVE", "SUSPENDED", "REVOKED")


async def get_all_tenant_licenses(request):
    tenants = await get_universal_tenants(request)
    licenses = []
    for tenant in tenants:
        tenant_id = validate_positive_integer(
            tenant_identifier(tenant),
            "ID Tenant",
        )
        tenant_licenses = await universal_api_collection(
            request,
            "/licenses",
            {"tenant_id": tenant_id, "limit": 100, "offset": 0},
            ("items", "licenses", "data", "results"),
        )
        for license_item in tenant_licenses:
            if not isinstance(license_item, dict):
                raise UniversalAPIError(
                    "Data lisensi Universal API tidak sesuai kontrak."
                )
            licenses.append({
                **license_item,
                "tenant_id": tenant_id,
                "tenant_name": tenant_label(tenant),
                "tenant_code": tenant.get("code", tenant.get("tenant_code", "")),
            })
    return tenants, licenses


async def get_license_detail(request, license_id, tenant_id):
    try:
        parsed_id = str(uuid.UUID(license_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("ID lisensi tidak valid.") from exc

    parsed_tenant_id = validate_positive_integer(tenant_id, "ID Tenant")
    response = await universal_api_request(
        request,
        "GET",
        f"/licenses/{parsed_id}",
        params={"tenant_id": parsed_tenant_id},
    )
    return normalize_license_detail(response)


@app.get("/licenses", response_class=HTMLResponse)
async def licenses_page(
    request: Request,
    q: str = "",
    status_filter: str = "",
    notice: str = "",
    error_notice: str = "",
):
    if not authenticated(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    tenants = []
    licenses = []
    error = error_notice or None
    try:
        tenants, licenses = await get_all_tenant_licenses(request)
    except (UniversalAPIError, ValueError) as exc:
        error = str(exc)

    keyword = q.strip().lower()
    if keyword:
        licenses = [
            item for item in licenses
            if keyword in str(item.get("license_key", "")).lower()
            or keyword in str(item.get("tenant_name", "")).lower()
            or keyword in str(item.get("tenant_code", "")).lower()
            or keyword in str(item.get("package_name", "")).lower()
        ]
    if status_filter in LICENSE_STATUSES:
        licenses = [
            item for item in licenses
            if str(
                item.get("computed_status", item.get("status", ""))
            ).upper() == status_filter
        ]

    counts = {
        "total": len(licenses),
        "active": sum(
            1 for item in licenses
            if str(item.get("computed_status", item.get("status", ""))).upper()
            == "ACTIVE"
        ),
        "suspended": sum(
            1 for item in licenses
            if str(item.get("computed_status", item.get("status", ""))).upper()
            == "SUSPENDED"
        ),
        "revoked": sum(
            1 for item in licenses
            if str(item.get("computed_status", item.get("status", ""))).upper()
            == "REVOKED"
        ),
    }

    return render_page(
        request,
        "licenses.html",
        active_slug="licenses",
        licenses=licenses,
        tenants=tenants,
        keyword=q,
        status_filter=status_filter,
        notice=notice,
        error=error,
        counts=counts,
    )


def new_license_form_data():
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    end = now + timedelta(days=365)
    return {
        "valid_from": now.strftime("%Y-%m-%dT%H:%M"),
        "valid_until": end.strftime("%Y-%m-%dT%H:%M"),
        "grace_period_days": 7,
        "max_installations": 1,
        "max_members": 50000,
        "max_accounts": 200,
        "max_concurrent_users": 25,
        "max_storage_mb": 20480,
        "notes": "",
    }


async def license_form_catalog(request):
    tenants = await get_universal_tenants(request)
    packages, modules = await get_license_catalog(request)
    return tenants, packages, modules


@app.get("/licenses/new", response_class=HTMLResponse)
async def license_new_page(request: Request):
    if not authenticated(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    try:
        tenants, packages, modules = await license_form_catalog(request)
    except UniversalAPIError as exc:
        return RedirectResponse(
            f"/licenses?error_notice={quote(str(exc), safe='')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return render_page(
        request,
        "license_form.html",
        active_slug="licenses",
        page_title="Terbitkan Lisensi",
        form_action="/licenses/create",
        license_data=new_license_form_data(),
        tenants=tenants,
        packages=packages,
        modules=modules,
        errors=[],
    )


def validate_license_issue(form_data, tenants, packages, modules):
    errors = []
    tenant_ids = set()
    for tenant in tenants:
        try:
            tenant_ids.add(str(int(tenant_identifier(tenant))))
        except (TypeError, ValueError):
            continue

    try:
        tenant_id = validate_positive_integer(
            form_data.get("tenant_id"),
            "Tenant",
        )
        if str(tenant_id) not in tenant_ids:
            errors.append("Pilih Tenant yang terdaftar pada Universal API.")
    except ValueError as exc:
        errors.append(str(exc))
        tenant_id = None

    package_ids = {
        str(item.get("id"))
        for item in packages
        if item.get("id")
    }
    package_id = str(form_data.get("package_id", "")).strip()
    if package_id not in package_ids:
        errors.append("Pilih paket aktif yang tersedia.")

    module_codes = {item["code"] for item in modules}
    selected_modules = form_data.get("modules", [])
    if not selected_modules:
        errors.append("Pilih setidaknya satu modul.")
    elif any(code not in module_codes for code in selected_modules):
        errors.append("Pilihan modul tidak valid.")

    try:
        valid_from, valid_until = validate_license_dates(
            form_data.get("valid_from"),
            form_data.get("valid_until"),
        )
    except ValueError as exc:
        errors.append(str(exc))
        valid_from = valid_until = None

    integer_fields = (
        ("grace_period_days", "Masa tenggang", 0),
        ("max_installations", "Batas instalasi", 1),
        ("max_members", "Batas anggota", 1),
        ("max_accounts", "Batas akun", 1),
        ("max_concurrent_users", "Batas pengguna bersamaan", 1),
        ("max_storage_mb", "Batas penyimpanan (MB)", 500),
    )
    values = {}
    for field, label, minimum in integer_fields:
        try:
            values[field] = validate_positive_integer(
                form_data.get(field),
                label,
                minimum,
            )
        except ValueError as exc:
            errors.append(str(exc))

    if values.get("grace_period_days", 0) > 90:
        errors.append("Masa tenggang maksimal 90 hari.")

    return errors, {
        "tenant_id": tenant_id,
        "package_id": package_id,
        "valid_from": valid_from.isoformat() if valid_from else None,
        "valid_until": valid_until.isoformat() if valid_until else None,
        "modules": selected_modules,
        "values": values,
    }


def license_form_context(
    request,
    *,
    page_title,
    form_action,
    license_data,
    tenants,
    packages,
    modules,
    errors,
):
    return render_page(
        request,
        "license_form.html",
        active_slug="licenses",
        page_title=page_title,
        form_action=form_action,
        license_data=license_data,
        tenants=tenants,
        packages=packages,
        modules=modules,
        errors=errors,
    )


@app.post("/licenses/create")
async def license_create(
    request: Request,
    csrf_token: str = Form(...),
    tenant_id: str = Form(...),
    package_id: str = Form(...),
    valid_from: str = Form(...),
    valid_until: str = Form(...),
    grace_period_days: str = Form("7"),
    max_installations: str = Form("1"),
    modules: list[str] = Form(default=[]),
    max_members: str = Form("50000"),
    max_accounts: str = Form("200"),
    max_concurrent_users: str = Form("25"),
    max_storage_mb: str = Form("20480"),
    notes: str = Form(""),
):
    if not authenticated(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if not verify_csrf(request, csrf_token):
        return HTMLResponse("Permintaan tidak valid. Silakan login ulang.", status_code=403)

    form_data = {
        "tenant_id": tenant_id,
        "package_id": package_id,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "grace_period_days": grace_period_days,
        "max_installations": max_installations,
        "modules": modules,
        "max_members": max_members,
        "max_accounts": max_accounts,
        "max_concurrent_users": max_concurrent_users,
        "max_storage_mb": max_storage_mb,
        "notes": notes,
    }
    try:
        tenants, packages, module_catalog = await license_form_catalog(request)
        errors, normalized = validate_license_issue(
            form_data,
            tenants,
            packages,
            module_catalog,
        )
        if errors:
            return license_form_context(
                request,
                page_title="Terbitkan Lisensi",
                form_action="/licenses/create",
                license_data=form_data,
                tenants=tenants,
                packages=packages,
                modules=module_catalog,
                errors=errors,
            )

        capacity = normalized["values"]
        payload = {
            "tenant_id": normalized["tenant_id"],
            "package_id": normalized["package_id"],
            "license_type": "COMMERCIAL",
            "valid_from": normalized["valid_from"],
            "valid_until": normalized["valid_until"],
            "grace_period_days": capacity["grace_period_days"],
            "max_installations": capacity["max_installations"],
            "modules": normalized["modules"],
            "capacity": {
                "max_members": capacity["max_members"],
                "max_accounts": capacity["max_accounts"],
                "max_concurrent_users": capacity["max_concurrent_users"],
                "max_storage_mb": capacity["max_storage_mb"],
            },
            "notes": notes.strip() or None,
        }
        created = await universal_api_request(
            request,
            "POST",
            "/licenses",
            data=payload,
        )
        license_record = (
            created.get("license", created)
            if isinstance(created, dict)
            else {}
        )
        created_id = (
            license_record.get("id")
            or license_record.get("license_id")
            if isinstance(license_record, dict)
            else None
        )
        if created_id:
            return RedirectResponse(
                f"/licenses/{quote(str(created_id), safe='')}?"
                f"tenant_id={normalized['tenant_id']}"
                "&notice=Lisensi+dan+Serial+Key+berhasil+diterbitkan",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        return RedirectResponse(
            "/licenses?notice=Lisensi+berhasil+diterbitkan.+"
            "Serial+Key+tersedia+pada+detail+lisensi",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except UniversalAPIError as exc:
        try:
            tenants, packages, module_catalog = await license_form_catalog(request)
        except UniversalAPIError:
            tenants, packages, module_catalog = [], [], []
        return license_form_context(
            request,
            page_title="Terbitkan Lisensi",
            form_action="/licenses/create",
            license_data=form_data,
            tenants=tenants,
            packages=packages,
            modules=module_catalog,
            errors=[str(exc)],
        )


@app.get("/licenses/{license_id}", response_class=HTMLResponse)
async def license_detail_page(
    request: Request,
    license_id: str,
    tenant_id: int,
    notice: str = "",
    error_notice: str = "",
):
    if not authenticated(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    try:
        license_data = await get_license_detail(
            request,
            license_id,
            tenant_id,
        )
        return render_page(
            request,
            "license_detail.html",
            active_slug="licenses",
            license=license_data,
            tenant_id=tenant_id,
            notice=notice,
            error_notice=error_notice,
            statuses=LICENSE_STATUSES,
        )
    except (UniversalAPIError, ValueError) as exc:
        return RedirectResponse(
            f"/licenses?error_notice={quote(str(exc), safe='')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@app.post("/licenses/{license_id}/extend")
async def license_extend(
    request: Request,
    license_id: str,
    tenant_id: int = Form(...),
    valid_until: str = Form(...),
    reason: str = Form(...),
    csrf_token: str = Form(...),
):
    if not authenticated(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if not verify_csrf(request, csrf_token):
        return HTMLResponse("Permintaan tidak valid. Silakan login ulang.", status_code=403)

    try:
        until = parse_license_datetime(valid_until, "Tanggal berakhir")
        if len(reason.strip()) < 3:
            raise ValueError("Alasan perpanjangan minimal 3 karakter.")
        current_license = await get_license_detail(
            request,
            license_id,
            tenant_id,
        )
        current_until = parse_license_datetime(
            current_license.get("valid_until"),
            "Tanggal berakhir lisensi saat ini",
        )
        if until <= current_until:
            raise ValueError(
                "Tanggal perpanjangan harus setelah masa berlaku saat ini."
            )
        await universal_api_request(
            request,
            "POST",
            f"/licenses/{uuid.UUID(license_id)}/extend",
            params={"tenant_id": tenant_id},
            data={
                "valid_until": until.isoformat(),
                "reason": reason.strip(),
            },
        )
        notice = "Masa berlaku lisensi berhasil diperpanjang"
        error_notice = ""
    except (UniversalAPIError, ValueError) as exc:
        notice = ""
        error_notice = str(exc)

    return RedirectResponse(
        f"/licenses/{quote(license_id, safe='')}?tenant_id={tenant_id}"
        f"&notice={quote(notice, safe='')}"
        f"&error_notice={quote(error_notice, safe='')}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/licenses/{license_id}/validity")
async def license_update_validity(
    request: Request,
    license_id: str,
    tenant_id: int = Form(...),
    valid_from: str = Form(...),
    valid_until: str = Form(...),
    grace_period_days: str = Form(""),
    reason: str = Form(...),
    csrf_token: str = Form(...),
):
    if not authenticated(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if not verify_csrf(request, csrf_token):
        return HTMLResponse("Permintaan tidak valid. Silakan login ulang.", status_code=403)

    try:
        start, end = validate_license_dates(valid_from, valid_until)
        if len(reason.strip()) < 3:
            raise ValueError("Alasan perubahan masa berlaku minimal 3 karakter.")
        payload = {
            "valid_from": start.isoformat(),
            "valid_until": end.isoformat(),
            "reason": reason.strip(),
        }
        if grace_period_days.strip():
            grace_days = validate_positive_integer(
                grace_period_days,
                "Masa tenggang",
                0,
            )
            if grace_days > 90:
                raise ValueError("Masa tenggang maksimal 90 hari.")
            payload["grace_period_days"] = grace_days

        await universal_api_request(
            request,
            "PATCH",
            f"/licenses/{uuid.UUID(license_id)}/validity",
            params={"tenant_id": tenant_id},
            data=payload,
        )
        notice = "Masa berlaku lisensi berhasil diperbarui"
        error_notice = ""
    except (UniversalAPIError, ValueError) as exc:
        notice = ""
        error_notice = str(exc)

    return RedirectResponse(
        f"/licenses/{quote(license_id, safe='')}?tenant_id={tenant_id}"
        f"&notice={quote(notice, safe='')}"
        f"&error_notice={quote(error_notice, safe='')}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/licenses/{license_id}/status")
async def license_change_status(
    request: Request,
    license_id: str,
    tenant_id: int = Form(...),
    new_status: str = Form(..., alias="status"),
    reason: str = Form(...),
    csrf_token: str = Form(...),
):
    if not authenticated(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if not verify_csrf(request, csrf_token):
        return HTMLResponse("Permintaan tidak valid. Silakan login ulang.", status_code=403)

    try:
        if new_status not in LICENSE_STATUSES:
            raise ValueError("Status lisensi tidak valid.")
        if len(reason.strip()) < 3:
            raise ValueError("Alasan perubahan status minimal 3 karakter.")
        await universal_api_request(
            request,
            "PATCH",
            f"/licenses/{uuid.UUID(license_id)}/status",
            params={"tenant_id": tenant_id},
            data={"status": new_status, "reason": reason.strip()},
        )
        notice = "Status lisensi berhasil diperbarui"
        error_notice = ""
    except (UniversalAPIError, ValueError) as exc:
        notice = ""
        error_notice = str(exc)

    return RedirectResponse(
        f"/licenses/{quote(license_id, safe='')}?tenant_id={tenant_id}"
        f"&notice={quote(notice, safe='')}"
        f"&error_notice={quote(error_notice, safe='')}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# =========================================================
# MANAJEMEN KLIEN
# =========================================================

@app.get("/clients", response_class=HTMLResponse)
async def clients_page(
    request: Request,
    q: str = "",
    notice: str = "",
):
    if not authenticated(request):
        return RedirectResponse(
            "/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    error = None
    clients = []

    try:
        clients = await get_clients()

        keyword = q.strip().lower()

        if keyword:
            clients = [
                client for client in clients
                if keyword in str(
                    client.get("client_name", "")
                ).lower()
                or keyword in str(
                    client.get("client_code", "")
                ).lower()
            ]

    except SupabaseError as exc:
        error = str(exc)

    active_count = sum(
        1 for client in clients
        if client.get("status") == "active"
    )

    inactive_count = sum(
        1 for client in clients
        if client.get("status") == "inactive"
    )

    return render_page(
        request,
        "clients.html",
        active_slug="clients",
        clients=clients,
        keyword=q,
        error=error,
        notice=notice,
        active_count=active_count,
        inactive_count=inactive_count,
        total_count=len(clients),
    )


@app.get("/clients/new", response_class=HTMLResponse)
async def client_new_page(request: Request):
    if not authenticated(request):
        return RedirectResponse(
            "/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not supabase_configured():
        return RedirectResponse(
            "/clients?notice=Konfigurasi+Supabase+belum+lengkap",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return render_page(
        request,
        "client_form.html",
        active_slug="clients",
        page_title="Tambah Klien",
        form_action="/clients/create",
        client={},
        errors=[],
    )


@app.post("/clients/create")
async def client_create(
    request: Request,
    csrf_token: str = Form(...),
    client_code: str = Form(...),
    client_name: str = Form(...),
    contact_person: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    notes: str = Form(""),
):
    if not authenticated(request):
        return RedirectResponse(
            "/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not verify_csrf(request, csrf_token):
        return HTMLResponse(
            "Permintaan tidak valid. Silakan login ulang.",
            status_code=403,
        )

    client = {
        "client_code": client_code.strip().upper(),
        "client_name": client_name.strip(),
        "contact_person": contact_person.strip(),
        "email": email.strip(),
        "phone": phone.strip(),
        "address": address.strip(),
        "notes": notes.strip(),
    }

    errors = validate_client(
        client["client_code"],
        client["client_name"],
    )

    if errors:
        return render_page(
            request,
            "client_form.html",
            active_slug="clients",
            page_title="Tambah Klien",
            form_action="/clients/create",
            client=client,
            errors=errors,
        )

    try:
        await supabase_request(
            "POST",
            "clients",
            params={"select": "id"},
            data=client,
        )

        return RedirectResponse(
            "/clients?notice=Klien+berhasil+ditambahkan",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    except SupabaseError as exc:
        return render_page(
            request,
            "client_form.html",
            active_slug="clients",
            page_title="Tambah Klien",
            form_action="/clients/create",
            client=client,
            errors=[str(exc)],
        )


@app.get(
    "/clients/{client_id}/edit",
    response_class=HTMLResponse,
)
async def client_edit_page(
    request: Request,
    client_id: str,
):
    if not authenticated(request):
        return RedirectResponse(
            "/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        client = await get_client(client_id)

        if not client:
            return RedirectResponse(
                "/clients?notice=Data+klien+tidak+ditemukan",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        return render_page(
            request,
            "client_form.html",
            active_slug="clients",
            page_title="Edit Klien",
            form_action=f"/clients/{client_id}/update",
            client=client,
            errors=[],
        )

    except SupabaseError as exc:
        return RedirectResponse(
            f"/clients?notice={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@app.post("/clients/{client_id}/update")
async def client_update(
    request: Request,
    client_id: str,
    csrf_token: str = Form(...),
    client_code: str = Form(...),
    client_name: str = Form(...),
    contact_person: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    notes: str = Form(""),
):
    if not authenticated(request):
        return RedirectResponse(
            "/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not verify_csrf(request, csrf_token):
        return HTMLResponse(
            "Permintaan tidak valid. Silakan login ulang.",
            status_code=403,
        )

    try:
        existing = await get_client(client_id)

        if not existing:
            return RedirectResponse(
                "/clients?notice=Data+klien+tidak+ditemukan",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        client = {
            "client_code": client_code.strip().upper(),
            "client_name": client_name.strip(),
            "contact_person": contact_person.strip(),
            "email": email.strip(),
            "phone": phone.strip(),
            "address": address.strip(),
            "notes": notes.strip(),
        }

        errors = validate_client(
            client["client_code"],
            client["client_name"],
        )

        if errors:
            return render_page(
                request,
                "client_form.html",
                active_slug="clients",
                page_title="Edit Klien",
                form_action=f"/clients/{client_id}/update",
                client={**existing, **client},
                errors=errors,
            )

        await supabase_request(
            "PATCH",
            "clients",
            params={"id": f"eq.{client_id}"},
            data={
                **client,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        return RedirectResponse(
            f"/clients/{client_id}?notice=Data+berhasil+diperbarui",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    except SupabaseError as exc:
        return RedirectResponse(
            f"/clients?notice={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@app.get(
    "/clients/{client_id}",
    response_class=HTMLResponse,
)
async def client_detail_page(
    request: Request,
    client_id: str,
    notice: str = "",
):
    if not authenticated(request):
        return RedirectResponse(
            "/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        client = await get_client(client_id)

        if not client:
            return RedirectResponse(
                "/clients?notice=Data+klien+tidak+ditemukan",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        return render_page(
            request,
            "client_detail.html",
            active_slug="clients",
            client=client,
            notice=notice,
        )

    except SupabaseError as exc:
        return RedirectResponse(
            f"/clients?notice={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@app.post("/clients/{client_id}/status")
async def client_change_status(
    request: Request,
    client_id: str,
    csrf_token: str = Form(...),
    new_status: str = Form(..., alias="status"),
):
    if not authenticated(request):
        return RedirectResponse(
            "/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not verify_csrf(request, csrf_token):
        return HTMLResponse(
            "Permintaan tidak valid. Silakan login ulang.",
            status_code=403,
        )

    if new_status not in ("active", "inactive"):
        return HTMLResponse(
            "Status klien tidak valid.",
            status_code=400,
        )

    try:
        client = await get_client(client_id)

        if not client:
            return RedirectResponse(
                "/clients?notice=Data+klien+tidak+ditemukan",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        await supabase_request(
            "PATCH",
            "clients",
            params={"id": f"eq.{client_id}"},
            data={
                "status": new_status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        message = (
            "Klien+berhasil+diaktifkan"
            if new_status == "active"
            else "Klien+berhasil+dinonaktifkan"
        )

        return RedirectResponse(
            f"/clients/{client_id}?notice={message}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    except SupabaseError as exc:
        from urllib.parse import quote

        return RedirectResponse(
            f"/clients/{client_id}?notice={quote(str(exc), safe='')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


# =========================================================
# DATA INSTALASI
# =========================================================

INSTALLATION_PRODUCTS = ("CORE", "SURVEY", "PROPOSAL")
INSTALLATION_ENVIRONMENTS = ("production", "staging", "development")
INSTALLATION_STATUSES = ("pending", "active", "maintenance", "failed", "inactive")


async def get_installations():
    result = await supabase_request(
        "GET",
        "installations",
        params={
            "select": "*",
            "order": "created_at.desc",
            "limit": "1000",
        },
    )
    return result or []


async def get_installation(installation_id: str):
    try:
        parsed_id = str(uuid.UUID(installation_id))
    except (ValueError, TypeError, AttributeError):
        return None

    result = await supabase_request(
        "GET",
        "installations",
        params={
            "select": "*",
            "id": f"eq.{parsed_id}",
            "limit": "1",
        },
    )
    return result[0] if result else None


def validate_installation(data, clients):
    errors = []
    client_ids = {str(item.get("id")) for item in clients}

    if str(data.get("client_id", "")) not in client_ids:
        errors.append("Pilih klien yang terdaftar.")

    code = str(data.get("installation_code", "")).strip().upper()
    name = str(data.get("installation_name", "")).strip()
    product = str(data.get("product_code", "")).strip().upper()
    environment = str(data.get("environment", "")).strip().lower()
    current_status = str(data.get("status", "pending")).strip().lower()

    if not code:
        errors.append("Kode instalasi wajib diisi.")
    elif len(code) > 50:
        errors.append("Kode instalasi maksimal 50 karakter.")
    elif not all(char.isalnum() or char in "-_" for char in code):
        errors.append("Kode instalasi hanya boleh berisi huruf, angka, tanda hubung, dan garis bawah.")

    if not name:
        errors.append("Nama instalasi wajib diisi.")
    elif len(name) > 150:
        errors.append("Nama instalasi maksimal 150 karakter.")

    if product not in INSTALLATION_PRODUCTS:
        errors.append("Produk harus CORE, SURVEY, atau PROPOSAL.")

    if environment not in INSTALLATION_ENVIRONMENTS:
        errors.append("Lingkungan instalasi tidak valid.")

    if current_status not in INSTALLATION_STATUSES:
        errors.append("Status instalasi tidak valid.")

    app_url = str(data.get("app_url", "")).strip()
    if app_url and not (app_url.startswith("https://") or app_url.startswith("http://")):
        errors.append("Alamat aplikasi harus diawali http:// atau https://.")

    version = str(data.get("version", "")).strip()
    if len(version) > 30:
        errors.append("Versi aplikasi maksimal 30 karakter.")

    return errors


def normalize_installed_at(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("Tanggal instalasi tidak valid.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def installation_payload(data):
    return {
        "client_id": str(data.get("client_id", "")).strip(),
        "installation_code": str(data.get("installation_code", "")).strip().upper(),
        "product_code": str(data.get("product_code", "")).strip().upper(),
        "installation_name": str(data.get("installation_name", "")).strip(),
        "app_url": str(data.get("app_url", "")).strip() or None,
        "version": str(data.get("version", "")).strip() or None,
        "environment": str(data.get("environment", "production")).strip().lower(),
        "status": str(data.get("status", "pending")).strip().lower(),
        "installed_at": normalize_installed_at(data.get("installed_at")),
        "notes": str(data.get("notes", "")).strip() or None,
    }


# =========================================================
# MANAJEMEN INSTALASI
# =========================================================

@app.get("/installations", response_class=HTMLResponse)
async def installations_page(
    request: Request,
    q: str = "",
    status_filter: str = "",
    notice: str = "",
):
    if not authenticated(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    installations = []
    clients = []
    error = None
    try:
        installations = await get_installations()
        clients = await get_clients()
        client_map = {str(item.get("id")): item for item in clients}
        for item in installations:
            client = client_map.get(str(item.get("client_id")), {})
            item["client_name"] = client.get("client_name", "Klien tidak ditemukan")
            item["client_code"] = client.get("client_code", "-")

        keyword = q.strip().lower()
        if keyword:
            installations = [
                item for item in installations
                if keyword in str(item.get("installation_code", "")).lower()
                or keyword in str(item.get("installation_name", "")).lower()
                or keyword in str(item.get("client_name", "")).lower()
            ]
        if status_filter in INSTALLATION_STATUSES:
            installations = [item for item in installations if item.get("status") == status_filter]
    except SupabaseError as exc:
        error = str(exc)

    counts = {
        "total": len(installations),
        "active": sum(1 for item in installations if item.get("status") == "active"),
        "pending": sum(1 for item in installations if item.get("status") == "pending"),
        "inactive": sum(1 for item in installations if item.get("status") == "inactive"),
    }
    return render_page(
        request,
        "installations.html",
        active_slug="installations",
        installations=installations,
        keyword=q,
        status_filter=status_filter,
        notice=notice,
        error=error,
        counts=counts,
    )


@app.get("/installations/new", response_class=HTMLResponse)
async def installation_new_page(request: Request):
    if not authenticated(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    try:
        clients = await get_clients()
        clients = [item for item in clients if item.get("status") == "active"]
    except SupabaseError as exc:
        return RedirectResponse(f"/installations?notice={quote(str(exc), safe='')}", status_code=status.HTTP_303_SEE_OTHER)

    return render_page(
        request,
        "installation_form.html",
        active_slug="installations",
        page_title="Tambah Instalasi",
        form_action="/installations/create",
        installation={"environment": "production", "status": "pending"},
        clients=clients,
        products=INSTALLATION_PRODUCTS,
        environments=INSTALLATION_ENVIRONMENTS,
        statuses=INSTALLATION_STATUSES,
        errors=[],
    )


@app.post("/installations/create")
async def installation_create(
    request: Request,
    csrf_token: str = Form(...),
    client_id: str = Form(...),
    installation_code: str = Form(...),
    product_code: str = Form(...),
    installation_name: str = Form(...),
    app_url: str = Form(""),
    version: str = Form(""),
    environment: str = Form("production"),
    installation_status: str = Form("pending", alias="status"),
    installed_at: str = Form(""),
    notes: str = Form(""),
):
    if not authenticated(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if not verify_csrf(request, csrf_token):
        return HTMLResponse("Permintaan tidak valid. Silakan login ulang.", status_code=403)

    form_data = {
        "client_id": client_id,
        "installation_code": installation_code,
        "product_code": product_code,
        "installation_name": installation_name,
        "app_url": app_url,
        "version": version,
        "environment": environment,
        "status": installation_status,
        "installed_at": installed_at,
        "notes": notes,
    }
    try:
        clients = [item for item in await get_clients() if item.get("status") == "active"]
        errors = validate_installation(form_data, clients)
        if errors:
            return render_page(request, "installation_form.html", active_slug="installations",
                page_title="Tambah Instalasi", form_action="/installations/create",
                installation=form_data, clients=clients, products=INSTALLATION_PRODUCTS,
                environments=INSTALLATION_ENVIRONMENTS, statuses=INSTALLATION_STATUSES, errors=errors)
        payload = installation_payload(form_data)
        await supabase_request("POST", "installations", params={"select": "id"}, data=payload)
        return RedirectResponse("/installations?notice=Instalasi+berhasil+ditambahkan", status_code=status.HTTP_303_SEE_OTHER)
    except (SupabaseError, ValueError) as exc:
        try:
            clients = [item for item in await get_clients() if item.get("status") == "active"]
        except SupabaseError:
            clients = []
        return render_page(request, "installation_form.html", active_slug="installations",
            page_title="Tambah Instalasi", form_action="/installations/create",
            installation=form_data, clients=clients, products=INSTALLATION_PRODUCTS,
            environments=INSTALLATION_ENVIRONMENTS, statuses=INSTALLATION_STATUSES, errors=[str(exc)])


@app.get("/installations/{installation_id}/edit", response_class=HTMLResponse)
async def installation_edit_page(request: Request, installation_id: str):
    if not authenticated(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    try:
        installation = await get_installation(installation_id)
        if not installation:
            return RedirectResponse("/installations?notice=Data+instalasi+tidak+ditemukan", status_code=status.HTTP_303_SEE_OTHER)
        clients = await get_clients()
        return render_page(request, "installation_form.html", active_slug="installations",
            page_title="Edit Instalasi", form_action=f"/installations/{installation_id}/update",
            installation=installation, clients=clients, products=INSTALLATION_PRODUCTS,
            environments=INSTALLATION_ENVIRONMENTS, statuses=INSTALLATION_STATUSES, errors=[])
    except SupabaseError as exc:
        return RedirectResponse(f"/installations?notice={quote(str(exc), safe='')}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/installations/{installation_id}/update")
async def installation_update(
    request: Request,
    installation_id: str,
    csrf_token: str = Form(...),
    client_id: str = Form(...),
    installation_code: str = Form(...),
    product_code: str = Form(...),
    installation_name: str = Form(...),
    app_url: str = Form(""),
    version: str = Form(""),
    environment: str = Form("production"),
    installation_status: str = Form("pending", alias="status"),
    installed_at: str = Form(""),
    notes: str = Form(""),
):
    if not authenticated(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if not verify_csrf(request, csrf_token):
        return HTMLResponse("Permintaan tidak valid. Silakan login ulang.", status_code=403)

    form_data = {
        "client_id": client_id, "installation_code": installation_code,
        "product_code": product_code, "installation_name": installation_name,
        "app_url": app_url, "version": version, "environment": environment,
        "status": installation_status, "installed_at": installed_at, "notes": notes,
    }
    try:
        existing = await get_installation(installation_id)
        if not existing:
            return RedirectResponse("/installations?notice=Data+instalasi+tidak+ditemukan", status_code=status.HTTP_303_SEE_OTHER)
        clients = await get_clients()
        errors = validate_installation(form_data, clients)
        if errors:
            return render_page(request, "installation_form.html", active_slug="installations",
                page_title="Edit Instalasi", form_action=f"/installations/{installation_id}/update",
                installation={**existing, **form_data}, clients=clients, products=INSTALLATION_PRODUCTS,
                environments=INSTALLATION_ENVIRONMENTS, statuses=INSTALLATION_STATUSES, errors=errors)
        payload = installation_payload(form_data)
        await supabase_request("PATCH", "installations", params={"id": f"eq.{installation_id}"}, data=payload)
        return RedirectResponse(f"/installations/{installation_id}?notice=Data+instalasi+berhasil+diperbarui", status_code=status.HTTP_303_SEE_OTHER)
    except (SupabaseError, ValueError) as exc:
        return RedirectResponse(f"/installations?notice={quote(str(exc), safe='')}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/installations/{installation_id}", response_class=HTMLResponse)
async def installation_detail_page(request: Request, installation_id: str, notice: str = ""):
    if not authenticated(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    try:
        installation = await get_installation(installation_id)
        if not installation:
            return RedirectResponse("/installations?notice=Data+instalasi+tidak+ditemukan", status_code=status.HTTP_303_SEE_OTHER)
        client = await get_client(installation.get("client_id", ""))
        return render_page(request, "installation_detail.html", active_slug="installations",
            installation=installation, client=client, notice=notice)
    except SupabaseError as exc:
        return RedirectResponse(f"/installations?notice={quote(str(exc), safe='')}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/installations/{installation_id}/status")
async def installation_change_status(
    request: Request,
    installation_id: str,
    csrf_token: str = Form(...),
    new_status: str = Form(..., alias="status"),
):
    if not authenticated(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if not verify_csrf(request, csrf_token):
        return HTMLResponse("Permintaan tidak valid. Silakan login ulang.", status_code=403)
    if new_status not in INSTALLATION_STATUSES:
        return HTMLResponse("Status instalasi tidak valid.", status_code=400)
    try:
        installation = await get_installation(installation_id)
        if not installation:
            return RedirectResponse("/installations?notice=Data+instalasi+tidak+ditemukan", status_code=status.HTTP_303_SEE_OTHER)
        await supabase_request("PATCH", "installations", params={"id": f"eq.{installation_id}"}, data={"status": new_status})
        return RedirectResponse(f"/installations/{installation_id}?notice=Status+instalasi+berhasil+diperbarui", status_code=status.HTTP_303_SEE_OTHER)
    except SupabaseError as exc:
        return RedirectResponse(f"/installations/{installation_id}?notice={quote(str(exc), safe='')}", status_code=status.HTTP_303_SEE_OTHER)


# =========================================================
# MENU LAIN YANG MASIH DALAM PENGEMBANGAN
# =========================================================

def create_module_page(module):
    async def module_page(request: Request):
        if not authenticated(request):
            return RedirectResponse(
                "/login",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        return render_page(
            request,
            "modul.html",
            active_slug=module["slug"],
            module=module,
        )

    return module_page


for item in MENU_ITEMS:
    if item["slug"] in (
        "dashboard",
        "clients",
        "installations",
        "licenses",
    ):
        continue

    app.add_api_route(
        item["path"],
        create_module_page(item),
        methods=["GET"],
        response_class=HTMLResponse,
        name=item["slug"],
    )


# =========================================================
# LOGOUT
# =========================================================

@app.post("/logout")
async def logout(
    request: Request,
    csrf_token: str = Form(...),
):
    if not authenticated(request):
        return RedirectResponse(
            "/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not verify_csrf(request, csrf_token):
        return HTMLResponse(
            "Permintaan tidak valid. Silakan muat ulang halaman.",
            status_code=403,
        )

    api_session = request.session.get("universal_api_session")
    if api_session:
        UNIVERSAL_API_SESSIONS.pop(api_session, None)
    request.session.clear()

    return RedirectResponse(
        "/login",
        status_code=status.HTTP_303_SEE_OTHER,
    )
