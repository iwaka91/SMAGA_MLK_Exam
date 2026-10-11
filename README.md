# SMAGA Maliku Exam — V1.0 Release Candidate 1

**Tujuan:** mempertahankan seluruh fitur Core V0.6 yang lolos uji, sambil menyiapkan keamanan dan deployment tanpa menulis ulang Numbas atau editor soal.

## Uji lokal (Windows)
1. Ekstrak ZIP pada folder baru (jangan ditimpa ke folder V0.6).
2. Jalankan `START_CORE.bat` (perlu Python 3). Runtime Numbas dicari otomatis dari cache Gate/Core sebelumnya; bila tidak ada akan diunduh dari demo resmi.
3. Browser Admin: `http://localhost:8788/admin.html`. PIN **2026 hanya dalam mode development lokal**.
4. Student: `http://localhost:8788` — Live: `http://localhost:8788/live.html`.
5. Jika ingin regresi tanpa UI: `python E2E_TEST.py`, `python tests/SECURITY_CHECK.py`, `python tests/LOAD_LOCAL.py 200`.

## Isi RC1
- **Fitur soal tetap V0.6:** Numbas headless, PG dan PGK all-or-nothing, kunci klik ala Google Forms, acak soal/opsi, XLSX, gambar, token cadangan, Admin, Live Board.
- **Mode produksi fail-closed:** tidak dapat berjalan tanpa Supabase server credentials valid, tanpa setelan production, atau tanpa runtime Numbas.
- **Admin production:** login email/password Supabase Auth, verifikasi token ke server dan role `admin` / `teacher` di `staff_roles`. PIN lokal tidak berlaku di produksi.
- **Live Board production:** login petugas wajib sebelum akses token dan hasil. Tidak terbuka untuk publik.
- **Submit server:** satu sesi satu hasil resmi, fingerprint dan idempotency key diperiksa, tidak boleh submit sebelum mulai/lebih dari 2 menit setelah akhir (grace jaringan), payload tidak valid ditolak. Hasil yang tidak diizinkan guru tidak ikut dikirim kepada siswa.
- **Gambar:** magic-byte check, mirror URL menolak redirect, lifecycle cleanup melindungi gambar yang masih direferensikan oleh soal/ujian aktif.
- **Audit:** penyimpanan `exam.save`, `exam.delete`, `session.reset`, `asset.upload`, `asset.archive`, dan cleanup dalam DB Supabase.
- **Load local:** skrip simulasi 200 peserta via stdlib. *Bukan* sertifikasi kapasitas produksi.

## Integrasi produksi
Lihat **`DEPLOY_1_HALAMAN.md`**. Backend Python ini harus berjalan di layanan web server online yang mendukung Python/Docker (contoh blueprint Render). **Netlify Static saja tidak dapat menjalankan `server.py`**. Untuk mencegah regresi, RC1 memakai satu layanan host Python (menyajikan Student/Admin/Live) + Supabase (DB/Auth/Storage), bukan langsung port ulang ke Edge Functions.

> **STATUS:** Release Candidate, **belum live / belum lulus uji beban Supabase**. Perlu konfigurasi Supabase, akun Admin, URL hosting dan uji siswa nyata sebelum digunakan ujian sekolah.

## Batasan dan risiko yang masih perlu dibereskan sebelum acara massal
- Simulasi localhost tidak menguji latensi, kuota atau rate limit Supabase/host nyata.
- Pembatasan per-IP saat ini hanya pada satu proses; produksi multi-instance memerlukan rate limit di gateway / WAF.
- Login peserta memakai kode, identitas dan token bersama. Belum ada roster/NIS tervalidasi; supervisor diperlukan untuk mencegah penyamaran peserta.
- Belum ada monitoring alert dan backup terjadwal yang diuji end-to-end.
- Regresi browser Android/iOS/IFP dan runtime Numbas saat deploy online masih harus diuji.
- Runtime Numbas yang belum di-vendor memerlukan unduhan saat build; simpan aset cache dan verifikasi checksum ketika deploy sudah sukses.

**Jangan menaruh `SUPABASE_SERVICE_ROLE_KEY` dalam HTML, JavaScript, ZIP publik, Netlify Static, screenshot atau GitHub repo.**
