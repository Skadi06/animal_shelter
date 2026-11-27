#Tom Gao, Dingzhen Yu
# Animal listing, filtering, detail, and favorites API routes.

from flask import Blueprint, jsonify, request, session

from database import db
from helpers import login_required

bp = Blueprint("animals", __name__)

@bp.get("/api/animals")
def list_animals():
    # Search the animal table and return one small page of matching results.
    #
    # Search, breed, and age fields can match part of the stored text. Gender is
    # an exact match so selecting Male cannot also match Female. Text matching
    # ignores capitalization. The response includes the current page, total
    # pages, and total results so the browser can build the paging controls.
    #
    filters = {key: request.args.get(key, "").strip() for key in ("search", "species", "breed", "age", "size", "gender", "status")}
    conditions, values = [], []
    for key, value in filters.items():
        if value:
            if key == "search":
                conditions.append("(LOWER(name) LIKE LOWER(?) OR LOWER(breed) LIKE LOWER(?) OR LOWER(description) LIKE LOWER(?))")
                values.extend([f"%{value}%"] * 3)
            elif key == "age":
                if value == "10+":
                    conditions.append("LOWER(age) ~ ?")
                    values.append(r"^(?:10\+(?:\s*years?(?:\s*old)?)?|(?:10|[1-9][0-9]+)(?:\s+years?(?:\s+old)?)?)$")
                elif value in {f"{month} month" if month == 1 else f"{month} months" for month in range(1, 12)}:
                    amount = value.split()[0]
                    conditions.append("LOWER(age) ~ ?")
                    values.append(rf"^{amount}\s+months?(?:\s+old)?$")
                elif value in {str(year) for year in range(1, 10)}:
                    conditions.append("LOWER(age) ~ ?")
                    values.append(rf"^{value}(?:\s+years?(?:\s+old)?)?$")
                else:
                    conditions.append("LOWER(age) = LOWER(?)")
                    values.append(value)
            elif key == "gender":
                conditions.append("LOWER(gender) = LOWER(?)")
                values.append(value)
            else:
                conditions.append(f"LOWER({key}) LIKE LOWER(?)")
                values.append(f"%{value}%")
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    page_size = 12
    page = max(1, request.args.get("page", 1, type=int) or 1)
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS total FROM animals{where}", values).fetchone()["total"]
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        animals = conn.execute(
            f"""SELECT animals.*,
                       EXISTS(SELECT 1 FROM adoptions a
                              WHERE a.animal_id=animals.id AND a.status IN ('In Review', 'Approved')) AS adoption_on_hold
                FROM animals{where} ORDER BY id DESC LIMIT ? OFFSET ?""",
            (*values, page_size, (page - 1) * page_size),
        ).fetchall()
    return jsonify(animals=[dict(row) for row in animals], page=page, pages=pages, total=total)

@bp.get("/api/animals/<int:animal_id>")
def animal_detail(animal_id):
    # Find one animal by its numeric ID and return every profile detail.
    #
    # The browser uses this when someone opens an animal's profile. If the ID
    # does not exist, return HTTP 404 so the browser knows there is no profile.
    #
    with db() as conn:
        animal = conn.execute(
            """SELECT animals.*,
                      EXISTS(SELECT 1 FROM adoptions a
                             WHERE a.animal_id=animals.id AND a.status IN ('In Review', 'Approved')) AS adoption_on_hold
               FROM animals WHERE id=?""",
            (animal_id,),
        ).fetchone()
    if not animal:
        return jsonify(error="Animal not found."), 404
    return jsonify(animal=dict(animal))

@bp.get("/api/animals/options")
def animal_options():
    # Return the short animal list used by the contact form dropdown.
    #
    # The form needs only each animal's ID (to connect the message to a record)
    # and name (the text the visitor sees), so the larger profile is not loaded.
    #
    with db() as conn:
        rows = conn.execute("SELECT id, name FROM animals ORDER BY name").fetchall()
    return jsonify(animals=[dict(row) for row in rows])

@bp.route("/api/favorites/<int:animal_id>", methods=["POST", "DELETE"])
@login_required
def favorite(animal_id):
    # Save or unsave one animal for the currently signed-in visitor.
    #
    # A POST request adds the relationship; a DELETE request removes it. The
    # database key prevents saving the same animal twice for one account.
    #
    with db() as conn:
        if request.method == "POST":
            conn.execute(
                "INSERT INTO favorites(user_id,animal_id) VALUES(?,?) ON CONFLICT (user_id,animal_id) DO NOTHING",
                (session["user_id"], animal_id),
            )
        else:
            conn.execute("DELETE FROM favorites WHERE user_id=? AND animal_id=?", (session["user_id"], animal_id))
    return jsonify(ok=True)

@bp.get("/api/favorites")
@login_required
def list_favorites():
    # Return all animal profiles the current account has saved.
    #
    # The SQL join connects the favorites table to animals, because favorites
    # stores only the two IDs while the website needs names, photos, and status.
    #
    with db() as conn:
        rows = conn.execute("SELECT a.* FROM animals a JOIN favorites f ON a.id=f.animal_id WHERE f.user_id=?", (session["user_id"],)).fetchall()
    return jsonify(animals=[dict(row) for row in rows])
