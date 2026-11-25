# Adoption, volunteer, and contact API routes.

from flask import Blueprint, jsonify, request, session

from database import db
from helpers import current_user, insert_id, json_body, login_required

bp = Blueprint("applications", __name__)

@bp.route("/api/applications", methods=["GET", "POST"])
@login_required
def applications():
    # Show this account's adoption applications or submit a new one.
    #
    # GET loads the signed-in account's application history for My Account. POST
    # reads the form fields, checks the required answers, saves a new application,
    # and returns its ID and initial In Review status to the browser.
    #
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
            volunteer_rows = conn.execute(
                "SELECT * FROM volunteer_applications WHERE user_id=? ORDER BY created_at DESC",
                (session["user_id"],),
            ).fetchall()
        return jsonify(
            applications=[dict(row) for row in rows],
            volunteer_applications=[dict(row) for row in volunteer_rows],
        )
    data, user = json_body(), current_user()
    required = ("animal_id", "name", "email", "phone", "housing", "experience")
    if any(not data.get(field) for field in required):
        return jsonify(error="Please complete all required application fields."), 400
    with db() as conn:
        animal = conn.execute(
            """SELECT status,
                      EXISTS(SELECT 1 FROM adoptions a
                             WHERE a.animal_id=animals.id AND a.status IN ('In Review', 'Approved')) AS adoption_on_hold
               FROM animals WHERE id=?""",
            (data["animal_id"],),
        ).fetchone()
        if not animal or animal["status"] != "Available":
            return jsonify(error="This animal is not currently available for adoption."), 409
        if animal["adoption_on_hold"]:
            return jsonify(error="This animal already has an application in review or approved."), 409
        item_id = insert_id(
            conn,
            """
            INSERT INTO adoptions
                (user_id, animal_id, name, email, phone, housing, other_pets, experience, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'In Review')
            """,
            (
                user["id"], data["animal_id"], data["name"], data["email"],
                data["phone"], data["housing"], data.get("other_pets", ""),
                data["experience"],
            ),
        )
        conn.execute("UPDATE animals SET status='Pending' WHERE id=?", (data["animal_id"],))
    return jsonify(id=item_id, status="In Review"), 201

@bp.get("/api/opportunities")
def opportunities():
    # Return the volunteer roles and schedules displayed on the Help section.
    with db() as conn:
        rows = conn.execute("SELECT * FROM opportunities ORDER BY id").fetchall()
    return jsonify(opportunities=[dict(row) for row in rows])

@bp.post("/api/volunteers")
@login_required
def volunteer_apply():
    # Save a signed-in user's volunteer application for staff to review.
    #
    # Contact identity and user ID come from the authenticated account, so every
    # submission is linked to the account that can track its status.
    #
    data, user = json_body(), current_user()
    if not data.get("availability"):
        return jsonify(error="Please enter your availability."), 400
    with db() as conn:
        item_id = insert_id(
            conn,
            """
            INSERT INTO volunteer_applications
                (user_id, name, email, phone, interests, availability, experience)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"], user["name"], user["email"],
                user.get("phone", ""), data.get("interests", ""),
                data.get("availability", ""), data.get("experience", ""),
            ),
        )
    return jsonify(id=item_id, status="Submitted"), 201

@bp.post("/api/contact")
@login_required
def contact():
    # Save a signed-in user's question for the shelter to follow up on.
    #
    # The animal ID is optional: an empty selection means the message is general,
    # while a selected animal links the question to that animal's database row.
    #
    data, user = json_body(), current_user()
    if not data.get("message"):
        return jsonify(error="Please enter a message."), 400
    data["name"], data["email"] = user["name"], user["email"]
    with db() as conn:
        conn.execute("INSERT INTO messages(user_id,name,email,animal_id,message) VALUES(?,?,?,?,?)", (user["id"] if user else None, data["name"], data["email"], data.get("animal_id") or None, data["message"]))
    return jsonify(message="Your message has been sent."), 201

@bp.get("/api/messages")
@login_required
def my_messages():
    # Return the signed-in user's questions and staff replies.
    with db() as conn:
        rows = conn.execute("SELECT m.*, a.name AS animal_name FROM messages m LEFT JOIN animals a ON a.id=m.animal_id WHERE m.user_id=? ORDER BY m.created_at DESC", (session["user_id"],)).fetchall()
    return jsonify(messages=[dict(row) for row in rows])
