# SIMPATI Developer Desktop

Aplikasi desktop SIMPATI berbasis Python dan PySide6 untuk menyiapkan
pengelolaan tenant, lisensi, instalasi, modul, pengguna Developer, dan audit.
Aplikasi memakai SIMPATI Universal API untuk koneksi dan autentikasi; Desktop
tidak mengakses database atau License Manager secara langsung.

## Integrasi Universal API

- Login Developer memakai `POST /auth/developer/login` dengan
  `username` dan `password`.
- Jika respons login berisi `user.must_change_password=true`, Desktop
  mewajibkan password baru melalui `POST /auth/password`
  (`current_password`, `new_password`; minimal 12 karakter). Setelah sukses,
  token lokal dihapus dan login ulang dengan password baru diperlukan sebelum
  Dashboard dapat dibuka.
- Pemulihan sesi memakai `GET /auth/me`. Jika access token kedaluwarsa,
  client mencoba `POST /auth/refresh`, menyimpan token hasil rotasi, lalu
  mengulang request satu kali. Refresh token tidak valid mengakhiri sesi lokal.
- Logout memakai `POST /auth/logout` dengan refresh token yang masih aktif.
- Access dan refresh token disimpan melalui Python Keyring ke credential store
  sistem operasi. Password Developer tidak disimpan. Jika secure credential
  store tidak tersedia, aplikasi menampilkan error dan tidak menggunakan
  penyimpanan teks biasa sebagai fallback.
- Status koneksi memeriksa endpoint publik `GET /health/live`; request gagal
  atau API tidak aktif ditampilkan sebagai status terputus.
- Menu Tenant memuat `GET /tenants` memakai access token Developer dan
  permission `tenants.read`. Daftar memakai kontrak pagination API
  `items`, `total`, `limit`, `offset`, lalu mengisi tabel dengan data server.
- Form tambah/edit Tenant memakai `POST /tenants` dan `PATCH /tenants/{id}`.
  Status menggunakan kode API `ACTIVE`, `INACTIVE`, atau `RESTRICTED`; Tenant
  baru dibuat sebagai `ACTIVE` oleh API, lalu status nonaktif/restricted
  diterapkan melalui `PATCH /tenants/{id}/status` dengan alasan wajib
  (3–1000 karakter). Jika langkah kedua gagal, form melaporkan bahwa Tenant
  sudah terbuat sebagai `ACTIVE` atau data identitas sudah diperbarui, lalu
  memuat ulang daftar.
- Field `EMAIL KONTAK` lama tetap ditampilkan, tetapi penyimpanan ditolak jika
  field tersebut diisi karena kontrak Tenant Universal API tidak menyediakan
  field email kontak.
- Endpoint dan payload autentikasi mengikuti kontrak SIMPATI Universal API.
  Menu dan fitur Desktop dipertahankan. Operasi Tenant menggunakan client API
  yang sama; operasi data lain, termasuk lisensi, harus melalui Universal API,
  bukan database Desktop atau License Manager langsung.

## Persiapan dan menjalankan

Gunakan Python 3.10 atau yang lebih baru, lalu dari direktori proyek jalankan:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Jika PowerShell menolak aktivasi environment, jalankan interpreter dan pip
secara langsung melalui `.\.venv\Scripts\python.exe`.

URL Universal API dapat diubah pada halaman Konfigurasi atau langsung dari
dialog Login Developer. Contoh untuk API lokal yang dijalankan pada port 8000:
`http://127.0.0.1:8000`. URL digunakan pada login berikutnya. Gunakan HTTPS
untuk API yang diakses melalui jaringan.

## Menguji login

1. Siapkan SIMPATI Universal API dan database-nya mengikuti instruksi serta
   konfigurasi backend di repository
   [simpati-universal-api](https://github.com/harriesfxpku/simpati-universal-api).
   Jalankan server lokal pada `127.0.0.1:8000` (atau catat base URL deployment
   yang disediakan administrator).
2. Pastikan API telah menyiapkan akun Developer awal melalui mekanisme bootstrap
   backend. Jangan menaruh credential backend, database, atau Supabase service
   role key di Desktop.
3. Jalankan Desktop, masukkan base URL API, username Developer, dan password.
   Desktop memeriksa `/health/live`, melakukan login terhadap endpoint
   `/auth/developer/login`, kemudian membuka Dashboard jika sukses. Jika akun
   mewajibkan rotasi password, ikuti halaman **Ganti Password**, lalu login
   kembali dengan password baru.
4. Status API terlihat pada bar atas dan kartu status Dashboard. Tombol **Keluar**
   memanggil `/auth/logout`; setelah logout aplikasi meminta login kembali.

Jika API tidak tersedia, periksa base URL, kesiapan server, TLS/firewall, dan
konfigurasi backend. Error HTTP dari API ditampilkan pada dialog login. Token
tidak dihapus hanya karena koneksi terputus.

## Pengujian

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m unittest discover -s tests -v
```

Pemeriksaan sintaks seluruh sumber Python:

```powershell
Get-ChildItem -Recurse -Filter *.py |
  Where-Object { $_.FullName -notlike '*\.venv\*' } |
  ForEach-Object { python -m py_compile $_.FullName }
```

## Persiapan installer Windows

Installer belum dibangun. Tentukan terlebih dahulu metadata aplikasi, ikon,
versi Python/PySide6 yang akan didukung, dan mekanisme penandatanganan rilis.
Untuk uji bundling, siapkan Windows build environment, pasang PyInstaller
sebagai dependency build, lalu buat dan uji executable pada mesin Windows
bersih. Distribusi final perlu menyertakan lisensi/notice Qt yang relevan,
konfigurasi endpoint non-secret, dan proses upgrade/uninstall.
