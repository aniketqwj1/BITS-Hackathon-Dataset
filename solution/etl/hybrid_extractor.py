"""Hybrid ETL: extract structured entities from the document corpus into SQLite.

Produces BOTH:
  1. Structured entity tables (the Text-to-SQL target):
       projects, engineers, credentials, financial, reference_letters, bonds
  2. raw_documents + doc_fts (FTS5) as the fallback retrieval layer.

Document layouts were confirmed by exploration (see plan). The master project
register is past_performance_portfolio/DOC-PPP-001.pdf (155-work index + detail
pages). Company completion certificates add the project manager (the only
project->engineer link). Personnel certificates give engineers + credentials.
Reference letters set has_reference_letter. The AR Ageing workbook gives
invoice->client->invoiced/received/outstanding.
"""
import json
import os
import re
import sqlite3
from collections import defaultdict

from .money import parse_money, parse_date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS = os.path.join(ROOT, "documents")
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hackathon.db")

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    project_id INTEGER PRIMARY KEY AUTOINCREMENT,
    pkg_number TEXT,
    project_name TEXT,
    category TEXT,
    client_name TEXT,
    value INTEGER,
    completion_date TEXT,
    issuance_date TEXT,
    project_manager TEXT,
    has_reference_letter INTEGER DEFAULT 0,
    grading TEXT,
    cert_ref TEXT,
    role TEXT,
    source_docs TEXT
);
CREATE TABLE IF NOT EXISTS engineers (
    engineer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    employee_id TEXT,
    designation TEXT,
    business_unit TEXT,
    qualification TEXT
);
CREATE TABLE IF NOT EXISTS credentials (
    credential_id INTEGER PRIMARY KEY AUTOINCREMENT,
    engineer_id INTEGER,
    credential_type TEXT,
    credential_number TEXT,
    issue_date TEXT,
    valid_through TEXT
);
CREATE TABLE IF NOT EXISTS financial (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_no TEXT,
    client_name TEXT,
    invoice_date TEXT,
    invoiced INTEGER,
    status TEXT,
    received INTEGER,
    outstanding INTEGER,
    pkg_number TEXT
);
CREATE TABLE IF NOT EXISTS reference_letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pkg_number TEXT,
    project_name TEXT,
    client_name TEXT,
    doc_id TEXT
);
CREATE TABLE IF NOT EXISTS bonds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bond_no TEXT,
    category TEXT,
    rfp_number TEXT,
    amount INTEGER,
    issue_date TEXT,
    expiry_date TEXT
);
CREATE TABLE IF NOT EXISTS raw_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT,
    filename TEXT,
    page_number INTEGER,
    content TEXT,
    metadata JSON,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _connect()
    # Reset: drop all tables so re-runs are idempotent.
    for t in ("projects", "engineers", "credentials", "financial",
              "reference_letters", "bonds", "raw_documents", "doc_fts"):
        conn.execute(f"DROP TABLE IF EXISTS {t}")
    conn.executescript(SCHEMA)
    conn.executescript("CREATE VIRTUAL TABLE doc_fts USING fts5(doc_id UNINDEXED, content)")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def pdf_text(path):
    """Extract full text of a PDF (all pages joined)."""
    import pdfplumber
    parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            parts.append(t)
    return "\n".join(parts)


def pdf_pages(path):
    """Extract per-page text of a PDF."""
    import pdfplumber
    out = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            out.append((i + 1, page.extract_text() or ""))
    return out


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


# ---------------------------------------------------------------------------
# 1. Master project register: Past Performance Portfolio (DOC-PPP-001.pdf)
# ---------------------------------------------------------------------------

def extract_ppp():
    """Parse the PPP detail pages (13-64) into project records."""
    path = os.path.join(DOCS, "past_performance_portfolio", "DOC-PPP-001.pdf")
    pages = pdf_pages(path)
    projects = []
    for pageno, text in pages:
        if pageno < 13:
            continue
        # Split into per-project blocks starting with "<N>. "
        blocks = re.split(r"(?=^\d+\.\s)", text, flags=re.M)
        for block in blocks:
            m = re.match(r"^(\d+)\.\s+(.+?)\n", block, re.S)
            if not m:
                continue
            proj = {"project_name": _norm(m.group(2)), "source_docs": "PPP"}
            m = re.search(r"Client\s+(.+?)\s*\((Prime|JV\s*Partner)\)", block, re.S)
            if m:
                proj["client_name"] = _norm(m.group(1))
                proj["role"] = m.group(2)
            m = re.search(r"Category\s+(.+?)\n", block, re.S)
            if m:
                proj["category"] = _norm(m.group(1))
            m = re.search(r"Executed Value\s+(.+?)\n", block, re.S)
            if m:
                proj["value"] = parse_money(m.group(1))
            m = re.search(r"Completed\s+(.+?)\s*·\s*Certificate\s+(.+?)\n", block, re.S)
            if m:
                proj["completion_date"] = parse_date(m.group(1))
                proj["cert_ref"] = _norm(m.group(2))
            projects.append(proj)

    # Derive pkg_number from the project name ("... — <State> Pkg-N").
    for p in projects:
        m = re.search(r"Pkg-(\d+)", p["project_name"], re.I)
        if m:
            p["pkg_number"] = f"Pkg-{int(m.group(1))}"
        else:
            p["pkg_number"] = None
    return projects


# ---------------------------------------------------------------------------
# 2. Company completion certificates -> project_manager + cross-check
# ---------------------------------------------------------------------------

def extract_company_certs():
    """Parse company completion certificates for project manager + value/date."""
    d = os.path.join(DOCS, "company_completion_certificate")
    records = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".pdf"):
            continue
        text = pdf_text(os.path.join(d, fn))
        rec = {"doc_id": fn.replace(".pdf", "")}
        # Sub-type A (detailed) labels
        m = re.search(r"Project Name\s+(.+)", text)
        if m:
            rec["project_name"] = _norm(m.group(1))
        m = re.search(r"Client\s+(.+?)(?:\s*\((?:Government|Private|Psu|government|private|psu)\))?\s*$", text, re.M)
        if m:
            rec["client_name"] = _norm(m.group(1))
        m = re.search(r"Work Category\s+(.+)", text)
        if m:
            rec["category"] = _norm(m.group(1))
        m = re.search(r"Contract Value\s+(.+)", text)
        if m:
            rec["value"] = parse_money(m.group(1))
        m = re.search(r"Completion Date\s+(\S+)", text)
        if m:
            rec["completion_date"] = parse_date(m.group(1))
        m = re.search(r"Project Manager\s+(.+)", text)
        if m:
            rec["project_manager"] = _norm(m.group(1))
        # Sub-type B (compact) labels
        if "project_name" not in rec:
            m = re.search(r"^Work\s+(.+)$", text, re.M)
            if m:
                rec["project_name"] = _norm(m.group(1))
        if "client_name" not in rec:
            m = re.search(r"^Client\s+(.+?)(?:\s*\((?:Government|Private|Psu|government|private|psu)\))?\s*$", text, re.M)
            if m:
                rec["client_name"] = _norm(m.group(1))
        if "category" not in rec:
            m = re.search(r"^Category\s+(.+)$", text, re.M)
            if m:
                rec["category"] = _norm(m.group(1))
        if "value" not in rec:
            m = re.search(r"Executed Value\s+(.+)", text)
            if m:
                rec["value"] = parse_money(m.group(1))
        if "completion_date" not in rec:
            m = re.search(r"^Completion\s+(\S+)$", text, re.M)
            if m:
                rec["completion_date"] = parse_date(m.group(1))
        if "project_manager" not in rec:
            m = re.search(r"Project Lead\s+(.+)", text)
            if m:
                rec["project_manager"] = _norm(m.group(1))
        # Grading from the declaration prose
        m = re.search(r"assessed the completed work as (\w[\w\s]*)\.", text)
        if m:
            rec["grading"] = _norm(m.group(1))
        records.append(rec)
    return records


# ---------------------------------------------------------------------------
# 3. Personnel certificates -> engineers + credentials
# ---------------------------------------------------------------------------

def extract_personnel():
    """Parse personnel certificates for engineers and their credentials."""
    d = os.path.join(DOCS, "personnel_certificate")
    records = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".pdf"):
            continue
        text = pdf_text(os.path.join(d, fn))
        rec = {"doc_id": fn.replace(".pdf", "")}
        # Name: after "This is to certify that" or "This credential is conferred upon"
        m = re.search(r"(?:This is to certify that|This credential is conferred upon)\s*\n\s*([A-Z][A-Za-z .]+)", text)
        if m:
            rec["name"] = _norm(m.group(1))
        m = re.search(r"Employee ID:\s*(EMP-\d+)", text)
        if m:
            rec["employee_id"] = m.group(1)
        # Credential type from header (Layout A: "PMP CERTIFICATION" /
        # "SIX SIGMA BLACK BELT"; Layout B: bare "PMP" / "SIX SIGMA BLACK BELT")
        if re.search(r"SIX SIGMA BLACK BELT", text, re.I):
            rec["credential_type"] = "Six Sigma Black Belt"
        elif re.search(r"\bPMP\b", text, re.I):
            rec["credential_type"] = "PMP"
        m = re.search(r"Credential Type\s+(.+)", text)
        if m:
            rec["credential_type"] = _norm(m.group(1))
        # Credential number
        m = re.search(r"Credential ID:?\s*(PMI-\d+|6S-\d+)", text)
        if not m:
            m = re.search(r"Certificate No\.?\s*(PMI-\d+|6S-\d+)", text)
        if m:
            rec["credential_number"] = m.group(1)
        # Issue date (full date, may be space-separated: "10 Mar 2021")
        m = re.search(r"Date of Issue\s+(.+?)(?:\n|$)", text)
        if not m:
            m = re.search(r"Issued:?\s+(.+?)(?:\n|$)", text)
        if m:
            rec["issue_date"] = parse_date(m.group(1))
        m = re.search(r"Valid Through\s+(.+?)(?:\n|$)", text)
        if m:
            rec["valid_through"] = parse_date(m.group(1))
        records.append(rec)
    return records


# ---------------------------------------------------------------------------
# 3b. CVs -> employee_id / business_unit / qualification (join by name)
# ---------------------------------------------------------------------------

def extract_cvs():
    """Parse CV headers: name + employee_id + business_unit + qualification."""
    d = os.path.join(DOCS, "cv")
    records = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".pdf"):
            continue
        text = pdf_text(os.path.join(d, fn))
        rec = {"doc_id": fn.replace(".pdf", "")}
        m = re.search(r"Name\s+([A-Z][A-Za-z .]+)\s+Employee ID\s+(EMP-\d+)", text)
        if m:
            rec["name"] = _norm(m.group(1))
            rec["employee_id"] = m.group(2)
        m = re.search(r"Business Unit\s+(.+?)\s+Total Experience", text)
        if m:
            rec["business_unit"] = _norm(m.group(1))
        m = re.search(r"Qualification\s+(.+?)\s+Date of Joining", text)
        if m:
            rec["qualification"] = _norm(m.group(1))
        records.append(rec)
    return records


# ---------------------------------------------------------------------------
# 4. Reference letters -> has_reference_letter per project
# ---------------------------------------------------------------------------

def extract_reference_letters():
    """Parse reference letters; extract the project name they reference."""
    d = os.path.join(DOCS, "reference_letter")
    records = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".pdf"):
            continue
        text = pdf_text(os.path.join(d, fn))
        rec = {"doc_id": fn.replace(".pdf", "")}
        # Project name appears in quotes (straight or curly, may wrap across
        # lines), or as "Work Executed", or "Project Name"
        m = re.search(r'["“]([^"”]*Pkg-\d+[^"”]*)["”]', text, re.S)
        if not m:
            m = re.search(r"Work Executed\s+(.+)", text)
        if not m:
            m = re.search(r"Project Name\s+(.+)", text)
        if m:
            rec["project_name"] = _norm(m.group(1))
        # Client from header org name (first line)
        first = text.strip().splitlines()[0] if text.strip() else ""
        if first:
            rec["client_name"] = _norm(first)
        records.append(rec)
    return records


# ---------------------------------------------------------------------------
# 5. AR Ageing workbook -> financial
# ---------------------------------------------------------------------------

def extract_ar_ageing():
    """Parse the Receivables_Ageing workbook into financial records."""
    import openpyxl
    path = os.path.join(DOCS, "workbooks", "Receivables_Ageing.xlsx")
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["AR Ageing"]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip() if h else "" for h in rows[0]]
    records = []
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        rec = {}
        for i, h in enumerate(header):
            if i < len(row):
                rec[h] = row[i]
        if not rec.get("Invoice No"):
            continue
        inv = str(rec.get("Invoice No", "")).strip()
        # Skip workbook TOTAL / grand-total rows (they are not invoices).
        if inv.upper().startswith("TOTAL") or inv.upper().startswith("GRAND"):
            continue
        status = str(rec.get("Status", "")).strip()
        records.append({
            "invoice_no": inv,
            "client_name": str(rec.get("Client", "")).strip(),
            "invoice_date": parse_date(rec.get("Invoice Date")),
            "invoiced": parse_money(rec.get("Invoiced (INR)")),
            "status": status if status and status != "None" else None,
            "received": parse_money(rec.get("Received (INR)")),
            "outstanding": parse_money(rec.get("Outstanding (INR)")),
        })
    return records


# ---------------------------------------------------------------------------
# 6. RA bills + final RA bills -> invoice -> contract -> client
# ---------------------------------------------------------------------------

def extract_ra_bills():
    """Parse RA bills: Contract #NN · Client, Bill No: AR-..."""
    records = []
    for sub in ("ra_bill", "final_ra_bill"):
        d = os.path.join(DOCS, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".pdf"):
                continue
            text = pdf_text(os.path.join(d, fn))
            rec = {"doc_id": fn.replace(".pdf", "")}
            m = re.search(r"Contract #(\d+)\s*·\s*(.+?)(?:\s*·|\s*$)", text)
            if m:
                rec["contract_no"] = m.group(1)
                rec["client_name"] = _norm(m.group(2))
            m = re.search(r"Bill No:\s*(AR-\d+-\d+)", text)
            if m:
                rec["invoice_no"] = m.group(1)
            m = re.search(r"Awarded Value\s+(.+)", text)
            if m:
                rec["awarded_value"] = parse_money(m.group(1))
            records.append(rec)
    return records


# ---------------------------------------------------------------------------
# 7. General Ledger -> revenue per invoice
# ---------------------------------------------------------------------------

def extract_gl():
    """Parse GL books: extract invoice numbers and revenue per segment."""
    d = os.path.join(DOCS, "general_ledger_book")
    records = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".pdf"):
            continue
        text = pdf_text(os.path.join(d, fn))
        rec = {"doc_id": fn.replace(".pdf", "")}
        invoices = set(re.findall(r"Client invoice (AR-\d+-\d+)", text))
        rec["invoices"] = sorted(invoices)
        # Revenue accounts
        rev = re.findall(r"ACCOUNT 40\d\d — CONTRACT REVENUE[^\n]*", text, re.I)
        rec["revenue_accounts"] = [_norm(x) for x in rev]
        records.append(rec)
    return records


# ---------------------------------------------------------------------------
# 8. Performance bonds
# ---------------------------------------------------------------------------

def extract_bonds():
    """Parse performance bonds: bond no, category, RFP, amount, dates."""
    d = os.path.join(DOCS, "performance_bond")
    records = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".pdf"):
            continue
        text = pdf_text(os.path.join(d, fn))
        rec = {"doc_id": fn.replace(".pdf", "")}
        m = re.search(r"Bond No:\s*(\S+)", text)
        if not m:
            m = re.search(r"BG No:\s*(\S+)", text)
        if m:
            rec["bond_no"] = m.group(1)
        m = re.search(r"Tender Ref:?\s*(RFP-\d+)", text)
        if m:
            rec["rfp_number"] = m.group(1)
        m = re.search(r"for the work of ([A-Za-z ]+?) Works", text)
        if m:
            rec["category"] = _norm(m.group(1))
        m = re.search(r"amount not exceeding\s+(.+?)(?:\s*\(|$)", text)
        if m:
            rec["amount"] = parse_money(m.group(1))
        m = re.search(r"Issue Date:\s*(\S+)", text)
        if m:
            rec["issue_date"] = parse_date(m.group(1))
        m = re.search(r"Expiry Date[^)]*?(\S+)\s*\)", text)
        if m:
            rec["expiry_date"] = parse_date(m.group(1))
        records.append(rec)
    return records


# ---------------------------------------------------------------------------
# Load into DB
# ---------------------------------------------------------------------------

def _pkg_from_name(name):
    m = re.search(r"Pkg-(\d+)", name or "", re.I)
    return f"Pkg-{int(m.group(1))}" if m else None


def load_projects(conn, projects, company_certs):
    """Merge PPP projects with company-cert project managers."""
    # Index company certs by pkg number
    cert_by_pkg = {}
    for c in company_certs:
        pkg = _pkg_from_name(c.get("project_name"))
        if pkg:
            cert_by_pkg[pkg] = c
    for p in projects:
        pkg = p.get("pkg_number")
        cert = cert_by_pkg.get(pkg, {})
        conn.execute("""
            INSERT INTO projects (pkg_number, project_name, category, client_name, value,
                                  completion_date, issuance_date, project_manager,
                                  has_reference_letter, grading, cert_ref, role, source_docs)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            pkg,
            p.get("project_name"),
            p.get("category"),
            p.get("client_name"),
            p.get("value"),
            p.get("completion_date"),
            cert.get("completion_date"),  # issuance_date placeholder (company cert date)
            cert.get("project_manager"),
            0,
            cert.get("grading"),
            p.get("cert_ref"),
            p.get("role"),
            p.get("source_docs"),
        ))


def load_engineers_credentials(conn, personnel, cvs):
    """Load engineers + credentials; backfill employee_id/business_unit from CVs by name.

    Dedupe engineers by employee_id (falling back to name): the 9 Six Sigma holders also
    hold a PMP, so they appear in two personnel certs. They must be ONE engineer row with
    TWO credentials, or joins by name would double-count.
    """
    cv_by_name = {}
    for c in cvs:
        if c.get("name"):
            cv_by_name[c["name"].lower()] = c
    eid_by_key = {}
    for p in personnel:
        cv = cv_by_name.get((p.get("name") or "").lower(), {})
        emp_id = p.get("employee_id") or cv.get("employee_id")
        key = emp_id or (p.get("name") or "").lower()
        eid = eid_by_key.get(key)
        if eid is None:
            cur = conn.execute(
                "INSERT INTO engineers (name, employee_id, business_unit, qualification) VALUES (?,?,?,?)",
                (p.get("name"), emp_id, cv.get("business_unit"), cv.get("qualification")))
            eid = cur.lastrowid
            eid_by_key[key] = eid
        conn.execute("""
            INSERT INTO credentials (engineer_id, credential_type, credential_number,
                                     issue_date, valid_through)
            VALUES (?,?,?,?,?)
        """, (eid, p.get("credential_type"), p.get("credential_number"),
              p.get("issue_date"), p.get("valid_through")))


def load_reference_letters(conn, ref_letters):
    for r in ref_letters:
        pkg = _pkg_from_name(r.get("project_name"))
        conn.execute("""
            INSERT INTO reference_letters (pkg_number, project_name, client_name, doc_id)
            VALUES (?,?,?,?)
        """, (pkg, r.get("project_name"), r.get("client_name"), r.get("doc_id")))
        if pkg:
            conn.execute("UPDATE projects SET has_reference_letter = 1 WHERE pkg_number = ?", (pkg,))


def load_financial(conn, ar_ageing):
    for f in ar_ageing:
        conn.execute("""
            INSERT INTO financial (invoice_no, client_name, invoice_date, invoiced,
                                   status, received, outstanding)
            VALUES (?,?,?,?,?,?,?)
        """, (f["invoice_no"], f["client_name"], f["invoice_date"], f["invoiced"],
              f["status"], f["received"], f["outstanding"]))


def load_bonds(conn, bonds):
    for b in bonds:
        conn.execute("""
            INSERT INTO bonds (bond_no, category, rfp_number, amount, issue_date, expiry_date)
            VALUES (?,?,?,?,?,?)
        """, (b.get("bond_no"), b.get("category"), b.get("rfp_number"),
              b.get("amount"), b.get("issue_date"), b.get("expiry_date")))


def load_raw_documents(conn):
    """Index every PDF's raw text into raw_documents + FTS5 (fallback layer)."""
    import pdfplumber
    for sub in sorted(os.listdir(DOCS)):
        d = os.path.join(DOCS, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".pdf"):
                continue
            path = os.path.join(d, fn)
            doc_id = fn.replace(".pdf", "")
            try:
                with pdfplumber.open(path) as pdf:
                    for i, page in enumerate(pdf.pages):
                        text = page.extract_text() or ""
                        if not text.strip():
                            continue
                        content = f"--- {doc_id} page {i+1} ---\n{text}"
                        conn.execute(
                            "INSERT INTO raw_documents (doc_id, filename, page_number, content, metadata) VALUES (?,?,?,?,?)",
                            (doc_id, fn, i + 1, content, json.dumps({"doc_type": sub})))
                        conn.execute("INSERT INTO doc_fts (doc_id, content) VALUES (?,?)",
                                     (doc_id, content))
            except Exception as e:
                print(f"  WARN: {fn}: {e}")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_etl(verbose=True):
    init_db()
    conn = _connect()

    if verbose:
        print("Extracting PPP master register...")
    projects = extract_ppp()
    if verbose:
        print(f"  {len(projects)} projects")

    if verbose:
        print("Extracting company completion certificates...")
    company_certs = extract_company_certs()
    if verbose:
        print(f"  {len(company_certs)} certs")

    if verbose:
        print("Extracting personnel certificates...")
    personnel = extract_personnel()
    if verbose:
        print(f"  {len(personnel)} personnel")

    if verbose:
        print("Extracting CVs...")
    cvs = extract_cvs()
    if verbose:
        print(f"  {len(cvs)} CVs")

    if verbose:
        print("Extracting reference letters...")
    ref_letters = extract_reference_letters()
    if verbose:
        print(f"  {len(ref_letters)} letters")

    if verbose:
        print("Extracting AR ageing...")
    ar_ageing = extract_ar_ageing()
    if verbose:
        print(f"  {len(ar_ageing)} invoices")

    if verbose:
        print("Extracting RA bills...")
    ra_bills = extract_ra_bills()
    if verbose:
        print(f"  {len(ra_bills)} bills")

    if verbose:
        print("Extracting GL...")
    gl = extract_gl()
    if verbose:
        print(f"  {len(gl)} ledgers")

    if verbose:
        print("Extracting performance bonds...")
    bonds = extract_bonds()
    if verbose:
        print(f"  {len(bonds)} bonds")

    load_projects(conn, projects, company_certs)
    load_engineers_credentials(conn, personnel, cvs)
    load_reference_letters(conn, ref_letters)
    load_financial(conn, ar_ageing)
    load_bonds(conn, bonds)
    conn.commit()

    if verbose:
        print("Indexing raw documents + FTS...")
    load_raw_documents(conn)
    conn.commit()

    if verbose:
        for t in ("projects", "engineers", "credentials", "financial",
                  "reference_letters", "bonds", "raw_documents"):
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {n} rows")
    conn.close()
    return DB_PATH


if __name__ == "__main__":
    run_etl()
