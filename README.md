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
- Dashboard memuat jumlah Tenant dari `GET /tenants`, jumlah instalasi dari
  metadata `total` pada `GET /tenants/{tenant_id}/installations`, jumlah modul
  dari `GET /modules`, dan aktivitas terbaru dari `GET /auth/audit-logs`.
  Data dashboard dapat dimuat ulang. Jika request gagal, status dan detail
  error ditampilkan; kartu lisensi ditandai belum tersedia karena Universal
  API saat ini belum menyediakan endpoint lisensi.
- Menu Tenant memuat `GET /tenants` memakai access token Developer dan
  permission `tenants.read`. Daftar memakai kontrak pagination API
  `items`, `total`, `limit`, `offset`, lalu mengisi tabel dengan data server.
- Menu Instalasi memuat Tenant melalui `GET /tenants` (`tenants.read`), lalu
  mengambil instalasi tiap Tenant melalui `GET /tenants/{tenant_id}/installations`
  (`tenants.installations.read`). Respons pagination dan field model
  `TenantInstallation` divalidasi sebelum ditampilkan. Tabel dan detail
  menyajikan ID/status instalasi, identitas Tenant, serta ID/nama/platform/
  versi dan detail perangkat; installation key tidak ditampilkan. Detail aktif
  dibaca melalui
  `GET /tenants/{tenant_id}/installations/{installation_id}` dengan permission
  yang sama. Opsi instalasi dicabut memakai endpoint
  `GET /tenants/{tenant_id}/installations/recycle-bin`; detailnya memakai data
  aktual dari respons recycle-bin karena endpoint detail hanya membaca
  instalasi yang belum dihapus. API belum menyediakan endpoint instalasi
  global; daftar Desktop merupakan penggabungan data endpoint per-Tenant.
- Menu Modul Sistem membaca katalog dan status `is_active` dari
  `GET /modules?include_inactive=true` dan detail dari
  `GET /modules/{module_id}` (`modules.read`). Pembuatan memakai
  `POST /modules`; perubahan nama/deskripsi dan status katalog memakai
  `PATCH /modules/{module_id}` (`modules.manage`).
  Detail modul juga memuat assignment Tenant dari
  `GET /tenants/{tenant_id}/modules` (`tenant.modules.read`), digabung dengan
  Tenant dari `GET /tenants` (`tenants.read`). API belum menyediakan endpoint
  penggunaan modul lintas Tenant; Desktop membaca data per-Tenant. Status
  katalog, status assignment Tenant, dan lisensi adalah konsep terpisah.
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
- Menu Lisensi menggunakan `GET /tenants/{tenant_id}/modules`,
  `POST /tenants/{tenant_id}/modules`, dan
  `DELETE /tenants/{tenant_id}/modules/{module_code}` hanya untuk membaca
  serta mengubah assignment modul Tenant. Permission backend masing-masing
  adalah `tenant.modules.read` dan `tenant.modules.manage`. Assignment modul
  bukan lisensi dan tidak memberi atau memvalidasi hak lisensi.
- Endpoint dan payload autentikasi mengikuti kontrak SIMPATI Universal API.
  Menu dan fitur Desktop dipertahankan. Operasi Tenant menggunakan client API
  yang sama; operasi data lain, termasuk lisensi, harus melalui Universal API,
  bukan database Desktop atau License Manager langsung.

## Kebutuhan pengembangan SIMPATI Universal API: Lisensi

Pemeriksaan API saat ini menemukan model assignment modul (`TenantModule`),
tetapi tidak menemukan model Lisensi, router, atau endpoint pengelolaan lisensi.
API utama juga tidak memasang router License Manager. Karena itu Desktop tidak
membuat daftar atau menyimpan data lisensi lokal.

Backend perlu menyediakan kontrak dan model lisensi yang mendukung:

- Membaca dan membuat lisensi untuk Tenant dengan ID dan paket yang valid.
- Mengubah atau menetapkan masa berlaku dan batas penggunaan.
- Membaca serta mengubah status lisensi dengan aturan transisi yang jelas.
- Mengaitkan modul yang diotorisasi ke lisensi, tanpa menyamakan assignment
  modul Tenant yang sudah ada dengan hak lisensi.
- Validasi kepemilikan Tenant, paket, rentang tanggal, batas penggunaan, status,
  dan modul; otorisasi berbasis permission serta audit untuk perubahan.
- Kontrak pagination/filter untuk daftar, bentuk respons/error yang stabil,
  dan endpoint baca/detail serta operasi create/update yang terdokumentasi.

Setelah kontrak tersebut tersedia, Desktop dapat mengimplementasikan
pengelolaan lisensi tanpa menyentuh database atau License Manager secara
langsung.

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
