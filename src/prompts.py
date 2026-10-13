"""Prompt construction and SQL extraction for text-to-SQL."""
import re
import sqlite3
from functools import lru_cache

from src.config import DB_PATH
from src.schema import get_schema_text

SYSTEM_TEMPLATE = """You are an expert data analyst who writes SQLite queries for a Brazilian e-commerce company (Olist).

{schema}

### Instructions
- Write ONE read-only SQLite query (SELECT or WITH ... SELECT) that answers the question.
- Use only tables and columns listed above. Never invent columns.
- Follow the business rules above exactly.
- Use table aliases and give every computed column a clear snake_case alias.
- Round money to 2 decimals and averages to 1 or 2 decimals.
- For rankings use ORDER BY with LIMIT (default LIMIT 10 if the user gives no number).
- Only when ranking AVERAGES by group: include a count column and HAVING COUNT(*) >= 30.
  Never add this HAVING filter to rankings of counts or sums.
- For row-level lists without a limit, add LIMIT 1000.
- Never use SELECT *.
- For trends over time, return the time column first, sorted ascending.
- If the user asks for one figure over a set of filters (e.g. "for customers in states A, B and C"),
  return a single overall row. Only group when the user says by, per, each, compare, or asks for a ranking.
- Never add filters, date ranges or limits the user did not ask for.
- If the question cannot be answered with this data (e.g. profit, costs, marketing, competitors),
  reply exactly: CANNOT_ANSWER: <short reason>
- Output only the SQL inside a ```sql code block. No explanation."""

# Ablation baseline: raw schema only. No column notes, business rules, allowed values or examples.
BASELINE_TEMPLATE = """You write SQLite queries.

Database schema:
{schema}

Write one SQLite SELECT query that answers the user's question.
If the question cannot be answered with this data, reply exactly: CANNOT_ANSWER: <short reason>
Output only the SQL inside a ```sql code block."""

FEW_SHOT = [
    ("What was the monthly revenue in 2017?",
     """SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month,
       ROUND(SUM(oi.price), 2) AS revenue
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.order_status NOT IN ('canceled', 'unavailable')
  AND strftime('%Y', o.order_purchase_timestamp) = '2017'
GROUP BY month
ORDER BY month"""),
    ("Top 5 product categories by sales",
     """SELECT p.product_category,
       ROUND(SUM(oi.price), 2) AS revenue
FROM order_items oi
JOIN orders o ON o.order_id = oi.order_id
JOIN products p ON p.product_id = oi.product_id
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY p.product_category
ORDER BY revenue DESC
LIMIT 5"""),
    ("Which states have the slowest delivery?",
     """SELECT c.customer_state,
       ROUND(AVG(julianday(o.order_delivered_customer_date)
                 - julianday(o.order_purchase_timestamp)), 1) AS avg_delivery_days,
       COUNT(*) AS delivered_orders
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
GROUP BY c.customer_state
HAVING COUNT(*) >= 30
ORDER BY avg_delivery_days DESC
LIMIT 10"""),
    ("Which product categories have the best customer reviews?",
     """WITH order_category AS (
    SELECT DISTINCT oi.order_id, p.product_category
    FROM order_items oi
    JOIN products p ON p.product_id = oi.product_id
)
SELECT oc.product_category,
       ROUND(AVG(r.review_score), 2) AS avg_review_score,
       COUNT(*) AS review_count
FROM reviews r
JOIN orders o ON o.order_id = r.order_id
JOIN order_category oc ON oc.order_id = r.order_id
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY oc.product_category
HAVING COUNT(*) >= 30
ORDER BY avg_review_score DESC
LIMIT 10"""),
    ("What share of orders uses each payment method?",
     """SELECT p.payment_type,
       COUNT(DISTINCT p.order_id) AS orders,
       ROUND(100.0 * COUNT(DISTINCT p.order_id)
             / (SELECT COUNT(DISTINCT order_id) FROM payments), 1) AS pct_of_orders
FROM payments p
GROUP BY p.payment_type
ORDER BY orders DESC"""),
]


@lru_cache(maxsize=1)
def get_raw_schema_text() -> str:
    """CREATE TABLE statements exactly as stored in SQLite (used by the baseline)."""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    con.close()
    return "\n\n".join(r[0] for r in rows)


def build_sql_messages(question: str, history: list[dict] | None = None) -> list[dict]:
    """history: list of {'question': str, 'sql': str} from earlier turns (most recent last)."""
    msgs = [{"role": "system", "content": SYSTEM_TEMPLATE.format(schema=get_schema_text())}]
    for q, sql in FEW_SHOT:
        msgs.append({"role": "user", "content": q})
        msgs.append({"role": "assistant", "content": f"```sql\n{sql}\n```"})
    for turn in (history or [])[-3:]:  # last 3 turns keeps tokens low
        msgs.append({"role": "user", "content": turn["question"]})
        msgs.append({"role": "assistant", "content": f"```sql\n{turn['sql']}\n```"})
    msgs.append({"role": "user", "content": question})
    return msgs


def build_baseline_messages(question: str) -> list[dict]:
    return [
        {"role": "system", "content": BASELINE_TEMPLATE.format(schema=get_raw_schema_text())},
        {"role": "user", "content": question},
    ]


def build_retry_messages(messages: list[dict], bad_sql: str, error: str) -> list[dict]:
    """Append the failed attempt and the error so the LLM can fix it."""
    return messages + [
        {"role": "assistant", "content": f"```sql\n{bad_sql}\n```"},
        {"role": "user", "content": (
            f"That query failed with this error:\n{error}\n"
            "Fix it while keeping exactly the same meaning as the user's question. "
            "Do not add filters, date ranges or limits the user did not ask for. "
            "Check table and column names against the schema. "
            "Return only the corrected SQL in a ```sql code block.")},
    ]


def extract_sql(text: str) -> str:
    """Pull SQL out of an LLM reply. Returns 'CANNOT_ANSWER: ...' unchanged."""
    text = text.strip()
    if text.upper().startswith("CANNOT_ANSWER"):
        return text
    match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    sql = match.group(1) if match else text
    return sql.strip().rstrip(";").strip()


if __name__ == "__main__":
    from src.llm import LLMClient

    full = build_sql_messages("Who are the top 5 sellers by revenue in 2018?")
    base = build_baseline_messages("Who are the top 5 sellers by revenue in 2018?")
    print(f"Full prompt:     ~{sum(len(m['content']) for m in full) // 4} tokens")
    print(f"Baseline prompt: ~{sum(len(m['content']) for m in base) // 4} tokens\n")

    llm = LLMClient()
    for q in ["Who are the top 5 sellers by revenue in 2018?",
              "What is our profit margin by category?"]:
        sql = extract_sql(llm.chat(build_sql_messages(q)))
        print(f"Q: {q}\n{sql}\n")
        if not sql.startswith("CANNOT_ANSWER"):
            import pandas as pd
            con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            print(pd.read_sql_query(sql, con).to_string(index=False), "\n")
            con.close()