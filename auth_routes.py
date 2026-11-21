"""Registration, login, session, and profile API routes."""

import sqlite3

from flask import Blueprint, jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

from database import db
from shelter_helpers import ROLES, current_user, insert_id, json_body, login_required

bp = Blueprint("auth", __name__)
# The @bp.post/get/patch lines below are decorators: they tell Flask which URL
# and HTTP method should call each function. bp is this file's route collection.

@bp.post("/api/register")
def register():
    """Create a new account from the registration form.

    The browser sends an email, password, name, and requested role as JSON.
    The password is turned into a one-way hash before it is saved, so the
    database does not store the password text itself. On success, the new
    account is signed in immediately and its public profile is returned.
    """
    data = json_body()
    # Normalize email so capitalization and extra spaces do not create separate accounts.
    email, password = data.get("email", "").strip().lower(), data.get("password", "")
    role = data.get("role", "volunteer")
    if not email or len(password) < 8 or role not in ROLES:
        return jsonify(error="Enter an email, a password of at least 8 characters, and a valid role."), 400
    try:
        with db() as conn:
            # Hash the password before saving it; then save the chosen role and name.
            user_id = insert_id(conn, "INSERT INTO users(email,password,role,name) VALUES(?,?,?,?)", (email, generate_password_hash(password), role, data.get("name", "")))
    except Exception as error:
        if isinstance(error, sqlite3.IntegrityError) or "unique" in str(error).lower():
            return jsonify(error="An account with that email already exists."), 409
        raise
    session["user_id"] = user_id
    return jsonify(user=current_user())


@bp.post("/api/login")
def login():
    """Sign in an existing account using the submitted email and password.

    The email is normalized just like it is during registration. The stored
    password hash is checked against the submitted password; when it matches,
    the account ID is put in the browser session for later requests.
    """
    data = json_body()
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=?", (data.get("email", "").strip().lower(),)).fetchone()
    if not user or not check_password_hash(user["password"], data.get("password", "")):
        return jsonify(error="Email or password is incorrect."), 401
    session["user_id"] = user["id"]
    return jsonify(user=current_user())


@bp.post("/api/logout")
def logout():
    """Forget which account is signed in by clearing the session cookie data."""
    session.clear()
    return jsonify(ok=True)


@bp.get("/api/me")
def me():
    """Let the browser check whether this visitor has an active login session."""
    return jsonify(user=current_user())


@bp.patch("/api/profile")
@login_required
def update_profile():
    """Save changes to the signed-in user's personal profile.

    The login decorator runs before this function. Only the listed profile
    fields are accepted; email, password, role, and account ID cannot be
    changed through this route. If no field was sent, nothing is updated.
    """
    data = json_body()
    allowed = ("name", "phone", "address", "experience", "pets")
    # Build a dictionary containing only fields the account owner may edit.
    fields = {key: data[key] for key in allowed if key in data}
    if fields:
        sql = ",".join(f"{key}=?" for key in fields)
        with db() as conn:
            conn.execute(f"UPDATE users SET {sql} WHERE id=?", (*fields.values(), session["user_id"]))
    return jsonify(user=current_user())



