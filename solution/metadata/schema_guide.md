# Schema Guide (auto-generated)

## bonds  (60 rows)

_One row per performance bond (60). bond_no, category, rfp_number, amount (rupees int), issue_date, expiry_date. Links to tenders via rfp_number, not pkg_number._

| column | type | samples / stats |
|---|---|---|
| id | INTEGER | min=1 max=60 avg=30.5 nulls=0/60 |
| bond_no | TEXT | `BG/101`, `BG/105`, `BG/120`, `BG/128`, `BG/132`, `BG/136` |
| category | TEXT | `Bridges Flyovers`, `Buildings`, `Industrial Epc`, `Irrigation`, `Roads Highways`, `Sewerage Drainage` |
| rfp_number | TEXT | `RFP-132000485`, `RFP-132000970`, `RFP-132002522`, `RFP-132003007`, `RFP-132003201`, `RFP-132004559` |
| amount | INTEGER | min=5214000 max=39665000 avg=13414478.3 nulls=37/60 |
| issue_date | TEXT | `2019-06-17`, `2019-10-08`, `2019-10-24`, `2019-11-03`, `2019-11-14`, `2020-04-19` |
| expiry_date | TEXT |  |

## credentials  (48 rows)

_One row per engineer credential (48). credential_type is 'PMP' or 'Six Sigma Black Belt'. credential_number is like 'PMI-200029' or '6S-500161'. issue_date is ISO. Join to engineers via engineer_id._

| column | type | samples / stats |
|---|---|---|
| credential_id | INTEGER | min=1 max=48 avg=24.5 nulls=0/48 |
| engineer_id | INTEGER | min=1 max=39 avg=20.4 nulls=0/48 |
| credential_type | TEXT | `PMP`, `Six Sigma Black Belt` |
| credential_number | TEXT | `6S-500156`, `6S-500157`, `6S-500158`, `6S-500159`, `6S-500160`, `6S-500161` |
| issue_date | TEXT | `2021-03-10`, `2023-01-01` |
| valid_through | TEXT | `2027-08-31`, `2028-01-01`, `2029-09-15` |

## engineers  (39 rows)

_One row per engineer (48). name is the full name; employee_id is EMP-xxxxx. Join to projects via projects.project_manager = engineers.name. Join to credentials via credentials.engineer_id._

| column | type | samples / stats |
|---|---|---|
| engineer_id | INTEGER | min=1 max=39 avg=20.0 nulls=0/39 |
| name | TEXT | `Amit Iyer`, `Amit Mukherjee`, `Asha Bose`, `Asha Nair`, `Chandan Banerjee`, `Deepa Chatterjee` |
| employee_id | TEXT | `EMP-001`, `EMP-002`, `EMP-003`, `EMP-004`, `EMP-005`, `EMP-006` |
| designation | TEXT |  |
| business_unit | TEXT | `Civil Construction & Infrastructure`, `Facility Maintenance & O&M`, `Industrial EPC`, `Small Works Division`, `Special Projects Division`, `Specialized Technical Services` |
| qualification | TEXT | `B.Com`, `B.E. Civil`, `B.Tech Civil`, `B.Tech Electrical`, `B.Tech Mechanical`, `Diploma Civil` |

## financial  (518 rows)

_One row per AR invoice (519). invoice_no like 'AR-2019-00007'. client_name is the client. invoiced / received / outstanding are rupees (int). status is 'paid' / 'due' / 'part_paid'. pkg_number is populated where the invoice maps to a project (may be NULL). Join to projects via pkg_number, or to clients via client_name._

| column | type | samples / stats |
|---|---|---|
| id | INTEGER | min=1 max=518 avg=259.5 nulls=0/518 |
| invoice_no | TEXT | `AR-2019-00007`, `AR-2019-00008`, `AR-2019-00009`, `AR-2019-00012`, `AR-2019-00017`, `AR-2019-00022` |
| client_name | TEXT | `Arunodaya Infrastructure`, `Central Works & Buildings Bureau`, `Gujarat Municipal Corporation`, `Irrigation & Waterways Dept, Govt of Rajasthan`, `Irrigation & Waterways Dept, Govt of Uttar Pradesh`, `Jal Nigam, Gujarat` |
| invoice_date | TEXT | `2019-07-06`, `2019-09-17`, `2019-10-02`, `2019-10-11`, `2019-11-29`, `2019-12-01` |
| invoiced | INTEGER | min=1541921 max=67434643 avg=33783783.3 nulls=0/518 |
| status | TEXT | `due`, `paid`, `part_paid` |
| received | INTEGER | min=0 max=74852454 avg=28703054.2 nulls=0/518 |
| outstanding | INTEGER | min=-9820053 max=67434643 avg=5080729.0 nulls=0/518 |
| pkg_number | TEXT |  |

## projects  (155 rows)

_One row per completed work (155). PRIMARY entity table. pkg_number is the canonical key (e.g. 'Pkg-21'); project_name embeds it. value is the contract value in rupees (int). has_reference_letter is 1/0. project_manager is the engineer's full name. completion_date / issuance_date are ISO dates. category is the work classification. grading is the completion grade. role is 'Prime' or 'JV'._

| column | type | samples / stats |
|---|---|---|
| project_id | INTEGER | min=1 max=155 avg=78.0 nulls=0/155 |
| pkg_number | TEXT | `Pkg-1`, `Pkg-10`, `Pkg-100`, `Pkg-101`, `Pkg-102`, `Pkg-103` |
| project_name | TEXT | `BitUminoUs overlay — odisha PkG-35`, `BitUminoUs overlay — odisha PkG-63`, `Box CUlvert Chain — madhya Pradesh PkG-57`, `Box CUlvert Chain — tamil nadU PkG-92`, `CaBle stayed BridGe — Jharkhand PkG-115`, `CaBle stayed BridGe — Uttar Pradesh PkG-121` |
| category | TEXT | `Bridges Flyovers`, `Buildings`, `Expressways`, `Industrial Epc`, `Irrigation`, `Large Bridges` |
| client_name | TEXT | `Arunodaya Infrastructure`, `Central Works & Buildings Bureau`, `Gujarat Municipal Corporation`, `Irrigation & Waterways Dept, Govt of Rajasthan`, `Irrigation & Waterways Dept, Govt of Uttar Pradesh`, `Irrigation & Waterways Dept, Govt of West Bengal` |
| value | INTEGER | min=10600000 max=2000000000 avg=356800000.0 nulls=0/155 |
| completion_date | TEXT | `2010-02-26`, `2010-03-01`, `2010-07-29`, `2010-08-13`, `2010-08-20`, `2010-08-23` |
| issuance_date | TEXT | `2010-02-26`, `2010-03-01`, `2010-07-29`, `2010-08-13`, `2010-08-20`, `2010-08-23` |
| project_manager | TEXT | `Amit Iyer`, `Amit Mukherjee`, `Asha Nair`, `Chandan Banerjee`, `Deepa Chatterjee`, `Divya Singh` |
| has_reference_letter | INTEGER | min=0 max=1 avg=0.9 nulls=0/155 |
| grading | TEXT | `Excellent`, `Good`, `Satisfactory`, `Very Good` |
| cert_ref | TEXT | `CC/1/2014/090`, `CC/10/2016/143`, `CC/10/2024/009`, `CC/11/2019/140`, `CC/11/2021/069`, `CC/12/2012/073` |
| role | TEXT | `JV
Partner`, `JV Partner`, `Prime` |
| source_docs | TEXT | `PPP` |

## raw_documents  (1953 rows)

_Fallback full-text layer: one row per extracted page (1953). content is the raw text. Use doc_fts (FTS5) to search it when structured tables come up empty._

| column | type | samples / stats |
|---|---|---|
| id | INTEGER | min=1 max=1953 avg=977.0 nulls=0/1953 |
| doc_id | TEXT | `DOC-AR-2024`, `DOC-AR-2025`, `DOC-BANK-2019`, `DOC-BANK-2020`, `DOC-BANK-2021`, `DOC-BANK-2022` |
| filename | TEXT | `DOC-AR-2024.pdf`, `DOC-AR-2025.pdf`, `DOC-BANK-2019.pdf`, `DOC-BANK-2020.pdf`, `DOC-BANK-2021.pdf`, `DOC-BANK-2022.pdf` |
| page_number | INTEGER | min=1 max=72 avg=11.7 nulls=0/1953 |
| content | TEXT | `--- DOC-AR-2024 page 1 ---
National Infrastructure Corp. Ltd…`, `--- DOC-AR-2024 page 10 ---
ANNEXURE — VARIATION ORDERS APPR…`, `--- DOC-AR-2024 page 11 ---
ANNEXURE — TRADE RECEIVABLES AGE…`, `--- DOC-AR-2024 page 12 ---
INDEPENDENT AUDITOR'S REPORT
To …`, `--- DOC-AR-2024 page 13 ---
ANNEXURE — TRIAL BALANCE AS AT 3…`, `--- DOC-AR-2024 page 14 ---
ANNEXURE — FIXED ASSET REGISTER …` |
| metadata | TEXT | `{"doc_type": "annual_report"}`, `{"doc_type": "bank_statement"}`, `{"doc_type": "company_completion_certificate"}`, `{"doc_type": "completion_certificate"}`, `{"doc_type": "compliance_matrix"}`, `{"doc_type": "cv"}` |
| timestamp | DATETIME | min=2026-08-12 16:41:00 max=2026-08-12 16:42:01 avg=2026.0 nulls=0/1953 |

## reference_letters  (132 rows)

_One row per reference letter (132). pkg_number links to projects. Presence of a row here means the project HAS a reference letter._

| column | type | samples / stats |
|---|---|---|
| id | INTEGER | min=1 max=132 avg=66.5 nulls=0/132 |
| pkg_number | TEXT | `Pkg-1`, `Pkg-10`, `Pkg-100`, `Pkg-102`, `Pkg-104`, `Pkg-105` |
| project_name | TEXT | `Anganwadi Centre — Gujarat Pkg-151`, `Bituminous Overlay — Odisha Pkg-35`, `Box Culvert Chain — Madhya Pradesh Pkg-57`, `Box Culvert Chain — Tamil Nadu Pkg-92`, `Cable Stayed Bridge — Delhi Pkg-109`, `Cable Stayed Bridge — Uttar Pradesh Pkg-121` |
| client_name | TEXT | `Arunodaya Infrastructure`, `Central Works & Buildings Bureau`, `Gujarat Municipal Corporation`, `Irrigation & Waterways Dept, Govt of Rajasthan`, `Irrigation & Waterways Dept, Govt of Uttar Pradesh`, `Irrigation & Waterways Dept, Govt of West` |
| doc_id | TEXT | `DOC-REF-001`, `DOC-REF-002`, `DOC-REF-003`, `DOC-REF-004`, `DOC-REF-005`, `DOC-REF-006` |

## Question-family → table/column map

- **absence**: projects.has_reference_letter (1/0) + reference_letters table. Count projects for a client with has_reference_letter=0, or check reference_letters for a pkg_number.
- **date_span**: projects.completion_date / issuance_date + credentials.issue_date. Use julianday() difference for whole days.
- **distinct_count**: projects.category (or project_name) filtered by project_manager / client.
- **hop_aggregate**: projects.value summed over a chain: credentials → engineers → projects (via project_manager) → client → all that client's projects.
- **temporal_chain**: projects.value summed where completion_date is after (or before) a credential issue_date, for a given engineer.
- **avg_work_size**: AVG(projects.value) over a client's projects (or an engineer's projects).
- **exclusion_aggregate**: SUM(projects.value) for a client EXCLUDING one or more categories.
- **gap_to_threshold**: SUM(projects.value) for a client, then threshold - sum (or sum - threshold).
- **rank_value**: ORDER BY projects.value DESC for a client; difference between rank 1 and rank 2.
- **referenced_share**: COUNT(projects) with has_reference_letter=1 / total COUNT(projects) for a client, expressed as a percentage.
- **threshold_aggregate**: SUM(projects.value) for a client where value >= (or >) a crore threshold.
- **financial_reconciliation**: financial table: SUM(invoiced), SUM(received), SUM(outstanding) per client; billed vs collected percentage.
