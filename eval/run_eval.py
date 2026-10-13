"""Evaluates the text-to-SQL pipeline on a labelled question set.

Metric: execution accuracy. The generated SQL and the gold SQL are both run, and the
answer counts as correct when every gold column is matched by a column in the model's
result (same values, same row count). Extra columns from the model are allowed.

Usage (from the project root):
    python -m eval.run_eval --check-gold                                # gold SQL only, no LLM calls
    python -m eval.run_eval                                             # full system, main set
    python -m eval.run_eval --file questions_hard.yaml                  # full system, held-out hard set
    python -m eval.run_eval --baseline --sleep 8                        # ablation: bare prompt
    python -m eval.run_eval --ids q12 q27                               # rerun specific questions
    python -m eval.run_eval --file questions_hard.yaml --tag v2         # save as a new version
"""
import argparse
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from src.config import DB_PATH, ROOT
from src.llm import LLMClient
from src.pipeline import ask

EVAL_DIR = ROOT / "eval"
REPORTS = ROOT / "reports"
FLOAT_DECIMALS = 1   # tolerance: values are compared after rounding to 1 decimal


# ---------- result comparison ----------

def _norm_value(v):
    """Numbers (including numeric text such as '2017' or '07') become rounded floats;
    other text becomes trimmed lowercase; missing values become 'null'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "null"
    try:
        return round(float(v), FLOAT_DECIMALS)
    except (TypeError, ValueError):
        return str(v).strip().lower()


def _norm_column(s: pd.Series) -> list:
    return [_norm_value(v) for v in s.tolist()]


def results_match(gold: pd.DataFrame, pred: pd.DataFrame | None) -> bool:
    if pred is None or len(gold) != len(pred):
        return False
    if gold.empty:
        return True

    gold_cols = {c: _norm_column(gold[c]) for c in gold.columns}
    pred_cols = {i: _norm_column(pred.iloc[:, i]) for i in range(pred.shape[1])}

    # 1) every gold column must match a distinct prediction column (as a multiset)
    mapping, used = {}, set()
    for g_name, g_vals in gold_cols.items():
        g_sorted = sorted(g_vals, key=repr)
        for p_idx, p_vals in pred_cols.items():
            if p_idx not in used and sorted(p_vals, key=repr) == g_sorted:
                mapping[g_name] = p_idx
                used.add(p_idx)
                break
        else:
            return False

    # 2) rows must line up across the matched columns
    g_rows = sorted(zip(*[gold_cols[g] for g in mapping]), key=repr)
    p_rows = sorted(zip(*[pred_cols[p] for p in mapping.values()]), key=repr)
    return g_rows == p_rows


# ---------- helpers ----------

def load_questions(file: str, ids: list[str] | None = None) -> list[dict]:
    items = yaml.safe_load((EVAL_DIR / file).read_text(encoding="utf-8"))
    if ids:
        items = [q for q in items if q["id"] in ids]
    return items


def run_gold(sql: str) -> pd.DataFrame:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        return pd.read_sql_query(sql, con)
    finally:
        con.close()


def check_gold(items: list[dict]) -> None:
    ok = 0
    for q in items:
        gold = q["gold_sql"].strip()
        if gold == "CANNOT_ANSWER":
            print(f"{q['id']} [{q['category']}] expects CANNOT_ANSWER")
            ok += 1
            continue
        try:
            df = run_gold(gold)
            preview = df.head(3).to_dict("records")
            print(f"{q['id']} [{q['category']}] {len(df)} rows -> {preview}")
            ok += 1
        except Exception as e:
            print(f"{q['id']} GOLD SQL ERROR: {e}")
    print(f"\n{ok}/{len(items)} gold queries ran successfully")


# ---------- main evaluation ----------

def evaluate(items: list[dict], sleep_s: float, baseline: bool = False) -> pd.DataFrame:
    llm = LLMClient()
    rows = []
    for i, q in enumerate(items, 1):
        gold_sql = q["gold_sql"].strip()
        expects_refusal = gold_sql == "CANNOT_ANSWER"
        r = ask(q["question"], llm=llm, baseline=baseline)

        if expects_refusal:
            correct = r.status == "cannot_answer"
            error = "" if correct else f"expected refusal, got status={r.status}"
        elif r.status != "ok":
            correct = False
            error = r.message or r.status
        else:
            correct = results_match(run_gold(gold_sql), r.df)
            error = "" if correct else "result differs from gold"

        n_attempts = len(r.attempts)
        rows.append({
            "id": q["id"],
            "category": q["category"],
            "question": q["question"],
            "correct": correct,
            "status": r.status,
            "attempts": n_attempts,
            "self_corrected": correct and n_attempts > 1,
            "latency_s": r.latency_s,
            "error": error,
            "attempt_errors": " | ".join(a.error for a in r.attempts if a.error),
            "generated_sql": r.sql or (r.attempts[-1].sql if r.attempts else ""),
            "gold_sql": gold_sql,
        })
        mark = "PASS" if correct else "FAIL"
        print(f"[{i:>2}/{len(items)}] {mark} {q['id']} ({q['category']}) "
              f"attempts={n_attempts} {r.latency_s}s  {error}")
        if i < len(items):
            time.sleep(sleep_s)   # stay under the free tier tokens-per-minute limit
    return pd.DataFrame(rows)


def write_report(df: pd.DataFrame, model: str, run_name: str) -> str:
    acc = df["correct"].mean() * 100
    by_cat = (df.groupby("category")
                .agg(questions=("id", "count"), correct=("correct", "sum"))
                .assign(accuracy_pct=lambda t: (100 * t["correct"] / t["questions"]).round(1))
                .reset_index())
    answerable = df[df["category"] != "unanswerable"]
    retried = answerable[answerable["attempts"] > 1]

    lines = [
        f"# Evaluation Results: {run_name}",
        "",
        f"- Date: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Model: {model}",
        f"- Questions: {len(df)}",
        f"- **Overall execution accuracy: {acc:.1f}%** ({int(df['correct'].sum())}/{len(df)})",
        f"- Answerable questions accuracy: {answerable['correct'].mean() * 100:.1f}%",
        f"- Questions that needed a retry: {len(retried)}, "
        f"recovered by self-correction: {int(retried['correct'].sum())}",
        f"- Median latency: {df['latency_s'].median():.2f}s",
        "",
        "## Accuracy by category",
        "",
        by_cat.to_markdown(index=False),
        "",
        "## Failed questions",
        "",
    ]
    failed = df[~df["correct"]]
    if failed.empty:
        lines.append("None.")
    for _, r in failed.iterrows():
        lines += [f"### {r['id']}: {r['question']}",
                  f"- Reason: {r['error']}",
                  f"- Attempts: {r['attempts']}"
                  + (f" (errors: {r['attempt_errors']})" if r["attempt_errors"] else ""),
                  "```sql", str(r["generated_sql"]).strip(), "```", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="questions.yaml", help="question file inside eval/")
    parser.add_argument("--baseline", action="store_true",
                        help="ablation: bare prompt with raw schema only")
    parser.add_argument("--check-gold", action="store_true", help="only run the gold SQL")
    parser.add_argument("--limit", type=int, help="evaluate only the first N questions")
    parser.add_argument("--ids", nargs="*", help="evaluate only these question ids")
    parser.add_argument("--sleep", type=float, default=15.0, help="seconds between questions")
    parser.add_argument("--tag", default="", help="suffix for output files, e.g. v2")
    args = parser.parse_args()

    items = load_questions(args.file, args.ids)
    if args.limit:
        items = items[:args.limit]

    if args.check_gold:
        check_gold(items)
        return

    run_name = f"{Path(args.file).stem}_{'baseline' if args.baseline else 'full'}"
    if args.tag:
        run_name += f"_{args.tag}"
    print(f"Run: {run_name} | {len(items)} questions "
          f"(about {len(items) * (args.sleep + 3) / 60:.0f} min)\n")
    df = evaluate(items, args.sleep, baseline=args.baseline)

    REPORTS.mkdir(exist_ok=True)
    csv_path = REPORTS / f"eval_results_{run_name}.csv"
    md_path = REPORTS / f"eval_summary_{run_name}.md"
    df.to_csv(csv_path, index=False)
    md_path.write_text(write_report(df, LLMClient().model, run_name), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"Overall accuracy: {df['correct'].mean() * 100:.1f}% "
          f"({int(df['correct'].sum())}/{len(df)})")
    print(df.groupby("category")["correct"].agg(["count", "sum", "mean"])
            .rename(columns={"count": "n", "sum": "correct", "mean": "accuracy"})
            .round(2).to_string())
    print(f"\nSaved: {csv_path.name} and {md_path.name} in reports/")


if __name__ == "__main__":
    main()