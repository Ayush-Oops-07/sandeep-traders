"""
migrate_adjustments.py — Run ONCE on server for Issue 5
(Convert/Adjust Payment Against Invoice + Advance accounting).

Creates the `invoice_adjustments` table if it doesn't exist, and adds
the new ledger entry types (advance_received, advance_paid, adjustment)
which SQLite/Postgres enums need recreated for — but since entry_type is
stored as VARCHAR under the hood via SQLAlchemy's Enum (not a native
DB enum on SQLite, and validated at the Python layer for Postgres only
if using ENUM type strictly), no destructive migration is required for
existing rows. New rows can simply start using the new type values.

Usage:
    python migrate_adjustments.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import engine, Base, InvoiceAdjustment, init_db


def run():
    init_db()
    print("Ensuring invoice_adjustments table exists...")
    Base.metadata.create_all(
        bind=engine, checkfirst=True, tables=[InvoiceAdjustment.__table__]
    )
    print("  ✓ invoice_adjustments table ready")
    print("\n✅ Adjustments migration complete!")
    print("   New ledger entry types available: advance_received, "
          "advance_paid, adjustment")


if __name__ == "__main__":
    run()
