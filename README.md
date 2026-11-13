# SIMPATI Developer Console

Fondasi awal aplikasi Developer Console untuk SIMPATI Universal.

## Fitur pada fondasi 0.1.0

- FastAPI application.
- Halaman login Developer berbasis environment variables.
- Session cookie HTTP-only dari Starlette SessionMiddleware.
- Dashboard awal dengan daftar menu dan status "Dalam persiapan".
- Endpoint pemeriksaan kesehatan `/health`.
- Dockerfile untuk deployment berbasis container.

## Menjalankan secara lokal

Gunakan Python 3.11 atau 3.12.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

Salin `.env.example` menjadi `.env`, lalu isi nilai rahasia. Muat environment variables sebelum menjalankan aplikasi.

```bash
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Buka `http://127.0.0.1:8000`.

## Environment variables

- `DEVELOPER_USERNAME`: nama pengguna Developer.
- `DEVELOPER_PASSWORD`: kata sandi Developer.
- `SESSION_SECRET`: rahasia untuk menandatangani session cookie. Gunakan nilai acak yang panjang.
- `COOKIE_SECURE`: `true` pada HTTPS; untuk pengujian lokal HTTP dapat diatur `false`.
- `PORT`: port aplikasi, disediakan platform hosting bila tersedia.

Jangan commit `.env` atau memasukkan kredensial ke GitHub.

## Catatan keamanan dan batas tahap

Ini adalah fondasi awal, belum merupakan sistem autentikasi final untuk penggunaan luas. Sebelum dipakai sebagai layanan operasional, perlu ditambahkan pembatasan percobaan login, perlindungan CSRF untuk seluruh aksi berbasis formulir, pengelolaan akun yang aman, rotasi session, audit autentikasi, dan pengujian keamanan.

Menu selain Dashboard saat ini masih berupa rancangan navigasi, belum terhubung ke database maupun License Manager.

## Deployment

Aplikasi mendengarkan `0.0.0.0` dan menggunakan environment variable `PORT`. Perintah container sudah tersedia di `Dockerfile`.
