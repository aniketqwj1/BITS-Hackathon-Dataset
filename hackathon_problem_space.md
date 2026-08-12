# Hackathon Problem Space Analysis

## 1. Domain & Problem Space Decomposition
* **Core Problem**: The challenge requires building a high-precision, generalizable verification system capable of auditing complex datasets across diverse document formats (PDFs, financial workbooks, reports). The system must move beyond simple retrieval to perform multi-hop reasoning, statistical aggregation, and "absence detection" (confirming the non-existence of data) to answer a rigorous set of queries.
* **Target Personas**: 
    * *Compliance Auditors*: Who need to verify if specific industrial standards or trial parameters were met.
    * *Financial Analysts*: Who need to reconcile billed amounts against invoiced claims and identify discrepancies.
    * *Data Analysts*: Who require statistical summaries (mean, median, variance) across categorized industrial data.
* **Existing Pain Points**:
    * *Fragmented Data*: Information is split between structured workbooks and unstructured PDF reports.
    * *Reasoning Complexity*: Queries often require connecting dots across multiple documents (e.g., comparing a value in a PDF to a total in a spreadsheet).
    * *Silent Failures*: Traditional RAG often "hallucinates" an answer or fails to explicitly recognize when information is missing (Absence family).
    * *Formatting Rigidity*: The need for plain-number outputs without units or commas creates a fragile interface between LLM reasoning and final submission.

## 2. Codebase & Repository Footprint
* **Directory Overview**:
    * `/data`: Contains the primary corpus and question sets.
    * `/data/questions.json`: The main set of 333 questions used for development.
    * `/data/sample_questions.json`: A smaller subset (21 questions) used for initial testing.
    * Root: Contains the harness and basic project structure.
* **Boilerplate Constraints**:
    * *Language*: Python-based.
    * *Environment*: Pre-configured with `PyMuPDF` for PDF parsing, `Torch`, and `Transformers` for model execution.
    * *Critical Limitation*: `Pandas` and `NumPy` are currently unstable or missing in the provided environment, restricting the use of standard dataframe-based tabular analysis unless manually installed.
    * *Provenace*: The submission is linked to a specific `Commit SHA`, meaning all logic must be committed and reproducible.
* **Integration Touchpoints**:
    * *Input*: Corpus of documents $\rightarrow$ PDF/Text extraction layer.
    * *Processing*: Embedding generation $\rightarrow$ Vector Retrieval $\rightarrow$ LLM Reasoning (Ollama Pro).
    * *Output*: Final answer filtering $\rightarrow$ CSV generation (`question_id,answer`).

## 3. Requirements Matrix

| ID | Type | Source | Requirement Description | Impact on Architecture |
| :--- | :--- | :--- | :--- | :--- |
| REQ-01 | Explicit | Brief/Portal | Submit CSV with `question_id,answer` columns | Requires a strict post-processing formatting layer. |
| REQ-02 | Explicit | Portal | Answers must be plain numbers (no units, no commas) | Requires a regex-based cleaning step for all LLM outputs. |
| REQ-03 | Explicit | Portal | Submission must include a valid Commit SHA | All pipeline logic must be committed to Git; no local-only scripts. |
| REQ-04 | Explicit | Brief | Handle "Hidden Question Set" (Tie-breaker) | System must be generalizable; cannot overfit to the 333 questions. |
| REQ-05 | Implicit | Questions | Support "Absence" queries (confirming data is missing) | Requires LLM to be prompted for "Not Found" rather than guessing. |
| REQ-06 | Implicit | Questions | Support "Temporal" queries (sequences/dates) | Requires robust date parsing and chronological sorting of retrieved chunks. |
| REQ-07 | Implicit | Questions | Support "Financial Reconciliation" (Billed vs. Invoiced) | Requires multi-document retrieval and arithmetic verification. |
| REQ-08 | Implicit | Questions | Support "Statistical" queries (Mean/Median/Variance) | Requires extraction of lists of numbers and a computation engine. |
| REQ-09 | Implicit | Codebase | Handle unstructured PDF and structured workbooks | Requires a hybrid extraction strategy (Text + Table extraction). |
| REQ-10 | Implicit | Env | Operability without Pandas/NumPy (initially) | May require implementing basic math utilities or fixing the environment first. |

## 4. Technical, Judging & Operational Guardrails
* **Technical Limitations**:
    * *Compute*: Solo team utilizing Ollama Pro (Cloud LLM/Embeddings), providing strong reasoning but subject to API rate limits.
    * *Environment*: Limited library availability (broken Pandas) necessitates a lightweight or self-contained processing approach.
    * *Latency*: While not explicitly capped, the 20-submission limit requires high confidence in each run.
* **Evaluation Mapping**:
    * *Technical Difficulty*: Satisfied by implementing multi-hop retrieval and handling the "Absence" and "Statistical" reasoning families.
    * *Innovation*: Satisfied by implementing a self-correction loop (e.g., LLM checks its own answer against the source text).
    * *Completeness*: Satisfied by correctly answering diverse families across both sample and full 333-question sets.
* **Execution Timeline & Hard Deadline Schedule** (<24h remaining):
    * **Phase 1 (Setup & Core Logic)**: [0-8h] $\rightarrow$ Target: Basic RAG pipeline operational; PDF extraction verified.
    * **Phase 2 (Integration & System Validation)**: [8-16h] $\rightarrow$ Target: All 5 reasoning families handled; internal validation on 333 questions $>80\%$.
    * **Phase 3 (Polishing, UI & Demo Freeze)**: [16-22h] $\rightarrow$ Target: Formatting layer verified; final Git commit pushed; `answers.csv` generated.
    * **Submission Gate**: [T-2h] $\rightarrow$ Final submission to portal.

## 5. Scope Boundaries
* **In-Scope Priority**:
    * High-fidelity extraction from PDFs and Workbooks.
    * Implementation of a "Reasoning Engine" that supports Temporal, Absence, and Financial families.
    * A foolproof CSV formatter.
    * A generalizable retrieval strategy that works on unseen questions.
* **Strictly Out-of-Scope**:
    * Building a custom UI/Frontend (unless it significantly improves the demo).
    * Manual hardcoding of answers for the 333-question set.
    * Training/Fine-tuning models (too time-constrained; rely on Prompt Engineering/RAG).

## 6. Strategic Brainstorming Vectors
* **UX & Workflow Vectors**:
    * How can we visualize the "Reasoning Chain" to quickly debug why a question was answered incorrectly?
    * What is the most efficient way to iterate on prompts for the "Absence" family without re-running the whole corpus?
* **Data Flow & Repository Integration Vectors**:
    * Should we use a local vector database or a simple in-memory index given the corpus size?
    * How do we handle "Table-to-Text" conversion for workbooks to ensure the LLM understands the structural relationships?
* **Feasibility vs. Impact Tradeoffs**:
    * *Tradeoff*: Advanced multi-agent debate vs. a single-pass a high-context window. (Given <24h, high-context single-pass is safer).
    * *Tradeoff*: Perfecting 100% of 333 questions vs. ensuring 80% generalizability for the hidden set. (Generalization is the priority).
* **Edge Case & Failure Prevention Vectors**:
    * *Failure Mode*: LLM provides the answer with "Rs." or "%" $\rightarrow$ *Prevention*: Regex-based strict numerical casting.
    * *Failure Mode*: Retrieval fails to find the "absence" of data $\rightarrow$ *Prevention*: Explicit "negative constraint" prompting.
    * *Failure Mode*: Environment crashes due to memory limits on large PDFs $\rightarrow$ *Prevention*: Chunk-based processing with overlapping windows.
