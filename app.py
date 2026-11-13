import hmac
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from fastapi import FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware


BASE_DIR = Path(__file__).resolve().parent
APP_VERSION = "0.3.1"

app = FastAPI(
    title="SIMPATI Developer Console",
    description="Pusat kendali ekosistem SIMPATI Universal.",
    version=APP_VERSION,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv(
        "SESSION_SECRET",
        "CHANGE-ME-BEFORE-DEPLOYMENT",
    ),
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
    if item["slug"] in ("dashboard", "clients"):
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

    request.session.clear()

    return RedirectResponse(
        "/login",
        status_code=status.HTTP_303_SEE_OTHER,
    )
