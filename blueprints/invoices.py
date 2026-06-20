"""
blueprints/invoices.py
FULL FIXED VERSION
- Product search fixed
- Invoice save fixed
- PostgreSQL safe
- Decimal safe
- Customer/Wholesale separate
- Render production safe
"""

import io
import logging

from datetime import date
from decimal import Decimal

from flask import (
    Blueprint,
    jsonify,
    request,
    session,
    send_file
)

from sqlalchemy import or_

from database import (
    SessionLocal,
    Invoice,
    InvoiceItem,
    LedgerEntry,
    Party,
    Product
)

from utils.helpers import (
    invoice_to_dict,
    entry_to_dict,
    d,
    parse_date,
    next_invoice_number,
    recalculate_from_entry,
    recalculate_party_balance,
    recalculate_customer_ledger
)

from blueprints.auth import require_auth

logger = logging.getLogger(
    "sandeep-traders.invoices"
)

invoices_bp = Blueprint(
    "invoices",
    __name__,
    url_prefix="/api/invoices"
)

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _calc_item_total(
    qty,
    rate,
    discount_pct,
    gst_pct
) -> Decimal:

    base = d(qty) * d(rate)

    after_discount = (
        base *
        (1 - d(discount_pct) / 100)
    )

    total = (
        after_discount *
        (1 + d(gst_pct) / 100)
    )

    return total

# ─────────────────────────────────────────────────────────────
# LIST INVOICES
# ─────────────────────────────────────────────────────────────

@invoices_bp.route("/", methods=["GET"])
@require_auth
def list_invoices():

    party_type = (
        request.args.get("type") or "customer"
    ).strip().lower()

    party_id = request.args.get("party_id")

    q = (
        request.args.get("q") or ""
    ).strip()

    page = max(
        1,
        int(request.args.get("page", 1))
    )

    per_page = min(
        50,
        int(request.args.get("per_page", 20))
    )

    db = SessionLocal()

    try:

        query = (
            db.query(Invoice)
            .join(
                Party,
                Party.id == Invoice.party_id
            )
            .filter(
                Invoice.party_type == party_type,
                Invoice.is_cancelled == False
            )
        )

        if party_id:
            query = query.filter(
                Invoice.party_id == int(party_id)
            )

        if q:

            like = f"%{q}%"

            query = query.filter(
                or_(
                    Invoice.invoice_number.ilike(like),
                    Party.name.ilike(like)
                )
            )

        total = query.count()

        invoices = (
            query
            .order_by(
                Invoice.invoice_date.desc(),
                Invoice.id.desc()
            )
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        return jsonify({
            "total": total,
            "page": page,
            "per_page": per_page,
            "invoices": [
                invoice_to_dict(inv)
                for inv in invoices
            ]
        })

    finally:
        db.close()

# ─────────────────────────────────────────────────────────────
# GET SINGLE
# ─────────────────────────────────────────────────────────────

@invoices_bp.route("/<int:inv_id>", methods=["GET"])
@require_auth
def get_invoice(inv_id):

    db = SessionLocal()

    try:

        inv = (
            db.query(Invoice)
            .filter(Invoice.id == inv_id)
            .one_or_none()
        )

        if inv is None:
            return jsonify({
                "error": "Invoice not found"
            }), 404

        return jsonify(
            invoice_to_dict(
                inv,
                include_items=True
            )
        )

    finally:
        db.close()

# ─────────────────────────────────────────────────────────────
# CREATE INVOICE
# ─────────────────────────────────────────────────────────────

@invoices_bp.route("/", methods=["POST"])
@require_auth
def create_invoice():

    data = request.get_json(
        force=True,
        silent=True
    ) or {}

    party_id = data.get("party_id")

    party_type = (
        data.get("party_type") or "customer"
    ).strip().lower()

    items_data = data.get("items", [])

    if not party_id:

        return jsonify({
            "error": "party_id required"
        }), 400

    if not items_data:

        return jsonify({
            "error": "At least one item required"
        }), 400

    db = SessionLocal()

    try:

        party = (
            db.query(Party)
            .filter(Party.id == party_id)
            .one_or_none()
        )

        if party is None:

            return jsonify({
                "error": "Party not found"
            }), 404

        inv_number = (
            data.get("invoice_number")
            or next_invoice_number(
                db,
                party_type
            )
        )

        inv_number = str(inv_number).strip()

        invoice_date = parse_date(
            data.get("invoice_date")
            or date.today().isoformat()
        )

        due_date = (
            parse_date(data["due_date"])
            if data.get("due_date")
            else None
        )

        invoice = Invoice(

            invoice_number=inv_number,

            party_id=party_id,

            party_type=party_type,

            invoice_date=invoice_date,

            due_date=due_date,

            notes=(
                data.get("notes") or ""
            ).strip() or None,

            created_by=session.get("user_id")
        )

        db.add(invoice)

        db.flush()

        subtotal = Decimal("0.00")
        discount_total = Decimal("0.00")
        gst_total = Decimal("0.00")
        # The grand total is ALWAYS the sum of each line's actual `total`
        # (whichever way that was derived) — this is what's truly billed.
        # subtotal/discount_total/gst_total below are purely an
        # informational breakdown for the invoice display and may not sum
        # exactly to invoice_total when a line's total was manually
        # overridden — that's expected and correct.
        invoice_total = Decimal("0.00")

        for item_d in items_data:

            # ISSUE 4: item_type drives whether this is a stock-tracked
            # product row or a free-text service/charge row.
            item_type = (
                item_d.get("item_type") or "inventory"
            ).strip().lower()

            if item_type not in ("inventory", "service"):
                item_type = "inventory"

            description = (
                item_d.get("product_name") or ""
            ).strip()

            if item_type == "inventory":
                description = description.upper()

            if not description:
                continue

            is_manual_total = bool(
                item_d.get("is_manual_total")
            )

            if item_type == "service":
                # Service/charge rows: no qty/rate/unit/GST requirement —
                # just a description and a directly-typed amount. Always
                # treated as a manually-entered total (there is no
                # qty*rate formula to derive it from).
                qty = Decimal("0.000")
                rate = Decimal("0.00")
                disc_pct = Decimal("0.00")
                gst_pct = Decimal("0.00")
                unit = None
                is_manual_total = True

                line_total = d(
                    item_d.get("amount")
                    if item_d.get("amount") is not None
                    else item_d.get("total")
                )

                base_amt = line_total
                disc_amt = Decimal("0.00")
                gst_amt = Decimal("0.00")

            else:
                qty = d(item_d.get("quantity") or 0)
                rate = d(item_d.get("rate") or 0)
                disc_pct = d(item_d.get("discount_pct") or 0)
                gst_pct = d(item_d.get("gst_pct") or 0)
                unit = (item_d.get("unit") or "").strip() or None

                auto_total = _calc_item_total(
                    qty, rate, disc_pct, gst_pct
                )

                if is_manual_total and item_d.get("total") is not None:
                    # User typed a final amount that overrides the
                    # qty*rate formula — respect it exactly as given.
                    line_total = d(item_d.get("total"))
                else:
                    line_total = auto_total
                    is_manual_total = False

                base_amt = qty * rate
                disc_amt = base_amt * disc_pct / 100
                gst_amt = (base_amt - disc_amt) * gst_pct / 100

            if line_total <= 0 and item_type == "service":
                continue
            if item_type == "inventory" and qty <= 0 and not is_manual_total:
                continue

            subtotal += base_amt
            discount_total += disc_amt
            gst_total += gst_amt
            invoice_total += line_total

            db.add(InvoiceItem(

                invoice_id=invoice.id,

                product_name=description,

                unit=unit,

                quantity=qty,

                rate=rate,

                discount_pct=disc_pct,

                gst_pct=gst_pct,

                total=line_total,

                item_type=item_type,

                is_manual_total=is_manual_total,
            ))

            # Service/charge lines never touch the product catalog or
            # stock — they are not inventory.
            if item_type != "inventory":
                continue

            existing_product = (
                db.query(Product)
                .filter(
                    Product.name == description,
                    Product.party_type == party_type
                )
                .first()
            )

            if not existing_product:

                db.add(Product(

                    name=description,

                    party_type=party_type,

                    default_unit=unit,

                    default_rate=rate,

                    is_active=True
                ))

            elif existing_product.stock_qty is not None:

                # Stock deduction ONLY for inventory items, and only for
                # products where stock is actually being tracked
                # (stock_qty is not NULL). Service items never reach here.
                existing_product.stock_qty = (
                    existing_product.stock_qty - qty
                )

        if invoice_total <= 0:
            db.rollback()
            return jsonify({"error": "Invoice total must be greater than zero"}), 400

        invoice.subtotal = subtotal
        invoice.discount_amount = discount_total
        invoice.gst_amount = gst_total
        invoice.total_amount = invoice_total

        db.flush()

        ledger_entry = LedgerEntry(

            party_id=party_id,

            entry_date=invoice_date,

            entry_type="sale",

            particulars=f"Invoice #{inv_number}",

            debit=invoice_total,

            credit=Decimal("0.00"),

            invoice_id=invoice.id,

            invoice_number=inv_number,

            created_by=session.get("user_id"),

            notes=None,

            payment_mode=None
        )

        db.add(ledger_entry)

        db.flush()

        recalculate_customer_ledger(
            party_id,
            db
        )

        db.commit()

        db.refresh(invoice)

        return jsonify({

            "ok": True,

            "invoice": invoice_to_dict(
                invoice,
                include_items=True
            ),

            "new_balance": float(
                party.balance or 0
            )
        }), 201

    except Exception as e:

        import traceback

        db.rollback()

        logger.exception(
            "CREATE INVOICE ERROR: %s",
            e
        )

        traceback.print_exc()

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500

    finally:
        db.close()

# ─────────────────────────────────────────────────────────────
# UPDATE / EDIT INVOICE
# Issue 2 requires recalculation whenever an invoice is edited
# (including when its date changes — a backdated correction).
# ─────────────────────────────────────────────────────────────

@invoices_bp.route("/<int:inv_id>", methods=["PUT"])
@require_auth
def update_invoice(inv_id):

    data = request.get_json(
        force=True,
        silent=True
    ) or {}

    db = SessionLocal()

    try:

        invoice = (
            db.query(Invoice)
            .filter(Invoice.id == inv_id)
            .one_or_none()
        )

        if invoice is None:
            return jsonify({"error": "Invoice not found"}), 404

        if invoice.is_cancelled:
            return jsonify({"error": "Cannot edit a cancelled invoice"}), 400

        party_id = invoice.party_id
        party_type = invoice.party_type

        # Allow re-pointing the invoice to a different party (rare, but
        # supported so the recalculation logic stays correct either way).
        new_party_id = data.get("party_id", party_id)

        if "invoice_date" in data and data["invoice_date"]:
            invoice.invoice_date = parse_date(data["invoice_date"])

        if "due_date" in data:
            invoice.due_date = (
                parse_date(data["due_date"]) if data["due_date"] else None
            )

        if "notes" in data:
            invoice.notes = (data.get("notes") or "").strip() or None

        # Replace items if provided (full replace — simplest & safest way to
        # keep subtotal/discount/gst/total consistent with the items list).
        items_data = data.get("items")
        if items_data is not None:

            if not items_data:
                return jsonify({"error": "At least one item required"}), 400

            # Remove old items
            for old_item in list(invoice.items):
                db.delete(old_item)
            db.flush()

            subtotal = Decimal("0.00")
            discount_total = Decimal("0.00")
            gst_total = Decimal("0.00")
            invoice_total = Decimal("0.00")

            for item_d in items_data:

                item_type = (item_d.get("item_type") or "inventory").strip().lower()
                if item_type not in ("inventory", "service"):
                    item_type = "inventory"

                description = (item_d.get("product_name") or "").strip()
                if item_type == "inventory":
                    description = description.upper()
                if not description:
                    continue

                is_manual_total = bool(item_d.get("is_manual_total"))

                if item_type == "service":
                    qty = Decimal("0.000")
                    rate = Decimal("0.00")
                    disc_pct = Decimal("0.00")
                    gst_pct = Decimal("0.00")
                    unit = None
                    is_manual_total = True
                    line_total = d(
                        item_d.get("amount") if item_d.get("amount") is not None
                        else item_d.get("total")
                    )
                    base_amt = line_total
                    disc_amt = Decimal("0.00")
                    gst_amt = Decimal("0.00")
                else:
                    qty = d(item_d.get("quantity") or 0)
                    rate = d(item_d.get("rate") or 0)
                    disc_pct = d(item_d.get("discount_pct") or 0)
                    gst_pct = d(item_d.get("gst_pct") or 0)
                    unit = (item_d.get("unit") or "").strip() or None

                    auto_total = _calc_item_total(qty, rate, disc_pct, gst_pct)
                    if is_manual_total and item_d.get("total") is not None:
                        line_total = d(item_d.get("total"))
                    else:
                        line_total = auto_total
                        is_manual_total = False

                    base_amt = qty * rate
                    disc_amt = base_amt * disc_pct / 100
                    gst_amt = (base_amt - disc_amt) * gst_pct / 100

                if line_total <= 0 and item_type == "service":
                    continue
                if item_type == "inventory" and qty <= 0 and not is_manual_total:
                    continue

                subtotal += base_amt
                discount_total += disc_amt
                gst_total += gst_amt
                invoice_total += line_total

                db.add(InvoiceItem(
                    invoice_id=invoice.id,
                    product_name=description,
                    unit=unit,
                    quantity=qty,
                    rate=rate,
                    discount_pct=disc_pct,
                    gst_pct=gst_pct,
                    total=line_total,
                    item_type=item_type,
                    is_manual_total=is_manual_total,
                ))

            if invoice_total <= 0:
                db.rollback()
                return jsonify({"error": "Invoice total must be greater than zero"}), 400

            invoice.subtotal = subtotal
            invoice.discount_amount = discount_total
            invoice.gst_amount = gst_total
            invoice.total_amount = invoice_total

        invoice.party_id = new_party_id

        db.flush()

        # Keep the mirrored ledger "sale" entry in sync with the invoice.
        ledger_entry = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.invoice_id == invoice.id)
            .one_or_none()
        )

        if ledger_entry:
            ledger_entry.party_id = invoice.party_id
            ledger_entry.entry_date = invoice.invoice_date
            ledger_entry.debit = invoice.total_amount
            ledger_entry.invoice_number = invoice.invoice_number
            ledger_entry.particulars = f"Invoice #{invoice.invoice_number}"
        else:
            # Defensive: recreate it if it was somehow missing.
            ledger_entry = LedgerEntry(
                party_id=invoice.party_id,
                entry_date=invoice.invoice_date,
                entry_type="sale",
                particulars=f"Invoice #{invoice.invoice_number}",
                debit=invoice.total_amount,
                credit=Decimal("0.00"),
                invoice_id=invoice.id,
                invoice_number=invoice.invoice_number,
                created_by=session.get("user_id"),
            )
            db.add(ledger_entry)

        db.flush()

        # Recalculate BOTH parties if the invoice moved between customers.
        recalculate_customer_ledger(invoice.party_id, db)
        if new_party_id != party_id:
            recalculate_customer_ledger(party_id, db)

        db.commit()
        db.refresh(invoice)

        party = db.query(Party).filter(Party.id == invoice.party_id).one()

        return jsonify({
            "ok": True,
            "invoice": invoice_to_dict(invoice, include_items=True),
            "new_balance": float(party.balance or 0),
        })

    except Exception as e:

        import traceback

        db.rollback()

        logger.exception("UPDATE INVOICE ERROR: %s", e)
        traceback.print_exc()

        return jsonify({"ok": False, "error": str(e)}), 500

    finally:
        db.close()

# ─────────────────────────────────────────────────────────────
# DELETE INVOICE
# Hard-deletes the invoice (and its mirrored ledger "sale" entry via
# the existing LedgerEntry.invoice_id SET NULL / explicit delete below),
# then recalculates the customer's ledger from scratch.
# ─────────────────────────────────────────────────────────────

@invoices_bp.route("/<int:inv_id>", methods=["DELETE"])
@require_auth
def delete_invoice(inv_id):

    db = SessionLocal()

    try:

        invoice = (
            db.query(Invoice)
            .filter(Invoice.id == inv_id)
            .one_or_none()
        )

        if invoice is None:
            return jsonify({"error": "Invoice not found"}), 404

        party_id = invoice.party_id

        ledger_entry = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.invoice_id == invoice.id)
            .one_or_none()
        )
        if ledger_entry:
            db.delete(ledger_entry)

        db.delete(invoice)
        db.flush()

        recalculate_customer_ledger(party_id, db)

        db.commit()

        party = db.query(Party).filter(Party.id == party_id).one()

        return jsonify({
            "ok": True,
            "new_balance": float(party.balance or 0),
        })

    except Exception as e:

        db.rollback()
        logger.exception("DELETE INVOICE ERROR: %s", e)

        return jsonify({"ok": False, "error": str(e)}), 500

    finally:
        db.close()

# ─────────────────────────────────────────────────────────────
# CANCEL INVOICE (soft — keeps the record, reverses the ledger effect)
# The frontend's "Cancel Invoice" button already calls this exact route;
# it previously did not exist on the backend (404). Implemented here as
# part of the Issue 2 fix since cancelling an invoice must also trigger a
# full ledger recalculation.
# ─────────────────────────────────────────────────────────────

@invoices_bp.route("/<int:inv_id>/cancel", methods=["POST"])
@require_auth
def cancel_invoice(inv_id):

    db = SessionLocal()

    try:

        invoice = (
            db.query(Invoice)
            .filter(Invoice.id == inv_id)
            .one_or_none()
        )

        if invoice is None:
            return jsonify({"error": "Invoice not found"}), 404

        if invoice.is_cancelled:
            return jsonify({"error": "Invoice already cancelled"}), 400

        party_id = invoice.party_id
        invoice.is_cancelled = True

        # Remove the mirrored ledger "sale" entry so the cancelled invoice
        # no longer affects the customer's balance, while keeping the
        # invoice record itself (for history/audit).
        ledger_entry = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.invoice_id == invoice.id)
            .one_or_none()
        )
        if ledger_entry:
            db.delete(ledger_entry)

        db.flush()

        recalculate_customer_ledger(party_id, db)

        db.commit()

        party = db.query(Party).filter(Party.id == party_id).one()

        return jsonify({
            "ok": True,
            "new_balance": float(party.balance or 0),
        })

    except Exception as e:

        db.rollback()
        logger.exception("CANCEL INVOICE ERROR: %s", e)

        return jsonify({"ok": False, "error": str(e)}), 500

    finally:
        db.close()

# ─────────────────────────────────────────────────────────────
# PRODUCTS AUTOCOMPLETE
# ─────────────────────────────────────────────────────────────

@invoices_bp.route("/products", methods=["GET"])
@require_auth
def list_products():

    q = (
        request.args.get("q") or ""
    ).strip().upper()

    party_type = (
        request.args.get("party_type") or "customer"
    ).strip().lower()

    db = SessionLocal()

    try:

        query = db.query(Product).filter(
            Product.is_active == True
        )

        if party_type in [
            "customer",
            "shoper"
        ]:

            query = query.filter(
                Product.party_type == party_type
            )

        else:

            query = query.filter(
                Product.party_type == "customer"
            )

        if q:

            query = query.filter(
                Product.name.ilike(f"%{q}%")
            )

        products = (
            query
            .order_by(Product.name.asc())
            .limit(50)
            .all()
        )

        result = []

        for p in products:

            result.append({

                "id": p.id,

                "name": p.name or "",

                "default_unit": (
                    p.default_unit or ""
                ),

                "default_rate": float(
                    p.default_rate or 0
                ),

                "stock_qty": (
                    float(p.stock_qty)
                    if p.stock_qty is not None
                    else None
                ),

                "party_type": p.party_type
            })

        return jsonify(result)

    except Exception as e:

        logger.exception(
            "PRODUCT SEARCH ERROR: %s",
            e
        )

        return jsonify([]), 200

    finally:
        db.close()

# ─────────────────────────────────────────────────────────────
# ADD PRODUCT
# ─────────────────────────────────────────────────────────────

@invoices_bp.route("/products", methods=["POST"])
@require_auth
def add_product():

    data = request.get_json(
        force=True,
        silent=True
    ) or {}

    name = (
        data.get("name") or ""
    ).strip().upper()

    party_type = (
        data.get("party_type") or "customer"
    ).strip().lower()

    if not name:

        return jsonify({
            "error": "Name required"
        }), 400

    db = SessionLocal()

    try:

        existing = (
            db.query(Product)
            .filter(
                Product.name == name,
                Product.party_type == party_type
            )
            .first()
        )

        if existing:

            return jsonify({
                "error": "Product already exists"
            }), 409

        p = Product(

            name=name,

            party_type=party_type,

            default_unit=(
                data.get("default_unit") or ""
            ).strip() or None,

            default_rate=d(
                data.get("default_rate") or 0
            ),

            is_active=True
        )

        db.add(p)

        db.commit()

        db.refresh(p)

        return jsonify({
            "id": p.id,
            "name": p.name
        }), 201

    finally:
        db.close()

# ─────────────────────────────────────────────────────────────
# DELETE PRODUCT
# ─────────────────────────────────────────────────────────────

@invoices_bp.route("/products/<int:pid>", methods=["DELETE"])
@require_auth
def delete_product(pid):

    db = SessionLocal()

    try:

        p = (
            db.query(Product)
            .filter(Product.id == pid)
            .one_or_none()
        )

        if p is None:

            return jsonify({
                "error": "Not found"
            }), 404

        p.is_active = False

        db.commit()

        return jsonify({
            "ok": True
        })

    finally:
        db.close()
