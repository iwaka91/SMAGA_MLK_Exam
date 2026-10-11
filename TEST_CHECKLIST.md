# Checklist akhir V1.0 RC1

**Lokal (tersedia skrip):**
- [x] PG 1 + PGK 1, 1/2 = 50 dan 2/2 = 100 (`E2E_TEST.py`)
- [x] XLSX, acak soal/opsi, upload gambar, token cadangan, submit & Live (`E2E_TEST.py`)
- [x] Admin tidak sah ditolak; mode produksi tanpa key ditolak; student hidden scores; idempotency (`tests/SECURITY_CHECK.py`)
- [x] 200 login dan 200 submit serentak via localhost/mock (`tests/LOAD_LOCAL.py`)

**Sebelum ujian sekolah online (belum):**
- [ ] SQL migrations Supabase di project sungguhan; teacher role JWT bekerja
- [ ] Cloud Docker build Numbas → satu ujian PG/PGK end-to-end pada URL HTTPS
- [ ] Tes upload/cleanup gambar tanpa menghapus gambar yang masih dipakai soal
- [ ] Tes bersamaan 200–250 sesi dengan Supabase sungguhan; peak submit 09:35
- [ ] Pengujian nyata Android + iOS + IFP, reload dan koneksi hilang
- [ ] Backup/restore dan kesiapan supervisor reset-session

**Aturan:** Jangan naik ke V1.0 FINAL bila butir online belum lolos.
