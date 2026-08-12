"""Agent tools: SQL execution, FTS fallback, schema access, entity lookup.

The reasoner uses these to fetch data. All queries are read-only. The data is small
(155 projects, 518 financial rows), so the reasoner fetches the relevant rows and
computes the answer in Python rather than pushing aggregation into SQL — that keeps
the SQL trivial (no syntax errors) and the arithmetic auditable.
"""
import json
import os
import re
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "hackathon.db")
META_PATH = os.path.join(ROOT, "metadata", "dynamic_dictionary.json")


def get_conn():
    return sqlite3.connect(DB_PATH)


def execute_sql(query, params=()):
    """Run a read-only SQL query; return rows as a list of tuples."""
    con = get_conn()
    try:
        return con.execute(query, params).fetchall()
    finally:
        con.close()


def fts_search(keyword, limit=10):
    """FTS5 fallback over raw document text. Returns (doc_id, snippet) rows."""
    con = get_conn()
    try:
        return con.execute(
            "SELECT doc_id, snippet(doc_fts, 1, '[', ']', '…', 12) FROM doc_fts "
            "WHERE doc_fts MATCH ? LIMIT ?", (keyword, limit)).fetchall()
    finally:
        con.close()


def get_schema():
    """Return the dynamic dictionary (DDL + value samples + family map)."""
    with open(META_PATH) as f:
        return json.load(f)


def load_entities():
    """Load every entity name from the DB for fuzzy matching against questions."""
    con = get_conn()
    try:
        engineers = [r[0] for r in con.execute(
            "SELECT DISTINCT name FROM engineers ORDER BY name")]
        clients = [r[0] for r in con.execute(
            "SELECT DISTINCT client_name FROM projects ORDER BY client_name")]
        # Include financial-only clients (billing data without completed works).
        fin_clients = [r[0] for r in con.execute(
            "SELECT DISTINCT client_name FROM financial WHERE client_name IS NOT NULL "
            "AND client_name != '' ORDER BY client_name")]
        for c in fin_clients:
            if c not in clients:
                clients.append(c)
        projects = [r[0] for r in con.execute(
            "SELECT project_name FROM projects ORDER BY project_name")]
        credentials = [r[0] for r in con.execute(
            "SELECT credential_number FROM credentials ORDER BY credential_number")]
    finally:
        con.close()
    return {
        "engineers": engineers,
        "clients": clients,
        "projects": projects,
        "credentials": credentials,
    }


# ---------------------------------------------------------------------------
# Entity resolution helpers
# ---------------------------------------------------------------------------

def _norm(s):
    """Lowercase, collapse whitespace, strip punctuation for matching."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


def resolve_engineer(question, engineers):
    """Return the engineer name mentioned in the question, or None."""
    q = _norm(question)
    for name in engineers:
        if _norm(name) in q:
            return name
    return None


def resolve_engineer_firstname(question, engineers):
    """Resolve an engineer by first name only (e.g. 'neha's', 'meera', 'amit').

    Returns the engineer if exactly one engineer's first name appears in the
    question. Ambiguous first names (e.g. 'priya' -> Priya Gupta / Priya Patel)
    return None so the LLM can disambiguate.
    """
    q = _norm(question)
    matches = []
    for name in engineers:
        first = _norm(name.split()[0])
        if first and first in q:
            matches.append(name)
    if len(matches) == 1:
        return matches[0]
    return None


def resolve_client(question, clients):
    """Return the client name mentioned in the question, or None."""
    q = _norm(question)
    for name in clients:
        if _norm(name) in q:
            return name
    return None


# Curated abbreviation -> full client name. Keys are normalized (lowercase, no punct).
_CLIENT_ALIASES = {
    "gujarat pw": "Public Works Department, Govt of Gujarat",
    "gujarat pwd": "Public Works Department, Govt of Gujarat",
    "pwd gujarat": "Public Works Department, Govt of Gujarat",
    "gujarat public works": "Public Works Department, Govt of Gujarat",
    "maharashtra pwd": "Public Works Department, Govt of Maharashtra",
    "mah pwd": "Public Works Department, Govt of Maharashtra",
    "maha pwd": "Public Works Department, Govt of Maharashtra",
    "mahanadi steel corp": "Mahanadi Steel Corporation",
    "mahanadi steel": "Mahanadi Steel Corporation",
    "mega infra authority": "Mega Infrastructure Authority",
    "peninsular petroleum": "Peninsular Petroleum Corporation",
    "subarnarekha valley corp": "Subarnarekha Valley Corporation",
    "subarnarekha valley": "Subarnarekha Valley Corporation",
    "trishakti": "Trishakti Power Generation Corporation",
    "neda": "National Expressway Development Authority",
    "phed odisha": "Public Health Engineering Dept, Odisha",
    "odisha phed": "Public Health Engineering Dept, Odisha",
    "pheg gujarat": "Public Health Engineering Dept, Gujarat",
    "up irrigation": "Irrigation & Waterways Dept, Govt of Uttar Pradesh",
    "irr waterways dept rajasthan": "Irrigation & Waterways Dept, Govt of Rajasthan",
    "irr waterways rajasthan": "Irrigation & Waterways Dept, Govt of Rajasthan",
    "jal nigam up": "Jal Nigam, Uttar Pradesh",
    "jal nigam gujarat": "Jal Nigam, Gujarat",
    "suvarna projects": "Suvarna Projects Limited",
    "meridian constructors": "Meridian Constructors & Co.",
    "lakshya engineering": "Lakshya Engineering & Construction",
    "central works": "Central Works & Buildings Bureau",
    "national special projects": "National Special Projects Office",
    "tamil nadu municipal": "Tamil Nadu Municipal Corporation",
    "mahanadi steel corp": "Mahanadi Steel Corporation",
    "west bengal irrigation": "Irrigation & Waterways Dept, Govt of West Bengal",
    "west bengal waterways": "Irrigation & Waterways Dept, Govt of West Bengal",
    "jal nigam account in gujarat": "Jal Nigam, Gujarat",
    "jal nigam gujarat account": "Jal Nigam, Gujarat",
    "public health engineering dept west bengal": "Public Health Engineering Dept, West Bengal",
    "public health engineering dept wb": "Public Health Engineering Dept, West Bengal",
}


def resolve_client_abbrev(question, clients):
    """Resolve a client from a known abbreviation, or None."""
    q = _norm(question)
    for alias, full in _CLIENT_ALIASES.items():
        if alias in q:
            return full
    return None


def resolve_project(question, projects):
    """Return the project name mentioned in the question, or None."""
    q = _norm(question)
    for name in projects:
        if _norm(name) in q:
            return name
    return None


def resolve_project_by_pkg(question, projects):
    """Resolve a project by its pkg number, tolerating 'Package 51' / 'Pkg-51' / 'pkg 51'."""
    m = re.search(r"(?:pkg|package)[- ]?(\d+)", question, re.I)
    if not m:
        return None
    pkg_num = m.group(1)
    for name in projects:
        if re.search(rf"pkg[- ]?{pkg_num}\b", name, re.I):
            return name
    return None


def resolve_credential(question, credentials):
    """Return the credential number (PMI-xxxxx / 6S-xxxxx) in the question, or None."""
    m = re.search(r"(PMI-\d+|6S-\d+)", question, re.I)
    return m.group(1) if m else None


def resolve_pkg(question):
    """Return the Pkg-N token in the question, or None."""
    m = re.search(r"Pkg[- ]?(\d+)", question, re.I)
    return f"Pkg-{m.group(1)}" if m else None
