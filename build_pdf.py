"""report.html -> Laporan_Tahap4.pdf via Chrome headless.

Jalankan:  python3 build_pdf.py
"""
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).parent
HTML = HERE / "report.html"
OUT = HERE / "Laporan_Tahap4.pdf"

CHROME_CANDIDATES = [
    "/Applications/Google Chrome Dev.app/Contents/MacOS/Google Chrome Dev",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]

if not HTML.exists():
    print("report.html belum ada, jalankan build_html.py dulu.")
    sys.exit(1)

chrome = next((c for c in CHROME_CANDIDATES if os.path.exists(c)), None)
if not chrome:
    print("Chrome tidak ditemukan, PDF tidak dibuat.")
    sys.exit(2)

if OUT.exists():
    OUT.unlink()

res = subprocess.run(
    [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
     "--print-to-pdf=" + str(OUT), "--no-pdf-header-footer", str(HTML)],
    capture_output=True, text=True,
)
if OUT.exists():
    print("PDF:", OUT, OUT.stat().st_size, "bytes")
else:
    print("PDF GAGAL dibuat. stderr:", res.stderr[-500:])
    sys.exit(3)
