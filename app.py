"""
app.py — Sandeep Traders Business Suite — Flask Application Entry Point.
Configured for Render.com deployment with PostgreSQL.
"""

import os
import logging
from datetime import datetime

from flask import Flask, render_template, jsonify
from werkzeug.security import generate_password_hash

from database import init_db, SessionLocal, User, Product

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("sandeep-traders")

# ── APP FACTORY ───────────────────────────────────────────────────────────────

def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    app.secret_key = os.getenv("SECRET_KEY", "st-super-secret-change-in-prod")
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # Secure cookies on HTTPS (Render always HTTPS)
    # Only send session cookies over HTTPS.
    # On Render (FLASK_ENV=production) this is correct — all traffic is HTTPS.
    # Locally (no FLASK_ENV set, or set to "development") keep it False so the
    # browser doesn't silently drop the cookie over plain HTTP.
    app.config["SESSION_COOKIE_SECURE"] = os.getenv("FLASK_ENV", "development") == "production"

    # ── BLUEPRINTS ─────────────────────────────────────────────────────────────
    from blueprints.auth        import auth_bp
    from blueprints.parties     import parties_bp
    from blueprints.ledger      import ledger_bp
    from blueprints.invoices    import invoices_bp
    from blueprints.dashboard   import dashboard_bp
    from blueprints.payments    import payments_bp
    from blueprints.adjustments import adjustments_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(parties_bp)
    app.register_blueprint(ledger_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(adjustments_bp)

    # ── ADMIN / MIGRATION ROUTES ───────────────────────────────────────────────
    @app.route("/api/admin/fix-products", methods=["POST"])
    def admin_fix_products():
        """
        One-time migration: ensures all default products exist for both
        party_type=customer and party_type=shoper.
        Call once after deployment: POST /api/admin/fix-products
        """
        from database import Product
        from sqlalchemy import text
        db = SessionLocal()
        added = 0
        try:
            # Fix NULL party_type → customer
            db.execute(text("UPDATE products SET party_type='customer' WHERE party_type IS NULL OR party_type = ''"))
            db.commit()

            # Seed missing products for each party_type
            for party_type in ("customer", "shoper"):
                existing_names = {r[0] for r in db.query(Product.name).filter(Product.party_type == party_type).all()}
                for name in DEFAULT_PRODUCTS:
                    if name not in existing_names:
                        db.add(Product(name=name, party_type=party_type))
                        added += 1
            db.commit()
            return jsonify({"ok": True, "products_added": added})
        except Exception as e:
            db.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()

    # ── FRONTEND ROUTES ────────────────────────────────────────────────────────
    @app.route("/")
    @app.route("/<path:path>")
    def index(path=None):
        return render_template("index.html")

    @app.route("/favicon.ico")
    def favicon():
        return "", 204

    # ── ERROR HANDLERS ─────────────────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"error": "Method not allowed"}), 405

    @app.errorhandler(Exception)
    def handle_exception(e):
        logger.exception("Unhandled exception: %s", e)
        return jsonify({"error": "Internal server error", "detail": str(e)}), 500

    return app


# ── SEED DATA ─────────────────────────────────────────────────────────────────

DEFAULT_USERS = [
    ("admin",   "Ayush@841440",  "Admin",   "admin"),
    ("mandeep", "Thawe@841440",  "Mandeep", "staff"),
    ("sandeep", "Thawe@841440",  "Sandeep", "owner"),
]

DEFAULT_PRODUCTS = [
    "NUVOCO CEMENT", "NUVOCO UNO CEMENT", "DALMIA CEMENT", "KONARK CEMENT",
    "DSP CEMENT", "SATNA CEMENT", "UNIQUE CEMENT", "PRISM CEMENT",
    "BALMUKUND TMT 8MM", "BALMUKUND TMT 10MM", "BALMUKUND TMT 12MM", "BALMUKUND TMT 16MM",
    "KAMDHENU TMT 8MM", "KAMDHENU TMT 10MM", "KAMDHENU TMT 12MM", "KAMDHENU TMT 16MM",
    "BALMUKUND TMT 10MM/12MM/16MM", "KAMDHENU TMT 10MM/12MM/16MM",
    "COIL", "TAR", "KATI", "TENT PIPE", "RING", "RING MAJDURI", "WATER PIPE",
    "KARKAT 8'", "KARKAT 6'", "KARKAT 10'", "KARKAT 12'",
    "TINA 8'", "TINA 10'", "TINA 12'",
    "BALU", "UJALA BALU", "G GITI", "P GITI", "JIRA GITI",
    "COVER BLOCK", "COVER BLOCK BORA",
    "DESIGN FOM 1 INCH", "DESIGN FOM 1.5 INCH", "DESIGN FOM 2 INCH",
    "FRIGHT", "POLDARI", "RETURN FRIGHT", "RETURN POLDARI",
    "TOTAL BACK DUE", "TOTAL PURJA", "GAMALA", "KATA BRUSH",
]


def seed_defaults():
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            for username, password, full_name, role in DEFAULT_USERS:
                db.add(User(
                    username      = username,
                    password_hash = generate_password_hash(password),
                    full_name     = full_name,
                    role          = role,
                ))
            db.commit()
            logger.info("Default users seeded.")

        # FIX: migrate any products with NULL party_type to 'customer' FIRST
        # (must run before count checks below)
        from sqlalchemy import text
        try:
            db.execute(text("UPDATE products SET party_type='customer' WHERE party_type IS NULL OR party_type = ''"))
            db.commit()
        except Exception:
            db.rollback()

        # Seed products for BOTH party types (customer + shoper)
        # Uses individual name checks so partial seeds are filled in correctly
        for party_type in ("customer", "shoper"):
            existing_names = {
                r[0] for r in db.query(Product.name)
                .filter(Product.party_type == party_type).all()
            }
            added = 0
            for name in DEFAULT_PRODUCTS:
                if name not in existing_names:
                    db.add(Product(
    name=name.strip().upper(),
    party_type=party_type,
    is_active=True
))
                    added += 1
            if added:
                db.commit()
                logger.info("Seeded %d products for party_type=%s.", added, party_type)

    except Exception as e:
        db.rollback()
        logger.error("Seed error: %s", e)
    finally:
        db.close()


# ── STARTUP ───────────────────────────────────────────────────────────────────

try:
    init_db()
    logger.info("Database initialized successfully")
except Exception as e:
    logger.exception("Database init failed: %s", e)

try:
    seed_defaults()
    logger.info("Default data seeded")
except Exception as e:
    logger.exception("Seed failed: %s", e)

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
