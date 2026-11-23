"""Konverter Laporan_Tahap4.md -> report.html (styled) lalu PDF via Chrome headless.

Jalankan:  python3 build_html.py      (membuat report.html)
           python3 build_pdf.py       (membuat Laporan_Tahap4.pdf dari report.html)

Angka pada tabel rata kanan otomatis. Gambar/img/*.png disemat dari path relatif.
"""
import base64
import html
import pathlib
import re

HERE = pathlib.Path(__file__).parent
SRC = HERE / "Laporan_Tahap4.md"
OUT = HERE / "report.html"

CSS = """
@page { size: A4; margin: 1.8cm 1.5cm 1.9cm 1.5cm; }
* { box-sizing: border-box; }
body { font-family: 'Calibri','Segoe UI',Arial,sans-serif; color:#1b1b1b;
       font-size: 10.8pt; line-height: 1.5; margin:0; text-align: justify; }
h1 { font-size: 17pt; color:#1f3d5c; border-bottom: 3px solid #1f3d5c; padding-bottom:6px;
     margin:0 0 10px; text-align:left; }
h2 { font-size: 13pt; color:#1f3d5c; margin:20px 0 7px; border-bottom:1px solid #cfd8e3;
     padding-bottom:3px; text-align:left; page-break-after: avoid; }
h3 { font-size: 11.3pt; margin:13px 0 5px; color:#24313f; text-align:left;
     page-break-after: avoid; }
p { margin:6px 0; text-align: justify; }
ul, ol { margin:6px 0 8px 20px; }
li { margin:2px 0; text-align: justify; }
table { border-collapse: collapse; width:100%; margin:10px 0 12px; font-size:9.2pt;
        page-break-inside: avoid; }
th, td { border:1px solid #9bb0c4; padding:4px 6px; vertical-align:top; }
th { background:#1f3d5c; color:#fff; font-weight:600; text-align:left; }
td.num { text-align:right; }
caption { caption-side: top; text-align:left; font-weight:600; font-size:9.4pt;
          color:#24313f; margin:12px 0 4px; page-break-after: avoid; }
pre.code { background:#f3f5f7; border:1px solid #c9d3dd; border-left:4px solid #1f3d5c;
           padding:8px 10px; font-family:'Consolas','Courier New',monospace; font-size:8.4pt;
           white-space:pre-wrap; line-height:1.3; margin:8px 0; page-break-inside: avoid; }
b { color:#16263a; }
img { max-width:78%; display:block; margin:8px auto 10px; border:1px solid #c9d3dd; }
.toc { background:#f7f9fb; border:1px solid #cfd8e3; padding:10px 14px; margin:10px 0 16px; }
.toc ol { margin:4px 0 0 18px; }
.toc li { margin:2px 0; }
h2.toc-h { background:none; border:none; margin:18px 0 4px; padding:0; }
.figcap { text-align:center; font-size:9pt; color:#46586b; margin:-6px 0 12px; }
"""

NUM_RE = re.compile(r"^\s*[-+]?[\d.,]+\s*(%|\s*ms)?\s*$")


def esc(t):
    return html.escape(t, quote=False)


def rich(t):
    out = []
    for p in re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*)", t):
        if not p:
            continue
        if p.startswith("**") and p.endswith("**"):
            out.append("<b>%s</b>" % esc(p[2:-2]))
        elif p.startswith("*") and p.endswith("*"):
            out.append("<i>%s</i>" % esc(p[1:-1]))
        else:
            out.append(esc(p))
    return "".join(out)


def is_num(t):
    return bool(NUM_RE.match(t)) and any(ch.isdigit() for ch in t)


def img_tag(src, alt):
    path = (HERE / src)
    if not path.exists():
        return '<p style="color:#a00">[gambar tidak ditemukan: %s]</p>' % esc(src)
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode()
    return '<img src="data:%s;base64,%s" alt="%s">' % (mime, data, esc(alt))


body = []
lines = SRC.read_text(encoding="utf-8").splitlines()
i, n = 0, len(lines)
in_toc = False
while i < n:
    ln = lines[i]
    if ln.strip() == "":
        i += 1
        continue

    if ln.startswith("```"):
        i += 1
        code = []
        while i < n and not lines[i].startswith("```"):
            code.append(lines[i])
            i += 1
        i += 1
        body.append('<pre class="code">%s</pre>' % esc("\n".join(code)))
        continue

    # tabel markdown
    if ln.lstrip().startswith("|") and i + 1 < n and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
        header = [c.strip() for c in ln.strip().strip("|").split("|")]
        i += 2
        rows = []
        while i < n and lines[i].lstrip().startswith("|"):
            cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            cells += [""] * (len(header) - len(cells))
            rows.append(cells[: len(header)])
            i += 1
        #_caption baris sebelum tabel (bold) jika ada
        cap = ""
        if body and body[-1].startswith("<p class='cap'>"):
            cap = body.pop()
        out = []
        if cap:
            out.append(cap)
        out.append("<table><thead><tr>")
        for c in header:
            cls = ' class="num"' if is_num(c) else ""
            out.append("<th%s>%s</th>" % (cls, rich(c)))
        out.append("</tr></thead><tbody>")
        for r in rows:
            out.append("<tr>")
            for c in r:
                cls = ' class="num"' if is_num(c) else ""
                out.append("<td%s>%s</td>" % (cls, rich(c)))
            out.append("</tr>")
        out.append("</tbody></table>")
        body.append("".join(out))
        continue

    if ln.startswith("### "):
        body.append("<h3>%s</h3>" % rich(ln[4:].strip()))
        i += 1
        continue
    if ln.startswith("## "):
        title = ln[3:].strip()
        if title == "Daftar Isi":
            body.append('<h2 class="toc-h">Daftar Isi</h2><div class="toc"><ol>')
            in_toc = True
            i += 1
            continue
        body.append("<h2>%s</h2>" % rich(title))
        i += 1
        continue
    if ln.startswith("# "):
        body.append("<h1>%s</h1>" % rich(ln[2:].strip()))
        i += 1
        continue

    # daftar isi: gather sampai "---"
    if in_toc:
        if ln.strip() == "---":
            body.append("</ol></div>")
            in_toc = False
            i += 1
            continue
        m = re.match(r"^\d+\.\s+(.*)$", ln.strip())
        if m:
            body.append("<li>%s</li>" % rich(m.group(1)))
        i += 1
        continue

    # gambar
    m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", ln.strip())
    if m:
        body.append(img_tag(m.group(2), m.group(1)))
        i += 1
        continue

    # hr
    if re.fullmatch(r"-{3,}", ln.strip()):
        body.append("<hr>")
        i += 1
        continue

    # bullet / numbered list
    bullet = re.match(r"^([-*])\s+", ln.lstrip())
    numbered = re.match(r"^\d+\.\s+", ln.lstrip())
    if bullet or numbered:
        ordered = bool(numbered)
        tag = "ol" if ordered else "ul"
        items = []
        while i < n:
            s = lines[i].strip()
            if not s:
                break
            if ordered and re.match(r"^\d+\.\s+", s):
                items.append("<li>%s</li>" % rich(re.sub(r"^\d+\.\s+", "", s)))
            elif not ordered and re.match(r"^[-*]\s+", s):
                items.append("<li>%s</li>" % rich(re.sub(r"^[-*]\s+", "", s)))
            else:
                break
            i += 1
        body.append("<%s>%s</%s>" % (tag, "".join(items), tag))
        continue

    # paragraf biasa
    if ln.startswith("**Gambar ") and ln.rstrip().endswith("."):
        body.append('<p class="cap"><b>%s</b></p>' % rich(ln.strip()))
        i += 1
        continue
    body.append("<p>%s</p>" % rich(ln.strip()))
    i += 1

doc = ("<!DOCTYPE html><html><head><meta charset='utf-8'><title>Laporan Tubes Tahap 4</title>"
       "<style>%s</style></head><body>%s</body></html>" % (CSS, "".join(body)))
OUT.write_text(doc, encoding="utf-8")
print("Saved", OUT, OUT.stat().st_size, "bytes")
