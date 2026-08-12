"""The agentic reasoning loop: question -> plan -> fetch -> compute -> format.

Design:
  - The LLM (Ollama deepseek-v4-flash:cloud) maps a natural-language question to a
    structured JSON *plan*: which operation, which entities, which filters. It is
    given the exact entity names (engineers, clients, projects, credentials) so it
    never has to guess spellings or resolve abbreviations blindly.
  - The reasoner then fetches the relevant rows with trivial, template SQL and does
    the arithmetic in Python. This keeps SQL syntax-error-free and the math auditable.
  - If the LLM call fails or returns an unusable plan, a deterministic keyword parser
    falls back to a best-effort plan so every question still gets an answer.

The answer is always a plain number (money in rupees, a count, a percentage out of
100, or a number of days) — see evaluate.py.
"""
import json
import os
import re
import urllib.request

from .tools import (
    execute_sql, fts_search, load_entities, resolve_engineer,
    resolve_engineer_firstname, resolve_client, resolve_client_abbrev,
    resolve_project, resolve_project_by_pkg, resolve_credential, resolve_pkg,
)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "deepseek-v4-flash:cloud")

# ---------------------------------------------------------------------------
# Operations the reasoner can execute
# ---------------------------------------------------------------------------

OPERATION_DOCS = {
    "sum": "total value of a client's or engineer's completed works",
    "count": "number of completed works",
    "distinct_count": "number of distinct work categories",
    "count_absent": "number of works that have NO reference letter on file",
    "avg": "mean (average) work value",
    "avg_minus_median": "average work value minus the median work value",
    "rank_diff": "largest minus second-largest work value",
    "percent": "share of works that carry a reference letter, out of 100",
    "days": "days between a credential issue date and a project completion date",
    "gap_threshold": "how much more value is needed to reach a crore/lakh target",
    "sum_threshold": "total value of works at or above a crore/lakh threshold",
    "sum_exclude": "total value excluding one or more categories",
    "cat_diff": "value difference between two categories",
    "year_diff": "value difference between two completion years",
    "outstanding": "total amount still owed by a client (from invoices)",
    "financial_gap": "awarded contract value minus invoiced amount for a client",
    "financial_percent": "collection percentage (received/invoiced) for a client",
}

# ---------------------------------------------------------------------------
# LLM plan generation
# ---------------------------------------------------------------------------

def _llm_chat(prompt, temperature=0.0):
    """Call Ollama chat API; return the assistant's text."""
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": temperature,
        "format": "json",
    }).encode()
    req = urllib.request.Request(
        OLLAMA_URL + "/api/chat", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    return data.get("message", {}).get("content", "")


def _build_plan_prompt(question, entities):
    eng = ", ".join(entities["engineers"])
    cli = ", ".join(entities["clients"])
    proj = ", ".join(entities["projects"])
    cred = ", ".join(entities["credentials"])
    ops = "\n".join(f"- {k}: {v}" for k, v in OPERATION_DOCS.items())
    return f"""You are a data analyst for a construction company. Given a question, produce a JSON plan that lets a program compute the answer.

QUESTION: {question}

KNOWN ENGINEERS (exact names): {eng}
KNOWN CLIENTS (exact names): {cli}
KNOWN PROJECTS (exact names, include Pkg-N): {proj}
KNOWN CREDENTIALS (exact numbers): {cred}

OPERATIONS (pick exactly one):
{ops}

Return ONLY a JSON object with these keys:
{{
  "operation": "one of the operations above",
  "engineer": "exact engineer name or null",
  "credential_number": "exact credential number or null",
  "reference_project": "exact project name or null",
  "client": "exact client name or null",
  "exclude_categories": ["category names to exclude, or []"],
  "category_a": "first category for cat_diff, or null",
  "category_b": "second category for cat_diff, or null",
  "year_a": "completion year (int) for year_diff, or null",
  "year_b": "completion year (int) for year_diff, or null",
  "threshold": "rupee amount (int) for gap_threshold/sum_threshold, or null",
  "threshold_dir": ">= or > or null",
  "date_anchor": "YYYY-MM-DD for days/temporal, or null",
  "date_dir": "after or before or null",
  "answer_type": "money or percent or days or count"
}}

Rules:
- Resolve abbreviations to the exact known names (e.g. 'gujarat pw' -> 'Public Works Department, Govt of Gujarat').
- If the question names a project and asks about 'the client' / 'the commissioning client', set reference_project to that project and leave client null (the program will resolve the client).
- For crore/lakh thresholds, convert to rupees: 1 crore = 10,000,000; 1 lakh = 100,000. 'seventy-three crore' = 730000000.
- For 'days' questions, set date_anchor to the credential issue date and reference_project to the project.
- answer_type: money for rupee amounts, percent for percentages out of 100, days for day counts, count for counts.
"""


def _parse_plan(text):
    """Parse the LLM's JSON response into a plan dict. Returns None on failure."""
    if not text:
        return None
    text = text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        plan = json.loads(text)
    except json.JSONDecodeError:
        # Try to find the first {...} block
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            plan = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(plan, dict) or not plan.get("operation"):
        return None
    return plan


# ---------------------------------------------------------------------------
# Deterministic extraction (used as fallback AND to fill gaps in the LLM plan)
# ---------------------------------------------------------------------------

# Work categories as stored in the projects table (normalized for matching).
_CATEGORIES = [
    "Bridges Flyovers", "Buildings", "Expressways", "Industrial Epc",
    "Irrigation", "Large Bridges", "Roads Highways", "Roads Maintenance",
    "Sewerage Drainage", "Small Buildings", "Tunnels", "Water Supply",
]

_ONES = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}


def _num_word_to_int(w):
    """Parse a number word: 'forty-three', 'twenty six', 'fifteen', 'forty'."""
    parts = w.replace("-", " ").split()
    if len(parts) == 1:
        return _ONES.get(parts[0]) or _TENS.get(parts[0])
    if len(parts) == 2:
        t, o = parts
        if t in _TENS and o in _ONES:
            return _TENS[t] + _ONES[o]
    return None


def _norm_cat(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _match_category(q, categories=_CATEGORIES):
    """Return the known category whose normalized form appears in the question."""
    for c in categories:
        if _norm_cat(c) in _norm_cat(q):
            return c
    return None


_NUMWORD = (r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
            r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
            r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)")


def _extract_threshold(q):
    """Parse a crore/lakh threshold from the question into rupees."""
    q = q.lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:cr|crore)", q)
    if m:
        return int(float(m.group(1)) * 10_000_000)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:lakh|lac)", q)
    if m:
        return int(float(m.group(1)) * 100_000)
    # number words, e.g. "seventy-three crore" / "twenty six crore". The word
    # sequence is constrained to actual number words so 'clear the twenty-three'
    # can't be captured as the number.
    m = re.search(rf"\b((?:{_NUMWORD})(?:[ -](?:{_NUMWORD}))*)\s+(?:crore|crs?)\b", q)
    if m:
        n = _num_word_to_int(m.group(1))
        if n:
            return n * 10_000_000
    return None


def _extract_date_anchor(q):
    """Parse a date like '2021-03-10' or 'March 10, 2021' from the question."""
    from etl.money import parse_date
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", q)
    if m:
        return m.group(1)
    # tolerate ordinals ("March 10th, 2021") and abbreviated months ("Mar 10 2021")
    m = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?[.,]?\s+(\d{4})", q)
    if m:
        return parse_date(f"{m.group(1)} {m.group(2)}, {m.group(3)}")
    return None


def _extract_exclude_categories(q):
    """Extract categories to exclude from 'excluding X' / 'minus X' / 'set aside X'."""
    out = []
    for m in re.finditer(r"(?:exclud\w*|minus|apart from|other than|set aside|drop\w*|remov\w*)\s+([^,.;]+)", q):
        frag = m.group(1)
        cat = _match_category(frag)
        if cat:
            out.append(cat)
    return out


def _extract_cat_diff(q):
    """Find the two work categories a question contrasts.

    Scans the whole question for known categories rather than splitting on
    'and' (which breaks on 'bridges and flyovers work and the expressways').
    'bridges and flyovers' is normalized to 'bridgesflyovers' so it matches the
    stored category 'Bridges Flyovers'.
    """
    qn = _norm_cat(q)
    qn_noand = qn.replace("and", "")
    cats = []
    for c in _CATEGORIES:
        cn = _norm_cat(c)
        if cn in qn or cn in qn_noand:
            cats.append(c)
    cats = list(dict.fromkeys(cats))
    if len(cats) >= 2:
        return cats[0], cats[1]
    return None, None


def _fallback_plan(question, entities):
    """Best-effort deterministic plan from keywords + entity matching."""
    q = question.lower()
    plan = {
        "operation": None, "engineer": None, "credential_number": None,
        "reference_project": None, "client": None, "exclude_categories": [],
        "category_a": None, "category_b": None, "year_a": None, "year_b": None,
        "threshold": None, "threshold_dir": ">=", "date_anchor": None,
        "date_dir": None, "answer_type": None,
    }
    plan["engineer"] = resolve_engineer(question, entities["engineers"])
    if not plan["engineer"]:
        plan["engineer"] = resolve_engineer_firstname(question, entities["engineers"])
    plan["client"] = resolve_client(question, entities["clients"])
    if not plan["client"]:
        plan["client"] = resolve_client_abbrev(question, entities["clients"])
    plan["reference_project"] = resolve_project(question, entities["projects"])
    if not plan["reference_project"]:
        plan["reference_project"] = resolve_project_by_pkg(question, entities["projects"])
    if not plan["reference_project"] and plan["engineer"]:
        # Prefer the engineer's own projects (e.g. 'priti's west bengal hospital
        # block' must be Priti Pillai's project, not another engineer's).
        plan["reference_project"] = _resolve_ref_via_engineer(question, plan["engineer"])
    if not plan["reference_project"]:
        plan["reference_project"] = _resolve_ref_fuzzy(question, entities["projects"])
    plan["credential_number"] = resolve_credential(question, entities["credentials"])

    # answer_type
    if re.search(r"percent|percentage|out[- ]?of[- ]?100|out of one hundred|share", q):
        plan["answer_type"] = "percent"
    elif re.search(r"days|interval|span|elapsed|how long|count from|from that (?:issue|date|certification)|to (?:handover|wrap up)", q):
        plan["answer_type"] = "days"
    elif re.search(r"how many|count|number of works|number of distinct|distinct work categor", q):
        plan["answer_type"] = "count"
    else:
        plan["answer_type"] = "money"

    # filters (extracted regardless of operation)
    plan["threshold"] = _extract_threshold(q)
    plan["date_anchor"] = _extract_date_anchor(q)
    plan["exclude_categories"] = _extract_exclude_categories(q)
    plan["category_a"], plan["category_b"] = _extract_cat_diff(q)
    years = re.findall(r"\b(20\d{2})\b", q)
    if len(years) >= 2:
        plan["year_a"], plan["year_b"] = int(years[0]), int(years[1])
    if re.search(r"after|wrapped up after|completed after|post", q):
        plan["date_dir"] = "after"
    elif re.search(r"before|prior to|preceding", q):
        plan["date_dir"] = "before"

    # operation
    if re.search(r"average.*median|median.*average|mean.*median|median.*mean|avg.*median|median.*avg", q):
        plan["operation"] = "avg_minus_median"
    elif re.search(r"(?:largest|biggest|highest[-\s]?value).*(?:next|subsequent)|exceeds the next|next one down|second largest", q):
        plan["operation"] = "rank_diff"
    elif re.search(r"no .*reference letter|lack .*reference letter|unreferenced|without .*reference", q):
        plan["operation"] = "count_absent"
    elif re.search(r"reference letter|on file|verification|testimonial|endorsement", q):
        plan["operation"] = "percent" if re.search(r"percent|share|out[- ]?of[- ]?100|out of one hundred", q) else "count"
    elif re.search(r"days|interval|span|elapsed|how long|count from|from that (?:issue|date|certification)|to (?:handover|wrap up)", q):
        plan["operation"] = "days"
    elif re.search(r"exclud|minus|apart from|other than|set aside|drop\w*|remov\w*", q):
        plan["operation"] = "sum_exclude"
    elif re.search(r"how much more|additional work|still need|clear the .* bar|reach the .* target", q):
        plan["operation"] = "gap_threshold"
    elif plan["threshold"] is not None and re.search(r"clear|cross|exceed|above|mark|cutoff|threshold|at least|or more", q):
        plan["operation"] = "sum_threshold"
    elif re.search(r"outstanding|still owed|remaining balance|amount remains|unpaid|pending|net balance|balance due|amount still|currently due|still outstand|balance.*invoice|invoice.*balance", q):
        plan["operation"] = "outstanding"
    elif re.search(r"collection|collected|received.*billed|billed.*received|percentage of billed|percent.*billed", q):
        plan["operation"] = "financial_percent"
    elif re.search(r"cross-check.*(?:invoice|claims|billed)|(?:invoice|claims|billed).*cross-check|amount after|gap between.*(?:awarded|invoiced)", q):
        plan["operation"] = "financial_gap"
    elif re.search(r"difference|variance|spread|gap|delta|net shift|two (?:figures|scopes|totals)|both scopes", q):
        ca, cb = _extract_cat_diff(q)
        if ca and cb:
            plan["operation"] = "cat_diff"
        elif len(years) >= 2:
            plan["operation"] = "year_diff"  # e.g. "difference between 2020 and 2022"
        else:
            plan["operation"] = "rank_diff"  # "difference between largest and next"
    elif re.search(r"count of separate|distinct work categor|separate work categor|count of distinct|number of distinct|how many work categor", q):
        plan["operation"] = "distinct_count"
    elif re.search(r"average|mean|typical", q):
        plan["operation"] = "avg"
    elif re.search(r"how many|count|number of", q):
        plan["operation"] = "count"
    else:
        plan["operation"] = "sum"

    return plan


def _merge_plans(llm_plan, det_plan):
    """Fill gaps in the LLM plan with deterministic extractions.

    The LLM is authoritative for operation / engineer / client / reference_project /
    credential_number (it resolves abbreviations). The deterministic parser fills in
    filters (date, exclude categories, threshold, cat_diff, years) that the LLM
    sometimes omits.
    """
    merged = dict(llm_plan)
    for field in ("date_anchor", "date_dir", "threshold", "threshold_dir",
                  "category_a", "category_b", "year_a", "year_b"):
        if not merged.get(field) and det_plan.get(field):
            merged[field] = det_plan[field]
    # exclude_categories: union of both (LLM may miss some)
    merged["exclude_categories"] = list(dict.fromkeys(
        list(merged.get("exclude_categories") or []) +
        list(det_plan.get("exclude_categories") or [])))
    # answer_type: LLM wins, but fall back to deterministic
    if not merged.get("answer_type"):
        merged["answer_type"] = det_plan.get("answer_type")
    return merged


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def _fetch_projects(client=None, engineer=None, pkg=None):
    """Fetch project rows (value, category, completion_date, has_reference_letter)."""
    if pkg:
        rows = execute_sql(
            "SELECT pkg_number, project_name, client_name, value, category, "
            "completion_date, has_reference_letter FROM projects WHERE pkg_number = ?",
            (pkg,))
    elif client:
        rows = execute_sql(
            "SELECT pkg_number, project_name, client_name, value, category, "
            "completion_date, has_reference_letter FROM projects WHERE client_name = ?",
            (client,))
    elif engineer:
        rows = execute_sql(
            "SELECT pkg_number, project_name, client_name, value, category, "
            "completion_date, has_reference_letter FROM projects WHERE project_manager = ?",
            (engineer,))
    else:
        rows = execute_sql(
            "SELECT pkg_number, project_name, client_name, value, category, "
            "completion_date, has_reference_letter FROM projects")
    return [{
        "pkg": r[0], "name": r[1], "client": r[2], "value": r[3],
        "category": r[4], "completion_date": r[5], "has_ref": r[6],
    } for r in rows]


def _fetch_credential(credential_number):
    rows = execute_sql(
        "SELECT c.issue_date, e.name FROM credentials c "
        "JOIN engineers e ON e.engineer_id = c.engineer_id "
        "WHERE c.credential_number = ?", (credential_number,))
    if not rows:
        return None
    return {"issue_date": rows[0][0], "engineer": rows[0][1]}


def _fetch_financial(client):
    rows = execute_sql(
        "SELECT invoiced, received, outstanding FROM financial WHERE client_name = ?",
        (client,))
    return [{"invoiced": r[0], "received": r[1], "outstanding": r[2]} for r in rows]


def _client_of_project(project_name):
    rows = execute_sql(
        "SELECT client_name FROM projects WHERE project_name = ?", (project_name,))
    return rows[0][0] if rows else None


def _fetch_engineer_credential(engineer):
    """Return the engineer's PMP credential (issue_date) for 'days' questions."""
    rows = execute_sql(
        "SELECT c.credential_number, c.issue_date FROM credentials c "
        "JOIN engineers e ON e.engineer_id = c.engineer_id "
        "WHERE e.name = ? AND c.credential_type = 'PMP'", (engineer,))
    if not rows:
        return None
    return {"credential_number": rows[0][0], "issue_date": rows[0][1]}


_REF_STOP = {
    "the", "a", "an", "for", "of", "on", "in", "to", "pmp", "pkg",
    "package", "issued", "was", "back", "march", "2021", "how", "many",
    "days", "elapsed", "before", "that", "project", "wrapped", "up", "do",
    "you", "know", "actually", "pretty", "sure", "but", "his", "her",
    "their", "from", "until", "date", "completion", "completed", "work",
    "works", "led", "with", "for", "and", "its", "it", "is", "im", "i",
    "me", "my", "we", "our", "us", "what", "this", "these", "those", "can",
    "could", "please", "confirm", "whether", "recollection", "right",
    "fairly", "certain", "exact", "span", "final", "mark", "issue",
    "certification", "handover", "wrap", "run", "ran", "long", "much",
    "count", "the", "assignment", "package", "scope", "job", "site",
    "mar", "10", "10th", "2021", "hit", "pmp", "pritis", "priti",
}


def _resolve_ref_via_engineer(question, engineer):
    """Resolve a loosely-worded reference project (e.g. 'Madhya Pradesh water
    plant') by matching question tokens against the engineer's own projects."""
    from .tools import _norm
    q_tokens = set(_norm(question).split()) - _REF_STOP
    best, best_score = None, 0
    for p in _fetch_projects(engineer=engineer):
        p_tokens = set(_norm(p["name"]).split())
        score = len(q_tokens & p_tokens)
        if score > best_score:
            best, best_score = p["name"], score
    return best if best_score >= 2 else None


def _resolve_ref_fuzzy(question, projects):
    """Resolve a loosely-worded project reference (e.g. 'rajasthan pumping
    station') by matching question tokens against all project names."""
    from .tools import _norm
    q_tokens = set(_norm(question).split()) - _REF_STOP
    best, best_score = None, 0
    for name in projects:
        p_tokens = set(_norm(name).split())
        score = len(q_tokens & p_tokens)
        if score > best_score:
            best, best_score = name, score
    return best if best_score >= 2 else None


# ---------------------------------------------------------------------------
# Computation
# ---------------------------------------------------------------------------

def _compute(plan, projects, financial, credential):
    """Apply the plan's operation to the fetched data. Returns a number or None."""
    op = plan["operation"]
    values = [p["value"] for p in projects if p["value"] is not None]

    if op == "count_absent":
        return sum(1 for p in projects if not p["has_ref"])
    if op == "sum":
        vals = values
        # Temporal filter: only projects completed after/before the anchor date.
        if plan.get("date_anchor") and plan.get("date_dir"):
            anchor = plan["date_anchor"]
            if plan["date_dir"] == "after":
                vals = [p["value"] for p in projects
                        if p["completion_date"] and p["completion_date"] > anchor]
            else:
                vals = [p["value"] for p in projects
                        if p["completion_date"] and p["completion_date"] < anchor]
        return sum(vals) if vals else None
    if op == "count":
        return len(projects)
    if op == "distinct_count":
        cats = {p["category"] for p in projects if p["category"]}
        return len(cats)
    if op == "avg_minus_median":
        if not values:
            return None
        import statistics
        avg = sum(values) / len(values)
        med = statistics.median(values)
        return round(avg - med)
    if op == "avg":
        return round(sum(values) / len(values)) if values else None
    if op == "rank_diff":
        if len(values) < 2:
            return None
        s = sorted(values, reverse=True)
        return s[0] - s[1]
    if op == "percent":
        if not projects:
            return None
        ref = sum(1 for p in projects if p["has_ref"])
        return round(100.0 * ref / len(projects), 2)
    if op == "days":
        try:
            from ..etl.money import days_between
        except ImportError:
            from etl.money import days_between
        # Anchor date: credential issue date, else the plan's date_anchor.
        anchor = None
        if credential and credential.get("issue_date"):
            anchor = credential["issue_date"]
        elif plan.get("date_anchor"):
            anchor = plan["date_anchor"]
        if not anchor or not projects:
            return None
        p = projects[0]
        return days_between(anchor, p["completion_date"])
    if op == "gap_threshold":
        if plan["threshold"] is None or not values:
            return None
        return plan["threshold"] - sum(values)
    if op == "sum_threshold":
        if plan["threshold"] is None:
            return None
        d = plan["threshold_dir"] or ">="
        if d == ">":
            return sum(v for v in values if v > plan["threshold"])
        return sum(v for v in values if v >= plan["threshold"])
    if op == "sum_exclude":
        excl = {c.lower() for c in plan.get("exclude_categories", [])}
        return sum(p["value"] for p in projects
                   if p["value"] is not None and (p["category"] or "").lower() not in excl)
    if op == "cat_diff":
        a = plan.get("category_a") or ""
        b = plan.get("category_b") or ""
        sa = sum(p["value"] for p in projects if (p["category"] or "").lower() == a.lower())
        sb = sum(p["value"] for p in projects if (p["category"] or "").lower() == b.lower())
        return sa - sb
    if op == "year_diff":
        ya, yb = plan.get("year_a"), plan.get("year_b")
        if not ya or not yb:
            return None
        sa = sum(p["value"] for p in projects
                 if p["completion_date"] and p["completion_date"].startswith(str(ya)))
        sb = sum(p["value"] for p in projects
                 if p["completion_date"] and p["completion_date"].startswith(str(yb)))
        return sa - sb
    if op == "outstanding":
        if not financial:
            return None
        return sum(f["outstanding"] for f in financial if f["outstanding"] is not None)
    if op == "financial_gap":
        awarded = sum(values) if values else 0
        invoiced = sum(f["invoiced"] for f in financial if f["invoiced"] is not None)
        return awarded - invoiced
    if op == "financial_percent":
        if not financial:
            return None
        inv = sum(f["invoiced"] for f in financial if f["invoiced"] is not None)
        rec = sum(f["received"] for f in financial if f["received"] is not None)
        if not inv:
            return None
        return round(100.0 * rec / inv, 2)
    return None


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

class Reasoner:
    def __init__(self, cache_path=None):
        self.entities = load_entities()
        self.cache_path = cache_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "metadata", "plan_cache.json")
        self._cache = {}
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path) as f:
                    self._cache = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def _cache_key(self, question):
        return re.sub(r"\s+", " ", question.strip().lower())

    def needs_llm(self, question):
        """True if the deterministic parser cannot resolve any entity for this question."""
        det = _fallback_plan(question, self.entities)
        return not (det.get("client") or det.get("engineer") or det.get("reference_project"))

    def plan(self, question, use_cache=True, use_llm=True):
        """Produce a plan: cache -> (LLM merged with deterministic) -> deterministic.

        When use_llm is False, only the deterministic parser runs (fast path).
        """
        key = self._cache_key(question)
        if use_cache and key in self._cache:
            return self._cache[key]
        det = _fallback_plan(question, self.entities)
        plan = None
        if use_llm:
            try:
                prompt = _build_plan_prompt(question, self.entities)
                text = _llm_chat(prompt)
                llm_plan = _parse_plan(text)
                if llm_plan:
                    plan = _merge_plans(llm_plan, det)
            except Exception:
                plan = None
        if not plan:
            plan = det
        self._cache[key] = plan
        return plan

    def save_cache(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w") as f:
            json.dump(self._cache, f, indent=1)

    def answer(self, question, qid=None, use_llm=True):
        """Answer one question. Returns (answer_number_or_None, plan, trace)."""
        plan = self.plan(question, use_llm=use_llm)
        trace = {"plan": plan}

        # Resolve the target client (explicit, or via reference project).
        client = plan.get("client")
        if not client and plan.get("reference_project"):
            # Prefer the unambiguous pkg number embedded in the project name.
            pkg = resolve_pkg(plan["reference_project"])
            if pkg:
                rows = execute_sql(
                    "SELECT client_name FROM projects WHERE pkg_number = ?", (pkg,))
                client = rows[0][0] if rows else None
            else:
                client = _client_of_project(plan["reference_project"])
            trace["resolved_client"] = client

        # cat_diff: if the client is ambiguous (e.g. 'the Public Works
        # Department account'), pick the client whose projects contain both
        # categories. If several clients qualify, narrow by the generic client
        # type the question names (e.g. 'public works department').
        if not client and plan["operation"] == "cat_diff" \
                and plan.get("category_a") and plan.get("category_b"):
            rows = execute_sql(
                "SELECT client_name FROM projects WHERE category IN (?, ?) "
                "GROUP BY client_name HAVING COUNT(DISTINCT category) = 2",
                (plan["category_a"], plan["category_b"]))
            if len(rows) == 1:
                client = rows[0][0]
                trace["resolved_client"] = client
            else:
                ql = question.lower()
                for token in ("public works", "municipal", "irrigation",
                              "waterways", "health engineering", "jal nigam"):
                    if token in ql:
                        matches = [r[0] for r in rows if token in r[0].lower()]
                        if len(matches) == 1:
                            client = matches[0]
                            trace["resolved_client"] = client
                        break

        # Resolve the engineer (explicit, or via credential).
        engineer = plan.get("engineer")
        credential = None
        if plan.get("credential_number"):
            credential = _fetch_credential(plan["credential_number"])
            if credential and not engineer:
                engineer = credential["engineer"]
                trace["resolved_engineer"] = engineer

        # 'days' questions: if the engineer is ambiguous (e.g. 'Meera'), resolve
        # them from the reference project's project manager.
        if plan["operation"] == "days" and not engineer and plan.get("reference_project"):
            pkg = resolve_pkg(plan["reference_project"])
            if pkg:
                rows = execute_sql(
                    "SELECT project_manager FROM projects WHERE pkg_number = ?", (pkg,))
                if rows and rows[0][0]:
                    engineer = rows[0][0]
                    trace["resolved_engineer"] = engineer

        # 'days' questions: the credential issue date is the anchor. If the plan
        # only names the engineer (e.g. "Pooja Bose's PMP"), look up their PMP.
        if plan["operation"] == "days" and not credential and engineer:
            cred = _fetch_engineer_credential(engineer)
            if cred:
                credential = {"issue_date": cred["issue_date"], "engineer": engineer}
                trace["resolved_credential"] = cred["credential_number"]

        # 'days' questions: resolve a loosely-worded reference project (e.g.
        # "the Madhya Pradesh water plant") via the engineer's own projects.
        if plan["operation"] == "days" and not plan.get("reference_project") and engineer:
            ref = _resolve_ref_via_engineer(question, engineer)
            if ref:
                plan["reference_project"] = ref
                trace["resolved_ref"] = ref

        # avg_minus_median: the client is the commissioning client of the
        # engineer's project (the question names the credential, not the client).
        if plan["operation"] == "avg_minus_median" and not client and not plan.get("reference_project") and engineer:
            ref = _resolve_ref_via_engineer(question, engineer)
            if ref:
                plan["reference_project"] = ref
                trace["resolved_ref"] = ref
                pkg = resolve_pkg(ref)
                if pkg:
                    rows = execute_sql(
                        "SELECT client_name FROM projects WHERE pkg_number = ?", (pkg,))
                    client = rows[0][0] if rows else None
                    trace["resolved_client"] = client

        # Fetch data.
        projects = _fetch_projects(client=client, engineer=engineer)
        financial = _fetch_financial(client) if client else []
        trace["n_projects"] = len(projects)
        trace["n_financial"] = len(financial)

        # For 'days', the reference project is the one to measure.
        if plan["operation"] == "days" and plan.get("reference_project"):
            pkg = resolve_pkg(plan["reference_project"])
            if pkg:
                projects = _fetch_projects(pkg=pkg)

        # Absence questions: count works with no reference letter.
        if plan["operation"] == "count" and plan.get("reference_project") is None \
                and re.search(r"no .*reference letter|lack .*reference letter|unreferenced",
                              question, re.I):
            return sum(1 for p in projects if not p["has_ref"]), plan, trace

        result = _compute(plan, projects, financial, credential)
        trace["result"] = result
        return result, plan, trace


def format_answer(value, answer_type):
    """Cast a computed number to the plain-number submission format."""
    if value is None:
        return ""
    if isinstance(value, float):
        # Percentages keep up to 2 decimals; money/counts/days are integers.
        if answer_type == "percent":
            return f"{value:.2f}".rstrip("0").rstrip(".")
        return str(int(round(value)))
    return str(value)
