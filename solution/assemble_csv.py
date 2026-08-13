#!/usr/bin/env python3
"""Assemble workflow output {qid: answer} into a submission CSV.

Usage:
    python3 solution/assemble_csv.py <results.json> <questions.json> <out.csv>

results.json  : the workflow's "final" map (a JSON object {qid: number})
questions.json: the questions file (to set row order + catch missing qids)
out.csv       : the written submission (header: question_id,answer)
"""
import csv
import json
import sys


def main(argv):
    if len(argv) != 4:
        print("Usage: assemble_csv.py <results.json> <questions.json> <out.csv>",
              file=sys.stderr)
        return 2
    results_path, questions_path, out_path = argv[1], argv[2], argv[3]

    with open(results_path) as f:
        raw = json.load(f)
    # Accept either the bare {qid: answer} map or the wrapper {final: {...}}.
    if isinstance(raw, dict) and "final" in raw and isinstance(raw["final"], dict):
        results = raw["final"]
    else:
        results = raw

    with open(questions_path) as f:
        qdata = json.load(f)
    qs = qdata["questions"] if isinstance(qdata, dict) else qdata

    rows = 0
    missing = []
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["question_id", "answer"])
        for q in qs:
            qid = q.get("qid") or q.get("id")
            ans = results.get(qid)
            if ans is None or ans == "":
                missing.append(qid)
                w.writerow([qid, ""])
            else:
                # Plain number: int for money/count/days, float-ish for percent.
                if isinstance(ans, float) and ans.is_integer():
                    ans = int(ans)
                w.writerow([qid, ans])
            rows += 1

    print(f"Wrote {rows} rows to {out_path}")
    if missing:
        print(f"MISSING/blank answers: {len(missing)} -> {missing}")
    else:
        print("No missing answers.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))