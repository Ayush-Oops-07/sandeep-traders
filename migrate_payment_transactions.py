"""
migrate_payment_transactions.py — Run ONCE on server to add the
payment_transactions table (Issue 1: Payment Receive / Payment Give).

Usage:
    python migrate_payment_transactions.py

This script:
1. Creates the `payment_transactions` table if it doesn't already exist
   (safe / idempotent — uses CREATE TABLE IF NOT EXISTS equivalent via
   SQLAlchemy's checkfirst, so it will never touch existing tables).
2. Recalculates every party's ledger from scratch using the new
   date-ordered recalculation logic, fixing any historical balance
   corruption caused by the old insertion-order bug (Issue 2).

Safe to run multiple times.
"""

import os
import sys

# Make sure we can import the app's modules when run from project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import init_db, engine, Base, PaymentTransaction, SessionLocal, Party
from utils.helpers import recalculate_party_balance


def run_migration():
    print("Step 1/2: Ensuring payment_transactions table exists...")
    # checkfirst=True (the default for create_all) makes this idempotent —
    # it only creates tables that don't already exist. Existing tables and
    # their data are left completely untouched.
    Base.metadata.create_all(bind=engine, checkfirst=True, tables=[PaymentTransaction.__table__])
    print("  ✓ payment_transactions table ready")

    print("\nStep 2/2: Recalculating ledger balances for all parties "
          "(fixes backdated-entry arithmetic bug)...")
    db = SessionLocal()
    try:
        party_ids = [p.id for p in db.query(Party.id).all()]
        fixed = 0
        for pid in party_ids:
            recalculate_party_balance(db, pid)
            fixed += 1
        db.commit()
        print(f"  ✓ Recalculated balances for {fixed} parties")
    except Exception as e:
        db.rollback()
        print(f"  ⚠ Error during recalculation: {e}")
        raise
    finally:
        db.close()

    print("\n✅ Migration complete!")
    print("   - payment_transactions table is ready")
    print("   - All customer/shoper balances rebuilt in chronological order")


if __name__ == "__main__":
    init_db()  # ensures all base tables exist too (no-op if already present)
    run_migration()
