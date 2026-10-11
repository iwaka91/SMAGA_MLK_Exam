# Panduan V1.0 RC1 — 1 halaman, ikuti berurutan

## A. Supabase (sekali saja)
1. Buat sebuah project Supabase di [supabase.com](https://supabase.com/). Simpan `Project URL` dan `service_role / secret key` **pribadi**, tidak dikirim lewat chat.
2. SQL Editor → jalankan secara urut:
   - `supabase/migrations/001_smaga_schema.sql`
   - `supabase/migrations/002_v06_scoring_shuffle.sql`
   - `supabase/migrations/003_rc_production.sql`
3. Supabase → Authentication → Users: buat pengguna guru/admin dengan **email pribadi khusus Admin dan password kuat**; nonaktifkan pendaftaran publik jika tidak dibutuhkan.
4. SQL Editor: izinkan akun itu menjadi admin (ganti alamat):
   ```sql
   insert into public.staff_roles(user_id, role)
   select id, 'admin' from auth.users where email='ADMIN@CONTOH.SCH.ID'
   on conflict (user_id) do update set role='admin', enabled=true;
   ```
5. Periksa `exam-assets` bucket ada, Public READ sesuai desain, `question_keys` hanya dibaca service-role, **tidak ada policy publik**.

## B. Host Python + Frontend satu alamat (contoh: Render)
1. Unggah kode ini ke repo GitHub **PRIVATE**, periksa `.env` dan key tidak ikut. Render: `New > Blueprint` membaca `render.yaml`.
2. Mode free dalam blueprint **hanya staging/demo**: layanan Free bisa tidur setelah idle. **Jangan pakai Free untuk acara 200 siswa.** Aktifkan layanan **always-on** bila akan digunakan untuk ujian sesungguhnya (biaya mengikuti host pilihan).
3. Isi Environment Variables pada dashboard host (bukan dalam repo):
   - `SUPABASE_URL` = URL Project
   - `SUPABASE_SERVICE_ROLE_KEY` = secret key Supabase
   - `SMAGA_ENV` = `production`
   - `SMAGA_DEMO_MODE` = `0`
   - `SMAGA_SKIP_NUMBAS` = `1` (runtime dibangun di Docker build)
   - `SMAGA_NO_BROWSER` = `1`
   - `SMAGA_PUBLIC_URL` = alamat HTTPS deploy (isi setelah didapat, redeploy bila berubah).
4. Docker build menjalankan `bootstrap_numbas.py`; **build harus gagal** jika runtime resmi Numbas tidak dapat diunduh, agar tidak menyajikan Student Client yang rusak.
5. Setelah deploy, buka `https://ALAMAT/api/health` → `ok:true`, `backend:supabase`, `storage:supabase`, dan `mode:production`.
6. Buka `/admin.html` → masukkan email/password yang diberi role; buat 1 ujian kecil → publish → login dari smartphone → submit → hasil Admin. **Live Board** memerlukan login guru/admin dari perangkat IFP juga.

## C. Gerbang kelulusan sebelum acara massal
1. Jalankan 200–250 simulasi **melalui HTTPS produksi** dengan akun ujian uji dan aset representatif; catat persentase login/submit berhasil, error rate, latensi p95, serta kuota dan CPU/RAM host.
2. Uji Android, iPhone dan IFP secara nyata; reload/resume; server deadline; reset satu peserta; duplikasi submit; gangguan jaringan saat akhir.
3. Coba restore backup database serta periksa penggunaan Storage dan kebijakan cleanup. Lakukan test di luar sesi ujian aktif.
4. Jika tahap C belum lolos, **status tetap RC, jangan sebut production-ready.**

**Mengapa tidak Netlify dulu?** UI+API Python V0.6 sudah lolos. Netlify static tidak menjalankan server Python; pemisahan dua hosting sekarang menambah risiko sinkronisasi. Setelah V1.0 stabil, boleh dipisah ke Netlify + API host atau di-port ke Supabase Edge Functions.
