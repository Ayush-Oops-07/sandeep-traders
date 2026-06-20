"""
blueprints/auth.py — Authentication routes.
"""

import os
import hashlib
from datetime import datetime
from functools import wraps

from flask import Blueprint, jsonify, request, session
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from database import SessionLocal, User

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# Boot token: derived from SECRET_KEY so all gunicorn workers share the same
# value. Using a random uuid4() caused login failures with multiple workers
# because each worker got a different token and would immediately reject
# sessions created by another worker.
_secret = os.getenv("SECRET_KEY", "st-super-secret-change-in-prod")
BOOT_TOKEN = hashlib.sha256(_secret.encode()).hexdigest()[:32]


# ── DECORATOR ─────────────────────────────────────────────────────────────────

def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Unauthorized"}), 401
        if session.get("boot_token") != BOOT_TOKEN:
            session.clear()
            return jsonify({"error": "Session expired"}), 401
        return fn(*args, **kwargs)
    return wrapper


# ── ROUTES ────────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    db = SessionLocal()
    try:
        user = db.query(User).filter(func.lower(User.username) == username).one_or_none()
        if user is None or not user.is_active:
            return jsonify({"error": "Invalid credentials"}), 401
        if not check_password_hash(user.password_hash, password):
            return jsonify({"error": "Invalid credentials"}), 401

        session.clear()
        session["user_id"]    = user.id
        session["username"]   = user.username
        session["full_name"]  = user.full_name
        session["role"]       = user.role
        session["boot_token"] = BOOT_TOKEN
        session.permanent     = False  # session dies when browser closes

        user.last_login = datetime.utcnow()
        db.commit()

        return jsonify({
            "ok": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "role": user.role,
            }
        })
    finally:
        db.close()


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@auth_bp.route("/me")
def me():
    if "user_id" not in session:
        return jsonify({"authenticated": False})
    if session.get("boot_token") != BOOT_TOKEN:
        session.clear()
        return jsonify({"authenticated": False})
    return jsonify({
        "authenticated": True,
        "user": {
            "id": session["user_id"],
            "username": session["username"],
            "full_name": session.get("full_name", ""),
            "role": session.get("role", "staff"),
        }
    })


@auth_bp.route("/change-password", methods=["POST"])
@require_auth
def change_password():
    data = request.get_json(force=True, silent=True) or {}
    old_pw = data.get("old_password") or ""
    new_pw = data.get("new_password") or ""

    if len(new_pw) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).one()
        if not check_password_hash(user.password_hash, old_pw):
            return jsonify({"error": "Current password incorrect"}), 401
        user.password_hash = generate_password_hash(new_pw)
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()
