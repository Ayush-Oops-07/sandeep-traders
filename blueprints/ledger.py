"""
blueprints/ledger.py — Ledger entry management.
All mutations trigger recalculate_customer_ledger (Issue 2 fix) for
mathematically correct, chronologically-ordered balance recalculation —
regardless of insertion order, so backdated entries can never corrupt
the ledger.
"""

from datetime import date
from flask import Blueprint, jsonify, request, session

from database import SessionLocal, LedgerEntry, Party
from utils.helpers import (
    entry_to_dict, d, parse_date,
    recalculate_party_balance, recalculate_customer_ledger
)
from blueprints.auth import require_auth

ledger_bp = Blueprint("ledger", __name__, url_prefix="/api/ledger")


# ── GET LEDGER FOR PARTY ──────────────────────────────────────────────────────

@ledger_bp.route("/<int:party_id>", methods=["GET"])
@require_auth
def get_ledger(party_id):
    db = SessionLocal()
    try:
        # Verify party exists
        p = db.query(Party).filter(Party.id == party_id).one_or_none()
        if p is None:
            return jsonify({"error": "Party not found"}), 404

        # Filters
        date_from = request.args.get("from")
        date_to   = request.args.get("to")
        q         = (request.args.get("q") or "").strip()

        query = db.query(LedgerEntry).filter(LedgerEntry.party_id == party_id)

        if date_from:
            try:
                query = query.filter(LedgerEntry.entry_date >= parse_date(date_from))
            except ValueError:
                pass
        if date_to:
            try:
                query = query.filter(LedgerEntry.entry_date <= parse_date(date_to))
            except ValueError:
                pass
        if q:
            query = query.filter(LedgerEntry.particulars.ilike(f"%{q}%"))

        entries = query.order_by(LedgerEntry.entry_date.asc(), LedgerEntry.id.asc()).all()

        return jsonify({
            "party_id": party_id,
            "balance": float(p.balance or 0),
            "opening_balance": float(p.opening_balance or 0),
            "entries": [entry_to_dict(e) for e in entries],
        })
    finally:
        db.close()


# ── ADD PAYMENT ENTRY ─────────────────────────────────────────────────────────

@ledger_bp.route("/payment", methods=["POST"])
@require_auth
def add_payment():
    data = request.get_json(force=True, silent=True) or {}
    party_id     = data.get("party_id")
    amount       = d(data.get("amount", 0))
    payment_mode = (data.get("payment_mode") or "cash").strip()
    particulars  = (data.get("particulars") or "Payment Received").strip()
    entry_date   = parse_date(data.get("date") or date.today().isoformat())
    notes        = (data.get("notes") or "").strip() or None

    if not party_id:
        return jsonify({"error": "party_id required"}), 400
    if amount <= 0:
        return jsonify({"error": "Amount must be > 0"}), 400

    db = SessionLocal()
    try:
        p = db.query(Party).filter(Party.id == party_id).one_or_none()
        if p is None:
            return jsonify({"error": "Party not found"}), 404

        entry = LedgerEntry(
            party_id     = party_id,
            entry_date   = entry_date,
            entry_type   = "payment",
            particulars  = particulars,
            debit        = d("0"),
            credit       = amount,
            payment_mode = payment_mode,
            notes        = notes,
            created_by   = session.get("user_id"),
        )
        db.add(entry)
        db.flush()  # get entry.id
        recalculate_customer_ledger(party_id, db)
        db.commit()
        db.refresh(entry)

        return jsonify({
            "ok": True,
            "entry": entry_to_dict(entry),
            "new_balance": float(p.balance),
        }), 201
    finally:
        db.close()


# ── ADD DEBIT ENTRY (manual) ──────────────────────────────────────────────────

@ledger_bp.route("/debit", methods=["POST"])
@require_auth
def add_debit():
    data = request.get_json(force=True, silent=True) or {}
    party_id    = data.get("party_id")
    amount      = d(data.get("amount", 0))
    particulars = (data.get("particulars") or "Debit Entry").strip()
    entry_date  = parse_date(data.get("date") or date.today().isoformat())
    notes       = (data.get("notes") or "").strip() or None

    if not party_id:
        return jsonify({"error": "party_id required"}), 400
    if amount <= 0:
        return jsonify({"error": "Amount must be > 0"}), 400

    db = SessionLocal()
    try:
        p = db.query(Party).filter(Party.id == party_id).one_or_none()
        if p is None:
            return jsonify({"error": "Party not found"}), 404

        entry = LedgerEntry(
            party_id    = party_id,
            entry_date  = entry_date,
            entry_type  = "debit",
            particulars = particulars,
            debit       = amount,
            credit      = d("0"),
            notes       = notes,
            created_by  = session.get("user_id"),
        )
        db.add(entry)
        db.flush()
        recalculate_customer_ledger(party_id, db)
        db.commit()
        db.refresh(entry)

        return jsonify({
            "ok": True,
            "entry": entry_to_dict(entry),
            "new_balance": float(p.balance),
        }), 201
    finally:
        db.close()


# ── EDIT ENTRY ────────────────────────────────────────────────────────────────

@ledger_bp.route("/<int:entry_id>", methods=["PUT"])
@require_auth
def update_entry(entry_id):
    data = request.get_json(force=True, silent=True) or {}
    db = SessionLocal()
    try:
        entry = db.query(LedgerEntry).filter(LedgerEntry.id == entry_id).one_or_none()
        if entry is None:
            return jsonify({"error": "Entry not found"}), 404

        # Prevent editing invoice-linked entries directly (use invoice API)
        if entry.invoice_id and entry.entry_type == "sale":
            return jsonify({"error": "Edit the invoice to change this entry"}), 400

        if "particulars" in data:
            entry.particulars = (data["particulars"] or "").strip()
        if "date" in data:
            entry.entry_date = parse_date(data["date"])
        if "notes" in data:
            entry.notes = (data["notes"] or "").strip() or None
        if "payment_mode" in data:
            entry.payment_mode = data["payment_mode"] or None

        # Allow editing amount only for non-invoice entries
        if not entry.invoice_id:
            if "amount" in data:
                amt = d(data["amount"])
                if amt <= 0:
                    return jsonify({"error": "Amount must be > 0"}), 400
                if entry.entry_type == "payment":
                    entry.credit = amt
                    entry.debit  = d("0")
                else:
                    entry.debit  = amt
                    entry.credit = d("0")

        party_id = entry.party_id
        db.flush()
        recalculate_customer_ledger(party_id, db)
        db.commit()
        db.refresh(entry)

        p = db.query(Party).filter(Party.id == party_id).one()
        return jsonify({
            "ok": True,
            "entry": entry_to_dict(entry),
            "new_balance": float(p.balance),
        })
    finally:
        db.close()


# ── DELETE ENTRY ──────────────────────────────────────────────────────────────

@ledger_bp.route("/<int:entry_id>", methods=["DELETE"])
@require_auth
def delete_entry(entry_id):
    db = SessionLocal()
    try:
        entry = db.query(LedgerEntry).filter(LedgerEntry.id == entry_id).one_or_none()
        if entry is None:
            return jsonify({"error": "Entry not found"}), 404

        # Deleting a sale entry linked to an invoice — cancel invoice too
        if entry.invoice_id and entry.entry_type == "sale":
            from database import Invoice
            inv = db.query(Invoice).filter(Invoice.id == entry.invoice_id).one_or_none()
            if inv:
                inv.is_cancelled = True

        # ISSUE 5: clean up any InvoiceAdjustment links that reference this
        # entry, on either side — as the original payment being adjusted,
        # or as the generated adjustment entry itself — so no orphaned
        # adjustment record is left pointing at a deleted ledger row.
        from database import InvoiceAdjustment
        linked = (
            db.query(InvoiceAdjustment)
            .filter(
                (InvoiceAdjustment.payment_ledger_entry_id == entry_id)
                | (InvoiceAdjustment.adjustment_ledger_entry_id == entry_id)
            )
            .all()
        )
        for link in linked:
            db.delete(link)

        party_id = entry.party_id

        db.delete(entry)
        db.flush()

        recalculate_customer_ledger(party_id, db)

        db.commit()
        p = db.query(Party).filter(Party.id == party_id).one()
        return jsonify({"ok": True, "new_balance": float(p.balance)})
    finally:
        db.close()


# ── MONTHLY SUMMARY (for charts) ─────────────────────────────────────────────

@ledger_bp.route("/monthly-summary", methods=["GET"])
@require_auth
def monthly_summary():
    from sqlalchemy import func, extract
    party_type = request.args.get("type", "customer")
    year       = int(request.args.get("year", date.today().year))

    db = SessionLocal()
    try:
        # Monthly sales
        sales = (
            db.query(
                extract("month", LedgerEntry.entry_date).label("month"),
                func.coalesce(func.sum(LedgerEntry.debit), 0).label("total")
            )
            .join(Party, Party.id == LedgerEntry.party_id)
            .filter(
                Party.party_type == party_type,
                LedgerEntry.entry_type == "sale",
                extract("year", LedgerEntry.entry_date) == year,
            )
            .group_by("month")
            .all()
        )

        # Monthly collections
        collections = (
            db.query(
                extract("month", LedgerEntry.entry_date).label("month"),
                func.coalesce(func.sum(LedgerEntry.credit), 0).label("total")
            )
            .join(Party, Party.id == LedgerEntry.party_id)
            .filter(
                Party.party_type == party_type,
                LedgerEntry.entry_type == "payment",
                extract("year", LedgerEntry.entry_date) == year,
            )
            .group_by("month")
            .all()
        )

        sales_map = {int(r.month): float(r.total) for r in sales}
        coll_map  = {int(r.month): float(r.total) for r in collections}

        months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        return jsonify({
            "year": year,
            "months": months,
            "sales":       [sales_map.get(i, 0) for i in range(1, 13)],
            "collections": [coll_map.get(i, 0)  for i in range(1, 13)],
        })
    finally:
        db.close()


# ── RECENT TRANSACTIONS ───────────────────────────────────────────────────────

@ledger_bp.route("/recent", methods=["GET"])
@require_auth
def recent_transactions():
    party_type = request.args.get("type", "customer")
    limit = min(int(request.args.get("limit", 20)), 100)

    db = SessionLocal()
    try:
        entries = (
            db.query(LedgerEntry)
            .join(Party, Party.id == LedgerEntry.party_id)
            .filter(Party.party_type == party_type)
            .order_by(LedgerEntry.entry_date.desc(), LedgerEntry.id.desc())
            .limit(limit)
            .all()
        )
        result = []
        for e in entries:
            d_dict = entry_to_dict(e)
            d_dict["party_name"] = e.party.name if e.party else ""
            result.append(d_dict)
        return jsonify(result)
    finally:
        db.close()
