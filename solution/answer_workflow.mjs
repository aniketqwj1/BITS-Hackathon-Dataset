export const meta = {
  name: 'text-to-sql-agent-judge',
  description: 'Answer construction-DB questions: analyst queries hackathon.db, judge verifies each',
  phases: [
    { title: 'Answer', detail: 'one analyst agent per question queries the DB and computes an answer' },
    { title: 'Judge', detail: 'one judge agent per question independently re-derives and returns the final answer' },
  ],
}

// ---------------------------------------------------------------------------
// Shared context embedded in every agent prompt
// ---------------------------------------------------------------------------

const QUERY_PY = '/Users/aniketsaxena/Documents/p/from_aug_1/p0/BITS-Hackathon-Dataset/solution/query.py'
const SCHEMA_GUIDE = '/Users/aniketsaxena/Documents/p/from_aug_1/p0/BITS-Hackathon-Dataset/solution/metadata/schema_guide.md'
const DICT = '/Users/aniketsaxena/Documents/p/from_aug_1/p0/BITS-Hackathon-Dataset/solution/metadata/dynamic_dictionary.json'

const CONTEXT = `
You are working against a SQLite database of a construction company.
DB helper (READ-ONLY, use via Bash):  python3 ${QUERY_PY} "SELECT ..."
  - It prints rows as a JSON array of objects. Example: python3 ${QUERY_PY} "SELECT pkg_number, value FROM projects WHERE client_name='X'"
  - Only SELECT / WITH allowed. No writes.

SCHEMA (read these files first with the Read tool for full detail):
  - ${SCHEMA_GUIDE}
  - ${DICT}

Tables (key facts):
  - projects (155 rows): the PRIMARY table. Columns: pkg_number (canonical key, e.g. 'Pkg-47'), project_name, category, client_name, value (rupees int), completion_date (ISO), issuance_date, project_manager (engineer's FULL NAME), has_reference_letter (1/0), grading, role ('Prime'/'JV Partner'), cert_ref.
  - engineers (39 rows): name, employee_id, business_unit, qualification. Join to projects via projects.project_manager = engineers.name.
  - credentials (48 rows): credential_type ('PMP' / 'Six Sigma Black Belt'), credential_number ('PMI-xxxxxx' / '6S-xxxxxx'), issue_date. Join to engineers via engineer_id.
  - financial (518 rows): invoice_no, client_name, invoiced, received, outstanding (rupees int), status ('paid'/'due'/'part_paid'). pkg_number is NULL for all rows -> join financial to clients ONLY via client_name.
  - reference_letters (132 rows): pkg_number. Presence of a row == the project HAS a reference letter (mirrors projects.has_reference_letter).
  - bonds (60 rows, sparse): bond_no, category, rfp_number, amount, issue_date. Usually irrelevant.

WORK CATEGORIES (exact strings in projects.category — 13 total):
  'Bridges Flyovers', 'Buildings', 'Expressways', 'Industrial Epc', 'Irrigation',
  'Large Bridges', 'Roads Highways', 'Roads Maintenance', 'Sewerage Drainage',
  'Small Buildings', 'Tunnels', 'Water Supply', 'Water Treatment'

CRITICAL MATCHING GOTCHAS:
  - pkg_number is CLEAN ('Pkg-47'). When a question names a package number (e.g. 'Pkg-47', 'Package 47'), match on pkg_number — it is the reliable key.
  - client_name is CLEAN (e.g. 'National Expressway Development Authority', 'Irrigation & Waterways Dept, Govt of Rajasthan'). Match directly.
  - project_manager is CLEAN proper names (e.g. 'Rajesh Rao'). Match directly.
  - project_name has ERRATIC capitalization (e.g. 'material handlinG Plant — Uttar Pradesh PkG-47'). NEVER match project_name with exact case — always use LOWER() / ILIKE-style LIKE, or match via pkg_number instead.
  - Engineer first-name-only references (e.g. 'Meera'): resolve to the full name by checking engineers.name / project_manager (use the unique match; if ambiguous, disambiguate via the named project/credential).
  - Client abbreviations: map to the exact client_name (e.g. 'Gujarat PWD' -> 'Public Works Department, Govt of Gujarat'; 'Jal Nigam UP' -> 'Jal Nigam, Uttar Pradesh'). When unsure, SELECT DISTINCT client_name FROM projects WHERE client_name LIKE '%...%' to find the exact string.

ANCHORS vs FILTERS (the #1 error source — read carefully):
  - A named ENGINEER, a CREDENTIAL (PMP / Six Sigma / 'PMI-xxx' / '6S-xxx'), and a named REFERENCE PROJECT exist to IDENTIFY the client or engineer being asked about. They are ANCHORS, NOT data filters.
  - Do NOT filter the project set by project_manager just because an engineer is named.
  - Do NOT filter by the credential issue_date just because a credential is named. ("under his PMP certification" / "referencing her PMP" means the PMP identifies the engineer — it does NOT mean "projects completed after the PMP date".)
  - ONLY apply a date filter when the question EXPLICITLY asks for a temporal comparison: "completed after his PMP date", "wrapped up after that date", "between 20XX and 20YY", "prior to that".

SCOPE (which set of projects to aggregate):
  - A CLIENT is identified whenever the question names a client directly OR says "that client" / "the client" / "that portfolio" / "that account" / "the commissioning client" (often alongside a reference project that pins down which client). When a client is identified, the scope is the CLIENT'S ENTIRE PORTFOLIO: ALL projects for that client, every project_manager. e.g. "every completed assignment he has delivered for the Public Works Department" = SUM over ALL of that client's projects (verified: 6 projects by 6 different PMs), NOT just the named engineer's.
  - Only when NO client is involved but an engineer is named ("all of Rahul Menon's completed assignments", "every completed assignment she has delivered" with no client) is the scope the ENGINEER's entire portfolio: WHERE project_manager = that engineer.
  - NEVER intersect engineer AND client. If a client is identified, use the client portfolio and ignore the engineer for filtering.
  - 'days' questions -> a SINGLE project (the named reference project) matched by pkg_number, with a credential issue_date as the anchor date.

VERIFIED EXAMPLE (from gold answers — match this behavior):
  Q: "Starting from Rahul Menon's PMP (PMI-200029) for the Ring Road — Maharashtra Pkg-125, what is the combined value of every completed assignment he has delivered for the Public Works Department, Govt of Maharashtra?"
  -> The client is "Public Works Department, Govt of Maharashtra" (identified by the named client AND the reference project). Rahul Menon / PMI-200029 / Pkg-125 are ANCHORS, not filters.
  -> Correct scope = ALL projects for that client (6 projects, by 6 different PMs): SELECT SUM(value) FROM projects WHERE client_name='Public Works Department, Govt of Maharashtra' = 2,008,200,000.
  -> WRONG (do not do this): filtering by project_manager='Rahul Menon' gives only Pkg-125 = 529,900,000.
  Q: "How many different categories of work has Chandan Banerjee led to completion under his PMP certification?"
  -> "under his PMP" identifies the engineer. Count distinct categories across ALL his projects: SELECT COUNT(DISTINCT category) FROM projects WHERE project_manager='Chandan Banerjee' = 3. Do NOT filter by the PMP issue_date.

QUESTION-FAMILY -> WHAT TO COMPUTE:
  - hop_aggregate: SUM(projects.value) over the resolved scope — almost always the CLIENT'S ENTIRE PORTFOLY (all of that client's projects, every PM), where the named engineer+credential+reference project merely identify which client. Sum ALL of the client's projects; do not filter by engineer.
  - exclusion_aggregate: SUM(projects.value) for a scope EXCLUDING one or more categories (use the exact category strings above; 'water treatment' = 'Water Treatment').
  - threshold_aggregate: SUM(projects.value) where value >= (or >) a crore/lakh threshold. 1 crore = 10,000,000; 1 lakh = 100,000.
  - gap_to_threshold: threshold - SUM(value) (how much more needed to reach the bar).
  - avg_work_size: AVG(value) over the scope (round to nearest rupee).
  - rank_value: over a client's projects, ORDER BY value DESC, return (largest - second-largest).
  - referenced_share: 100 * COUNT(has_reference_letter=1) / COUNT(*) for a scope, rounded to 2 decimals (a percent out of 100).
  - absence: COUNT of projects in a scope with has_reference_letter=0 (no reference letter on file).
  - distinct_count: COUNT(DISTINCT category) over a scope (e.g. all of an engineer's projects, or all of a client's projects). "under his PMP certification" identifies the engineer — count distinct categories across ALL his projects, do NOT filter by the PMP date.
  - date_span / days: julianday(completion_date) - julianday(issue_date) for the named project + credential. Whole days.
  - temporal_chain: SUM(value) for an engineer where completion_date is after (or before) a credential issue_date.
  - year_diff: SUM(value where completion_date LIKE 'YYYY-%') for year_a minus same for year_b.
  - cat_diff: SUM(value for category_a) - SUM(value for category_b) over a scope.
  - financial_reconciliation: from financial per client: outstanding = SUM(outstanding); billed = SUM(invoiced); collected = SUM(received); collection % = 100*received/invoiced (out of 100); awarded-vs-invoiced gap = SUM(projects.value for client) - SUM(financial.invoiced for client).

ANSWER FORMAT (the scorer compares numbers; get the unit right):
  - money -> rupees as a plain integer (e.g. 129400000), NOT crores, NOT with commas/units.
  - percent -> a number OUT OF 100, rounded to EXACTLY 2 decimals (e.g. 90.19, 33.33, 66.67). NEVER round a percent to an integer (33 is WRONG, 33.33 is RIGHT; 67 is WRONG, 66.67 is RIGHT). Never return a 0-1 fraction.
  - count -> an integer.
  - days -> an integer (whole days).
  - Never return blank/null if the data exists; if genuinely unanswerable, return null. The scorer gives 0 for missing answers but partial credit for close numbers, so always give your best numeric answer.

QUESTION-SPECIFIC NOTE: many questions are wrapped in conversational filler ("I'm pretty sure...", "to lock the submission", "still getting my head around..."). IGNORE the filler and extract the actual quantitative ask.
`

// ---------------------------------------------------------------------------
// Structured-output schemas
// ---------------------------------------------------------------------------

const ANALYST_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    qid: { type: 'string' },
    answer: { type: ['number', 'null'] },
    answer_type: { type: 'string', enum: ['money', 'percent', 'days', 'count'] },
    reasoning: { type: 'string', description: 'brief: scope resolved, operation, key query results' },
    queries: { type: 'array', items: { type: 'string' }, description: 'the SQL statements you ran' },
  },
  required: ['qid', 'answer', 'answer_type', 'reasoning', 'queries'],
}

const JUDGE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    qid: { type: 'string' },
    verdict: { type: 'string', enum: ['agree', 'disagree'] },
    final_answer: { type: ['number', 'null'], description: 'the verified answer (echo analyst answer if agree; corrected if disagree)' },
    reason: { type: 'string', description: 'brief: what you independently verified, or the error you found' },
  },
  required: ['qid', 'verdict', 'final_answer', 'reason'],
}

// ---------------------------------------------------------------------------
// Load the question list (a workflow script cannot read files, so a single
// loader agent reads the questions JSON and returns the structured array the
// orchestrator fans out over). args = absolute path to the questions JSON.
// ---------------------------------------------------------------------------

const QLIST_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    questions: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          qid: { type: 'string' },
          question: { type: 'string' },
          answer_type: { type: 'string', enum: ['money', 'percent', 'days', 'count'] },
        },
        required: ['qid', 'question', 'answer_type'],
      },
    },
  },
  required: ['questions'],
}

const questionsPath = args
log(`Loading questions from ${questionsPath}`)
const loaded = await agent(
  `Read the file at ${questionsPath} with the Read tool. It is a JSON object with a top-level "questions" array (each item has qid, question, answer_type — and possibly other keys you should ignore). Return EVERY question verbatim, in file order, as the structured object. Do not paraphrase, truncate, or skip any question.`,
  { label: 'loader', phase: 'Answer', schema: QLIST_SCHEMA },
)
const questions = (loaded && loaded.questions) || []
log(`Loaded ${questions.length} questions`)
if (questions.length === 0) {
  return { final: {}, missing: [], judged: 0, error: 'loader returned no questions' }
}

// ---------------------------------------------------------------------------
// Pipeline: each question -> analyst -> judge
// ---------------------------------------------------------------------------

const analystPrompt = (q) => `${CONTEXT}

QUESTION (qid=${q.qid}, answer_type=${q.answer_type}):
${q.question}

TASK:
1. Read ${SCHEMA_GUIDE} and ${DICT} for exact entity names / schema.
2. Use Bash: python3 ${QUERY_PY} "SELECT ..." to query the DB. Run as many queries as needed (resolve entities exactly, then compute).
3. Compute the numeric answer per the question-family rules above. Watch the SCOPE (intersection vs client-only vs engineer) and the ANSWER FORMAT.
4. Return the JSON object per the schema (qid, answer, answer_type, reasoning, queries).`

const judgePrompt = (q, analyst) => `${CONTEXT}

QUESTION (qid=${q.qid}, answer_type=${q.answer_type}):
${q.question}

ANALYST ANSWER: ${analyst && analyst.answer !== undefined ? analyst.answer : '(analyst produced no answer)'}
ANALYST REASONING: ${analyst && analyst.reasoning ? analyst.reasoning : '(none)'}
ANALYST QUERIES:
${analyst && Array.isArray(analyst.queries) ? analyst.queries.map((s) => '  ' + s).join('\n') : '  (none)'}

TASK — you are a STRICT JUDGE. Do NOT trust the analyst. Independently re-derive the answer:
1. Read ${SCHEMA_GUIDE} and ${DICT}.
2. Use Bash: python3 ${QUERY_PY} "SELECT ..." to run your OWN queries. Verify the entity resolution (exact names), the SCOPE (intersection vs client-only vs engineer — the #1 error source), the operation, and the arithmetic.
3. If the analyst is correct, set verdict='agree' and final_answer = the analyst's answer. If wrong, set verdict='disagree' and final_answer = the corrected answer.
4. Return the JSON object per the schema (qid, verdict, final_answer, reason). Always provide final_answer.`

phase('Answer')
const results = await pipeline(
  questions,
  (q) => agent(analystPrompt(q), { label: `analyst:${q.qid}`, phase: 'Answer', schema: ANALYST_SCHEMA }),
  (analyst, q) => agent(judgePrompt(q, analyst), { label: `judge:${q.qid}`, phase: 'Judge', schema: JUDGE_SCHEMA }),
)

// Assemble qid -> final_answer (judge wins).
const final = {}
for (const r of results) {
  if (r && r.qid && r.final_answer !== undefined && r.final_answer !== null) {
    final[r.qid] = r.final_answer
  }
}
const missing = questions.filter((q) => !(q.qid in final)).map((q) => q.qid)
return { final, missing, judged: results.filter(Boolean).length }