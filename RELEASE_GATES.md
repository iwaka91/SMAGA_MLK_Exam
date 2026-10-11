# Status Gerbang Rilis V1.0 RC1 (10 Oktober 2026)

| Gerbang | Status | Bukti/Batas |
|---|---|---|
| Fitur utama V0.6 tidak regresi | PASS (lokal) | `python E2E_TEST.py` |
| Mode produksi tidak hidup tanpa kredensial | PASS (lokal) | `python tests/SECURITY_CHECK.py` |
| Admin lokal menolak tanpa PIN | PASS (lokal) | `tests/SECURITY_CHECK.py` |
| Hidden student scores & duplicate submit | PASS (lokal) | `tests/SECURITY_CHECK.py` |
| Burst 200 login + 200 submit | PASS (lokal mock) | `python tests/LOAD_LOCAL.py 200` |
| Supabase Auth role JWT sungguhan | BELUM | Harus diuji di project Supabase milik sekolah |
| Migrasi SQL Supabase benar-benar berjalan | BELUM | Tidak ada akses ke project eksternal |
| Hosting Python HTTPS hidup terus | BELUM | Menunggu user mengaktifkan hosting |
| Numbas di cloud + uji 3 browser nyata | BELUM | Build vendor/production perlu dijalankan |
| 200–250 user di Supabase online | BELUM | Perlu staged load test nyata |
| Backup/restore data hasil | BELUM | Perlu prosedur sekolah |

RC1 tidak boleh dipromosikan menjadi **V1.0 Final** sebelum seluruh bagian wajib selesai.
