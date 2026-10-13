"""Shared paths. Also restores the database from its compressed copy when needed.

GitHub rejects files over 100 MB, so the repository stores data/db/olist.db.gz.
On first start (for example on Streamlit Cloud) the database is unpacked once.
"""
import gzip
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "db" / "olist.db"
DB_GZ_PATH = DB_PATH.with_name(DB_PATH.name + ".gz")


def ensure_database() -> None:
    """Unpack olist.db.gz into olist.db if the database file is missing."""
    if DB_PATH.exists() or not DB_GZ_PATH.exists():
        return
    tmp = DB_PATH.with_suffix(".db.part")
    with gzip.open(DB_GZ_PATH, "rb") as src, open(tmp, "wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
    tmp.replace(DB_PATH)   # atomic rename, so a half-written file is never used


ensure_database()