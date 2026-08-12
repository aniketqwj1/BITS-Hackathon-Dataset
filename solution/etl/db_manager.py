"""Dynamic metadata layer — auto-introspect the SQLite DB and emit a semantic dictionary.

The agent never guesses string values (client names, categories, statuses). This module samples
the actual database and writes:

    solution/metadata/dynamic_dictionary.json   — machine-readable (fed to the agent as context)
    solution/metadata/schema_guide.md           — human-readable reference for debugging

For every table it records the DDL, row count, and per-column stats:
  - TEXT columns: up to MAX_SAMPLES distinct values (so the agent can match exact spellings)
  - INTEGER columns: min / max / avg / null count (so the agent knows the value range)
  - plus a per-table "notes" hint describing what the table represents and how to join it.

It also emits a question-family → table/column mapping so the agent knows where to look first
for each of the 12 question shapes seen in the sample set.
"""
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB_PATH = os.path.join(ROOT, "hackathon.db")
META_DIR = os.path.join(ROOT, "metadata")

MAX_SAMPLES = 12          # distinct values sampled per TEXT column
MAX_VALUE_LEN = 60        # truncate long sampled values for readability

# Tables the agent should query, in priority order, with a plain-language description.
TABLE_NOTES = {
    "projects": (
        "One row per completed work (155). PRIMARY entity table. pkg_number is the canonical key "
        "(e.g. 'Pkg-21'); project_name embeds it. value is the contract value in rupees (int). "
        "has_reference_letter is 1/0. project_manager is the engineer's full name. "
        "completion_date / issuance_date are ISO dates. category is the work classification. "
        "grading is the completion grade. role is 'Prime' or 'JV'."
    ),
    "engineers": (
        "One row per engineer (48). name is the full name; employee_id is EMP-xxxxx. "
        "Join to projects via projects.project_manager = engineers.name. "
        "Join to credentials via credentials.engineer_id."
    ),
    "credentials": (
        "One row per engineer credential (48). credential_type is 'PMP' or 'Six Sigma Black Belt'. "
        "credential_number is like 'PMI-200029' or '6S-500161'. issue_date is ISO. "
        "Join to engineers via engineer_id."
    ),
    "financial": (
        "One row per AR invoice (519). invoice_no like 'AR-2019-00007'. client_name is the client. "
        "invoiced / received / outstanding are rupees (int). status is 'paid' / 'due' / 'part_paid'. "
        "pkg_number is populated where the invoice maps to a project (may be NULL). "
        "Join to projects via pkg_number, or to clients via client_name."
    ),
    "reference_letters": (
        "One row per reference letter (132). pkg_number links to projects. "
        "Presence of a row here means the project HAS a reference letter."
    ),
    "bonds": (
        "One row per performance bond (60). bond_no, category, rfp_number, amount (rupees int), "
        "issue_date, expiry_date. Links to tenders via rfp_number, not pkg_number."
    ),
    "raw_documents": (
        "Fallback full-text layer: one row per extracted page (1953). content is the raw text. "
        "Use doc_fts (FTS5) to search it when structured tables come up empty."
    ),
}

# Question family → where to look first. The agent should consult this before writing SQL.
FAMILY_MAP = {
    "absence": "projects.has_reference_letter (1/0) + reference_letters table. Count projects for a "
               "client with has_reference_letter=0, or check reference_letters for a pkg_number.",
    "date_span": "projects.completion_date / issuance_date + credentials.issue_date. Use "
                 "julianday() difference for whole days.",
    "distinct_count": "projects.category (or project_name) filtered by project_manager / client.",
    "hop_aggregate": "projects.value summed over a chain: credentials → engineers → projects "
                     "(via project_manager) → client → all that client's projects.",
    "temporal_chain": "projects.value summed where completion_date is after (or before) a "
                      "credential issue_date, for a given engineer.",
    "avg_work_size": "AVG(projects.value) over a client's projects (or an engineer's projects).",
    "exclusion_aggregate": "SUM(projects.value) for a client EXCLUDING one or more categories.",
    "gap_to_threshold": "SUM(projects.value) for a client, then threshold - sum (or sum - threshold).",
    "rank_value": "ORDER BY projects.value DESC for a client; difference between rank 1 and rank 2.",
    "referenced_share": "COUNT(projects) with has_reference_letter=1 / total COUNT(projects) for a "
                        "client, expressed as a percentage.",
    "threshold_aggregate": "SUM(projects.value) for a client where value >= (or >) a crore threshold.",
    "financial_reconciliation": "financial table: SUM(invoiced), SUM(received), SUM(outstanding) "
                                "per client; billed vs collected percentage.",
}


def _sample_values(cur, table, column, limit=MAX_SAMPLES):
    """Return up to `limit` distinct non-null values for a column, truncated."""
    rows = cur.execute(
        f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL "
        f"AND {column} != '' ORDER BY {column} LIMIT ?",
        (limit,),
    ).fetchall()
    out = []
    for (v,) in rows:
        s = str(v)
        if len(s) > MAX_VALUE_LEN:
            s = s[:MAX_VALUE_LEN] + "…"
        out.append(s)
    return out


def _int_stats(cur, table, column):
    row = cur.execute(
        f"SELECT MIN({column}), MAX({column}), AVG({column}), "
        f"SUM(CASE WHEN {column} IS NULL THEN 1 ELSE 0 END), COUNT(*) FROM {table}"
    ).fetchone()
    mn, mx, avg, nulls, total = row
    return {
        "min": mn,
        "max": mx,
        "avg": round(avg, 1) if avg is not None else None,
        "nulls": nulls,
        "total": total,
    }


def introspect(db_path=DB_PATH):
    """Return the full dynamic dictionary as a dict."""
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'doc_fts%' AND name != 'sqlite_sequence' ORDER BY name").fetchall()]

    dictionary = {"tables": {}, "family_map": FAMILY_MAP}
    for t in tables:
        cols = cur.execute(f"PRAGMA table_info({t})").fetchall()
        col_info = {}
        for cid, name, ctype, notnull, dflt, pk in cols:
            if ctype.upper() in ("TEXT", "VARCHAR", "JSON"):
                col_info[name] = {
                    "type": "TEXT",
                    "samples": _sample_values(cur, t, name),
                }
            else:
                col_info[name] = {"type": ctype, "stats": _int_stats(cur, t, name)}
        (count,) = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
        dictionary["tables"][t] = {
            "row_count": count,
            "columns": col_info,
            "notes": TABLE_NOTES.get(t, ""),
        }
    con.close()
    return dictionary


def write_metadata(db_path=DB_PATH, meta_dir=META_DIR):
    """Introspect and write dynamic_dictionary.json + schema_guide.md. Returns the dict."""
    os.makedirs(meta_dir, exist_ok=True)
    d = introspect(db_path)

    json_path = os.path.join(meta_dir, "dynamic_dictionary.json")
    with open(json_path, "w") as f:
        json.dump(d, f, indent=2)

    md_path = os.path.join(meta_dir, "schema_guide.md")
    with open(md_path, "w") as f:
        f.write("# Schema Guide (auto-generated)\n\n")
        for t, info in d["tables"].items():
            f.write(f"## {t}  ({info['row_count']} rows)\n\n")
            if info["notes"]:
                f.write(f"_{info['notes']}_\n\n")
            f.write("| column | type | samples / stats |\n|---|---|---|\n")
            for cname, c in info["columns"].items():
                if c["type"] == "TEXT":
                    samples = ", ".join(f"`{s}`" for s in c["samples"][:6])
                    f.write(f"| {cname} | TEXT | {samples} |\n")
                else:
                    st = c["stats"]
                    f.write(f"| {cname} | {c['type']} | min={st['min']} max={st['max']} "
                            f"avg={st['avg']} nulls={st['nulls']}/{st['total']} |\n")
            f.write("\n")
        f.write("## Question-family → table/column map\n\n")
        for fam, hint in d["family_map"].items():
            f.write(f"- **{fam}**: {hint}\n")

    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return d


if __name__ == "__main__":
    d = write_metadata()
    for t, info in d["tables"].items():
        print(f"{t:20s} {info['row_count']:5d} rows")
