# Security Notes — V1.0 RC1

- Mode `SMAGA_ENV=production` **wajib** memiliki konfigurasi Supabase; fail-closed. Host dengan environment `PORT` menolak mode development.
- Tidak ada akses PIN Admin saat production. Login memakai Supabase Auth + role `staff_roles`.
- JWT role dicek server; browser tidak pernah menerima Supabase service-role key atau tabel jawaban.
- Token utama dan token cadangan adalah kredensial peserta sementara; jangan disebar di halaman publik. Live Board hanya untuk petugas login.
- Submit deadline enforced di server dengan transport grace 120 detik; official answer key tetap server-only; hidden score tidak dikirim ke siswa.
- Pembatasan login in-memory berlaku per satu proses; untuk banyak instance/serangan bot gunakan WAF/rate limiter di depan API.
- Link mirror gambar ditolak bila private network, redirect, MIME tidak sesuai. Proteksi SSRF tingkat jaringan tetap disarankan.
- Tidak ada fitur penguncian BYOD penuh; butuh native app/device-owner untuk kiosk kuat.
- **Kelemahan sebelum final:** identitas peserta tidak terikat roster resmi, audit online, backup, performance Supabase dan deteksi abuse skala besar belum tervalidasi.