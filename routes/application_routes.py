"""Adoption, volunteer, and contact API routes."""

from flask import Blueprint, jsonify, request, session

from database import db
from shelter_helpers import current_user, insert_id, json_body, login_required

bp = Blueprint("applications", __name__)
# These route decorators connect the form-related URLs to the functions below.

@bp.route("/api/applications", methods=["GET", "POST"])
@login_required
def applications():
    """Show this account's adoption applications or submit a new one.

    GET loads the signed-in account's application history for My Account. POST
    reads the form fields, checks the required answers, saves a new application,
    and returns its ID and initial Submitted status to the browser.
    """
    if request.method == "GET":
        with db() as conn:
            rows = conn.execute(
                """
                SELECT a.*, animal.name AS animal_name, animal.status AS adoption_status
                FROM adoptions a
                LEFT JOIN animals animal ON animal.id = a.animal_id
                WHERE a.user_id = ?
                ORDER BY a.created_at DESC
                """,
                (session["user_id"],),
            ).fetchall()
        return jsonify(applications=[dict(row) for row in rows])
    data, user = json_body(), current_user()
    required = ("animal_id", "name", "email", "phone", "housing", "experience")
    if any(not data.get(field) for field in required):
        return jsonify(error="Please complete all required application fields."), 400
    with db() as conn:
        item_id = insert_id(
            conn,
            """
            INSERT INTO adoptions
                (user_id, animal_id, name, email, phone, housing, other_pets, experience)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"], data["animal_id"], data["name"], data["email"],
                data["phone"], data["housing"], data.get("other_pets", ""),
                data["experience"],
            ),
        )
    return jsonify(id=item_id, status="Submitted"), 201


@bp.get("/api/opportunities")
def opportunities():
    """Return the volunteer roles and schedules displayed on the Help section."""
    with db() as conn:
        rows = conn.execute("SELECT * FROM opportunities ORDER BY id").fetchall()
    return jsonify(opportunities=[dict(row) for row in rows])


@bp.post("/api/volunteers")
def volunteer_apply():
    """Save a visitor's volunteer form as an application for staff to review.

    Visitors may apply without signing in, so ``user_id`` is empty for them.
    If a visitor is signed in, their account ID is attached to the application.
    Name, email, and availability must be present before a row is saved.
    """
    data, user = json_body(), current_user()
    if not data.get("name") or not data.get("email") or not data.get("availability"):
        return jsonify(error="Name, email, and availability are required."), 400
    with db() as conn:
        item_id = insert_id(
            conn,
            """
            INSERT INTO volunteer_applications
                (user_id, name, email, phone, interests, availability, experience)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"] if user else None, data["name"], data["email"],
                data.get("phone", ""), data.get("interests", ""),
                data.get("availability", ""), data.get("experience", ""),
            ),
        )
    return jsonify(id=item_id, status="Submitted"), 201


@bp.post("/api/contact")
def contact():
    """Save a message from the contact form for the shelter to follow up on.

    The animal ID is optional: an empty selection means the message is general,
    while a selected animal links the question to that animal's database row.
    """
    data, user = json_body(), current_user()
    if user:
        data["name"], data["email"] = user["name"], user["email"]
    if not data.get("name") or not data.get("email") or not data.get("message"):
        return jsonify(error="Please enter your name, email, and message."), 400
    with db() as conn:
        conn.execute("INSERT INTO messages(user_id,name,email,animal_id,message) VALUES(?,?,?,?,?)", (user["id"] if user else None, data["name"], data["email"], data.get("animal_id") or None, data["message"]))
    return jsonify(message="Your message has been sent."), 201


@bp.get("/api/messages")
@login_required
def my_messages():
    """Return the signed-in user's questions and staff replies."""
    with db() as conn:
        rows = conn.execute("SELECT m.*, a.name AS animal_name FROM messages m LEFT JOIN animals a ON a.id=m.animal_id WHERE m.user_id=? ORDER BY m.created_at DESC", (session["user_id"],)).fetchall()
    return jsonify(messages=[dict(row) for row in rows])



