# AI Data Analyst: Ask Your Data in Plain English

Type a business question, get the answer as a table, an automatic chart and a short plain-English summary.
An LLM translates the question into SQL, the SQL is validated for safety, run on a read-only SQLite
database of **~100k real e-commerce orders**, and corrected automatically if it fails.

**Full project report (PDF):** [docs/AI_Data_Analyst_Project_Report.pdf](docs/AI_Data_Analyst_Project_Report.pdf)

![App home](docs/screenshots/01_home.png)

---

## Results at a glance

| Evaluation run | Questions | Execution accuracy |
|---|---:|---:|
| Baseline: raw schema only, no prompt engineering | 35 | 68.6% |
| **Full system, main set** | 35 | **100%** |
| **Full system, held-out hard set (unseen during tuning)** | 15 | **73.3%** |
| Full system, hard set after error analysis | 15 | 93.3% |
| Full system, main set rerun after the fixes | 29 of 35 * | 100% |

\* The free daily Groq quota ran out during the rerun, so 6 questions never reached the model. All 29 that did were correct, and the other 6 had passed in the first run.

- Prompt engineering (business rules, column notes, real enum values, few-shot examples) added **+31.4 points** over the raw-schema baseline.
- The baseline scored **0/6** on revenue questions with joins, because without business rules it counted canceled orders as revenue. It also invented a "profit margin" that the data cannot support; the full system refuses.
- The held-out score (73.3%) is the honest number. The 93.3% is reported separately because those fixes were informed by the hard-set failures.

Model: `openai/gpt-oss-120b` on the Groq free tier, with automatic fallback to Gemini Flash (free tier) when the daily quota runs out.

---

## Features

- **Plain-English questions to SQL**, with follow-up support ("now split that by state")
- **Schema-aware prompting**: table and column descriptions, relationships, real category values and 13 business rules (e.g. revenue excludes canceled orders, customers are counted by `customer_unique_id`)
- **SQL safety in four layers**: SQL parser check (exactly one SELECT), keyword blocklist, table allowlist, read-only database connection with a 10 second timeout and a 1,000 row cap
- **Self-correction**: if a query fails validation or execution, the error is sent back to the model (up to 3 attempts)
- **Honest refusals**: questions the data cannot answer (profit, marketing spend, stock) get `CANNOT_ANSWER` instead of a made-up query
- **Automatic charts**: line chart for time series, bar chart for rankings, KPI card for single values (rule-based, never LLM-generated code)
- **Grounded summaries**: highest, lowest, first and last values are computed in Python and passed to the LLM, which is told to quote numbers exactly and never do its own arithmetic
- **Evaluation harness**: execution accuracy on labelled questions, per-category scores, baseline ablation and a held-out hard set

---

## How it works

```mermaid
flowchart LR
    Q[User question] --> P[Prompt builder<br/>schema + rules + examples<br/>+ chat history]
    P --> L[LLM<br/>Groq gpt-oss-120b<br/>fallback: Gemini]
    L --> S[SQL]
    S --> G{Safety guard<br/>sqlglot + allowlist}
    G -- rejected --> R[Error sent back<br/>to the LLM]
    G -- ok --> E[(SQLite<br/>read-only)]
    E -- SQL error --> R
    R --> L
    E -- rows --> C[Chart selector]
    E -- rows --> F[Facts computed<br/>in Python]
    F --> M[LLM summary]
    C --> U[Streamlit chat app]
    M --> U
```

---

## Dataset

[Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) (Kaggle, CC BY-NC-SA 4.0).

| Table | Rows | Notes |
|---|---:|---|
| orders | 99,441 | status and timestamps |
| order_items | 112,650 | revenue comes from `price` |
| payments | 103,886 | split payments per order |
| reviews | 99,224 | score 1 to 5 |
| customers | 99,441 | `customer_unique_id` identifies a person |
| products | 32,951 | English category names merged in |
| sellers | 3,095 | |

Data preparation choices: clean table names, English categories merged into `products`, misspelled column names fixed (`lenght` to `length`), dates stored as ISO text for `strftime`, and indexes on every key used in joins. The 1M-row geolocation table is skipped to keep the database small.

---

## Evaluation

**Metric: execution accuracy.** The generated SQL and a hand-written gold SQL are both run, and the results are compared. Column names and row order may differ and extra columns are allowed; values are compared after rounding to one decimal. Questions the data cannot answer count as correct only when the model refuses.

**Question sets**
- `eval/questions.yaml`: 35 questions in 6 categories (simple, aggregation with joins, time series, ranking, complex, unanswerable)
- `eval/questions_hard.yaml`: 15 harder questions written after tuning (business jargon like GMV, typos, median, share of total, deduplication traps, a question that sounds answerable but is not)

**Error analysis of the held-out run** (each failure had a different root cause):

| Question | What went wrong | Root cause | Fix |
|---|---|---|---|
| Average delivery time for northern states | one row per state instead of one overall number | model copied a few-shot example too closely | instruction to group only when asked |
| Customers buying from more than one category | added a `year = 2017` filter nobody asked for | a timeout, then the retry message said "add filters", so the model changed the question | indexes on all join keys; retries must keep the question's meaning |
| Sellers with average review below 3 | each review counted once per item | deduplication trap | explicit rule: reviews are per order |
| `whats the totl revnue from sao paulo city` | `customer_city = 'São Paulo'` | data stores `'sao paulo'` (lowercase, no accents) | column notes show the stored format |

The most important lesson: the self-correction loop itself caused a **silent wrong answer** by letting the model change the question to make a query pass. Retries are now constrained to preserve meaning.

Run the evaluation yourself:
```bash
python -m eval.run_eval --check-gold                    # verify gold answers, no LLM calls
python -m eval.run_eval                                 # full system, main set
python -m eval.run_eval --file questions_hard.yaml      # held-out hard set
python -m eval.run_eval --baseline --sleep 8            # ablation baseline
```
Reports are saved to `reports/eval_summary_*.md` and `reports/eval_results_*.csv`.

---

## Screenshots

| Trend question with line chart | Follow-up question |
|---|---|
| ![Line chart](docs/screenshots/02_line_chart.png) | ![Follow-up](docs/screenshots/03_follow_up.png) |

| Refusal and read-only protection | SQL and details |
|---|---|
| ![Refusal](docs/screenshots/04_refusal.png) | ![SQL details](docs/screenshots/05_sql_details.png) |

---

## Project structure

```
ai-data-analyst/
├── app/
│   └── streamlit_app.py      # chat UI
├── src/
│   ├── build_db.py           # CSV files to SQLite, with indexes
│   ├── config.py             # shared paths
│   ├── schema.py             # LLM-friendly schema, business rules
│   ├── prompts.py            # system prompt, few-shot examples, retry prompt
│   ├── llm.py                # Groq / Gemini client, backoff, fallback
│   ├── sql_guard.py          # SQL safety validator
│   ├── pipeline.py           # question to validated, executed SQL with retries
│   └── insights.py           # chart selection, KPI, grounded summary
├── eval/
│   ├── questions.yaml        # 35 labelled questions
│   ├── questions_hard.yaml   # 15 held-out hard questions
│   └── run_eval.py           # execution accuracy harness
├── reports/                  # evaluation results
├── docs/
│   ├── AI_Data_Analyst_Project_Report.pdf
│   ├── report_figures/
│   └── screenshots/
├── requirements.txt
└── .env.example
```

---

## Run it locally

Requires Python 3.11 or newer.

```bash
git clone <this repo>
cd ai-data-analyst
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

1. Download the [Olist dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) from Kaggle and extract the CSV files into `data/raw/`.
   (The database is not stored in this repository because of its size.)
2. Build the database: `python src/build_db.py`
3. Copy `.env.example` to `.env` and add a free API key from [Groq](https://console.groq.com) (and optionally [Google AI Studio](https://aistudio.google.com) for the fallback).
4. Start the app: `streamlit run app/streamlit_app.py`

Test the safety guard: `python -m src.sql_guard` (12 attack and edge cases).

---

## Limitations and next steps

- Summaries are LLM-written. Numbers and rankings are grounded in code, but softer pattern statements (for example "slower states tend to have fewer orders") are not verified.
- Follow-up questions inherit earlier constraints, such as a `LIMIT 10`, which is sometimes not what the user meant.
- Hosted models are not fully deterministic even at temperature 0; one hard question flipped between runs.
- The evaluation set is small (50 questions). Next steps: a larger set built from real user questions, a query cache, and a semantic layer (dbt metrics) instead of rules written in the prompt.

---

## Tech stack

Python, SQLite, pandas, sqlglot, Plotly, Streamlit, Groq API (gpt-oss-120b), Gemini API, OpenAI Python SDK (OpenAI-compatible endpoints), PyYAML