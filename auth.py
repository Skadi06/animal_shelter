#Tom Gao, Dingzhen Yu
# Registration, login, session, and profile API routes.

from flask import Blueprint, jsonify, session

from database import db
from helpers import current_user, insert_id, json_body, login_required

bp = Blueprint("auth", __name__)

@bp.post("/api/register")
def register():
    # Create a new account from the registration form.
    #
    # The browser sends an email, password, and name. Public registration always
    # creates a regular user; privileged roles are assigned in the database.
    # The password is saved as submitted. On success, the new account is signed
    # in immediately and its public profile is returned.
    #
    data = json_body()
    email, password = data.get("email", "").strip().lower(), data.get("password", "")
    if not email or len(password) < 8:
        return jsonify(error="Enter an email and a password of at least 8 characters."), 400
    try:
        with db() as conn:
            user_id = insert_id(conn, "INSERT INTO users(email,password,role,name) VALUES(?,?,?,?)", (email, password, "user", data.get("name", "")))
    except Exception as error:
        if "unique" in str(error).lower():
            return jsonify(error="An account with that email already exists."), 409
        raise
    session["user_id"] = user_id
    return jsonify(user=current_user())

@bp.post("/api/login")
def login():
    # Sign in an existing account using the submitted email and password.
    #
    # Compare the submitted password with the value stored for this account.
    #
    data = json_body()
    password = data.get("password", "")
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=?", (data.get("email", "").strip().lower(),)).fetchone()
        password_matches = user and user["password"] == password
    if not user or not password_matches:
        return jsonify(error="Email or password is incorrect."), 401
    session["user_id"] = user["id"]
    return jsonify(user=current_user())

@bp.post("/api/logout")
def logout():
    # Forget which account is signed in by clearing the session cookie data.
    session.clear()
    return jsonify(ok=True)

@bp.get("/api/me")
def me():
    # Let the browser check whether this visitor has an active login session.
    return jsonify(user=current_user())

@bp.patch("/api/profile")
@login_required
def update_profile():
    # Save changes to the signed-in user's personal profile.
    #
    # The login decorator runs before this function. Only the listed profile
    # fields are accepted; email, password, role, and account ID cannot be
    # changed through this route. If no field was sent, nothing is updated.
    #
    data = json_body()
    allowed = ("name", "phone", "address", "experience", "pets")
    fields = {key: data[key] for key in allowed if key in data}
    if fields:
        sql = ",".join(f"{key}=?" for key in fields)
        with db() as conn:
            conn.execute(f"UPDATE users SET {sql} WHERE id=?", (*fields.values(), session["user_id"]))
    return jsonify(user=current_user())
