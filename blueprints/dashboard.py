"""
blueprints/dashboard.py — Aggregated dashboard stats for Customer & Shoper modules.
"""

from datetime import date, timedelta
from flask import Blueprint, jsonify, request
from sqlalchemy import func, extract

from database import SessionLocal, Party, LedgerEntry, Invoice
from utils.helpers import party_to_dict, entry_to_dict
from blueprints.auth import require_auth

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


@dashboard_bp.route("/", methods=["GET"])
@require_auth
def get_dashboard():
    party_type = request.args.get("type", "customer")
    year       = int(request.args.get("year", date.today().year))
    db         = SessionLocal()

    try:
        # ── KPI STATS ──────────────────────────────────────────────────────────
        base_q = db.query(Party).filter(
            Party.party_type == party_type,
            Party.is_active == True
        )

        total_parties   = base_q.count()
        pending_count   = base_q.filter(Party.balance > 0).count()
        advance_count   = base_q.filter(Party.balance < 0).count()
        clear_count     = base_q.filter(Party.balance == 0).count()

        total_pending = float(
            db.query(func.coalesce(func.sum(Party.balance), 0))
            .filter(Party.party_type == party_type, Party.is_active == True, Party.balance > 0)
            .scalar() or 0
        )
        total_advance = abs(float(
            db.query(func.coalesce(func.sum(Party.balance), 0))
            .filter(Party.party_type == party_type, Party.is_active == True, Party.balance < 0)
            .scalar() or 0
        ))
        net_outstanding = total_pending - total_advance

        # ── TODAY SALES ────────────────────────────────────────────────────────
        today = date.today()
        today_sales = float(
            db.query(func.coalesce(func.sum(LedgerEntry.debit), 0))
            .join(Party, Party.id == LedgerEntry.party_id)
            .filter(
                Party.party_type == party_type,
                LedgerEntry.entry_type == "sale",
                LedgerEntry.entry_date == today,
            )
            .scalar() or 0
        )
        today_collections = float(
            db.query(func.coalesce(func.sum(LedgerEntry.credit), 0))
            .join(Party, Party.id == LedgerEntry.party_id)
            .filter(
                Party.party_type == party_type,
                LedgerEntry.entry_type.in_(("payment", "advance_received")),
                LedgerEntry.entry_date == today,
            )
            .scalar() or 0
        )

        # ── MONTHLY CHART DATA ─────────────────────────────────────────────────
        sales_rows = (
            db.query(
                extract("month", LedgerEntry.entry_date).label("m"),
                func.coalesce(func.sum(LedgerEntry.debit), 0).label("total")
            )
            .join(Party, Party.id == LedgerEntry.party_id)
            .filter(
                Party.party_type == party_type,
                LedgerEntry.entry_type == "sale",
                extract("year", LedgerEntry.entry_date) == year,
            )
            .group_by("m").all()
        )

        coll_rows = (
            db.query(
                extract("month", LedgerEntry.entry_date).label("m"),
                func.coalesce(func.sum(LedgerEntry.credit), 0).label("total")
            )
            .join(Party, Party.id == LedgerEntry.party_id)
            .filter(
                Party.party_type == party_type,
                LedgerEntry.entry_type.in_(("payment", "advance_received")),
                extract("year", LedgerEntry.entry_date) == year,
            )
            .group_by("m").all()
        )

        sales_map = {int(r.m): float(r.total) for r in sales_rows}
        coll_map  = {int(r.m): float(r.total) for r in coll_rows}
        months    = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        sales_arr = [sales_map.get(i, 0) for i in range(1, 13)]
        coll_arr  = [coll_map.get(i, 0)  for i in range(1, 13)]

        # ── TOP PENDING ────────────────────────────────────────────────────────
        top10 = (
            base_q.filter(Party.balance > 0)
            .order_by(Party.balance.desc())
            .limit(10)
            .all()
        )

        # ── RECENT TRANSACTIONS ────────────────────────────────────────────────
        recent = (
            db.query(LedgerEntry)
            .join(Party, Party.id == LedgerEntry.party_id)
            .filter(Party.party_type == party_type)
            .order_by(LedgerEntry.entry_date.desc(), LedgerEntry.id.desc())
            .limit(15)
            .all()
        )
        recent_list = []
        for e in recent:
            d_dict = entry_to_dict(e)
            d_dict["party_name"] = e.party.name if e.party else ""
            recent_list.append(d_dict)

        # ── PORTFOLIO DISTRIBUTION for donut chart ─────────────────────────────
        portfolio = {
            "pending": pending_count,
            "advance": advance_count,
            "clear":   clear_count,
        }

        return jsonify({
            "kpi": {
                "total_parties":   total_parties,
                "pending_count":   pending_count,
                "advance_count":   advance_count,
                "clear_count":     clear_count,
                "total_pending":   total_pending,
                "total_advance":   total_advance,
                "net_outstanding": net_outstanding,
                "today_sales":     today_sales,
                "today_collections": today_collections,
            },
            "charts": {
                "months": months,
                "sales": sales_arr,
                "collections": coll_arr,
            },
            "top_pending": [party_to_dict(p) for p in top10],
            "recent_transactions": recent_list,
            "portfolio": portfolio,
        })
    finally:
        db.close()
