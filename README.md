# SIMPATI Developer Desktop

Aplikasi desktop SIMPATI berbasis Python dan PySide6 untuk menyiapkan
pengelolaan tenant, lisensi, instalasi, modul, pengguna developer, dan audit.

## Status integrasi

Proyek ini belum menyertakan dokumentasi atau implementasi SIMPATI Universal
API. Karena itu aplikasi menampilkan status **BELUM TERHUBUNG**, tidak membuat
data produksi contoh, dan tidak mengakses database secara langsung. Formulir
pengelolaan hanya memvalidasi input; data tidak dikirim atau disimpan. URL API
dan branding disimpan sebagai konfigurasi lokal. Tidak ada kolom untuk
memasukkan secret key.

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

## Integrasi API mendatang

Sebelum mengaktifkan operasi data, tambahkan dokumentasi API resmi yang
menentukan autentikasi, endpoint, skema, izin, dan perilaku error. Implementasi
client API harus menjadi satu-satunya jalur data, menggunakan transport yang
aman, dan tidak menyertakan kredensial database atau service-role key. Uji
integrasi harus dilakukan terhadap lingkungan API yang disetujui sebelum
mengubah status koneksi menjadi aktif.

## Persiapan installer Windows

Installer belum dibangun. Tentukan terlebih dahulu metadata aplikasi, ikon,
versi Python/PySide6 yang akan didukung, dan mekanisme penandatanganan rilis.
Untuk uji bundling, siapkan Windows build environment, pasang PyInstaller
sebagai dependency build, lalu buat dan uji executable pada mesin Windows
bersih. Distribusi final perlu menyertakan lisensi/notice Qt yang relevan,
konfigurasi endpoint non-secret, dan proses upgrade/uninstall.
