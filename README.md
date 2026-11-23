# Tubes Kecerdasan Buatan Tahap 4: Basis Pengetahuan, Logika, dan Automated Planning

Permainan grid *Ksatria vs Naga* yang memadukan seluruh materi tubes: pencarian informed,
pencarian adversarial, pemenuhan kendala, basis pengetahuan, perencanaan otomatis, dan
pengambilan keputusan dalam kondisi tidak pasti.

Mata kuliah Kecerdasan Buatan, Universitas Pendidikan Indonesia.
Anggota Kelompok 13: Azzam Muhammad Naufal, Salman Ghiffari, Zora Riyadhul Jinan.

## Ringkasan

Empat agen hidup bersama di satu peta: ksatria (pemain), naga, goblin, dan penyihir. Perilaku
ketiga NPC bukan ditulis manual per agen, melainkan diturunkan dari satu basis pengetahuan
yang sama. Basis pengetahuan itu berada di file terpisah `kb.txt`, sehingga menambah perilaku
baru cukup dengan menambahkan aturan, tanpa menyentuh kode Python.

Pipeline keputusan tiap giliran:

```
persepsi -> inferensi forward chaining -> penentuan tujuan -> perencanaan STRIPS
          -> expected utility / MDP -> eksekusi aksi
```

## Isi Repository

| Berkas | Keterangan |
|--------|------------|
| `index.html` | Aplikasi web (PyScript + Canvas), seluruh antarmuka dan panel debug |
| `main.py` | `GridMap`, `Pathfinding` (UCS/A*), battle engine (Minimax/Alpha-Beta/Expectimax), `LevelCSP`, dan lapisan tampilan |
| `kb.txt` | Basis pengetahuan: 44 fakta statis dan 28 aturan Horn dengan prioritas |
| `kb_engine.py` | Parser KB, forward chaining ronde sinkron, pelacakan jejak penurunan |
| `planner.py` | STRIPS: definisi operator, UCS, A* goal-count, A* h_max |
| `decision.py` | Model hasil aksi, expected utility, value iteration MDP |
| `agents.py` | `WorldSim`: persepsi, inferensi, keputusan, perencanaan, eksekusi |
| `experiments_agents.py` | Eksperimen headless untuk KB, planner, dan MDP |
| `experiments_battle.py` | Eksperimen headless untuk battle engine |
| `experiments_search.py` | Eksperimen headless untuk pathfinding dan generator level |
| `hasil_agents.json` | Data mentah eksperimen KB, planner, dan MDP |
| `hasil_battle.json` | Data mentah eksperimen battle engine |
| `hasil_search.json` | Data mentah eksperimen pathfinding dan generator level |
| `Laporan_Tahap4.md` | Laporan sumber (Markdown) |
| `Laporan_Tahap4.docx` | Laporan final (Word) |
| `Laporan_Tahap4.pdf` | Laporan final (PDF) |
| `build_html.py` | Konverter Markdown ke HTML untuk dicetak jadi PDF |
| `build_pdf.py` | Cetak `report.html` ke PDF lewat Chrome headless |
| `build_docx.py` | Konverter Markdown ke DOCX (butuh `python-docx`) |

## Menjalankan Aplikasi

Aplikasi berjalan sepenuhnya di browser tanpa server khusus, namun modul-modul Python
diambil lewat protokol `file`, sehingga paling aman dijalankan lewat server statis lokal.

```bash
cd "Tubes/Tahap 4"
python3 -m http.server 8899
```

Buka `http://localhost:8899/index.html`. PyScript memuat Pyodide dari CDN, jadi koneksi
internet diperlukan pada muat pertama.

Kontrol: gerakkan ksatria dengan tombol panah atau WASD. Jarak Manhattan ksatria dan naga
yang tidak lebih dari dua memicu mode battle turn-based.

## Menjalankan Eksperimen

Eksperimen berjalan tanpa browser dan menghasilkan data JSON yang dipakai laporan.

```bash
python3 experiments_agents.py     # KB, planner, MDP   -> hasil_agents.json
python3 experiments_battle.py     # battle engine      -> hasil_battle.json
python3 experiments_search.py     # pathfinding, CSP   -> hasil_search.json
```

## Membangun Laporan

```bash
python3 build_html.py && python3 build_pdf.py          # PDF lewat Chrome headless

python3 -m venv .venv && .venv/bin/pip install python-docx
.venv/bin/python build_docx.py                          # DOCX
```

## Hasil Eksperimen Ringkas

| Eksperimen | Angka kunci | Simpulan |
|------------|-------------|----------|
| Skala inferensi KB | 0,55 sampai 1,26 ms; 2 sampai 3 ronde | Inferensi cukup murah untuk tiap giliran |
| Ablations aturan KB | Tanpa R1-R6: 0 fakta turunan | Aturan turunan adalah fondasi, bukan lapisan tambahan |
| Automated planning | Biaya 12,02 seragam; A* h_max 18 kali lebih lambat | A* goal-count terbaik pada domain dangkal |
| Discount factor MDP | Iterasi 8 sampai 11; kebijakan stabil di gamma 0,80 | Gamma 0,95 titik tengah yang wajar |
| Mode keputusan | Kabur 18,9 vs 5,1 vs 2,5 per seed | MDP menghasilkan perilaku paling jarang agresif |
| Informed search | Node 304,3 vs 194,5; biaya sama 39,7 | A* Manhattan menghemat 36,1 persen node |
| Generator level | Skor -27,45 vs -15,52 vs 63,37 | Mode gabungan menghasilkan level terbaik |
| Ablations CSP | Tanpa LCV: 13,69 ms vs 54,36 ms | Biaya tiap komponen bergantung pada kondisi domain |
| Battle engine | Node 1872 vs 298 pada kedalaman 8 | Alpha-Beta menghemat 84,1 persen node |

## Catatan Teknis

Logika permainan sepenuhnya terpisah dari lapisan tampilan. Modul Python murni tidak
menyentuh DOM, sehingga algoritma yang dijalankan skrip eksperimen identik dengan yang
dipakai pemain. Angka pada laporan berasal dari kode yang sama dengan aplikasi, bukan
ditulis manual.

Semua angka pada laporan memakai pemisah desimal koma mengikuti ejaan bahasa Indonesia.
