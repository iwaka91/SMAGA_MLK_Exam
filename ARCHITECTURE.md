# SMAGA Maliku Exam — V1.0 Release Candidate 1

**Keputusan:** mempertahankan Student/Admin/Live web dari V0.6, Numbas headless dan scorer Python terpisah untuk meminimalkan risiko regresi. Satu Python web service melayani UI + API di satu origin; Supabase menjadi Auth/PostgREST DB/Storage.

## Boundary
- Browser siswa: hanya mendapat paket soal TANPA key dan catatan rahasia, menyimpan jawaban pada IndexedDB, submit satu batch memakai opaque `session_id`.
- Browser guru: login Supabase email/password melalui endpoint backend, menyimpan token sesi di `sessionStorage`, mengirim bearer JWT pada setiap Admin request.
- Python API: memverifikasi Auth user dan `staff_roles`, menggunakan service-role untuk akses DB; tetap menjaga kunci/server scoring; audit mutations.
- Supabase: RLS enabled pada tabel inti; hanya service-role dipakai server. `exam-assets` public READ, WRITE/DELETE via server saja.
- Live Board: petugas masuk dengan credential guru/admin sendiri; menampilkan token dan leaderboard hanya kepada petugas yang berhasil login.
- Developer lokal: backend JSON mock + PIN 2026. Production dengan PORT dari host tidak dapat menggunakan mode ini.

## Reliability
- Unique `(exam_id, participant_number)` untuk sesi peserta dan unique `session_id` pada hasil di Supabase.
- Idempotency key + SHA256 payload; replay identik boleh, variasi ditolak.
- Grace **120 detik** setelah `end_at` untuk transfer/konfirmasi di jaringan yang lambat, bukan tambahan waktu mengerjakan di UI.
- Paket diambil sesudah login; shuffle deterministik per session; client tidak mengirim progress/heartbeat.
- Files gambar aktif terproteksi dari cleanup otomatis, termasuk saat storage di ambang warning.

## Why single host now?
Netlify melayani static files, bukan `server.py`. Port ulang ke Edge Functions akan mengubah banyak bagian yang sudah teruji; RC1 memilih deployment 1 host Python + Supabase dulu, dan Netlify bisa menjadi langkah terpisah setelah V1.0 stabil.

## Important unknowns
Belum dites dengan project Supabase online, DNS HTTPS, Numbas vendor deployment cloud, load 250 peserta nyata, backup/restore, maupun perangkat lapangan. Seluruhnya tercatat di `RELEASE_GATES.md`.
