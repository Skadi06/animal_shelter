"""Staff-only routes for reviewing applications and managing animals."""

from flask import Blueprint, jsonify, request

from database import db
from shelter_helpers import clean_animal, insert_id, json_body, roles_required, upload_animal_photo

bp = Blueprint("admin", __name__)
# The route decorators connect staff URLs to functions below. @roles_required
# is another decorator: it checks the current account before the route runs.

@bp.get("/api/admin/applications")
@roles_required("staff", "administrator")
def admin_applications():
    """Give shelter staff the adoption and volunteer queues to review.

    The role decorator blocks visitors and volunteers. Adoption rows are joined
    with account and animal tables so staff see the applicant and animal names;
    volunteer rows already contain the contact details staff need.
    """
    with db() as conn:
        adoptions = conn.execute(
            """
            SELECT a.*, u.email AS account_email, an.name AS animal_name
            FROM adoptions a
            LEFT JOIN users u ON u.id = a.user_id
            LEFT JOIN animals an ON an.id = a.animal_id
            ORDER BY a.created_at DESC
            """
        ).fetchall()
        volunteers = conn.execute("SELECT * FROM volunteer_applications ORDER BY created_at DESC").fetchall()
    return jsonify(adoptions=[dict(r) for r in adoptions], volunteers=[dict(r) for r in volunteers])


@bp.patch("/api/admin/applications/<kind>/<int:item_id>")
@roles_required("staff", "administrator")
def update_application(kind, item_id):
    """Save a staff member's new status for one application.

    ``kind`` selects the adoption or volunteer table, and ``item_id`` identifies
    the row. Only the four status choices shown in the admin interface are
    accepted, preventing arbitrary table names or status values from being used.
    """
    table = {"adoption": "adoptions", "volunteer": "volunteer_applications"}.get(kind)
    status = json_body().get("status")
    if not table or status not in {"Submitted", "In Review", "Approved", "Declined"}:
        return jsonify(error="Invalid application type or status."), 400
    with db() as conn:
        conn.execute(f"UPDATE {table} SET status=? WHERE id=?", (status, item_id))
    return jsonify(ok=True)


@bp.get("/api/admin/messages")
@roles_required("staff", "administrator")
def admin_messages():
    """Return customer questions for staff to answer."""
    with db() as conn:
        rows = conn.execute("SELECT m.*, a.name AS animal_name FROM messages m LEFT JOIN animals a ON a.id=m.animal_id ORDER BY m.created_at DESC").fetchall()
    return jsonify(messages=[dict(row) for row in rows])


@bp.patch("/api/admin/messages/<int:message_id>")
@roles_required("staff", "administrator")
def reply_message(message_id):
    """Save a staff response to a customer question."""
    reply = json_body().get("reply", "").strip()
    with db() as conn:
        conn.execute("UPDATE messages SET reply=? WHERE id=?", (reply, message_id))
    return jsonify(ok=True)


@bp.route("/api/admin/animals", defaults={"animal_id": None}, methods=["POST"])
@bp.route("/api/admin/animals/<int:animal_id>", methods=["PUT", "DELETE"])
@roles_required("staff", "administrator")
def manage_animal(animal_id):
    """Create, change, or delete an animal profile for shelter staff.

    POST creates a new animal, PUT changes an existing animal, and DELETE
    removes it. Create/edit forms use multipart data so a photo can be uploaded.
    If an edit does not include a replacement photo, the current photo stays.
    The role decorator permits only staff and administrator accounts.
    """
    # Preserve the current image on edits when no replacement is uploaded.
    with db() as conn:
        if request.method == "DELETE":
            conn.execute("DELETE FROM animals WHERE id=?", (animal_id,))
            return jsonify(ok=True)
        data = request.form.to_dict() if request.mimetype == "multipart/form-data" else json_body()
        animal = clean_animal(data)
        photo = request.files.get("photo_upload")
        if photo and photo.filename:
            try:
                animal["photo"] = upload_animal_photo(photo)
            except ValueError as error:
                return jsonify(error=str(error)), 400
        elif request.method == "PUT":
            previous = conn.execute("SELECT photo FROM animals WHERE id=?", (animal_id,)).fetchone()
            if previous and not animal["photo"]:
                animal["photo"] = previous["photo"]
        if not animal["name"]:
            return jsonify(error="Animal name is required."), 400
        if animal["status"] not in {"Available", "Pending", "Adopted"}:
            return jsonify(error="Choose an adoption status."), 400
        if request.method == "POST":
            keys = tuple(animal)
            placeholders = ",".join("?" for _ in keys)
            item_id = insert_id(conn, f"INSERT INTO animals ({','.join(keys)}) VALUES ({placeholders})", tuple(animal.values()))
            return jsonify(id=item_id), 201
        assignments = ",".join(f"{key}=?" for key in animal)
        conn.execute(f"UPDATE animals SET {assignments} WHERE id=?", (*animal.values(), animal_id))
        return jsonify(ok=True)



