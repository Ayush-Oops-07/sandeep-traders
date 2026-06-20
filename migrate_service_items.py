"""
migrate_service_items.py — Run ONCE on server for Issue 4 (Service Items).

Adds to existing tables:
  invoice_items : item_type VARCHAR(10)  DEFAULT 'inventory'
                  is_manual_total BOOLEAN DEFAULT FALSE
  products      : stock_qty NUMERIC(14,3) nullable

Safe / idempotent — skips columns that already exist.

Usage:
    python migrate_service_items.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import engine, init_db

def column_exists(conn, table, col):
    from sqlalchemy import text
    dialect = engine.dialect.name
    if dialect == "sqlite":
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return any(r[1] == col for r in rows)
    elif dialect == "postgresql":
        r = conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            f"WHERE table_name='{table}' AND column_name='{col}'"
        )).fetchone()
        return r is not None
    return False

def run():
    init_db()
    print("Applying Issue 4 schema changes (service items / stock_qty)...")
    with engine.begin() as conn:
        dialect = engine.dialect.name

        if not column_exists(conn, "invoice_items", "item_type"):
            conn.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE invoice_items ADD COLUMN item_type VARCHAR(10) NOT NULL DEFAULT 'inventory'"
                )
            )
            print("  ✓ invoice_items.item_type added")
        else:
            print("  · invoice_items.item_type already exists")

        if not column_exists(conn, "invoice_items", "is_manual_total"):
            conn.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE invoice_items ADD COLUMN is_manual_total BOOLEAN NOT NULL DEFAULT FALSE"
                )
            )
            print("  ✓ invoice_items.is_manual_total added")
        else:
            print("  · invoice_items.is_manual_total already exists")

        if not column_exists(conn, "products", "stock_qty"):
            conn.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE products ADD COLUMN stock_qty NUMERIC(14,3)"
                )
            )
            print("  ✓ products.stock_qty added (nullable — opt-in stock tracking)")
        else:
            print("  · products.stock_qty already exists")

    print("\n✅ Service items migration complete!")

if __name__ == "__main__":
    run()
