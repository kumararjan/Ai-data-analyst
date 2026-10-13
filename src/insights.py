"""Auto chart selection and plain-English summaries for query results."""
import numbers
import re

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src.llm import LLMClient

TIME_PATTERN = re.compile(r"^\d{4}(-\d{2}){0,2}( \d{2}:\d{2}:\d{2})?$")
ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
MONEY_PATTERN = re.compile(
    r"(revenue|sales|price|freight|payment_value|amount|spend|value|aov|gmv|ticket)",
    re.IGNORECASE)
NOT_MONEY_PATTERN = re.compile(r"(count|qty|quantity|pct|percent|share|days|score|num_|number)",
                               re.IGNORECASE)
COUNT_PATTERN = re.compile(r"(count|orders|reviews|customers|sellers|items|num_|^n_|_n$)",
                           re.IGNORECASE)
BULLET_PATTERN = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+")
MAX_INSIGHT_BULLETS = 3

SUMMARY_PROMPT = """You are a data analyst explaining query results to a business manager.

Question: {question}
SQL used:
{sql}

Result ({n_rows} rows{trunc}):
{table}

Column units:
{units}

Precomputed facts (computed by code, always correct):
{facts}

Small samples present (any group count below 30): {small}

Write at most 4 short bullet points in plain English, each starting with "- ":
- Lead with the direct answer and the key numbers.
- If the result has many rows, summarize them in ONE bullet (highest, lowest, overall pattern).
  Never write one bullet per row.
- Point out one notable pattern or comparison if it is visible in the result.
- If the SQL applied a filter or assumption the user may not expect (for example excluding canceled orders,
  a date range), state it in ONE bullet starting with "Note:".
- If small samples present is "yes", mention it inside the Note bullet. If it is "no", never mention
  sample size at all.

Strict rules:
- For any highest, lowest, most, fewest, first or last claim, use ONLY the precomputed facts.
  Never work out rankings yourself.
- Copy numbers exactly as they are written (same digits, commas and decimals).
- Put "R$" ONLY in front of numbers from columns marked as money above. Never on counts, scores,
  percentages or days.
- Do NOT add numbers together or calculate new totals, percentages, ratios or differences.
- Do not guess causes or reasons.
- No headings, no intro sentence."""


def _pretty(col: str) -> str:
    return col.replace("_", " ").title()


def _is_text(s: pd.Series) -> bool:
    """True for text columns in both pandas 2 (object) and pandas 3 (str)."""
    return pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)


def _is_time(s: pd.Series) -> bool:
    if not _is_text(s):
        return False
    vals = s.dropna().astype(str)
    return len(vals) > 0 and bool(vals.str.match(TIME_PATTERN).all())


def _shorten_ids(s: pd.Series) -> pd.Series:
    if _is_text(s) and bool(s.dropna().astype(str).str.match(ID_PATTERN).all()):
        return s.astype(str).str[:8] + "..."
    return s


def _fmt(v, integer: bool) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return f"{int(v):,}" if integer else f"{float(v):,.2f}"


def money_columns(df: pd.DataFrame) -> list[str]:
    """Numeric columns whose names indicate Brazilian reais."""
    return [c for c in df.select_dtypes("number").columns
            if MONEY_PATTERN.search(c) and not NOT_MONEY_PATTERN.search(c)]


def has_small_samples(df: pd.DataFrame, threshold: int = 30) -> bool:
    """True if a grouped result has a count-like column with any value below the threshold."""
    if df is None or len(df) < 2:
        return False
    for c in df.select_dtypes("number").columns:
        if COUNT_PATTERN.search(c) and c not in money_columns(df):
            if pd.api.types.is_integer_dtype(df[c]) and df[c].min() < threshold:
                return True
    return False


def _units_text(df: pd.DataFrame) -> str:
    money = set(money_columns(df))
    lines = []
    for c in df.select_dtypes("number").columns:
        lines.append(f"- {c}: {'money in BRL (use R$)' if c in money else 'NOT money (no R$)'}")
    return "\n".join(lines) or "- no numeric columns"


def _key_facts(df: pd.DataFrame) -> str:
    """Highest/lowest (and first/last for time series) computed in Python, not by the LLM."""
    if df is None or len(df) < 2:
        return "- none (single row result)"
    num_cols = df.select_dtypes("number").columns.tolist()
    label_col = next((c for c in df.columns if c not in num_cols), None)
    if label_col is None and len(num_cols) >= 2:      # e.g. review_score used as the label
        label_col, num_cols = num_cols[0], num_cols[1:]
    if label_col is None or not num_cols:
        return "- none"

    lines = []
    for c in num_cols:
        s = df[c]
        if s.dropna().empty:
            continue
        is_int = pd.api.types.is_integer_dtype(s)
        hi_i, lo_i = s.idxmax(), s.idxmin()
        lines.append(f"- highest {c}: {df.at[hi_i, label_col]} ({_fmt(s[hi_i], is_int)})")
        lines.append(f"- lowest {c}: {df.at[lo_i, label_col]} ({_fmt(s[lo_i], is_int)})")
        if _is_time(df[label_col]):
            ordered = df.sort_values(label_col)
            first, last = ordered.iloc[0], ordered.iloc[-1]
            lines.append(f"- first period {first[label_col]}: {_fmt(first[c], is_int)}; "
                         f"last period {last[label_col]}: {_fmt(last[c], is_int)}")
    return "\n".join(lines) or "- none"


def _table_for_llm(df: pd.DataFrame, max_rows: int = 20) -> str:
    """Pre-format numbers (commas, 2 decimals) so the LLM copies them exactly."""
    view = df.head(max_rows).copy()
    for c in view.select_dtypes("number").columns:
        is_int = pd.api.types.is_integer_dtype(view[c])
        view[c] = view[c].map(lambda v, i=is_int: _fmt(v, i))
    return view.to_markdown(index=False, disable_numparse=True)


def _clean_bullets(text: str) -> str:
    """Enforce the format in code: max 3 insight bullets plus 1 Note bullet."""
    bullets = []
    for line in text.splitlines():
        if BULLET_PATTERN.match(line):
            bullets.append(BULLET_PATTERN.sub("", line).strip())
        elif line.strip() and bullets:          # wrapped continuation line
            bullets[-1] += " " + line.strip()
    if not bullets:
        return text.strip()

    def is_note(b: str) -> bool:
        return b.lstrip("*_ ").lower().startswith("note")

    insights = [b for b in bullets if not is_note(b)][:MAX_INSIGHT_BULLETS]
    notes = [b for b in bullets if is_note(b)][:1]
    return "\n".join(f"- {b}" for b in insights + notes)


def kpi_value(df: pd.DataFrame) -> str | None:
    """If the result is a single value, return it formatted for a metric card."""
    if df is None or df.shape != (1, 1):
        return None
    v = df.iat[0, 0]
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "No value"
    is_money = df.columns[0] in money_columns(df)
    prefix = "R$ " if is_money else ""
    if isinstance(v, numbers.Integral):          # covers int and numpy.int64
        return f"{prefix}{int(v):,}"
    if isinstance(v, numbers.Real):              # covers float and numpy.float64
        return f"{prefix}{float(v):,.2f}"
    return str(v)


def make_chart(df: pd.DataFrame, question: str = "") -> go.Figure | None:
    """Pick a sensible chart from the shape of the data. Returns None if a chart wouldn't help."""
    if df is None or df.empty or df.shape == (1, 1) or len(df) < 2:
        return None
    df = df.copy()
    num_cols = df.select_dtypes("number").columns.tolist()
    if not num_cols:
        return None
    other_cols = [c for c in df.columns if c not in num_cols]

    # Small integer column used as a category (e.g. review_score 1..5)
    if not other_cols and len(num_cols) >= 2 and df[num_cols[0]].nunique() <= 20 and len(df) <= 20:
        df[num_cols[0]] = df[num_cols[0]].astype(str)
        other_cols, num_cols = [num_cols[0]], num_cols[1:]

    y = num_cols[0]
    time_col = next((c for c in other_cols if _is_time(df[c])), None)

    if time_col:
        df = df.sort_values(time_col)
        fig = px.line(df, x=time_col, y=y, markers=True)
    elif other_cols and len(df) <= 30:
        cat = other_cols[0]
        df[cat] = _shorten_ids(df[cat]).astype(str)
        long_labels = df[cat].str.len().max() > 12
        if len(df) > 6 or long_labels:
            fig = px.bar(df, x=y, y=cat, orientation="h")
            fig.update_yaxes(autorange="reversed")  # keep SQL ranking order top-down
        else:
            fig = px.bar(df, x=cat, y=y)
            fig.update_xaxes(type="category")       # e.g. review scores 1..5 as labels
    elif not other_cols and len(num_cols) >= 2:
        fig = px.scatter(df, x=num_cols[0], y=num_cols[1], opacity=0.6)
    else:
        return None

    fig.update_layout(
        title=question[:90], template="plotly_white", height=420,
        margin=dict(l=10, r=10, t=50, b=10),
        xaxis_title=_pretty(fig.layout.xaxis.title.text or ""),
        yaxis_title=_pretty(fig.layout.yaxis.title.text or ""),
    )
    return fig


def summarize(question: str, sql: str, df: pd.DataFrame, truncated: bool = False,
              llm: LLMClient | None = None) -> str:
    if df is None or df.empty:
        return "No rows matched this question. Try widening the date range or filters."
    llm = llm or LLMClient()
    trunc = ", truncated to first 1000" if truncated else ""
    prompt = SUMMARY_PROMPT.format(
        question=question, sql=sql, n_rows=len(df), trunc=trunc,
        table=_table_for_llm(df), units=_units_text(df), facts=_key_facts(df),
        small="yes" if has_small_samples(df) else "no")
    try:
        raw = llm.chat([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=400)
        return _clean_bullets(raw)
    except Exception:
        return f"The query returned {len(df)} rows. See the table and chart for details."


if __name__ == "__main__":
    from pathlib import Path

    from src.pipeline import ask

    out = Path("reports/chart_tests")
    out.mkdir(parents=True, exist_ok=True)
    llm = LLMClient()
    questions = [
        "Monthly number of orders in 2017",
        "Top 10 cities by number of customers",
        "How many orders got each review score?",
        "How many unique customers do we have?",
        "What is the total revenue in 2018?",
    ]
    for i, q in enumerate(questions, 1):
        r = ask(q, llm=llm)
        print(f"Q{i}: {q}  [{r.status}]")
        if r.status != "ok":
            print(f"   {r.message}\n")
            continue
        kpi = kpi_value(r.df)
        fig = make_chart(r.df, q)
        if kpi:
            print(f"   KPI: {kpi}")
        if fig:
            path = out / f"chart_{i}.html"
            fig.write_html(path, include_plotlyjs="cdn")
            print(f"   Chart saved: {path}  ({fig.data[0].type})")
        print("   facts:", _key_facts(r.df).replace("\n", " | "))
        print(summarize(q, r.sql, r.df, r.truncated, llm=llm), "\n")