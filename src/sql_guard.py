"""Validates LLM-generated SQL: single, read-only SELECT on known tables only."""
import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

ALLOWED_TABLES = {"customers", "sellers", "orders", "order_items",
                  "payments", "reviews", "products"}

ALLOWED_ROOTS = tuple(c for c in (getattr(exp, n, None) for n in
                      ["Select", "Union", "Intersect", "Except"]) if c)

FORBIDDEN_NODES = tuple(c for c in (getattr(exp, n, None) for n in
                        ["Insert", "Update", "Delete", "Drop", "Create", "Alter",
                         "AlterTable", "Merge", "TruncateTable", "Command",
                         "Pragma", "Attach", "Detach"]) if c)

FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|REPLACE\s+INTO|ATTACH|DETACH|"
    r"PRAGMA|VACUUM|REINDEX|TRUNCATE|GRANT|LOAD_EXTENSION)\b",
    re.IGNORECASE)


@dataclass
class GuardResult:
    ok: bool
    sql: str
    error: str = ""


def _strip_literals(sql: str) -> str:
    """Remove quoted strings so words inside them don't trigger the blocklist."""
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def validate_sql(sql: str) -> GuardResult:
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        return GuardResult(False, sql, "Empty query.")

    # Layer 2: keyword blocklist (outside string literals)
    hit = FORBIDDEN_KEYWORDS.search(_strip_literals(sql))
    if hit:
        return GuardResult(False, sql, f"Blocked keyword: {hit.group(0).upper()}")

    # Layer 1: parse and check structure
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except sqlglot.errors.ParseError as e:
        return GuardResult(False, sql, f"SQL syntax error: {str(e).splitlines()[0]}")
    if len(statements) != 1:
        return GuardResult(False, sql, "Only one SQL statement is allowed.")
    tree = statements[0]
    if not isinstance(tree, ALLOWED_ROOTS):
        return GuardResult(False, sql, f"Only SELECT queries are allowed (got {tree.key.upper()}).")
    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            return GuardResult(False, sql, f"Forbidden operation: {node.key.upper()}")

    # Layer 3: table allowlist (CTE names are fine)
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if name and name not in ALLOWED_TABLES | cte_names:
            return GuardResult(False, sql, f"Unknown or restricted table: {table.name}")

    return GuardResult(True, sql)


if __name__ == "__main__":
    cases = [
        # (sql, should_pass)
        ("SELECT COUNT(*) FROM orders", True),
        ("WITH m AS (SELECT order_id FROM orders) SELECT COUNT(*) FROM m", True),
        ("SELECT review_score FROM reviews WHERE review_comment_message LIKE '%delete%'", True),
        ("SELECT customer_state FROM customers UNION SELECT seller_state FROM sellers", True),
        ("SELECT 1; DROP TABLE orders", False),
        ("DELETE FROM orders", False),
        ("UPDATE products SET product_category = 'x'", False),
        ("PRAGMA table_info(orders)", False),
        ("ATTACH DATABASE 'evil.db' AS evil", False),
        ("SELECT name FROM sqlite_master", False),
        ("SELECT load_extension('evil')", False),
        ("SELEC order_id FROM orders", False),
    ]
    passed = 0
    for sql, expected in cases:
        r = validate_sql(sql)
        status = "PASS" if r.ok == expected else "FAIL"
        passed += status == "PASS"
        verdict = "allowed" if r.ok else f"blocked ({r.error})"
        print(f"[{status}] {sql[:55]:<55} -> {verdict}")
    print(f"\n{passed}/{len(cases)} guard tests passed")