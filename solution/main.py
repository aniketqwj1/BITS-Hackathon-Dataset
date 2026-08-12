#!/usr/bin/env python3
"""End-to-end pipeline: run the reasoner over a question set and emit answers.csv.

Usage (from the solution/ directory):
    .venv/bin/python -m main --questions ../questions.json --out answers.csv
    .venv/bin/python -m main --questions ../sample_questions.json --out sample_answers.csv

The reasoner caches LLM plans to metadata/plan_cache.json, so re-runs are instant.
LLM plan generation is parallelized across questions (the Ollama server handles
concurrent requests) to keep the full 333-question run tractable.
"""
import argparse
import csv
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from agent.reasoner import Reasoner, format_answer  # noqa: E402

DEFAULT_WORKERS = 6


def load_questions(path):
    with open(path) as f:
        data = json.load(f)
    qs = data.get("questions") or data.get("answers") or data
    if isinstance(qs, dict):
        qs = list(qs.values())
    return qs


def run_one(reasoner, q, use_llm):
    """Answer a single question; returns (qid, answer_str, plan, trace)."""
    qid = q.get("qid") or q.get("id")
    question = q.get("question")
    try:
        ans, plan, trace = reasoner.answer(question, qid, use_llm=use_llm)
        answer_str = format_answer(ans, plan.get("answer_type"))
    except Exception as e:  # never let one question kill the run
        answer_str = ""
        plan = {"operation": "ERROR", "error": str(e)}
        trace = {}
    return qid, answer_str, plan, trace


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True, help="questions.json or sample_questions.json")
    ap.add_argument("--out", default="answers.csv", help="output CSV path")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--no-llm", action="store_true",
                    help="skip LLM plan generation entirely (deterministic parser only)")
    ap.add_argument("--llm-all", action="store_true",
                    help="use the LLM for every question (slow); default is LLM only when needed")
    a = ap.parse_args()

    questions = load_questions(a.questions)
    print(f"loaded {len(questions)} questions from {a.questions}")

    reasoner = Reasoner()

    # Decide which questions need the LLM: only those the deterministic parser
    # cannot resolve (abbreviations, ambiguous first names). Everything else is
    # answered deterministically — fast and reproducible.
    llm_qids = set()
    if not a.no_llm:
        for q in questions:
            if a.llm_all or reasoner.needs_llm(q.get("question")):
                llm_qids.add(q.get("qid") or q.get("id"))
    print(f"LLM plan generation needed for {len(llm_qids)}/{len(questions)} questions")

    results = {}
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(run_one, reasoner, q, (q.get("qid") or q.get("id")) in llm_qids): q
                for q in questions}
        done = 0
        for fut in as_completed(futs):
            qid, answer_str, plan, trace = fut.result()
            results[qid] = answer_str
            done += 1
            if done % 25 == 0 or done == len(questions):
                print(f"  {done}/{len(questions)} answered")

    reasoner.save_cache()

    # Write CSV (question_id,answer) — plain numbers only.
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["question_id", "answer"])
        for q in questions:
            qid = q.get("qid") or q.get("id")
            w.writerow([qid, results.get(qid, "")])
    print(f"wrote {a.out} ({len(results)} answers)")

    # Quick stats on unanswered / non-numeric.
    bad = [qid for qid, v in results.items() if not v]
    if bad:
        print(f"WARNING: {len(bad)} unanswered: {bad[:10]}")


if __name__ == "__main__":
    main()
