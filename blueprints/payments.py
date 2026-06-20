"""
blueprints/payments.py — Quick Payment Receive / Payment Give entries.

ISSUE 1: Staff often receive/give payments without an invoice existing yet
(the invoice gets created later). This blueprint lets them log a payment
transaction immediately against a customer, search-driven by name/mobile,
and automatically keeps the ledger + customer balance in sync.

Every payment_transactions row created here is mirrored by exactly one
LedgerEntry row (entry_type="payment") so that:
  - Payment Receive  -> Credit entry  (reduces what the customer owes)
  - Payment Give     -> Debit entry   (increases what the customer owes)
and so that ALL balance/ledger math continues to flow through the single
centralized recalculation function (`recalculate_customer_ledger`), per the
"ONE centralized ledger calculation source" requirement.
"""

from datetime import date

from flask import Blueprint, jsonify, request, session

from database import SessionLocal, PaymentTransaction, LedgerEntry, Party
from utils.helpers import (
    d,
    parse_date,
    recalculate_customer_ledger,
    get_customer_ledger_summary,
)
from blueprints.auth import require_auth

payments_bp = Blueprint("payments", __name__, url_prefix="/api/payments")


# ── HELPERS ────────────────────────────────────────────────────────────────────

def _payment_txn_to_dict(t: PaymentTransaction) -> dict:
    return {
        "id": t.id,
        "customer_id": t.customer_id,
        "customer_name": t.customer.name if t.customer else "",
        "payment_type": t.payment_type,
        "amount": float(t.amount or 0),
        "payment_mode": t.payment_mode or "",
        "reference_no": t.reference_no or "",
        "note": t.note or "",
        "transaction_date": t.transaction_date.isoformat() if t.transaction_date else None,
        "ledger_entry_id": t.ledger_entry_id,
        "created_by": t.created_by,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def _validate_payload(data):
    """Shared validation for create/update. Returns (errors_response_or_None, cleaned)."""
    customer_id = data.get("customer_id") or data.get("party_id")
    payment_type = (data.get("payment_type") or "").strip().upper()
    amount = d(data.get("amount", 0))
    payment_mode = (data.get("payment_mode") or "cash").strip().lower()
    reference_no = (data.get("reference_no") or "").strip() or None
    note = (data.get("note") or "").strip() or None

    if not customer_id:
        return (jsonify({"error": "customer_id (customer) is required"}), 400), None
    if payment_type not in ("RECEIVED", "GIVEN"):
        return (jsonify({"error": "payment_type must be RECEIVED or GIVEN"}), 400), None
    if amount <= 0:
        return (jsonify({"error": "Amount must be greater than 0"}), 400), None

    valid_modes = ("cash", "upi", "bank_transfer", "bank", "cheque", "other")
    if payment_mode == "bank":
        payment_mode = "bank_transfer"
    if payment_mode not in valid_modes and payment_mode != "bank_transfer":
        payment_mode = "other"

    try:
        txn_date = parse_date(data.get("transaction_date") or data.get("date") or date.today().isoformat())
    except ValueError:
        return (jsonify({"error": "Invalid transaction_date"}), 400), None

    return None, {
        "customer_id": int(customer_id),
        "payment_type": payment_type,
        "amount": amount,
        "payment_mode": payment_mode,
        "reference_no": reference_no,
        "note": note,
        "transaction_date": txn_date,
    }


def _particulars_for(payment_type, reference_no):
    base = "Payment Received" if payment_type == "RECEIVED" else "Payment Given"
    if reference_no:
        base += f" (Ref: {reference_no})"
    return base


def _classify_entry_type(party, payment_type):
    """
    Issue 5 — Advance accounting. A payment is classified as a plain
    "payment" if the customer currently has an outstanding balance it
    can be applied against; otherwise (balance already zero/negative,
    i.e. no debt exists) it's recorded as an advance:
      - RECEIVED with no outstanding debt -> advance_received
      - GIVEN    with no outstanding debt -> advance_paid
    This mirrors how Tally/Vyapar/KhataBook auto-tag "on account"
    receipts vs payments applied against a bill. The distinction is
    informational (for reporting/filtering) — it does NOT change the
    debit/credit direction or the balance math, which stays driven
    purely by entry.debit/entry.credit either way.
    """
    current_balance = d(party.balance)
    if payment_type == "RECEIVED":
        return "advance_received" if current_balance <= 0 else "payment"
    else:
        return "advance_paid" if current_balance >= 0 else "payment"


# ── LIST PAYMENT TRANSACTIONS ─────────────────────────────────────────────────

@payments_bp.route("/", methods=["GET"])
@require_auth
def list_payments():
    customer_id = request.args.get("customer_id")
    payment_type = (request.args.get("payment_type") or "").strip().upper() or None
    limit = min(int(request.args.get("limit", 50)), 200)

    db = SessionLocal()
    try:
        query = db.query(PaymentTransaction)
        if customer_id:
            query = query.filter(PaymentTransaction.customer_id == int(customer_id))
        if payment_type in ("RECEIVED", "GIVEN"):
            query = query.filter(PaymentTransaction.payment_type == payment_type)

        rows = (
            query.order_by(
                PaymentTransaction.transaction_date.desc(),
                PaymentTransaction.id.desc(),
            )
            .limit(limit)
            .all()
        )
        return jsonify([_payment_txn_to_dict(t) for t in rows])
    finally:
        db.close()


# ── CREATE PAYMENT TRANSACTION (Payment Receive / Payment Give) ──────────────

@payments_bp.route("/", methods=["POST"])
@require_auth
def create_payment():
    data = request.get_json(force=True, silent=True) or {}

    err, clean = _validate_payload(data)
    if err:
        return err

    db = SessionLocal()
    try:
        customer = db.query(Party).filter(Party.id == clean["customer_id"]).one_or_none()
        if customer is None:
            return jsonify({"error": "Customer not found"}), 404

        is_received = clean["payment_type"] == "RECEIVED"

        # ISSUE 5: classify as advance_received/advance_paid when there's
        # no outstanding balance to apply this payment against.
        entry_type = _classify_entry_type(customer, clean["payment_type"])

        # 1. Create the ledger entry first (single source of truth for balance).
        #    Payment Receive -> Credit. Payment Give -> Debit.
        ledger_entry = LedgerEntry(
            party_id=customer.id,
            entry_date=clean["transaction_date"],
            entry_type=entry_type,
            particulars=_particulars_for(clean["payment_type"], clean["reference_no"]),
            debit=d("0") if is_received else clean["amount"],
            credit=clean["amount"] if is_received else d("0"),
            payment_mode=clean["payment_mode"],
            notes=clean["note"],
            created_by=session.get("user_id"),
        )
        db.add(ledger_entry)
        db.flush()  # get ledger_entry.id

        # 2. Create the payment_transactions row, linked to that ledger entry.
        txn = PaymentTransaction(
            customer_id=customer.id,
            payment_type=clean["payment_type"],
            amount=clean["amount"],
            payment_mode=clean["payment_mode"],
            reference_no=clean["reference_no"],
            note=clean["note"],
            transaction_date=clean["transaction_date"],
            ledger_entry_id=ledger_entry.id,
            created_by=session.get("user_id"),
        )
        db.add(txn)
        db.flush()

        # 3. Recalculate the customer's ledger (Issue 2 fix: full chronological
        #    rebuild, so backdated payments never corrupt the balance).
        recalculate_customer_ledger(customer.id, db)

        db.commit()
        db.refresh(txn)

        summary = get_customer_ledger_summary(db, customer.id)

        return jsonify({
            "ok": True,
            "transaction": _payment_txn_to_dict(txn),
            "ledger_entry_id": ledger_entry.id,
            "new_balance": summary["current_balance"],
            "summary": summary,
        }), 201

    except Exception as e:
        db.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        db.close()


# ── UPDATE PAYMENT TRANSACTION ────────────────────────────────────────────────

@payments_bp.route("/<int:txn_id>", methods=["PUT"])
@require_auth
def update_payment(txn_id):
    data = request.get_json(force=True, silent=True) or {}

    db = SessionLocal()
    try:
        txn = db.query(PaymentTransaction).filter(PaymentTransaction.id == txn_id).one_or_none()
        if txn is None:
            return jsonify({"error": "Payment transaction not found"}), 404

        ledger_entry = None
        if txn.ledger_entry_id:
            ledger_entry = (
                db.query(LedgerEntry)
                .filter(LedgerEntry.id == txn.ledger_entry_id)
                .one_or_none()
            )

        # Merge incoming fields over the existing row for validation.
        merged = {
            "customer_id": data.get("customer_id", txn.customer_id),
            "payment_type": data.get("payment_type", txn.payment_type),
            "amount": data.get("amount", float(txn.amount)),
            "payment_mode": data.get("payment_mode", txn.payment_mode),
            "reference_no": data.get("reference_no", txn.reference_no),
            "note": data.get("note", txn.note),
            "transaction_date": data.get("transaction_date") or data.get("date")
                or (txn.transaction_date.isoformat() if txn.transaction_date else None),
        }
        err, clean = _validate_payload(merged)
        if err:
            return err

        old_customer_id = txn.customer_id
        is_received = clean["payment_type"] == "RECEIVED"

        txn.customer_id = clean["customer_id"]
        txn.payment_type = clean["payment_type"]
        txn.amount = clean["amount"]
        txn.payment_mode = clean["payment_mode"]
        txn.reference_no = clean["reference_no"]
        txn.note = clean["note"]
        txn.transaction_date = clean["transaction_date"]

        if ledger_entry:
            ledger_entry.party_id = clean["customer_id"]
            ledger_entry.entry_date = clean["transaction_date"]
            ledger_entry.particulars = _particulars_for(clean["payment_type"], clean["reference_no"])
            ledger_entry.debit = d("0") if is_received else clean["amount"]
            ledger_entry.credit = clean["amount"] if is_received else d("0")
            ledger_entry.payment_mode = clean["payment_mode"]
            ledger_entry.notes = clean["note"]

        db.flush()

        # Recalculate BOTH the old and new customer if the customer changed.
        recalculate_customer_ledger(clean["customer_id"], db)
        if old_customer_id != clean["customer_id"]:
            recalculate_customer_ledger(old_customer_id, db)

        db.commit()
        db.refresh(txn)

        summary = get_customer_ledger_summary(db, clean["customer_id"])

        return jsonify({
            "ok": True,
            "transaction": _payment_txn_to_dict(txn),
            "new_balance": summary["current_balance"],
            "summary": summary,
        })

    except Exception as e:
        db.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        db.close()


# ── DELETE PAYMENT TRANSACTION ────────────────────────────────────────────────

@payments_bp.route("/<int:txn_id>", methods=["DELETE"])
@require_auth
def delete_payment(txn_id):
    db = SessionLocal()
    try:
        txn = db.query(PaymentTransaction).filter(PaymentTransaction.id == txn_id).one_or_none()
        if txn is None:
            return jsonify({"error": "Payment transaction not found"}), 404

        customer_id = txn.customer_id
        ledger_entry_id = txn.ledger_entry_id

        db.delete(txn)
        if ledger_entry_id:
            # ISSUE 5: remove any InvoiceAdjustment links that reference
            # this payment's ledger entry, so deleting a payment that was
            # adjusted against an invoice doesn't leave an orphaned link.
            from database import InvoiceAdjustment
            linked = (
                db.query(InvoiceAdjustment)
                .filter(InvoiceAdjustment.payment_ledger_entry_id == ledger_entry_id)
                .all()
            )
            for link in linked:
                if link.adjustment_ledger_entry_id:
                    adj_entry = (
                        db.query(LedgerEntry)
                        .filter(LedgerEntry.id == link.adjustment_ledger_entry_id)
                        .one_or_none()
                    )
                    if adj_entry:
                        db.delete(adj_entry)
                db.delete(link)

            ledger_entry = (
                db.query(LedgerEntry)
                .filter(LedgerEntry.id == ledger_entry_id)
                .one_or_none()
            )
            if ledger_entry:
                db.delete(ledger_entry)

        db.flush()
        recalculate_customer_ledger(customer_id, db)
        db.commit()

        summary = get_customer_ledger_summary(db, customer_id)
        return jsonify({"ok": True, "new_balance": summary["current_balance"], "summary": summary})

    except Exception as e:
        db.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        db.close()
