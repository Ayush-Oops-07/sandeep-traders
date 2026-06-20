"""
blueprints/parties.py
FULL FIXED VERSION
- Customer & Wholesale support
- Hard delete with cascade
- PostgreSQL safe
- Render production safe
"""

from flask import (
    Blueprint,
    jsonify,
    request,
    session
)

from sqlalchemy import or_

from database import (
    SessionLocal,
    Party
)

from utils.helpers import (
    party_to_dict,
    d,
    recalculate_customer_ledger,
    get_customer_ledger_summary
)

from blueprints.auth import require_auth

parties_bp = Blueprint(
    "parties",
    __name__,
    url_prefix="/api/parties"
)

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _get_type():

    return (
        request.args.get("type")
        or (
            request.get_json(
                silent=True
            ) or {}
        ).get("party_type")
        or "customer"
    )

# ─────────────────────────────────────────────────────────────
# LIST PARTIES
# ─────────────────────────────────────────────────────────────

@parties_bp.route("/", methods=["GET"])
@require_auth
def list_parties():

    party_type = (
        request.args.get("type")
        or "customer"
    ).strip().lower()

    q = (
        request.args.get("q")
        or ""
    ).strip()

    status = request.args.get("status")

    db = SessionLocal()

    try:

        query = db.query(Party).filter(
            Party.party_type == party_type,
            Party.is_active == True
        )

        if q:

            like = f"%{q}%"

            query = query.filter(
                or_(
                    Party.name.ilike(like),
                    Party.mobile.ilike(like)
                )
            )

        if status == "pending":

            query = query.filter(
                Party.balance > 0
            )

        elif status == "advance":

            query = query.filter(
                Party.balance < 0
            )

        elif status == "clear":

            query = query.filter(
                Party.balance == 0
            )

        parties = (
            query
            .order_by(Party.name.asc())
            .all()
        )

        return jsonify([
            party_to_dict(p)
            for p in parties
        ])

    finally:
        db.close()

# ─────────────────────────────────────────────────────────────
# GET SINGLE PARTY
# ─────────────────────────────────────────────────────────────

@parties_bp.route("/<int:pid>", methods=["GET"])
@require_auth
def get_party(pid):

    db = SessionLocal()

    try:

        party = (
            db.query(Party)
            .filter(Party.id == pid)
            .one_or_none()
        )

        if party is None:

            return jsonify({
                "error": "Not found"
            }), 404

        return jsonify(
            party_to_dict(party)
        )

    finally:
        db.close()

# ─────────────────────────────────────────────────────────────
# CREATE PARTY
# ─────────────────────────────────────────────────────────────

@parties_bp.route("/", methods=["POST"])
@require_auth
def create_party():

    data = request.get_json(
        force=True,
        silent=True
    ) or {}

    name = (
        data.get("name") or ""
    ).strip().upper()

    party_type = (
        data.get("party_type")
        or "customer"
    ).strip().lower()

    if not name:

        return jsonify({
            "error": "Name is required"
        }), 400

    if party_type not in [
        "customer",
        "shoper"
    ]:

        return jsonify({
            "error": "Invalid party_type"
        }), 400

    db = SessionLocal()

    try:

        opening = d(
            data.get("opening_balance") or 0
        )

        existing = (
            db.query(Party)
            .filter(
                Party.name == name,
                Party.party_type == party_type,
                Party.is_active == True
            )
            .first()
        )

        if existing:

            return jsonify({
                "error": "Party already exists"
            }), 409

        party = Party(

            party_type=party_type,

            name=name,

            mobile=(
                data.get("mobile") or ""
            ).strip() or None,

            mobile2=(
                data.get("mobile2") or ""
            ).strip() or None,

            address=(
                data.get("address") or ""
            ).strip() or None,

            city=(
                data.get("city") or ""
            ).strip() or None,

            gstin=(
                data.get("gstin") or ""
            ).strip() or None,

            email=(
                data.get("email") or ""
            ).strip() or None,

            opening_balance=opening,

            balance=opening,

            notes=(
                data.get("notes") or ""
            ).strip() or None,

            is_active=True
        )

        db.add(party)

        db.commit()

        db.refresh(party)

        return jsonify(
            party_to_dict(party)
        ), 201

    except Exception as e:

        db.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:
        db.close()

# ─────────────────────────────────────────────────────────────
# UPDATE PARTY
# ─────────────────────────────────────────────────────────────

@parties_bp.route("/<int:pid>", methods=["PUT"])
@require_auth
def update_party(pid):

    data = request.get_json(
        force=True,
        silent=True
    ) or {}

    db = SessionLocal()

    try:

        party = (
            db.query(Party)
            .filter(Party.id == pid)
            .one_or_none()
        )

        if party is None:

            return jsonify({
                "error": "Not found"
            }), 404

        if "name" in data:

            name = (
                data["name"] or ""
            ).strip().upper()

            if not name:

                return jsonify({
                    "error": "Name cannot be empty"
                }), 400

            party.name = name

        for field in [
            "mobile",
            "mobile2",
            "address",
            "city",
            "gstin",
            "email",
            "notes"
        ]:

            if field in data:

                setattr(
                    party,
                    field,
                    (
                        data[field] or ""
                    ).strip() or None
                )

        if "opening_balance" in data:

            old_opening = d(
                party.opening_balance or 0
            )

            new_opening = d(
                data["opening_balance"] or 0
            )

            if old_opening != new_opening:

                party.opening_balance = new_opening

                recalculate_customer_ledger(
                    pid,
                    db
                )

        db.commit()

        db.refresh(party)

        return jsonify(
            party_to_dict(party)
        )

    except Exception as e:

        db.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:
        db.close()

# ─────────────────────────────────────────────────────────────
# DELETE PARTY + ALL RELATED DATA
# ─────────────────────────────────────────────────────────────

@parties_bp.route("/<int:pid>", methods=["DELETE"])
@require_auth
def delete_party(pid):

    db = SessionLocal()

    try:

        party = (
            db.query(Party)
            .filter(Party.id == pid)
            .one_or_none()
        )

        if party is None:

            return jsonify({
                "error": "Party not found"
            }), 404

        # HARD DELETE
        # Automatically deletes:
        #
        # - invoices
        # - invoice items
        # - ledger entries
        # - transactions
        # - sales data

        db.delete(party)

        db.commit()

        return jsonify({

            "ok": True,

            "message": (
                "Party and all related "
                "transactions/invoices deleted successfully"
            )
        })

    except Exception as e:

        db.rollback()

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500

    finally:
        db.close()

# ─────────────────────────────────────────────────────────────
# CUSTOMER LEDGER SUMMARY (single source of truth for dashboard cards)
# Returns Total Sales / Total Payments Received / Total Payments Given /
# Outstanding / Advance / Current Balance — all derived purely from
# ledger_entries + opening_balance via recalculate_customer_ledger's
# underlying data, so these numbers can NEVER diverge from what the
# ledger table itself shows. Per the spec: "All dashboard cards must use
# ONE centralized ledger calculation source."
# ─────────────────────────────────────────────────────────────

@parties_bp.route("/<int:pid>/summary", methods=["GET"])
@require_auth
def get_party_summary(pid):

    db = SessionLocal()

    try:

        party = (
            db.query(Party)
            .filter(Party.id == pid)
            .one_or_none()
        )

        if party is None:
            return jsonify({"error": "Not found"}), 404

        # Always recalculate before reading, so the summary is guaranteed
        # fresh even if something else changed the ledger moments ago.
        recalculate_customer_ledger(pid, db)
        db.commit()

        summary = get_customer_ledger_summary(db, pid)
        summary["party"] = party_to_dict(party)

        return jsonify(summary)

    finally:
        db.close()

# ─────────────────────────────────────────────────────────────
# DASHBOARD STATS
# ─────────────────────────────────────────────────────────────

@parties_bp.route("/stats", methods=["GET"])
@require_auth
def party_stats():

    from sqlalchemy import func

    party_type = (
        request.args.get("type")
        or "customer"
    ).strip().lower()

    db = SessionLocal()

    try:

        base = db.query(Party).filter(
            Party.party_type == party_type,
            Party.is_active == True
        )

        total = base.count()

        pending_n = (
            base
            .filter(Party.balance > 0)
            .count()
        )

        advance_n = (
            base
            .filter(Party.balance < 0)
            .count()
        )

        clear_n = (
            base
            .filter(Party.balance == 0)
            .count()
        )

        total_pending = float(

            db.query(
                func.coalesce(
                    func.sum(Party.balance),
                    0
                )
            )
            .filter(
                Party.party_type == party_type,
                Party.is_active == True,
                Party.balance > 0
            )
            .scalar() or 0
        )

        total_advance = abs(float(

            db.query(
                func.coalesce(
                    func.sum(Party.balance),
                    0
                )
            )
            .filter(
                Party.party_type == party_type,
                Party.is_active == True,
                Party.balance < 0
            )
            .scalar() or 0
        ))

        net_outstanding = (
            total_pending -
            total_advance
        )

        top10 = (

            base
            .filter(Party.balance > 0)
            .order_by(Party.balance.desc())
            .limit(10)
            .all()
        )

        return jsonify({

            "total": total,

            "pending": pending_n,

            "advance": advance_n,

            "clear": clear_n,

            "total_pending_amount": total_pending,

            "total_advance_amount": total_advance,

            "net_outstanding": net_outstanding,

            "top_pending": [
                party_to_dict(p)
                for p in top10
            ]
        })

    finally:
        db.close()
