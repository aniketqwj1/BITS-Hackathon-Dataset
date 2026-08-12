"""Deterministic Indian money + date parsing utilities.

The corpus renders money in many lossless formats (see BRIEFING.md §2):
    INR 33.38 Cr            -> 333,800,000
    Rs. 11.23 Crore         -> 112,300,000
    INR 24.85 Cr (Rupees 24.85 Crore Only)
    Rs. 2441.00 Lakh        -> 244,100,000
    Rs. 160.51 Lakh (Rupees 1.61 Crore Only)   -> 16,051,000 (primary figure wins)
    INR 11,32,00,000/-      -> 113,200,000  (Indian digit grouping)
    333,800,000             -> 333,800,000  (western grouping)
    333800000               -> 333,800,000  (plain)
    -3,90,26,159            -> -39,026,159  (negative, Indian grouping)

Dates appear as: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, "October 8, 2024",
"06 Feb 2011", "31 Mar 2026", and Excel serial integers (BOQ Measurements).
"""
import datetime
import re

UNIT_FACTORS = {
    "cr": 10_000_000, "crs": 10_000_000, "crore": 10_000_000, "crores": 10_000_000,
    "lakh": 100_000, "lacs": 100_000, "lakhs": 100_000, "lac": 100_000,
    "mn": 1_000_000, "million": 1_000_000,
    "k": 1_000, "thousand": 1_000,
}

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def parse_money(text):
    """Parse an Indian money string into rupees (int). Returns None if unparseable."""
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    # Strip currency symbols / words / suffixes, keep digits, commas, dots, minus.
    s = s.replace("₹", "").replace("/-", "").replace("Rs.", " ").replace("rs.", " ")
    s = re.sub(r"\b(?:INR|Rs|Rupees|Only|India\s*Rupees)\b", " ", s, flags=re.I)
    s = s.strip()

    # 1) Number + unit (Cr / Lakh / Million / Thousand). First match wins — the
    #    parenthetical "(Rupees 1.61 Crore Only)" is a conversion, not the primary.
    m = re.search(r"(-?\d[\d,]*\.?\d*)\s*(cr|crs|crore|crores|lakh|lacs|lakhs|lac|mn|million|k|thousand)\b",
                  s, re.I)
    if m:
        num = float(m.group(1).replace(",", ""))
        factor = UNIT_FACTORS.get(m.group(2).lower())
        if factor:
            return int(round(num * factor))

    # 2) Plain number (Indian or western grouping, optional sign).
    m = re.search(r"-?\d[\d,]*\.?\d*", s)
    if m:
        num_str = m.group(0).replace(",", "")
        try:
            return int(round(float(num_str)))
        except ValueError:
            return None
    return None


def parse_date(text):
    """Parse a date string into ISO 'YYYY-MM-DD'. Returns None if unparseable."""
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None

    # Excel serial date (e.g. 44211 = 2021-01-15).
    if re.fullmatch(r"\d{5}", s):
        try:
            return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(s))).isoformat()
        except (ValueError, OverflowError):
            return None

    # YYYY-MM-DD
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s

    # DD/MM/YYYY or DD-MM-YYYY
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime.date(y, mo, d).isoformat()
        except ValueError:
            return None

    # "06 Feb 2011" / "31 Mar 2026" / "25 Apr 2019"
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})[.,]?\s+(\d{4})", s)
    if m:
        d, mo, y = int(m.group(1)), m.group(2).lower()[:3], int(m.group(3))
        if mo in _MONTHS:
            try:
                return datetime.date(y, _MONTHS[mo], d).isoformat()
            except ValueError:
                return None

    # "October 8, 2024" / "March 31, 2026"
    m = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2})[.,]?\s+(\d{4})", s)
    if m:
        mo, d, y = m.group(1).lower()[:3], int(m.group(2)), int(m.group(3))
        if mo in _MONTHS:
            try:
                return datetime.date(y, _MONTHS[mo], d).isoformat()
            except ValueError:
                return None
    return None


def days_between(date_a, date_b):
    """Whole days from date_a to date_b (ISO strings). Returns None if either is bad."""
    a, b = parse_date(date_a), parse_date(date_b)
    if not a or not b:
        return None
    try:
        return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days
    except ValueError:
        return None


if __name__ == "__main__":
    # Quick self-test against the formats documented in BRIEFING.md.
    cases = [
        ("INR 33.38 Cr", 333_800_000),
        ("Rs. 11.23 Crore", 112_300_000),
        ("INR 24.85 Cr (Rupees 24.85 Crore Only)", 248_500_000),
        ("Rs. 2441.00 Lakh", 244_100_000),
        ("Rs. 160.51 Lakh (Rupees 1.61 Crore Only)", 16_051_000),
        ("INR 11,32,00,000/-", 113_200_000),
        ("333,800,000", 333_800_000),
        ("333800000", 333_800_000),
        ("-3,90,26,159", -39_026_159),
        ("Rs. 0 (Rupees 0 Only)", 0),
        ("INR 200.00 Cr", 2_000_000_000),
        ("INR 1.06 Cr", 10_600_000),
    ]
    bad = [(t, parse_money(t), e) for t, e in cases if parse_money(t) != e]
    print(f"money: {len(cases) - len(bad)}/{len(cases)} correct")
    for t, g, e in bad:
        print(f"  FAIL {t!r} -> {g} expected {e}")

    dcases = [
        ("2021-03-10", "2021-03-10"),
        ("11/01/2013", "2013-01-11"),
        ("06/02/2011", "2011-02-06"),
        ("October 8, 2024", "2024-10-08"),
        ("06 Feb 2011", "2011-02-06"),
        ("31 Mar 2026", "2026-03-31"),
        ("44211", "2021-01-15"),
    ]
    dbad = [(t, parse_date(t), e) for t, e in dcases if parse_date(t) != e]
    print(f"date: {len(dcases) - len(dbad)}/{len(dcases)} correct")
    for t, g, e in dbad:
        print(f"  FAIL {t!r} -> {g} expected {e}")
