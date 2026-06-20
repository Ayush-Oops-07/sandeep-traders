"""
utils/helpers.py — Shared utilities: balance recalc, invoice numbering, formatters.
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime
from sqlalchemy import func

from database import LedgerEntry, Invoice, Party, SystemSetting, SessionLocal


TWO = Decimal("0.01")


# ── DECIMAL HELPERS ───────────────────────────────────────────────────────────

def d(value) -> Decimal:
    """Convert any value to Decimal safely."""
    if value is None:
        return Decimal("0.00")
    try:
        return Decimal(str(value)).quantize(TWO, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def to_float(value) -> float:
    return float(d(value))


# ── BALANCE RECALCULATION ─────────────────────────────────────────────────────
#
# ISSUE 2 FIX — Backdated Entry Arithmetic Bug
# ─────────────────────────────────────────────────────────────────────────────
# Root cause: the old `recalculate_from_entry()` only recalculated rows with
# id >= the changed row's id. That is correct ONLY if ids always increase in
# the same order as transaction_date. The moment a backdated transaction is
# inserted (a row whose date is in the past but whose id is the newest/largest
# because it was entered later), two things break:
#   1. Rows with a smaller id than the backdated row, but a LATER date, never
#      get touched by the partial recalc — they keep their stale balance.
#   2. The "previous row" lookup (used to seed the starting running balance)
#      also used id ordering, so it could seed from the wrong row.
# The fix: every recalculation ALWAYS rebuilds the party's entire ledger in
# strict chronological order (transaction_date ASC, id ASC) from the opening
# balance forward. This is the only ordering that is guaranteed correct
# regardless of insertion order, and it is cheap enough (a single indexed
# query per party) to run on every mutation.

def recalculate_party_balance(db, party_id: int) -> Decimal:
    """
    Recalculate running balance for ALL ledger entries of a party in
    chronological order (entry_date ASC, id ASC). Updates every entry's
    running_balance in-place and updates Party.balance.

    Balance formula (per spec): Current Balance = Total Debit - Total Credit
    Running balance is rebuilt incrementally from the opening balance so it
    is always consistent with this formula no matter how/when rows were
    inserted, edited, or deleted.

    Returns the final balance.
    """
    party = db.query(Party).filter(Party.id == party_id).one()
    entries = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.party_id == party_id)
        .order_by(LedgerEntry.entry_date.asc(), LedgerEntry.id.asc())
        .all()
    )

    running = d(party.opening_balance)
    for entry in entries:
        running = running + d(entry.debit) - d(entry.credit)
        entry.running_balance = running

    party.balance = running
    return running


def recalculate_from_entry(db, party_id: int, from_entry_id: int = None) -> Decimal:
    """
    Backwards-compatible wrapper kept so existing call sites don't need to
    change. `from_entry_id` is now IGNORED on purpose: partial/incremental
    recalculation by id is exactly what caused Issue 2 (backdated entries
    corrupting the ledger), so we always perform a full chronological
    rebuild via `recalculate_party_balance`. The extra cost is negligible
    (one indexed SELECT per party) and guarantees correctness.
    """
    return recalculate_party_balance(db, party_id)


def recalculate_customer_ledger(customer_id: int, db=None) -> Decimal:
    """
    PUBLIC ENTRY POINT requested in Issue 2.

    Recalculates a single customer's ledger from scratch:
      1. Fetches ALL ledger transactions for the customer.
      2. Sorts them by transaction_date ASC, id ASC.
      3. Rebuilds the running balance from the beginning.
      4. Updates running_balance for every row.
      5. Updates the customer's summary balance (Party.balance), which is
         what every dashboard card reads — so this single call keeps
         Total Sales / Total Payments / Outstanding / Current Balance all
         consistent (see `get_customer_ledger_summary` below).

    Call this automatically after:
      - Invoice added / edited / deleted
      - Payment added / edited / deleted (including quick Payment
        Receive / Payment Give entries)
      - Manual debit/credit added
      - Any transaction's date is changed

    Can be called with an existing session (`db`) so it participates in the
    caller's transaction, or on its own (it will open + commit + close its
    own session) for one-off / admin / migration use.
    """
    owns_session = db is None
    if owns_session:
        db = SessionLocal()
    try:
        balance = recalculate_party_balance(db, customer_id)
        if owns_session:
            db.commit()
        return balance
    except Exception:
        if owns_session:
            db.rollback()
        raise
    finally:
        if owns_session:
            db.close()


def get_customer_ledger_summary(db, party_id: int) -> dict:
    """
    SINGLE CENTRALIZED SOURCE for every dashboard card that shows
    Total Sales / Total Payments (Received & Given) / Outstanding /
    Current Balance for a customer. Every card MUST read from here (or
    from Party.balance, which this function also reads) instead of doing
    its own separate arithmetic — this is what the spec calls out
    explicitly under "IMPORTANT".

    All figures are derived purely from LedgerEntry rows + opening_balance,
    so they can never drift from what `recalculate_party_balance` computed.
    """
    party = db.query(Party).filter(Party.id == party_id).one()

    totals = (
        db.query(
            func.coalesce(func.sum(LedgerEntry.debit), 0).label("total_debit"),
            func.coalesce(func.sum(LedgerEntry.credit), 0).label("total_credit"),
        )
        .filter(LedgerEntry.party_id == party_id)
        .one()
    )

    total_sales = d(
        db.query(func.coalesce(func.sum(LedgerEntry.debit), 0))
        .filter(LedgerEntry.party_id == party_id, LedgerEntry.entry_type == "sale")
        .scalar()
    )

    total_payments_received = d(
        db.query(func.coalesce(func.sum(LedgerEntry.credit), 0))
        .filter(
            LedgerEntry.party_id == party_id,
            LedgerEntry.entry_type.in_(("payment", "advance_received")),
        )
        .scalar()
    )

    total_payments_given = d(
        db.query(func.coalesce(func.sum(LedgerEntry.debit), 0))
        .filter(
            LedgerEntry.party_id == party_id,
            LedgerEntry.entry_type.in_(("payment", "advance_paid")),
        )
        .scalar()
    )

    total_debit = d(totals.total_debit)
    total_credit = d(totals.total_credit)
    current_balance = d(party.opening_balance) + total_debit - total_credit

    return {
        "party_id": party_id,
        "opening_balance": to_float(party.opening_balance),
        "total_debit": to_float(total_debit),
        "total_credit": to_float(total_credit),
        "total_sales": to_float(total_sales),
        "total_payments_received": to_float(total_payments_received),
        "total_payments_given": to_float(total_payments_given),
        "outstanding": to_float(current_balance if current_balance > 0 else 0),
        "advance": to_float(abs(current_balance) if current_balance < 0 else 0),
        "current_balance": to_float(current_balance),
    }


# ── INVOICE NUMBER GENERATION ─────────────────────────────────────────────────

def next_invoice_number(db, party_type: str) -> str:
    """
    Generates sequential invoice numbers:
      Customer  → C-0001, C-0002 ...
      Shoper    → S-0001, S-0002 ...
    Stored in system_settings so it survives restarts.
    """
    prefix = "C" if party_type == "customer" else "S"
    key = f"last_invoice_{party_type}"

    setting = db.query(SystemSetting).filter(SystemSetting.key == key).one_or_none()
    if setting is None:
        # Find max from existing invoices as seed
        last = (
            db.query(func.max(Invoice.invoice_number))
            .filter(Invoice.party_type == party_type)
            .scalar()
        )
        if last:
            try:
                seq = int(last.split("-")[-1])
            except Exception:
                seq = 0
        else:
            seq = 0
        setting = SystemSetting(key=key, value=str(seq))
        db.add(setting)
        db.flush()  # ← flush immediately so duplicate key errors surface now

    next_seq = int(setting.value or 0) + 1
    setting.value = str(next_seq)
    db.flush()  # ← persist updated counter before returning

    # Safety: if this number already exists, keep incrementing
    for _ in range(100):
        candidate = f"{prefix}-{next_seq:04d}"
        exists = db.query(Invoice).filter(Invoice.invoice_number == candidate).count()
        if not exists:
            return candidate
        next_seq += 1
        setting.value = str(next_seq)

    raise RuntimeError("Could not generate unique invoice number")


# ── DATE HELPERS ──────────────────────────────────────────────────────────────

def parse_date(value) -> date:
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {value}")


def today_str() -> str:
    return date.today().isoformat()


# ── SERIALIZERS ───────────────────────────────────────────────────────────────

def party_to_dict(p: Party) -> dict:
    return {
        "id": p.id,
        "party_type": p.party_type,
        "name": p.name,
        "mobile": p.mobile or "",
        "mobile2": p.mobile2 or "",
        "address": p.address or "",
        "city": p.city or "",
        "gstin": p.gstin or "",
        "email": p.email or "",
        "opening_balance": to_float(p.opening_balance),
        "balance": to_float(p.balance),
        "is_active": p.is_active,
        "notes": p.notes or "",
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def entry_to_dict(e: LedgerEntry) -> dict:
    return {
        "id": e.id,
        "party_id": e.party_id,
        "entry_date": e.entry_date.isoformat() if e.entry_date else None,
        "entry_type": e.entry_type,
        "particulars": e.particulars or "",
        "debit": to_float(e.debit),
        "credit": to_float(e.credit),
        "running_balance": to_float(e.running_balance),
        "payment_mode": e.payment_mode or "",
        "invoice_id": e.invoice_id,
        "invoice_number": e.invoice_number or "",
        "notes": e.notes or "",
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def invoice_to_dict(inv: Invoice, include_items: bool = False) -> dict:
    data = {
        "id": inv.id,
        "invoice_number": inv.invoice_number,
        "party_id": inv.party_id,
        "party_type": inv.party_type,
        "party_name": inv.party.name if inv.party else "",
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "subtotal": to_float(inv.subtotal),
        "discount_amount": to_float(inv.discount_amount),
        "gst_amount": to_float(inv.gst_amount),
        "total_amount": to_float(inv.total_amount),
        "notes": inv.notes or "",
        "is_cancelled": inv.is_cancelled,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
    }
    if include_items:
        data["items"] = [
            {
                "id": it.id,
                "product_name": it.product_name,
                "unit": it.unit or "",
                "quantity": float(it.quantity),
                "rate": float(it.rate),
                "discount_pct": float(it.discount_pct),
                "gst_pct": float(it.gst_pct),
                "total": float(it.total),
                "item_type": it.item_type or "inventory",
                "is_manual_total": bool(it.is_manual_total),
            }
            for it in inv.items
        ]
    return data
