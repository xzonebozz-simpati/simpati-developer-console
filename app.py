import hmac
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="SIMPATI Developer Console",
    description="Pusat kendali ekosistem SIMPATI Universal.",
    version="0.1.0",
)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "CHANGE-ME-BEFORE-DEPLOYMENT"),
    session_cookie="simpati_developer_session",
    max_age=60 * 60 * 8,
    same_site="lax",
    https_only=os.getenv("COOKIE_SECURE", "true").lower() == "true",
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def is_configured() -> bool:
    return bool(
        os.getenv("DEVELOPER_USERNAME")
        and os.getenv("DEVELOPER_PASSWORD")
        and os.getenv("SESSION_SECRET")
    )


def authenticated(request: Request) -> bool:
    return request.session.get("developer_authenticated") is True


@app.get("/health")
async def health():
    return {"status": "ok", "service": "simpati-developer-console", "version": "0.1.0"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if authenticated(request):
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if authenticated(request):
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": None, "configured": is_configured()},
    )


@app.post("/login", response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if not is_configured():
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Konfigurasi akun Developer belum lengkap. Periksa environment variables.", "configured": False},
            status_code=503,
        )

    expected_user = os.environ["DEVELOPER_USERNAME"]
    expected_password = os.environ["DEVELOPER_PASSWORD"]

    valid_user = hmac.compare_digest(username.encode(), expected_user.encode())
    valid_password = hmac.compare_digest(password.encode(), expected_password.encode())

    if not (valid_user and valid_password):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Nama pengguna atau kata sandi tidak sesuai.", "configured": True},
            status_code=401,
        )

    request.session.clear()
    request.session["developer_authenticated"] = True
    request.session["csrf_token"] = secrets.token_urlsafe(32)
    return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not authenticated(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    menu_items = [
        ("Dashboard", "Ringkasan ekosistem SIMPATI", "active"),
        ("Manajemen Klien", "Data organisasi pelanggan", "planned"),
        ("Manajemen Instalasi", "Daftar instalasi aplikasi pelanggan", "planned"),
        ("Manajemen Lisensi", "Akses ke layanan License Manager", "planned"),
        ("Manajemen Paket", "Paket dan pilihan modul", "planned"),
        ("Manajemen Tenant", "Identitas dan branding pelanggan", "planned"),
        ("Manajemen Akun", "Akun Superadmin pelanggan", "planned"),
        ("Manajemen Modul", "Ketersediaan modul aplikasi", "planned"),
        ("Monitoring Sistem", "Kondisi aplikasi dan layanan", "planned"),
        ("Pengaturan Global", "Konfigurasi ekosistem", "planned"),
        ("Audit Log", "Riwayat aktivitas pengembang", "planned"),
    ]
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"menu_items": menu_items, "username": os.getenv("DEVELOPER_USERNAME", "Developer")},
    )


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
