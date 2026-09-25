# VIGILO-INJECTOR

Otomatisasi input **Task** OWL-Plantation (`http://182.23.67.40/vigilo`) tanpa browser.
Script login via HTTP murni dan otomatis, menyimpan sesi, lalu input task massal dari file CSV.

> Menyimpan task (`method=insert`) dan posting task (`method=posting`). **Tidak** melakukan approve/delete.

## Prasyarat

- Python 3.8+
- Paket: `pip install -r requirements.txt`

## Konfigurasi

Isi `.env`:

```
VIGILO_BASE_URL=http://182.23.67.40/vigilo
VIGILO_LOGIN_PATH=slave_login.php
VIGILO_USERNAME=user.anda
VIGILO_PASSWORD=rahasia
VIGILO_LANGUAGE=ID
VIGILO_THEME=skyblue
VIGILO_SESSION_FILE=session.json
VIGILO_KEEPALIVE_SECONDS=240
VIGILO_CLIENT=BKNS
VIGILO_DEVELOPER=0000000021
```

File `.env`, `session.json`, dan `tasks.csv` tidak di-commit (lihat `.gitignore`).

## Alur singkat

```bash
pip install -r requirements.txt
python vigilo.py options      # lihat daftar ID client/modul/tipe/pegawai
python vigilo.py template     # buat tasks.csv berisi contoh
# isi tasks.csv ...
python vigilo.py add          # DRY-RUN (belum kirim)
python vigilo.py add --submit # kirim sungguhan (loop insert)
```

Login & pengelolaan sesi **otomatis**: setiap perintah memuat `session.json` bila ada,
dan hanya login ulang bila sesi sudah expired.

## Perintah

| Perintah | Fungsi |
|---|---|
| `python vigilo.py options` | Tampilkan ID valid: client, modul, tipe, developer, qc |
| `python vigilo.py template [--force]` | Buat `tasks.csv` dari contoh asli server |
| `python vigilo.py svn-import` | Generate `tasks.csv` dari riwayat commit SVN (per commit) |
| `python vigilo.py xlsx [--file CSV] [--output X]` | Buat versi Excel `tasks.xlsx` berborder dari CSV |
| `python vigilo.py add` | Validasi + **dry-run** (tidak mengirim) |
| `python vigilo.py add --submit` | Kirim semua baris (`method=insert`) |
| `python vigilo.py post` | Tampilkan task belum diposting (dry-run) |
| `python vigilo.py post --submit` | Posting task (permanen, konfirmasi `POSTING`) |
| `python vigilo.py progress --template` | Generate `progress.csv` dari task sudah diposting |
| `python vigilo.py progress` | Validasi + **dry-run** progress |
| `python vigilo.py progress --submit` | Simpan progress (`method=simpan_progress`) |
| `python vigilo.py keepalive` | Jaga sesi tetap hidup (ping tiap `VIGILO_KEEPALIVE_SECONDS`) |
| `python vigilo.py recon` | Enumerasi endpoint (debug) |

Opsi `add`:

| Opsi | Default | Keterangan |
|---|---|---|
| `--submit` | mati | Tanpa ini hanya dry-run |
| `--limit N` | 0 (semua) | Batasi jumlah baris, mis. `--limit 1` untuk uji |
| `--delay DETIK` | 0.5 | Jeda antar submit |
| `--file PATH` | `tasks.csv` | File task lain |

Contoh uji satu baris:

```bash
python vigilo.py add --limit 1 --submit
```

## Posting

Posting adalah aksi **permanen** — data yang sudah diposting tidak dapat diubah/dibatalkan.

```bash
python vigilo.py post                  # DRY-RUN: daftar task belum diposting (milik Anda)
python vigilo.py post --submit         # posting (wajib ketik POSTING)
python vigilo.py post --limit 1 --submit
```

Opsi `post`:

| Opsi | Default | Keterangan |
|---|---|---|
| `--submit` | mati | Tanpa ini hanya dry-run |
| `--developer` | `VIGILO_DEVELOPER` | Filter PIC |
| `--status` | `belum_posting` | Filter status |
| `--client` / `--modul` | kosong | Filter tambahan |
| `--limit N` | 0 (semua) | Batasi jumlah |
| `--delay DETIK` | 0.5 | Jeda antar posting |

Alur `--submit`: tampil ringkasan → konfirmasi ketik `POSTING` → posting satu per satu → **verifikasi ulang** status tiap ID dan laporkan sukses/gagal.

## Progress

Input progress PIC (`progresstipe=developer`) untuk task yang **sudah diposting**. Berbeda dari posting, progress bisa diperbarui lagi.

```bash
python vigilo.py progress --template    # buat progress.csv dari task sudah diposting
# isi kolom progress (0-100) dan keterangan ...
python vigilo.py progress               # DRY-RUN validasi
python vigilo.py progress --submit      # simpan (loop)
python vigilo.py progress --limit 1 --submit
```

Format `progress.csv` (pemisah `;`):

```csv
idtask;progress;keterangan;task
796;100;Selesai implementasi approval;Perbaikan Approval
795;50;BA Finger setengah jalan;Pengembangan BA Finger
```

| Kolom | Wajib | Isi |
|---|---|---|
| `idtask` | ya | ID task (dari `--template`) |
| `progress` | ya | Angka 0–100 |
| `keterangan` | ya | Teks keterangan progress |
| `task` | tidak | Hanya info tampilan, tidak dikirim |

Opsi `progress`:

| Opsi | Default | Keterangan |
|---|---|---|
| `--submit` | mati | Tanpa ini dry-run |
| `--template` / `--force` | mati | Generate / timpa `progress.csv` |
| `--file PATH` | `progress.csv` | File progress |
| `--tipe` | `developer` | `developer` atau `qc` |
| `--developer` | `VIGILO_DEVELOPER` | Filter PIC |
| `--limit N` / `--delay D` | 0 / 0.5 | Batasi & jeda |

Validasi: `idtask` harus task `sudah diposting` milik Anda, `progress` 0–100, `keterangan` tidak kosong.
Setelah `--submit`, script memverifikasi ulang kolom Progress PIC tiap ID — mencakup status
`Sudah Diposting`, `PIC Sudah Selesai`, dan `DONE` (karena progress 100% otomatis memindahkan status).

## Impor dari SVN

Membuat `tasks.csv` dari riwayat commit SVN (per commit) secara read-only dari `.svn/wc.db`:

```bash
python vigilo.py svn-import --force
python vigilo.py add            # review dry-run
python vigilo.py add --submit   # kirim
```

Opsi `svn-import`:

| Opsi | Default | Keterangan |
|---|---|---|
| `--svn-path` | `C:\laragon\www\local-bkns` | Path working copy SVN |
| `--author` | `junaidi` | Filter author commit |
| `--output` | `tasks.csv` | File keluaran |
| `--force` | mati | Timpa file yang ada |
| `--client` | `VIGILO_CLIENT` | Kode client |
| `--developer` | `VIGILO_DEVELOPER` | ID developer |
| `--qc` | `0000000016,0000000002` | ID QC (pisah koma) |
| `--deadline` | hari ini | `dd-mm-yyyy` |

Deskripsi task diturunkan dari nama file commit (commit message tidak tersimpan lokal);
`tipe` diestimasi dari jumlah & jenis file (`easy`/`medium`/`hard`/`super hard`).

## Format `tasks.csv`

Header wajib di baris pertama data, diikuti baris task. Pemisah kolom memakai **titik-koma `;`**:

```csv
client;modul;task;tipe;developer;qc;deadline
BKNS;KEBUN;Contoh task deadline otomatis;medium;0000000001;0000000024,0000000053;
CSU;KEU;Contoh task deadline manual;easy;0000000053;0000000029;31-12-2026
```

> Baris contoh pada file yang dihasilkan `template` masih diawali `#` (di-comment) agar tidak ikut ter-submit. Hapus `#` di awal baris untuk mengaktifkannya.

| Kolom | Wajib | Isi |
|---|---|---|
| `client` | ya | ID client, mis. `BKNS`, `CSU` |
| `modul` | ya | ID modul, mis. `KEBUN`, `KEU` |
| `task` | ya | Teks pekerjaan |
| `tipe` | tidak | `easy` / `medium` / `hard` / `super hard` |
| `developer` | ya | ID pegawai, mis. `0000000001` |
| `qc` | ya | ID pegawai; boleh banyak dipisah koma di dalam satu sel |
| `deadline` | tidak | `dd-mm-yyyy`; **kosong = otomatis** dari tipe |

Aturan:

- Pemisah kolom `;`, bukan koma (koma dipakai untuk memisah beberapa `qc`).
- Baris diawali `#` dan baris kosong diabaikan.
- `deadline` otomatis: easy 1 hari, medium 3, hard 7, super hard 10 (dari hari ini).
- Resolver menerima ID; nama masih ditoleransi bila diisi.

### Border visual (Excel)

CSV tidak mendukung border (format teks). Untuk tampilan berborder, generate file Excel dari CSV:

```bash
python vigilo.py xlsx
```

Hasil `tasks.xlsx` (header tebal + border tiap sel, kolom auto-lebar, baris header dibekukan).
Mengubah `tasks.csv` tidak memengaruhi `tasks.xlsx`; jalankan ulang perintah ini setelah CSV diperbarui.

## Catatan

- Kredensial tersimpan plaintext di `.env` — jaga kerahasiaan file ini.
- Login dan sesi ditangani otomatis; tidak ada perintah login terpisah.
- `add` tanpa `--submit` aman untuk memastikan payload benar sebelum kirim.
- Bila sesi expired saat submit, script otomatis login ulang.
- Tersedia operasi simpan/insert (`add`), posting (`post`), dan progress (`progress`); delete/approve tidak disediakan.
- `post` bersifat permanen: selalu jalankan tanpa `--submit` dulu untuk memeriksa daftar.
- `progress` tidak permanen (bisa diperbarui), tetap jalankan dry-run dulu.
