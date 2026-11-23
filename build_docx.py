"""Konverter Laporan_Tahap4.md -> Laporan_Tahap4.docx

Jalankan:  .venv/bin/python build_docx.py

Menangani heading (#/##/###), paragraf, tabel markdown (angka rata kanan),
blok kode, daftar bullet/nomor, baris bold sebagai caption tabel, dan gambar.

Butuh python-docx: python3 -m venv .venv && .venv/bin/pip install python-docx
"""
import pathlib
import re

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = pathlib.Path(__file__).parent
SRC = HERE / "Laporan_Tahap4.md"
OUT = HERE / "Laporan_Tahap4.docx"

ACCENT = RGBColor(0x1F, 0x3D, 0x5C)
NUM_RE = re.compile(r"^\s*[-+]?[\d.,]+\s*(%|\s*ms)?\s*$")

doc = Document()

# ---- gaya halaman dan paragraf ----
sec = doc.sections[0]
sec.top_margin = Cm(1.8)
sec.bottom_margin = Cm(1.9)
sec.left_margin = Cm(1.5)
sec.right_margin = Cm(1.5)

normal = doc.styles["Normal"]
normal.font.name = "Calibri"
normal.font.size = Pt(10.8)
normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
pf = normal.paragraph_format
pf.line_spacing = 1.15
pf.space_after = Pt(6)
pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY


def is_num(t):
    return bool(NUM_RE.match(t)) and any(ch.isdigit() for ch in t)


def add_rich(par, text):
    """Parse **bold** dan *italic* tanpa nesting."""
    for p in re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*)", text):
        if not p:
            continue
        if p.startswith("**") and p.endswith("**"):
            r = par.add_run(p[2:-2])
            r.bold = True
        elif p.startswith("*") and p.endswith("*"):
            r = par.add_run(p[1:-1])
            r.italic = True
        else:
            par.add_run(p)


def shade(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = tcPr.makeelement(qn("w:shd"), {})
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hexcolor)
    tcPr.append(shd)


def add_table(header, rows):
    t = doc.add_table(rows=len(rows) + 1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = True
    for ci, c in enumerate(header):
        cell = t.cell(0, ci)
        cell.text = ""
        par = cell.paragraphs[0]
        par.paragraph_format.space_after = Pt(2)
        run = par.add_run(c.strip())
        run.bold = True
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        shade(cell, "1F3D5C")
    for ri, row in enumerate(rows, start=1):
        for ci, c in enumerate(row):
            cell = t.cell(ri, ci)
            cell.text = ""
            par = cell.paragraphs[0]
            par.paragraph_format.space_after = Pt(2)
            par.paragraph_format.line_spacing = 1.0
            add_rich(par, c.strip())
            for r in par.runs:
                r.font.size = Pt(9)
            if is_num(c):
                par.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            if ri % 2 == 0:
                shade(cell, "F4F7FA")
    doc.add_paragraph().paragraph_format.space_after = Pt(4)
    return t


lines = SRC.read_text(encoding="utf-8").splitlines()
i, n = 0, len(lines)
pending_caption = None
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
        cp = doc.add_paragraph()
        cp.paragraph_format.left_indent = Cm(0.6)
        cp.paragraph_format.space_after = Pt(8)
        cp.paragraph_format.line_spacing = 1.0
        cr = cp.add_run("\n".join(code))
        cr.font.name = "Consolas"
        cr.font.size = Pt(8.5)
        cr.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
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
        if pending_caption:
            cp = doc.add_paragraph()
            cp.paragraph_format.space_before = Pt(8)
            cp.paragraph_format.space_after = Pt(3)
            cp.paragraph_format.keep_with_next = True
            add_rich(cp, pending_caption)
            for r in cp.runs:
                r.bold = True
                r.font.size = Pt(9.5)
                r.font.color.rgb = ACCENT
            pending_caption = None
        add_table(header, rows)
        continue

    if ln.startswith("### "):
        h = doc.add_heading(ln[4:].strip(), level=3)
        h.paragraph_format.space_before = Pt(10)
        h.paragraph_format.space_after = Pt(4)
        h.paragraph_format.keep_with_next = True
        for r in h.runs:
            r.font.color.rgb = ACCENT
            r.font.size = Pt(11.3)
        i += 1
        continue

    if ln.startswith("## "):
        title = ln[3:].strip()
        if title == "Daftar Isi":
            h = doc.add_heading(title, level=2)
            h.paragraph_format.space_before = Pt(10)
            h.paragraph_format.space_after = Pt(4)
            for r in h.runs:
                r.font.color.rgb = ACCENT
            in_toc = True
            i += 1
            continue
        h = doc.add_heading(title, level=2)
        h.paragraph_format.space_before = Pt(14)
        h.paragraph_format.space_after = Pt(5)
        h.paragraph_format.keep_with_next = True
        for r in h.runs:
            r.font.color.rgb = ACCENT
            r.font.size = Pt(13)
        i += 1
        continue

    if ln.startswith("# "):
        h = doc.add_heading(ln[2:].strip(), level=1)
        h.paragraph_format.space_after = Pt(10)
        for r in h.runs:
            r.font.color.rgb = ACCENT
            r.font.size = Pt(17)
        i += 1
        continue

    # daftar isi
    if in_toc:
        if ln.strip() == "---":
            in_toc = False
            i += 1
            continue
        m = re.match(r"^\d+\.\s+(.*)$", ln.strip())
        if m:
            p = doc.add_paragraph(style="List Number")
            p.paragraph_format.space_after = Pt(1)
            p.paragraph_format.left_indent = Cm(0.8)
            p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
            add_rich(p, m.group(1))
            for r in p.runs:
                r.font.size = Pt(10.5)
        i += 1
        continue

    # gambar
    m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", ln.strip())
    if m:
        path = HERE / m.group(2)
        if path.exists():
            ip = doc.add_paragraph()
            ip.alignment = WD_ALIGN_PARAGRAPH.CENTER
            ip.paragraph_format.space_before = Pt(6)
            ip.paragraph_format.space_after = Pt(3)
            ip.add_run().add_picture(str(path), width=Cm(12.5))
        i += 1
        continue

    if re.fullmatch(r"-{3,}", ln.strip()):
        i += 1
        continue

    # caption tabel / gambar: baris dengan label bold di awal, mis. **Tabel 1.** ...
    if re.match(r"^\*\*(Tabel|Gambar)\s+\d+\.\*\*", ln.strip()):
        pending_caption = ln.strip()
        i += 1
        continue

    bullet = re.match(r"^([-*])\s+", ln.lstrip())
    numbered = re.match(r"^\d+\.\s+", ln.lstrip())
    if bullet or numbered:
        style = "List Number" if numbered else "List Bullet"
        buf = []
        while i < n:
            s = lines[i].strip()
            if not s:
                break
            if numbered and re.match(r"^\d+\.\s+", s):
                buf.append(re.sub(r"^\d+\.\s+", "", s))
            elif not numbered and re.match(r"^[-*]\s+", s):
                buf.append(re.sub(r"^[-*]\s+", "", s))
            else:
                break
            i += 1
        for b in buf:
            p = doc.add_paragraph(style=style)
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.left_indent = Cm(0.8)
            add_rich(p, b)
        continue

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    add_rich(p, ln.strip())
    i += 1

doc.save(str(OUT))
print("Saved", OUT, OUT.stat().st_size, "bytes")
