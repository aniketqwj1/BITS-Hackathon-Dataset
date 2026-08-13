# BITS-Hackathon-Dataset — Complete Learnings & Retrospective

> Text-to-SQL over a construction-company SQLite DB. 333 hidden questions
> (`HV-IC-0001`…`HV-IC-0477`), scored by continuous closeness
> `max(0, 1 − |your−gold|/|gold|)` averaged. Baseline solution: a
> deterministic reasoner + frozen plan cache, stuck at **74.754%** and
> regenerating a byte-identical `answers.csv` on every run.
>
> Final state: `answers.csv` regenerated via an agentic analyst+judge
> pipeline over the DB, **333/333 answers, 0 blanks**, **17/17 hand-audited
> correct**. Pushed to `origin/main` at SHA **`5f882cf`**.

---

## 1. The real problem (and why "again and again we get the same result")

The symptom was "regenerating answers.csv keeps producing the same file."
The first instinct — "the model is bad, load a HuggingFace text-to-SQL
model" — was **wrong**. The model was never the bottleneck.

**Root cause:** `solution/agent/reasoner.py`'s `plan()` method returned a
cached plan from `metadata/plan_cache.json` **before any LLM or
deterministic logic ran**, and `main.py` never disabled the cache. So 333
stale plans were frozen on disk and replayed verbatim every run. No amount
of re-running, prompt-tweaking, or model-swapping could change the output,
because the output came from a JSON file, not from reasoning.

> **Lesson:** When output is identical across runs, suspect **cached state**
> before suspecting the model. Read the control flow: is the result computed,
> or replayed? `grep -n "cache"` the entrypoint. A frozen cache is silent —
> it doesn't error, it just makes the system deterministic in the worst way.

### How to learn from this
- Before "improving the model," prove the model is even being called. Add a
  print/log inside the reasoning path and confirm it fires.
- Treat `plan_cache.json`-style artifacts as **build outputs, not inputs**.
  If you can't regenerate them from scratch with one command, delete them and
  watch what breaks.
- A test that asserts "output changes when the input changes" would have
  caught this instantly. We never had one.

---

## 2. The single biggest domain lesson: ANCHORS vs FILTERS

This was the #1 accuracy lever, and the place I was most confidently wrong.

Many questions are wrapped like:
> *"Starting with Rajesh Rao's Six Sigma Black Belt (6S-500161) work on the
> Material Handling Plant — UP Pkg-47 with the National Expressway
> Development Authority, what is the combined value of every completed
> assignment he has delivered for that client?"*

The naive (and wrong) reading: filter by engineer `Rajesh Rao` AND client
`NEDA`. That returns only Pkg-47 = 129,400,000.

The **gold** reading: Rajesh Rao / 6S-500161 / Pkg-47 are **ANCHORS** — they
exist only to identify *which client* is being asked about. The actual scope
is the **client's entire portfolio** (all 9 NEDA projects, by 9 different
PMs) = **2,942,400,000**. The named engineer is *not* a filter.

The same applies to credentials:
> *"How many different categories has Chandan Banerjee led under his PMP?"*
→ "under his PMP" **identifies the engineer**, it does **not** mean
"projects completed after the PMP issue_date." Count distinct categories
across ALL his projects = 3. Do NOT filter by the PMP date.

**Rule of thumb:** A named engineer, credential, or reference project is an
IDENTIFIER, not a WHERE clause. Only apply a date/engineer filter when the
question *explicitly* asks a temporal comparison ("completed **after** his
PMP date", "**between** 20XX and 20YY").

> **Lesson:** In these questions, the long human preamble is doing
> *entity resolution*, not *query filtering*. The hard part isn't writing
> the SQL — it's deciding what's an anchor vs what's a predicate. I got this
> backwards first, and only the 21-sample gate (below) caught it before it
> poisoned all 333 answers.

### How to learn from this
- For every question, explicitly separate **"who/what is being asked about"**
  (the entity to resolve) from **"what filter narrows the rows"** (the
  predicate). Write both down before writing SQL.
- If a named entity doesn't change the row count vs. the unfiltered scope,
  it's an anchor. Test it: run the query with and without the engineer
  filter; if gold matches the unfiltered version, the engineer was an anchor.

---

## 3. The 21-sample gate was the only thing that saved us

There was **no hidden gold** for the 333 — only a 21-question sample set
(`sample_questions.json` + `sample_answers.csv`, prefix `HS-IC`) gradable via
`python evaluate.py --submission … --questions sample_questions.json`.

This gate was the **single most valuable safeguard** in the whole effort:
- It proved my first scope hypothesis (engineer×client intersection) was
  **wrong** — gold was client-only.
- It proved the corrected semantics (client portfolio, anchors-not-filters,
  2-decimal percents) were **right** — 100% (21/21).
- It ran in ~5 min (42 agents), so I could iterate cheaply *before* touching
  the 333.

> **Lesson:** Never tune on the hidden set. Build the smallest possible
> graded proxy and gate every semantic change on it. The gate turned a
> confident-but-wrong assumption into a 5-minute correction instead of a
> 333-question disaster.

### How to learn from this
- Always find (or construct) a graded sample before scaling. If none exists,
  hand-label 10–20 questions yourself and treat them as gold.
- Run the gate after **every** prompt/rule change. If a change drops the
  gate, revert before it touches the big set.
- Keep the gate fast. A 5-min gate that runs 50× is worth more than a perfect
  one-shot that runs once.

---

## 4. The agentic approach (and where it broke)

We replaced the frozen reasoner with a **per-question analyst + judge**
pipeline via the Workflow tool:
- **Analyst** (one per question): reads schema, runs read-only SQL via
  `solution/query.py`, computes the answer, returns structured JSON.
- **Judge** (one per question): independently re-queries the DB, verifies
  entity resolution + scope + arithmetic, returns a final answer.

`solution/query.py` is a **read-only** helper: rejects non-SELECT, blocks
pragma/attach/writes, opens the DB in `mode=ro`. Agents never touch the DB
directly. This is non-negotiable for agentic SQL — give agents a sandboxed
tool, not a connection string.

### Where it broke: the rate limit
The 333×2 = 666-agent run hit the **Ollama account session usage limit
(HTTP 429)** ~7 hours in. 255/537 agents survived; 282 failed. The run kept
"completing" failed agents fast, but the result was 51 judge-verified
answers + a huge `missing` list.

> **Lesson:** Multi-agent fan-out is **fragile against rate limits**. A 666-
> agent burst can exhaust a session budget mid-run and there is no clean
> partial-success story. Plan for it.

### Recovery (what actually worked)
1. **Recover everything from the journal.** The workflow journal
   (`journal.jsonl`) records every agent's full return value. Even where the
   judge 429'd, the analyst's DB-computed answer was recoverable. I extracted
   203 answers (51 judge + 152 analyst-only) from the journal — not from the
   workflow's `missing`-laden return value.
2. **Probe the rate limit before re-bursting.** I launched 4 single agents.
   They succeeded in ~12s → the limit had a rolling window that reset. Then I
   ran a **leaner analyst-only** workflow (130 agents, no judge — half the
   load) for the missing set. 114/130 succeeded; the last 16 429'd again.
3. **Compute the simple remainder directly.** The last 16 were all
   two-category `cat_diff` questions — `SUM(catA) − SUM(catB)` per client.
   Trivially computable from the DB with one query each. No agent needed.
   I validated the sign convention against 3 existing agent answers, then
   computed all 16 myself. This finished the set without touching the rate
   limit again.

> **Lesson:** Don't use an agent where one SQL query will do. The agent is
> for the *hard* part (entity resolution, scope judgment, noise parsing).
> Once you've decoded a question family and validated the formula, compute
> it directly. The last 16 took 30 seconds and zero API budget.

### How to learn from this
- **Persist agent results to a journal you control.** Never depend on the
  orchestrator's final return value alone — it collapses to `missing` on any
  failure. The per-agent journal is your source of truth.
- **Stage your fan-out.** Run a small probe first to test limits, then scale.
  A 4-agent probe is cheaper than a 666-agent disaster.
- **Match the tool to the difficulty.** Agent for ambiguity; direct query
  for arithmetic. Halving agent count (analyst-only) when the judge adds
  little is a legitimate call once the analyst is validated.
- **Read-only DB tool for any agentic SQL.** Always. Agents will surprise
  you; make surprise impossible.

---

## 5. The audit: why we can trust the result (with no hidden gold)

Since the 333 have no local gold, the only confidence comes from
**hand-auditing against the DB**. I verified **17 answers across every
question family — 17/17 correct**:

| qid | type | answer | what it proved |
|-----|------|--------|----------------|
| 0001 | money | 2,942,400,000 | client portfolio (9 NEDA projects), not engineer |
| 0002 | money | 1,516,600,000 | exclusion_aggregate (drop Water Treatment) |
| 0322 | money | 2,860,100,000 | threshold ≥ 10 crore (1e8, **not** 1e9) |
| 0025 | money | −1,521,400,000 | year_diff (2024 − 2020), sign preserved |
| 0343 | money | 3,296,200,000 | client portfolio, anchor-not-filter |
| 0003 | percent | 90.19 | collection %, 2 decimals |
| 0253 | percent | 83.33 | 5/6 → **33.33 not 83** |
| 0256 | percent | 79.82 | collection % from financial |
| 0314 | percent | 85.71 | referenced_share 6/7 |
| 0164 | days | 143 | julianday diff, single project |
| 0031 | days | 1267 | days from PMP issue to completion |
| 0225 | count | 6 | distinct categories, engineer scope |
| 0263 | count | 3 | absence (no reference letter) |
| 0127 | money | 33,000,000 | gap_to_threshold (120 Cr − sum) |
| 0414 | cat_diff | 315,700,000 | sign convention: first − second |
| 0416 | cat_diff | −129,100,000 | sign preserved (negative) |
| 0419 | cat_diff | 985,600,000 | first − second confirmed |

> **Lesson:** With no gold, the audit **is** the test. Audit across *every
> answer family*, not just the easy ones — a solution that gets money right
> but percent wrong will still score poorly. The percent-integer bug (33 vs
> 33.33) only shows up if you specifically audit a 1/3-fraction percent.

### How to learn from this
- Audit one question per answer family, minimum. Don't audit 10 money
  questions and declare victory.
- For each audit, **recompute from scratch with a query you write yourself**
  — not the agent's query. The point is independent verification.
- Watch the unit traps: crore/lakh conversion (1 crore = 1e7, 10 crore =
  1e8), percent-out-of-100 vs 0–1 fraction, sign of differences, 2-decimal
  rounding.

---

## 6. Answer-format traps (where points silently leak)

The scorer is continuous closeness, so being "close" still scores — but
unit/format errors produce exact-zero or near-zero on questions you
*understood* correctly. These bit us:

- **Percent = out of 100, EXACTLY 2 decimals, NEVER an integer.**
  `33` is **wrong**, `33.33` is right. `67` is wrong, `66.67` is right.
  A 1/3 share → 33.33. The question saying "whole number out of a hundred"
  is filler — the format rule wins. Audit a 1/3-fraction percent to catch
  this.
- **Money = rupees as a plain integer.** Not crores, not "12.94 Cr", no
  commas. `129400000`, not `12.94`.
- **Crore/lakh thresholds:** 1 crore = 10,000,000 (1e7); 1 lakh = 100,000
  (1e5). "ten crore mark" = 1e8. I once audited with 1e9 (100 crore) and
  falsely flagged a correct answer — the conversion is a frequent error
  source on *both* sides.
- **Sign matters for differences.** `cat_diff` gold preserves sign:
  first-mentioned minus second-mentioned category. `|A−B|` when gold is
  `A−B=−X` gives `|your|=X, |gold|=X` but `|your−gold|=2X` → score 0.
- **Missing answer = 0.0.** Always submit your best numeric guess; never
  blank. Partial credit beats zero.

> **Lesson:** Most "wrong" answers in a closeness-scored contest aren't
> comprehension failures — they're unit/format/sign failures on questions
> you actually solved. Build a formatter that enforces these rules
> deterministically and never lets an agent return `33` for a percent.

---

## 7. The improvement was surgical, not wholesale

Only **37 of 333 rows changed** vs the old 74.754% version. The agents
**agreed** with the old reasoner on ~296 questions and **corrected 37
specific ones**. The two highest-value fixes:

1. **HV-IC-0002:** old `1,957,800,000` (Irrigation Rajasthan, **including**
   Water Treatment) → correct `1,516,600,000` (**excluding** Water
   Treatment). The exclusion_aggregate rule.
2. **HV-IC-0468:** old `8,563,200,000` (the entire Trishakti portfolio) →
   correct `1,042,700,000` (Large Bridges − Water Supply only). A
   cat_diff the old reasoner mis-scoped.

> **Lesson:** "Throw out the old solution and rebuild" often overcorrects.
> The old reasoner was ~89% right; the win was in finding and fixing the
> specific 11%, not in re-answering everything. Diffing old vs new and
> inspecting *which* rows changed (and why) is how you confirm the new
> approach is actually better, not just different.

### How to learn from this
- After regenerating, `git diff` the answers file and categorize every
  changed row: is the change a *correction* (old was wrong, new matches the
  DB) or a *regression* (old was right, new is wrong)? Audit both.
- A new method that changes 300/333 rows is suspicious; one that changes 37
  targeted rows, each auditable, is trustworthy.

---

## 8. Engineering / process checklist (what to do next time)

**Before writing any answerer:**
1. [ ] Confirm the model/reasoner is actually being invoked (not cached).
2. [ ] Build a graded sample gate. Run it after every change.
3. [ ] Build a read-only DB tool. Never give agents raw write access.
4. [ ] Decide anchor-vs-filter explicitly per question before SQL.

**During generation:**
5. [ ] Stage fan-out: probe limits with a few agents before bursting 100s.
6. [ ] Persist per-agent results to a journal; don't trust the orchestrator's
      collapsed return value.
7. [ ] Match tool to difficulty: agent for ambiguity, direct query for
      arithmetic once the family is decoded.

**After generation:**
8. [ ] Audit one answer per family, recomputed from scratch independently.
9. [ ] `git diff` vs the previous submission; classify each changed row as
      correction or regression.
10. [ ] Enforce answer format deterministically (percent 2-dec, money int,
       sign preserved, no blanks).

**Structural:**
11. [ ] Treat caches/plan files as build outputs. Be able to wipe and
       regenerate them in one command.
12. [ ] Add a "output changes when input changes" smoke test.

---

## 9. The domain semantics, condensed (the actual cheat-sheet)

These are the rules that, once known, make the questions mechanical:

- **Scope:** client identified → **client's entire portfolio** (all PMs).
  Never intersect engineer AND client. Engineer-only scope only when **no**
  client is named.
- **Anchors ≠ filters:** named engineer/credential/reference-project
  *identify* the entity; they are not WHERE predicates. No date filter
  unless an explicit temporal comparison is asked.
- **`financial` joins by `client_name` only** — `pkg_number` is NULL for all
  financial rows.
- **`has_reference_letter`** 0/1 mirrors `reference_letters` table presence.
- **`project_name`** has erratic capitalization — use `LOWER()`/`LIKE` or
  match via `pkg_number`.
- **Question families:** `hop_aggregate` (SUM over client portfolio),
  `exclusion_aggregate` (SUM minus a category), `threshold_aggregate`
  (SUM ≥ crore/lakh bar), `gap_to_threshold` (bar − SUM), `avg_work_size`
  (AVG, round), `rank_value` (largest − 2nd), `referenced_share`
  (100·refs/total, 2 dec), `absence` (count no-ref), `distinct_count`
  (distinct category), `date_span`/`days` (julianday diff, single project),
  `temporal_chain` (SUM after/before a credential date), `year_diff`
  (year_a − year_b), `cat_diff` (catA − catB, first-mentioned minus
  second-mentioned), `financial_reconciliation` (outstanding/billed/
  collected/collection%/awarded−invoiced gap).
- **Units:** money = rupees int; percent = out of 100, 2 decimals; count &
  days = int. 1 crore = 1e7, 1 lakh = 1e5.

---

## 10. Artifacts (how to reproduce / study this)

| File | Purpose |
|------|---------|
| `solution/answers.csv` | The deliverable: 333 rows, `question_id,answer`, 0 blanks |
| `solution/query.py` | Read-only SQLite helper for agents (rejects non-SELECT) |
| `solution/answer_workflow.mjs` | Analyst+judge Workflow orchestrator (run 1) |
| `solution/answer_missing.mjs` | Analyst-only Workflow for the missing set (run 2) |
| `solution/assemble_csv.py` | Assemble a result map → CSV |
| `solution/merge_final.py` | Merge run-1 + run-2 + last-16 into final `answers.csv` |
| `solution/result333.json` | Run-1 recovered answers (judge + analyst) |
| `solution/result_missing.json` | Run-2 recovered answers |
| `solution/result_last16.json` | The 16 cat_diffs computed directly |
| `solution/agent/reasoner.py` | The OLD deterministic reasoner (kept as documentation) |
| `evaluate.py` + `sample_questions.json` | The 21-sample gate |

**Key commits:**
- `77458ef` — Regenerate via agentic analyst+judge (203 fresh + 130 fallback)
- `5f882cf` — Complete all 333 (fill final 16 cat_diff from DB) ← **final**

**Reproduce the gate:**
```bash
python evaluate.py --submission solution/sample_answers.csv --questions sample_questions.json
```

**Reproduce a single answer by hand (the audit method):**
```bash
python3 solution/query.py "SELECT SUM(value) FROM projects WHERE client_name='National Expressway Development Authority'"
```

---

## 11. The honest one-liners

- "Same output every run" is a **cache** problem, not a model problem.
- The long preamble in a question is doing **entity resolution**, not
  **filtering**. Anchors ≠ predicates.
- The **sample gate** is the only thing standing between a confident wrong
  assumption and a 333-question disaster. Build it first.
- Multi-agent fan-out is **fragile against rate limits**; stage it, journal
  it, and don't use an agent where one query will do.
- With no hidden gold, the **hand-audit across every answer family** is the
  test.
- Most leaked points are **unit/format/sign** errors on solved questions, not
  comprehension failures.
- The win was **surgical** (37 targeted fixes), not wholesale — diff and
  classify every changed row.