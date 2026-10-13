"""Builds a compact, LLM-friendly description of the database schema."""
import sqlite3
from functools import lru_cache

from src.config import DB_PATH

TABLE_NOTES = {
    "customers": "One row per customer_id. customer_id is unique PER ORDER; "
                 "customer_unique_id identifies the real person.",
    "sellers": "One row per seller.",
    "orders": "One row per order. Main fact table for dates and status.",
    "order_items": "One row per item in an order. Revenue comes from here.",
    "payments": "One or more rows per order (split payments).",
    "reviews": "Customer review per order, score 1 to 5.",
    "products": "One row per product with English category.",
}

COLUMN_NOTES = {
    "order_items.order_item_id": "item sequence number inside the order (1,2,3...)",
    "order_items.price": "item price in BRL (Brazilian real), excludes freight",
    "order_items.freight_value": "shipping cost in BRL for that item",
    "payments.payment_value": "amount paid in BRL",
    "payments.payment_installments": "number of installments",
    "payments.payment_sequential": "payment sequence number within the order",
    "orders.order_purchase_timestamp": "when the order was placed, 'YYYY-MM-DD HH:MM:SS'",
    "orders.order_delivered_customer_date": "actual delivery date, NULL if not delivered",
    "orders.order_estimated_delivery_date": "promised delivery date",
    "customers.customer_city": "lowercase, no accents, e.g. 'sao paulo', 'rio de janeiro', 'belo horizonte'",
    "customers.customer_state": "2-letter Brazilian state code, e.g. SP, RJ, MG",
    "sellers.seller_city": "lowercase, no accents, e.g. 'sao paulo', 'curitiba'",
    "sellers.seller_state": "2-letter Brazilian state code",
    "products.product_category": "English category name, 'unknown' if missing",
    "products.product_category_pt": "original Portuguese category name (ignore unless asked)",
}

# low-cardinality columns: show their real values to the LLM
ENUM_COLUMNS = [
    ("orders", "order_status"),
    ("payments", "payment_type"),
]

RELATIONSHIPS = [
    "orders.customer_id = customers.customer_id",
    "order_items.order_id = orders.order_id",
    "order_items.product_id = products.product_id",
    "order_items.seller_id = sellers.seller_id",
    "payments.order_id = orders.order_id",
    "reviews.order_id = orders.order_id",
]

BUSINESS_RULES = [
    "Revenue / sales = SUM(order_items.price). Add freight_value only if asked for total incl. shipping.",
    "Number of orders = COUNT(DISTINCT orders.order_id).",
    "Number of customers = COUNT(DISTINCT customers.customer_unique_id).",
    "Units sold = COUNT(*) of order_items rows.",
    "Average order value = SUM(order_items.price) / COUNT(DISTINCT order_id).",
    "Unless the user says otherwise, exclude orders with order_status IN ('canceled','unavailable').",
    "Data covers 2016-09 to 2018-10; 2016 and late 2018 are sparse.",
    "Month: strftime('%Y-%m', order_purchase_timestamp). Year: strftime('%Y', ...).",
    "Delivery days = julianday(order_delivered_customer_date) - julianday(order_purchase_timestamp).",
    "Do not SUM payments.payment_value joined to order_items (it duplicates rows).",
    "Reviews are per ORDER. When linking reviews to sellers or categories through order_items, first "
    "build DISTINCT (order_id, seller_id) or (order_id, product_category) pairs so each review counts "
    "once per group, never once per item.",
    "City names are stored lowercase without accents: write c.customer_city = 'sao paulo', never 'São Paulo'.",
    "When ranking AVERAGES by group (review score, delivery days, price), ignore small groups "
    "with HAVING COUNT(*) >= 30 unless the user says otherwise.",
]


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


@lru_cache(maxsize=1)
def get_schema_text() -> str:
    con = _connect()
    lines = ["### Tables"]
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for t in tables:
        lines.append(f"\n{t}: {TABLE_NOTES.get(t, '')}")
        for _, col, ctype, *_ in con.execute(f"PRAGMA table_info({t})"):
            note = COLUMN_NOTES.get(f"{t}.{col}")
            lines.append(f"  - {col} ({ctype or 'TEXT'})" + (f": {note}" if note else ""))

    lines.append("\n### Allowed values")
    for t, c in ENUM_COLUMNS:
        vals = [r[0] for r in con.execute(f"SELECT DISTINCT {c} FROM {t} ORDER BY 1")]
        lines.append(f"- {t}.{c}: {', '.join(map(str, vals))}")
    cats = [r[0] for r in con.execute(
        "SELECT product_category FROM products GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 15")]
    lines.append(f"- products.product_category (top 15 of 70+): {', '.join(cats)}")

    lines.append("\n### Relationships")
    lines += [f"- {r}" for r in RELATIONSHIPS]
    lines.append("\n### Business rules")
    lines += [f"- {r}" for r in BUSINESS_RULES]
    con.close()
    return "\n".join(lines)


if __name__ == "__main__":
    print(get_schema_text())