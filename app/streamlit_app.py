"""AI Data Analyst: ask business questions in plain English, get SQL, a table, a chart and a summary.

Run from the project root:
    streamlit run app/streamlit_app.py
"""
import re
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd
import sqlglot
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:          # lets "from src..." work under streamlit run
    sys.path.insert(0, str(ROOT))

from src.config import DB_PATH  # noqa: E402
from src.insights import kpi_value, make_chart, summarize  # noqa: E402
from src.llm import LLMClient  # noqa: E402
from src.pipeline import ask  # noqa: E402

MAX_QUESTIONS_PER_SESSION = 25   # protects the free LLM quota on the public demo
HISTORY_TURNS = 3                # earlier questions passed to the model for follow-ups

# Plain-English names for saved evaluation runs, in display order
RUN_LABELS = {
    "questions_baseline": "Baseline (raw schema only)",
    "questions_full": "Main set v1",
    "questions_hard_full": "Hard held-out v1",
    "questions_full_v2": "Main set v2",
    "questions_hard_full_v2": "Hard set v2",
}

EXAMPLES = [
    "What was the monthly revenue in 2017?",
    "Top 10 product categories by revenue",
    "Which states have the slowest delivery?",
    "How many orders got each review score?",
    "What is the average order value in 2018?",
    "What share of revenue comes from the top 10 sellers?",
]

READ_ONLY_HINT = re.compile(r"\b(delete|drop|update|insert|alter|modify|remove|read-only|"
                            r"destructive|write)\b", re.IGNORECASE)

st.set_page_config(page_title="AI Data Analyst", page_icon="📊", layout="wide")


def md_safe(text: str) -> str:
    """Escape $ so Streamlit does not render text between two R$ signs as a math formula."""
    return (text or "").replace("$", r"\$")


# ---------- cached resources ----------

@st.cache_resource(show_spinner=False)
def get_llm() -> LLMClient:
    return LLMClient(allow_fallback=True)


@st.cache_data(show_spinner=False)
def dataset_stats() -> dict:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    stats = {
        "orders": q("SELECT COUNT(*) FROM orders"),
        "customers": q("SELECT COUNT(DISTINCT customer_unique_id) FROM customers"),
        "items": q("SELECT COUNT(*) FROM order_items"),
        "start": q("SELECT MIN(order_purchase_timestamp) FROM orders")[:7],
        "end": q("SELECT MAX(order_purchase_timestamp) FROM orders")[:7],
    }
    con.close()
    return stats


@st.cache_data(show_spinner=False)
def eval_scores() -> pd.DataFrame:
    """Accuracy per evaluation run. Files named ..._part2 are merged into their run.
    Rows where the model was never reached (quota or network error: status failed with
    zero SQL attempts) are excluded, because they say nothing about the model."""
    runs: dict[str, list[pd.DataFrame]] = {}
    for path in sorted((ROOT / "reports").glob("eval_results_*.csv")):
        name = re.sub(r"_part\d+$", "", path.stem.replace("eval_results_", ""))
        runs.setdefault(name, []).append(pd.read_csv(path))
    rows = []
    for name in sorted(runs, key=lambda n: list(RUN_LABELS).index(n) if n in RUN_LABELS else 99):
        df = pd.concat(runs[name], ignore_index=True)
        never_reached = (df["status"] == "failed") & (df["attempts"] == 0)
        df = df[~never_reached].drop_duplicates("id", keep="last")
        if len(df):
            rows.append({"Run": RUN_LABELS.get(name, name), "Qs": len(df),
                         "Accuracy": f"{df['correct'].mean() * 100:.1f}%"})
    return pd.DataFrame(rows)


# ---------- answer pipeline ----------

def pretty_sql(sql: str) -> str:
    """Consistent, readable SQL for display (falls back to the raw text)."""
    try:
        return sqlglot.transpile(sql, read="sqlite", write="sqlite", pretty=True)[0]
    except Exception:
        return sql


def answer_question(question: str) -> dict:
    history = [{"question": m["question"], "sql": m["sql"]}
               for m in st.session_state.messages
               if m["role"] == "assistant" and m.get("status") == "ok"][-HISTORY_TURNS:]
    llm = get_llm()
    with st.status("Analyzing your question...", expanded=False) as status:
        status.update(label="Writing SQL and running it on the database...")
        result = ask(question, history=history, llm=llm)
        msg = {
            "role": "assistant", "question": question, "status": result.status,
            "sql": result.sql, "df": result.df, "message": result.message,
            "truncated": result.truncated, "latency": result.latency_s,
            "attempts": [(a.sql, a.error) for a in result.attempts],
            "provider": f"{llm.provider} / {llm.model}",
        }
        if result.status == "ok":
            status.update(label="Summarizing the result...")
            t0 = time.time()
            msg["summary"] = summarize(question, result.sql, result.df, result.truncated, llm=llm)
            msg["latency"] = round(result.latency_s + time.time() - t0, 2)
        label = {"ok": "Done", "cannot_answer": "Not answerable with this data"}.get(
            result.status, "Could not answer")
        status.update(label=label, state="complete" if result.status != "failed" else "error")
    return msg


def render_answer(msg: dict, idx: int) -> None:
    if msg["status"] == "cannot_answer":
        reason = md_safe(msg["message"][:1].upper() + msg["message"][1:])
        if READ_ONLY_HINT.search(msg["question"]) or READ_ONLY_HINT.search(msg["message"]):
            st.warning(f"**This assistant is read-only.** {reason}")
            st.caption("It can only run validated SELECT queries on a read-only database "
                       "connection, so your data cannot be changed.")
        else:
            st.warning(f"**I can't answer that from this dataset.** {reason}")
            st.caption("This database has orders, items, payments, reviews, customers, sellers "
                       "and products. It has no costs, profit, marketing, stock or demographic data.")
        return
    if msg["status"] != "ok":
        st.error(md_safe(msg["message"]) or "Something went wrong.")
        _render_details(msg, idx)
        return

    df = msg["df"]
    kpi = kpi_value(df)
    if kpi is not None:
        st.metric(df.columns[0].replace("_", " ").title(), kpi)
    st.markdown(md_safe(msg.get("summary", "")))

    fig = make_chart(df, msg["question"])
    if fig is not None:
        st.plotly_chart(fig, key=f"chart_{idx}")

    if kpi is None:
        label = f"Result table ({len(df):,} rows{', first 1,000 shown' if msg['truncated'] else ''})"
        with st.expander(label, expanded=fig is None):
            st.dataframe(df, hide_index=True)
            st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8"),
                               file_name="query_result.csv", mime="text/csv",
                               key=f"dl_{idx}")
    _render_details(msg, idx)


def _render_details(msg: dict, idx: int) -> None:
    with st.expander("SQL and details"):
        if msg["sql"]:
            st.code(pretty_sql(msg["sql"]), language="sql")
        failed = [(s, e) for s, e in msg["attempts"] if e]
        st.caption(f"Model: {msg['provider']}  |  Time: {msg['latency']}s  |  "
                   f"Attempts: {len(msg['attempts'])}  |  Read-only, validated query")
        for i, (sql, err) in enumerate(failed, 1):
            st.markdown(f"**Self-correction {i}:** this query failed with `{err}`, "
                        "so the error was sent back to the model to fix.")
            st.code(pretty_sql(sql), language="sql")


# ---------- layout ----------

def sidebar():
    with st.sidebar:
        st.header("About")
        st.markdown(
            "Ask business questions about **100k real e-commerce orders** from Olist (Brazil). "
            "An LLM turns your question into SQL, the query is checked for safety and run on a "
            "SQLite database, and you get a table, a chart and a short summary.")
        st.subheader("How it works")
        st.markdown(
            "1. **Schema-aware prompt** with business rules and examples\n"
            "2. **SQL safety guard**: one read-only SELECT on known tables\n"
            "3. **Self-correction**: errors are sent back to the model (max 3 tries)\n"
            "4. **Grounded summary**: rankings and numbers come from code, not the LLM")
        scores = eval_scores()
        if not scores.empty:
            st.subheader("Evaluation (execution accuracy)")
            st.dataframe(scores, hide_index=True)
        st.subheader("Try a question")
        for i, q in enumerate(EXAMPLES):
            if st.button(q, key=f"ex_{i}", width="stretch"):
                st.session_state.pending = q
        st.divider()
        if st.button("Clear chat", width="stretch"):
            st.session_state.messages = []
            st.rerun()
        return st.empty()   # filled at the end of the run, so the count is up to date


def header() -> None:
    st.title("📊 AI Data Analyst")
    st.caption(md_safe("Ask your data in plain English. Answers in Brazilian reais (R$)."))
    s = dataset_stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Orders", f"{s['orders']:,}")
    c2.metric("Customers", f"{s['customers']:,}")
    c3.metric("Items sold", f"{s['items']:,}")
    c4.metric("Period", f"{s['start'][:4]}-{s['end'][:4]}",
              help=f"Orders from {s['start']} to {s['end']}")


def main() -> None:
    st.session_state.setdefault("messages", [])
    counter = sidebar()
    header()
    try:
        chat()
    finally:
        used = sum(1 for m in st.session_state.messages if m["role"] == "user")
        counter.caption(f"Questions this session: {used}/{MAX_QUESTIONS_PER_SESSION}")


def chat() -> None:
    try:
        get_llm()
    except ValueError as e:
        st.error(f"LLM is not configured: {e}. Add your API key to .env (local) "
                 "or to the app secrets (deployed).")
        st.stop()

    if not st.session_state.messages:
        st.info("Type a question below, or pick an example from the sidebar. "
                "Follow-ups work too, for example: *now split that by state*.")

    for i, m in enumerate(st.session_state.messages):
        with st.chat_message(m["role"]):
            if m["role"] == "user":
                st.markdown(md_safe(m["content"]))
            else:
                render_answer(m, i)

    typed = st.chat_input("Ask a question about orders, revenue, products, delivery, reviews...")
    question = typed or st.session_state.pop("pending", None)
    if not question:
        return

    used = sum(1 for m in st.session_state.messages if m["role"] == "user")
    if used >= MAX_QUESTIONS_PER_SESSION:
        st.warning("You've reached the question limit for this demo session. "
                   "Refresh the page to start a new session.")
        return

    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(md_safe(question))
    with st.chat_message("assistant"):
        msg = answer_question(question)
        st.session_state.messages.append(msg)
        render_answer(msg, len(st.session_state.messages) - 1)


main()