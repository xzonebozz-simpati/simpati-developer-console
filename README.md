# SIMPATI Developer Console

Aplikasi Developer Console untuk mengelola ekosistem SIMPATI Universal.

## Fitur

- FastAPI application.
- Halaman login Developer berbasis environment variables dan autentikasi Developer Universal API.
- Session cookie HTTP-only dari Starlette SessionMiddleware.
- Manajemen klien dan instalasi berbasis Supabase.
- Manajemen lisensi Tenant melalui SIMPATI Universal API: daftar lisensi lintas Tenant, penerbitan Serial Key, paket/modul, masa berlaku, perpanjangan, kapasitas, status, detail, dan riwayat.
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
- `UNIVERSAL_API_BASE_URL`: base URL SIMPATI Universal API; default `https://simpatiuniapi.hostless.app`.

Gunakan akun Developer yang terdaftar pada Universal API untuk masuk; `DEVELOPER_USERNAME` dan `DEVELOPER_PASSWORD` harus cocok dengan akun tersebut. Console hanya mengirim permintaan lisensi ke Universal API; Universal API meneruskannya ke License Manager yang tetap menjadi sumber data lisensi dan pembuat Serial Key. Console tidak menyimpan atau menerbitkan Serial Key secara lokal.

Jangan commit `.env` atau memasukkan kredensial ke GitHub.

## Catatan keamanan dan batas tahap

Ini adalah fondasi awal, belum merupakan sistem autentikasi final untuk penggunaan luas. Sebelum dipakai sebagai layanan operasional, perlu ditambahkan pembatasan percobaan login, perlindungan CSRF untuk seluruh aksi berbasis formulir, pengelolaan akun yang aman, rotasi session, audit autentikasi, dan pengujian keamanan.

Data lisensi, paket, modul, dan riwayat dibaca/diubah hanya melalui endpoint Universal API. Fitur klien dan instalasi tetap menggunakan koneksi Supabase yang sudah ada.

## Deployment

Aplikasi mendengarkan `0.0.0.0` dan menggunakan environment variable `PORT`. Perintah container sudah tersedia di `Dockerfile`.
