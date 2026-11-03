"""Builds small real resume files for the tests: a PDF (with a hidden LinkedIn link), a DOCX (paragraphs + a table + a link)
and the AI reply a model would give for them. All people and companies are invented."""
from __future__ import annotations

import io

SAMPLE_LINES = [
    "Aarav Mehta",
    "Data Analyst | Mumbai, Maharashtra",
    "aarav.mehta@example.org | +91 98765 43210",
    "linkedin.com/in/aarav-mehta | github.com/aaravm",
    "SUMMARY",
    "Analyst who builds dashboards and SQL pipelines for retail and sales teams.",
    "EXPERIENCE",
    "Senior Data Analyst, Northwind Retail   Mar 2020 - Dec 2023",
    "Built Power BI dashboards and SQL pipelines for the sales team.",
    "Data Analyst, Contoso Ltd   Mar 2018 - Feb 2020",
    "Cleaned data in Python and reported weekly KPIs in Excel.",
    "SKILLS: SQL, Python, Power BI, Excel, Tableau",
    "EDUCATION: B.E. in Information Technology, University of Mumbai, 2018",
    "CERTIFICATIONS: Microsoft PL-300",
]

# What a model returns for SAMPLE_LINES. The router never sees the model; tests plug this in.
GOOD_AI = {
    "full_name": "Aarav Mehta",
    "headline": "Senior Data Analyst",
    "current_company": "Northwind Retail",
    "location": "Mumbai, Maharashtra",
    "qualification": "B.E. in Information Technology",
    "skills": ["SQL", "Python", "Power BI", "Excel", "Tableau", "Kubernetes"],  # Kubernetes is not in the resume
    "employers": [
        {"company": "Northwind Retail", "title": "Senior Data Analyst", "start": "2020-03", "end": "2023-12",
         "summary": "Built Power BI dashboards and SQL pipelines for the sales team."},
        {"company": "Contoso Ltd", "title": "Data Analyst", "start": "2018-03", "end": "2020-02",
         "summary": "Cleaned data in Python and reported weekly KPIs in Excel."},
    ],
    "education": [{"degree": "B.E. in Information Technology", "institution": "University of Mumbai", "year": "2018"}],
    "certifications": ["Microsoft PL-300"],
}


def _esc(text: str) -> bytes:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1", "replace")


def make_pdf(lines: list[str], links: tuple[str, ...] = ()) -> bytes:
    """A one-page PDF with the lines as text and each link as a clickable area (like the word 'LinkedIn')."""
    stream = b"BT /F1 11 Tf 50 800 Td 14 TL\n" + b"".join(b"(" + _esc(l) + b") Tj T*\n" for l in lines) + b"ET"
    first_annot = 6
    annots = " ".join(f"{first_annot + i} 0 R" for i in range(len(links)))
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> /Annots [" + annots.encode() + b"] >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, url in enumerate(links):
        y = 700 - 20 * i
        objs.append(
            b"<< /Type /Annot /Subtype /Link /Rect [50 " + str(y).encode() + b" 150 " + str(y + 14).encode() +
            b"] /Border [0 0 0] /A << /S /URI /URI (" + _esc(url) + b") >> >>"
        )
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{n} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def make_docx(lines: list[str], table_rows: list[list[str]] | None = None, link: str | None = None) -> bytes:
    import docx
    from docx.opc.constants import RELATIONSHIP_TYPE as RT

    doc = docx.Document()
    for line in lines:
        doc.add_paragraph(line)
    if table_rows:
        table = doc.add_table(rows=len(table_rows), cols=len(table_rows[0]))
        for r, row in enumerate(table_rows):
            for c, cell in enumerate(row):
                table.cell(r, c).text = cell
    if link:
        doc.part.relate_to(link, RT.HYPERLINK, is_external=True)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def other_resume_lines(name: str, email: str, skill: str = "SQL") -> list[str]:
    """A second, different resume (different bytes, so a different file hash)."""
    return [name, "Business Analyst | Pune", f"{email} | 9123456780", "EXPERIENCE",
            "Business Analyst, Fabrikam Ltd   Jan 2021 - Dec 2022", f"Worked with {skill} and Excel for monthly reporting every week.",
            f"SKILLS: {skill}, Excel", "EDUCATION: B.Com, Pune University, 2020"]
