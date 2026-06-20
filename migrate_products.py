"""
migrate_products.py — Run ONCE on server to add party_type to products table.

Usage:
    python migrate_products.py

This script:
1. Adds `party_type` column to products table (if not exists)
2. Sets existing products default to 'customer'
3. Creates new unique index on (party_type, name)
4. Removes old unique constraint on name alone (if exists)
"""

import os
from sqlalchemy import text

# Import engine from your app
_raw_url = os.getenv("DATABASE_URL", "")
if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql://", 1)
DATABASE_URL = _raw_url if _raw_url else "sqlite:///sandeep_traders.db"

from sqlalchemy import create_engine

_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
    engine = create_engine(DATABASE_URL, connect_args=_connect_args)
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

IS_SQLITE = DATABASE_URL.startswith("sqlite")

def run_migration():
    with engine.connect() as conn:
        # ── Step 1: Check if party_type column already exists ──────────────────
        if IS_SQLITE:
            result = conn.execute(text("PRAGMA table_info(products)")).fetchall()
            col_names = [r[1] for r in result]
        else:
            result = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='products' AND column_name='party_type'"
            )).fetchall()
            col_names = [r[0] for r in result]

        if "party_type" not in col_names:
            print("Adding party_type column to products table...")
            if IS_SQLITE:
                conn.execute(text(
                    "ALTER TABLE products ADD COLUMN party_type VARCHAR(20) NOT NULL DEFAULT 'customer'"
                ))
            else:
                # PostgreSQL
                conn.execute(text(
                    "ALTER TABLE products ADD COLUMN IF NOT EXISTS party_type VARCHAR(20) NOT NULL DEFAULT 'customer'"
                ))
            conn.commit()
            print("  ✓ Column added, all existing products set to 'customer'")
        else:
            print("  ✓ party_type column already exists — skipping")

        # ── Step 2: Create index on (party_type, name) ─────────────────────────
        if IS_SQLITE:
            existing_idx = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='ix_products_type_name'"
            )).fetchone()
            if not existing_idx:
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_products_type_name ON products(party_type, name)"
                ))
                conn.commit()
                print("  ✓ Index ix_products_type_name created")
            else:
                print("  ✓ Index already exists — skipping")
        else:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_products_type_name ON products(party_type, name)"
            ))
            conn.commit()
            print("  ✓ Index ix_products_type_name ensured")

        # ── Step 3: Remove old unique constraint on name alone (PostgreSQL only) ─
        if not IS_SQLITE:
            try:
                conn.execute(text(
                    "ALTER TABLE products DROP CONSTRAINT IF EXISTS products_name_key"
                ))
                conn.commit()
                print("  ✓ Old unique constraint on name removed")
            except Exception as e:
                print(f"  ⚠ Could not remove old constraint (may not exist): {e}")
                conn.rollback()

        print("\n✅ Migration complete!")
        print("   Products are now separated by party_type (customer / shoper)")


if __name__ == "__main__":
    run_migration()
