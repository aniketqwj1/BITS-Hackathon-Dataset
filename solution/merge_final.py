#!/usr/bin/env python3
"""Merge agent answers from both workflow runs into the final answers.csv.

Reads:
  - solution/result333.json      -> {final:{qid:answer}, analyst:{...}, judge:{...}} (run 1: 203)
  - solution/result_missing.json -> {final:{qid:answer}, ...} or bare {qid:answer}    (run 2: 130)
  - questions.json               -> row order + answer_type
  - solution/answers.csv (old)  -> last-resort fallback for any still-missing qid

Writes solution/answers.csv (question_id,answer), ordered by questions.json.

Precedence per qid: run1 final (judge>analyst) > run2 final/analyst > old answers.csv > blank.
"""
import csv
import json
import sys


def load_map(path):
    if not path:
        return {}
    try:
        with open(path) as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}
    if isinstance(raw, dict) and "final" in raw and isinstance(raw["final"], dict):
        m = dict(raw["final"])
        # also fold in analyst-only answers (run2 may store them under 'final' already)
        for k, v in (raw.get("analyst") or {}).items():
            m.setdefault(k, v)
        return m
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def main():
    run1 = load_map("solution/result333.json")
    run2 = load_map("solution/result_missing.json")
    # run1's 'final' already prefers judge>analyst; also fold run1 analyst-only explicitly
    with open("solution/result333.json") as f:
        r1 = json.load(f)
    run1_full = dict(r1.get("final") or {})
    for k, v in (r1.get("analyst") or {}).items():
        run1_full.setdefault(k, v)

    # old answers fallback
    old = {}
    try:
        with open("solution/answers.csv") as f:
            rd = csv.reader(f); next(rd, None)
            for row in rd:
                if len(row) >= 2 and row[0]:
                    v = row[1].strip()
                    try:
                        old[row[0]] = int(v) if v and "." not in v else (float(v) if v else None)
                    except Exception:
                        old[row[0]] = v if v else None
    except FileNotFoundError:
        pass

    with open("questions.json") as f:
        qs = json.load(f)["questions"]

    rows = 0
    src = {"run1": 0, "run2": 0, "old": 0, "blank": 0}
    with open("solution/answers.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["question_id", "answer"])
        for q in qs:
            qid = q["qid"]
            if qid in run1_full and run1_full[qid] is not None:
                a = run1_full[qid]; s = "run1"
            elif qid in run2 and run2[qid] is not None:
                a = run2[qid]; s = "run2"
            elif qid in old and old[qid] not in (None, ""):
                a = old[qid]; s = "old"
            else:
                a = ""; s = "blank"
            if isinstance(a, float) and a.is_integer():
                a = int(a)
            w.writerow([qid, a])
            src[s] = src.get(s, 0) + 1
            rows += 1

    print(f"Wrote {rows} rows to solution/answers.csv")
    print(f"  run1 (judge>analyst): {src['run1']}")
    print(f"  run2 (missing analyst): {src['run2']}")
    print(f"  old fallback: {src['old']}")
    print(f"  blank: {src['blank']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())