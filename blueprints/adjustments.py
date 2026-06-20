"""
blueprints/adjustments.py — Convert/Adjust a payment against an invoice.

ISSUE 5: A staff member logs Payment Received ₹5,000 on 4-Jun.
Later they create Invoice ₹8,000 on 18-Jun. Now they need to
"link" that payment to the invoice — without creating a duplicate
credit entry.

How it works (Tally/Vyapar-style):
  - The original payment LedgerEntry stays intact (full audit trail).
  - We create a new "adjustment" LedgerEntry that offsets the
    original payment credit with a matching debit, plus links it
    logically to the invoice, so the ledger shows:
        Payment Received (credit)            ₹5,000   Adv (-5,000)
        Invoice #C-0001  (debit)             ₹8,000   Bal (+3,000)
        Adjustment vs C-0001 (credit-back)  -₹5,000  [nets to 0]
    … which results in the customer's outstanding balance being ₹3,000
    instead of showing an unexplained credit that obscures what's billed.

  Simpler view for the user:
    Payment Received ₹5,000  →  Adjusted against Invoice ₹8,000
    Outstanding on invoice    =  ₹3,000
    If payment > invoice      →  Advance ₹1,000 remains in account
"""
from datetime import date as _date
from decimal import Decimal

from flask import Blueprint, jsonify, request, session
from sqlalchemy import func as sa_func

from database import (
    SessionLocal,
    LedgerEntry,
    Invoice,
    Party,
    InvoiceAdjustment,
)
from utils.helpers import (
    d,
    parse_date,
    recalculate_customer_ledger,
    to_float,
)
from blueprints.auth import require_auth

adjustments_bp = Blueprint(
    "adjustments", __name__, url_prefix="/api/adjustments"
)


def _adj_to_dict(adj: InvoiceAdjustment) -> dict:
    return {
        "id": adj.id,
        "party_id": adj.party_id,
        "payment_ledger_entry_id": adj.payment_ledger_entry_id,
        "invoice_id": adj.invoice_id,
        "amount": to_float(adj.amount),
        "adjustment_date": adj.adjustment_date.isoformat() if adj.adjustment_date else None,
        "notes": adj.notes or "",
        "created_at": adj.created_at.isoformat() if adj.created_at else None,
        "adjustment_ledger_entry_id": adj.adjustment_ledger_entry_id,
    }


# ── LIST ADJUSTMENTS FOR A PARTY ─────────────────────────────────────────────

@adjustments_bp.route("/", methods=["GET"])
@require_auth
def list_adjustments():
    party_id = request.args.get("party_id")
    invoice_id = request.args.get("invoice_id")
    db = SessionLocal()
    try:
        q = db.query(InvoiceAdjustment)
        if party_id:
            q = q.filter(InvoiceAdjustment.party_id == int(party_id))
        if invoice_id:
            q = q.filter(InvoiceAdjustment.invoice_id == int(invoice_id))
        rows = q.order_by(InvoiceAdjustment.id.desc()).limit(100).all()
        return jsonify([_adj_to_dict(a) for a in rows])
    finally:
        db.close()


# ── CREATE ADJUSTMENT ─────────────────────────────────────────────────────────

@adjustments_bp.route("/", methods=["POST"])
@require_auth
def create_adjustment():
    """
    Body (JSON):
      payment_ledger_entry_id : int   — the payment entry to adjust against
      invoice_id              : int?  — existing invoice to apply against
      amount                  : float — amount to apply (≤ payment amount)
      adjustment_date         : str?  — ISO date, defaults to today
      notes                   : str?
    """
    data = request.get_json(force=True, silent=True) or {}

    payment_entry_id = data.get("payment_ledger_entry_id")
    invoice_id = data.get("invoice_id")
    amount = d(data.get("amount") or 0)
    notes = (data.get("notes") or "").strip() or None

    if not payment_entry_id:
        return jsonify({"error": "payment_ledger_entry_id is required"}), 400
    if amount <= 0:
        return jsonify({"error": "Amount must be greater than 0"}), 400

    try:
        adj_date = parse_date(
            data.get("adjustment_date") or _date.today().isoformat()
        )
    except ValueError:
        return jsonify({"error": "Invalid adjustment_date"}), 400

    db = SessionLocal()
    try:
        # Load and validate the payment entry
        pay_entry = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.id == payment_entry_id)
            .one_or_none()
        )
        if pay_entry is None:
            return jsonify({"error": "Payment ledger entry not found"}), 404

        party_id = pay_entry.party_id

        # Validate that the entry is a payment/credit (not an invoice debit)
        if d(pay_entry.credit) <= 0:
            return jsonify({
                "error": "Selected entry is not a credit/payment — only "
                         "Payment Received entries can be adjusted against invoices"
            }), 400

        # Amount being adjusted cannot exceed the original payment's credit
        already_adjusted = d(
            db.query(
                sa_func.coalesce(sa_func.sum(InvoiceAdjustment.amount), 0)
            )
            .filter(InvoiceAdjustment.payment_ledger_entry_id == payment_entry_id)
            .scalar()
        )
        available = d(pay_entry.credit) - already_adjusted

        if amount > available:
            return jsonify({
                "error": f"Cannot adjust more than the available balance "
                         f"(₹{to_float(available):.2f}) on this payment entry"
            }), 400

        # Optionally validate the invoice
        invoice = None
        inv_label = ""
        if invoice_id:
            invoice = (
                db.query(Invoice)
                .filter(
                    Invoice.id == int(invoice_id),
                    Invoice.party_id == party_id
                )
                .one_or_none()
            )
            if invoice is None:
                return jsonify({"error": "Invoice not found for this customer"}), 404
            if invoice.is_cancelled:
                return jsonify({"error": "Cannot adjust against a cancelled invoice"}), 400
            inv_label = f" vs Invoice #{invoice.invoice_number}"

        # Accounting note on what an "adjustment" represents here:
        #
        # The original Payment Received entry and the Invoice entry were
        # ALREADY posted to the ledger (as credit and debit respectively)
        # at the time each was created, so the customer's running balance
        # is already arithmetically correct (Invoice 8,000 − Payment 5,000
        # = 3,000 outstanding) without this step.
        #
        # What's missing without this feature is the *link* — there is no
        # record that the ₹5,000 payment was specifically intended to
        # cover this invoice. This endpoint creates that link:
        #   - InvoiceAdjustment row: the durable record of "this much of
        #     this payment was applied to this invoice".
        #   - A zero-value (debit=0, credit=0) "adjustment" LedgerEntry,
        #     purely so the linkage is visible in the ledger timeline
        #     ("Payment adjusted vs Invoice #C-0001") without double
        #     counting money that's already been posted.
        #
        # If the payment is for MORE than the invoice (e.g. ₹5,000 paid,
        # ₹4,000 invoiced), the unadjusted remainder (₹1,000) simply stays
        # as an advance/credit balance on the account — exactly as Tally/
        # Vyapar/KhataBook behave. No further entry is needed for that;
        # `available - amount` in the response tells the UI how much
        # advance remains for future adjustments.

        particulars = (
            f"Payment adjustment{inv_label}"
            + (f" — {notes}" if notes else "")
        )

        adj_entry = LedgerEntry(
            party_id=party_id,
            entry_date=adj_date,
            entry_type="adjustment",
            particulars=particulars,
            debit=Decimal("0.00"),
            credit=Decimal("0.00"),
            invoice_id=invoice.id if invoice else None,
            invoice_number=invoice.invoice_number if invoice else None,
            notes=notes,
            created_by=session.get("user_id"),
        )
        db.add(adj_entry)
        db.flush()

        # Record the link
        adj = InvoiceAdjustment(
            party_id=party_id,
            payment_ledger_entry_id=payment_entry_id,
            invoice_id=invoice.id if invoice else None,
            amount=amount,
            adjustment_date=adj_date,
            notes=notes,
            adjustment_ledger_entry_id=adj_entry.id,
            created_by=session.get("user_id"),
        )
        db.add(adj)
        db.flush()

        # Recalculate (balance isn't changed by the adjustment entry
        # since debit=credit=0, but the recalc is cheap and keeps
        # running_balance values fresh).
        recalculate_customer_ledger(party_id, db)
        db.commit()
        db.refresh(adj)

        # Build a human-readable summary for the UI response
        party = db.query(Party).filter(Party.id == party_id).one()
        return jsonify({
            "ok": True,
            "adjustment": _adj_to_dict(adj),
            "summary": {
                "payment_amount": to_float(pay_entry.credit),
                "adjusted_amount": to_float(amount),
                "remaining_advance": to_float(available - amount),
                "invoice_total": to_float(invoice.total_amount) if invoice else None,
                "customer_balance": to_float(party.balance),
            }
        }), 201

    except Exception as e:
        db.rollback()
        import traceback; traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        db.close()


# ── DELETE ADJUSTMENT ─────────────────────────────────────────────────────────

@adjustments_bp.route("/<int:adj_id>", methods=["DELETE"])
@require_auth
def delete_adjustment(adj_id):
    db = SessionLocal()
    try:
        adj = (
            db.query(InvoiceAdjustment)
            .filter(InvoiceAdjustment.id == adj_id)
            .one_or_none()
        )
        if adj is None:
            return jsonify({"error": "Not found"}), 404

        party_id = adj.party_id
        entry_id = adj.adjustment_ledger_entry_id

        db.delete(adj)
        if entry_id:
            entry = db.query(LedgerEntry).filter(LedgerEntry.id == entry_id).one_or_none()
            if entry:
                db.delete(entry)

        db.flush()
        recalculate_customer_ledger(party_id, db)
        db.commit()
        return jsonify({"ok": True})

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()
