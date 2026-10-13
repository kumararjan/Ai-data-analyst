"""Builds the SQLite sales database from the raw Olist CSV files."""
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "db" / "olist.db"

# raw file -> clean table name
TABLES = {
    "olist_customers_dataset.csv": "customers",
    "olist_sellers_dataset.csv": "sellers",
    "olist_orders_dataset.csv": "orders",
    "olist_order_items_dataset.csv": "order_items",
    "olist_order_payments_dataset.csv": "payments",
    "olist_order_reviews_dataset.csv": "reviews",
    "olist_products_dataset.csv": "products",
}

DATE_COLS = {
    "orders": [
        "order_purchase_timestamp", "order_approved_at",
        "order_delivered_carrier_date", "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ],
    "order_items": ["shipping_limit_date"],
    "reviews": ["review_creation_date", "review_answer_timestamp"],
}

# (table, column, unique). Unique indexes on primary keys make every join fast,
# so complex LLM queries finish well inside the 10 second timeout.
INDEXES = [
    ("orders", "order_id", True),
    ("customers", "customer_id", True),
    ("products", "product_id", True),
    ("sellers", "seller_id", True),
    ("orders", "customer_id", False),
    ("orders", "order_purchase_timestamp", False),
    ("order_items", "order_id", False),
    ("order_items", "product_id", False),
    ("order_items", "seller_id", False),
    ("payments", "order_id", False),
    ("reviews", "order_id", False),
    ("customers", "customer_unique_id", False),
]


def load_products() -> pd.DataFrame:
    products = pd.read_csv(RAW / "olist_products_dataset.csv")
    trans = pd.read_csv(RAW / "product_category_name_translation.csv",
                        encoding="utf-8-sig")
    products = products.merge(trans, on="product_category_name", how="left")
    # English category becomes the main column; keep Portuguese for reference
    products = products.rename(columns={
        "product_category_name": "product_category_pt",
        "product_category_name_english": "product_category",
        # fix spelling mistakes in the original dataset
        "product_name_lenght": "product_name_length",
        "product_description_lenght": "product_description_length",
    })
    products["product_category"] = products["product_category"].fillna("unknown")
    return products


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    con = sqlite3.connect(DB_PATH)
    for file, table in TABLES.items():
        df = load_products() if table == "products" else pd.read_csv(RAW / file)
        for col in DATE_COLS.get(table, []):
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime(
                "%Y-%m-%d %H:%M:%S")
        df.to_sql(table, con, index=False)
        print(f"{table:<12} {len(df):>8,} rows")

    for table, col, unique in INDEXES:
        kind = "UNIQUE INDEX" if unique else "INDEX"
        con.execute(f"CREATE {kind} idx_{table}_{col} ON {table}({col})")
    con.execute("ANALYZE")   # gives the SQLite query planner table statistics
    con.commit()
    con.close()
    print(f"\n{len(INDEXES)} indexes created")
    print(f"Database saved to {DB_PATH}")


if __name__ == "__main__":
    main()