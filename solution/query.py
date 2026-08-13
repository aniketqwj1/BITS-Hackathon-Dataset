#!/usr/bin/env python3
"""Read-only SQLite helper for agentic text-to-SQL.

Usage:
    python3 solution/query.py "SELECT ..."
    python3 solution/query.py /abs/path/hackathon.db "SELECT ..."

Prints matching rows as a JSON array of objects (column names = keys).
Read-only: any statement whose first non-whitespace token is not SELECT (or
WITH) is rejected. No PRAGMA, no writes, no ATTACH.

Intended to be called by analyst/judge agents via Bash:
    python3 /Users/aniketsaxena/Documents/p/from_aug_1/p0/BITS-Hackathon-Dataset/solution/query.py "SELECT ..."
"""
import json
import os
import sqlite3
import sys

DEFAULT_DB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "hackathon.db")


def main(argv):
    if len(argv) == 1:
        print('Usage: query.py "SELECT ..."  |  query.py <db> "SELECT ..."',
              file=sys.stderr)
        return 2
    if len(argv) == 2:
        db, sql = DEFAULT_DB, argv[1]
    else:
        db, sql = argv[1], argv[2]

    stripped = sql.lstrip().lower()
    if not (stripped.startswith("select") or stripped.startswith("with")):
        print("ERROR: only SELECT / WITH statements are allowed.", file=sys.stderr)
        return 3
    # Block obvious escape hatches.
    low = sql.lower()
    for bad in ("pragma", "attach", "insert", "update", "delete", "drop",
                "create", "alter", "replace", "vacuum", "reindex"):
        if re_word(low, bad):
            print(f"ERROR: disallowed keyword '{bad}'.", file=sys.stderr)
            return 3

    if not os.path.exists(db):
        print(f"ERROR: db not found: {db}", file=sys.stderr)
        return 4

    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        rows = con.execute(sql).fetchall()
        out = [dict(r) for r in rows]
        con.close()
    except sqlite3.Error as e:
        print(f"SQL ERROR: {e}", file=sys.stderr)
        return 5

    print(json.dumps(out, default=str))
    return 0


def re_word(haystack, needle):
    import re
    return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None


if __name__ == "__main__":
    sys.exit(main(sys.argv))