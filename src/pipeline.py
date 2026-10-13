"""End-to-end: question -> SQL -> validate -> execute (with self-correcting retries)."""
import sqlite3
import time
from dataclasses import dataclass, field

import pandas as pd

from src.config import DB_PATH
from src.llm import LLMClient
from src.prompts import (build_baseline_messages, build_retry_messages,
                         build_sql_messages, extract_sql)
from src.sql_guard import validate_sql

MAX_ATTEMPTS = 3
MAX_ROWS = 1000
QUERY_TIMEOUT_S = 10


@dataclass
class Attempt:
    sql: str
    error: str = ""


@dataclass
class AnswerResult:
    question: str
    status: str = "failed"           # ok | cannot_answer | failed
    sql: str = ""
    df: pd.DataFrame | None = None
    message: str = ""
    truncated: bool = False
    attempts: list[Attempt] = field(default_factory=list)
    latency_s: float = 0.0


def run_query(sql: str) -> tuple[pd.DataFrame, bool]:
    """Execute on a read-only connection with timeout and row cap."""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    deadline = time.time() + QUERY_TIMEOUT_S
    con.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 10_000)
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(MAX_ROWS + 1)
        truncated = len(rows) > MAX_ROWS
        return pd.DataFrame(rows[:MAX_ROWS], columns=cols), truncated
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e):
            raise TimeoutError(
                f"Query exceeded the {QUERY_TIMEOUT_S}s time limit. Rewrite it to run faster "
                "(join on id columns, aggregate before joining) without changing its meaning "
                "or adding filters.") from e
        raise
    finally:
        con.close()


def ask(question: str, history: list[dict] | None = None,
        llm: LLMClient | None = None, initial_sql: str | None = None,
        baseline: bool = False) -> AnswerResult:
    """initial_sql: only for testing the retry path with a deliberately broken query.
    baseline: use the bare prompt (raw schema only) for the ablation study."""
    llm = llm or LLMClient()
    result = AnswerResult(question=question)
    t0 = time.time()
    messages = (build_baseline_messages(question) if baseline
                else build_sql_messages(question, history))

    for attempt_no in range(1, MAX_ATTEMPTS + 1):
        if attempt_no == 1 and initial_sql:
            sql = initial_sql
        else:
            try:
                sql = extract_sql(llm.chat(messages))
            except Exception as e:  # network / rate limit exhausted
                result.message = f"LLM service error: {e}"
                break

        if sql.upper().startswith("CANNOT_ANSWER"):
            result.status = "cannot_answer"
            result.message = sql.split(":", 1)[-1].strip() or "This data isn't available."
            break

        guard = validate_sql(sql)
        if not guard.ok:
            result.attempts.append(Attempt(sql, guard.error))
            messages = build_retry_messages(messages, sql, guard.error)
            continue

        try:
            df, truncated = run_query(guard.sql)
        except (sqlite3.Error, TimeoutError) as e:
            result.attempts.append(Attempt(sql, str(e)))
            messages = build_retry_messages(messages, sql, str(e))
            continue

        result.attempts.append(Attempt(sql))
        result.status, result.sql, result.df, result.truncated = "ok", guard.sql, df, truncated
        if df.empty:
            result.message = "The query ran successfully but returned no rows."
        break
    else:
        last = result.attempts[-1].error if result.attempts else "unknown error"
        result.message = f"Couldn't produce a working query after {MAX_ATTEMPTS} attempts. Last error: {last}"

    result.latency_s = round(time.time() - t0, 2)
    return result


def _print(r: AnswerResult) -> None:
    print(f"Q: {r.question}")
    print(f"   status={r.status} | attempts={len(r.attempts)} | {r.latency_s}s")
    for i, a in enumerate(r.attempts, 1):
        print(f"   attempt {i}: {'OK' if not a.error else 'ERROR -> ' + a.error[:80]}")
    if r.status == "ok":
        print(r.df.head(5).to_string(index=False))
    else:
        print(f"   message: {r.message}")
    print()


if __name__ == "__main__":
    llm = LLMClient()
    _print(ask("How many orders were delivered late compared to the estimated date?", llm=llm))
    _print(ask("What is the average review score by product category? Top 5.", llm=llm))
    _print(ask("Which competitor has the lowest prices?", llm=llm))
    # Force the retry path: start with a broken query (column 'category' does not exist)
    _print(ask("Revenue by product category, top 5", llm=llm,
               initial_sql="SELECT category, SUM(price) FROM order_items GROUP BY category"))
    # Force a guard rejection, then recovery
    _print(ask("Count all orders", llm=llm, initial_sql="DROP TABLE orders"))