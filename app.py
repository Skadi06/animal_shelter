from pathlib import Path
import os
import sqlite3
from functools import wraps
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import Flask, jsonify, request, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "local-shelter-demo-key"
ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "shelter.db"
# Supabase's Vercel integration provides POSTGRES_URL; DATABASE_URL also works.
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
_db_ready = False
ROLES = {"volunteer", "staff", "administrator"}
ANIMAL_FIELDS = ("name", "species", "breed", "age", "gender", "size", "description", "status", "photo", "vaccinated", "spayed_neutered", "dietary_needs", "behavior", "special_care")


@app.before_request
def check_vercel_database():
    global _db_ready
    # Return useful API messages instead of crashing during a function cold start.
    if request.path.startswith("/api/") and os.environ.get("VERCEL") and not DATABASE_URL:
        return jsonify(error="Vercel is missing a PostgreSQL connection string. Add DATABASE_URL or POSTGRES_URL, then redeploy."), 503
    if request.path.startswith("/api/") and DATABASE_URL and not _db_ready:
        try:
            init_db()
            _db_ready = True
        except Exception as error:
            app.logger.exception("Database initialization failed")
            details = str(error)
            if DATABASE_URL:
                details = details.replace(DATABASE_URL, "[database URL hidden]")
            return jsonify(error=f"Database initialization failed ({type(error).__name__}): {details[:400]}"), 503


class Database:
    """Use hosted PostgreSQL on Vercel, or a local SQLite file for development."""
    def __init__(self):
        if DATABASE_URL:
            import psycopg
            from psycopg.rows import dict_row
            # The Supabase/Vercel integration can append a hint for Vercel's
            # JavaScript driver; libpq/Psycopg rejects that unknown URI option.
            parts = urlsplit(DATABASE_URL)
            query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "workaround"])
            postgres_url = urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
            self.connection = psycopg.connect(
                postgres_url,
                row_factory=dict_row,
                prepare_threshold=None,  # Supabase transaction pooler does not support prepared statements.
            )
            self.postgres = True
        else:
            self.connection = sqlite3.connect(DB_PATH)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.postgres = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return self.connection.__exit__(exc_type, exc_value, traceback)
        finally:
            self.connection.close()

    def execute(self, sql, values=()):
        if self.postgres:
            sql = sql.replace("INSERT OR IGNORE INTO favorites", "INSERT INTO favorites")
            sql = sql.replace("VALUES(?,?)", "VALUES(%s,%s) ON CONFLICT (user_id, animal_id) DO NOTHING") if "INSERT INTO favorites" in sql else sql
            sql = sql.replace("?", "%s")
        return self.connection.execute(sql, values)

    def executemany(self, sql, values):
        for row in values:
            self.execute(sql, row)


def db():
    return Database()


def init_db():
    id_type = "SERIAL" if DATABASE_URL else "INTEGER"
    time_default = "CURRENT_TIMESTAMP::text" if DATABASE_URL else "CURRENT_TIMESTAMP"
    with db() as conn:
        schema = f"""
        CREATE TABLE IF NOT EXISTS users (
            id {id_type} PRIMARY KEY, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'volunteer', name TEXT DEFAULT '', phone TEXT DEFAULT '',
            address TEXT DEFAULT '', experience TEXT DEFAULT '', pets TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS animals (
            id {id_type} PRIMARY KEY, name TEXT NOT NULL, species TEXT DEFAULT 'Dog', breed TEXT DEFAULT '',
            age TEXT DEFAULT '', gender TEXT DEFAULT '', size TEXT DEFAULT '', description TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Available', photo TEXT DEFAULT '', vaccinated TEXT DEFAULT '',
            spayed_neutered TEXT DEFAULT '', dietary_needs TEXT DEFAULT '', behavior TEXT DEFAULT '', special_care TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            animal_id INTEGER NOT NULL REFERENCES animals(id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, animal_id)
        );
        CREATE TABLE IF NOT EXISTS adoptions (
            id {id_type} PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), animal_id INTEGER NOT NULL REFERENCES animals(id),
            name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT DEFAULT '', housing TEXT DEFAULT '',
            other_pets TEXT DEFAULT '', experience TEXT DEFAULT '', status TEXT DEFAULT 'Submitted', created_at TEXT DEFAULT {time_default}
        );
        CREATE TABLE IF NOT EXISTS volunteer_applications (
            id {id_type} PRIMARY KEY, user_id INTEGER REFERENCES users(id), name TEXT NOT NULL, email TEXT NOT NULL,
            phone TEXT DEFAULT '', interests TEXT DEFAULT '', availability TEXT DEFAULT '', experience TEXT DEFAULT '',
            status TEXT DEFAULT 'Submitted', created_at TEXT DEFAULT {time_default}
        );
        CREATE TABLE IF NOT EXISTS opportunities (
            id {id_type} PRIMARY KEY, title TEXT NOT NULL, description TEXT DEFAULT '', schedule TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS messages (
            id {id_type} PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, animal_id INTEGER,
            message TEXT NOT NULL, created_at TEXT DEFAULT {time_default}
        );
        """
        for statement in schema.split(";"):
            if statement.strip():
                conn.execute(statement)
        count = conn.execute("SELECT COUNT(*) AS total FROM animals").fetchone()
        if count["total"] == 0:
            conn.executemany("""INSERT INTO animals
              (name,species,breed,age,gender,size,description,status,photo,vaccinated,spayed_neutered,dietary_needs,behavior,special_care)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", [
                ("Charlie", "Dog", "Golden Retriever", "2 years", "Male", "Large", "A friendly, playful companion who loves long walks and meeting people.", "Available", "https://images.unsplash.com/photo-1552053831-71594a27632d?w=800", "Up to date", "Yes", "Standard adult diet", "Friendly and energetic", "Daily exercise"),
                ("Bella", "Dog", "Mixed Breed", "8 months", "Female", "Medium", "A curious puppy who is learning quickly and enjoys gentle play.", "Available", "https://images.unsplash.com/photo-1543466835-00a7907e9de1?w=800", "Up to date", "Scheduled", "Puppy food", "Still in training", "Needs puppy socialization"),
                ("Max", "Dog", "Rescue Dog", "3 years", "Male", "Medium", "A calm, affectionate dog ready for a patient forever family.", "Pending", "https://images.unsplash.com/photo-1517849845537-4d257902454a?w=800", "Up to date", "Yes", "Sensitive stomach; vet-approved food", "Gentle and relaxed", "Slow introductions to new dogs"),
                ("Mittens", "Cat", "Domestic Shorthair", "1 year", "Female", "Small", "A sweet indoor cat who likes sunny windows and quiet company.", "Available", "https://images.unsplash.com/photo-1514888286974-6c03e2ca1dba?w=800", "Up to date", "Yes", "Standard cat diet", "Litter trained", "Indoor home preferred")
            ])
        # Add sample dogs by name so existing databases receive these once too.
        sample_dogs = [
            ("Daisy", "Dog", "Beagle Mix", "4 years", "Female", "Small", "Daisy is a cheerful trail buddy who loves sniffing around the yard and curling up after a walk.", "Available", "https://images.unsplash.com/photo-1548199973-03cce0bbc87b?w=800", "Up to date", "Yes", "Standard adult diet", "Social and curious", "Daily walks and a secure yard"),
            ("Cooper", "Dog", "Labrador Retriever Mix", "1 year", "Male", "Large", "Cooper is an affectionate young dog who enjoys fetch, learning tricks, and spending time with people.", "Available", "https://images.unsplash.com/photo-1518717758536-85ae29035b6d?w=800", "Up to date", "Yes", "Standard adult diet", "Playful and eager to learn", "Needs regular exercise and training"),
            ("Luna", "Dog", "Terrier Mix", "6 months", "Female", "Small", "Luna is a gentle puppy who is building confidence and would enjoy a patient home with time for training.", "Available", "https://images.unsplash.com/photo-1552053831-71594a27632d?w=800", "In progress", "Scheduled", "Puppy food", "Shy at first, warms up with treats", "Puppy socialization and basic training"),
        ]
        for dog in sample_dogs:
            if not conn.execute("SELECT id FROM animals WHERE name=?", (dog[0],)).fetchone():
                conn.execute("""INSERT INTO animals
                  (name,species,breed,age,gender,size,description,status,photo,vaccinated,spayed_neutered,dietary_needs,behavior,special_care)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", dog)
        if conn.execute("SELECT COUNT(*) AS total FROM opportunities").fetchone()["total"] == 0:
            conn.executemany("INSERT INTO opportunities (title,description,schedule) VALUES (?,?,?)", [
                ("Animal Care Helper", "Help with feeding, enrichment, and keeping animal spaces tidy.", "Weekdays, 8–11 AM or 3–6 PM"),
                ("Adoption Event Support", "Welcome visitors and introduce them to animals at community events.", "Saturday events, 10 AM–2 PM"),
                ("Foster a Friend", "Provide a temporary home for an animal while they wait for adoption.", "Flexible, coordinated with shelter staff")
            ])


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with db() as conn:
        row = conn.execute("SELECT id,email,role,name,phone,address,experience,pets FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user():
            return jsonify(error="Please log in first."), 401
        return fn(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def decorate(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user()["role"] not in roles:
                return jsonify(error="You don't have permission to do that."), 403
            return fn(*args, **kwargs)
        return wrapped
    return decorate


def json_body():
    return request.get_json(silent=True) or {}


def insert_id(conn, sql, values):
    cursor = conn.execute(sql + (" RETURNING id" if DATABASE_URL else ""), values)
    return cursor.fetchone()["id"] if DATABASE_URL else cursor.lastrowid


def clean_animal(data):
    return {key: data.get(key, "") for key in ANIMAL_FIELDS}


@app.get("/")
def home():
    return send_from_directory(ROOT, "index.html")


@app.get("/<path:filename>")
def website_files(filename):
    return send_from_directory(ROOT, filename)


@app.post("/api/register")
def register():
    data = json_body()
    email, password = data.get("email", "").strip().lower(), data.get("password", "")
    role = data.get("role", "volunteer")
    if not email or len(password) < 8 or role not in ROLES:
        return jsonify(error="Enter an email, a password of at least 8 characters, and a valid role."), 400
    try:
        with db() as conn:
            user_id = insert_id(conn, "INSERT INTO users(email,password,role,name) VALUES(?,?,?,?)", (email, generate_password_hash(password), role, data.get("name", "")))
    except Exception as error:
        if isinstance(error, sqlite3.IntegrityError) or "unique" in str(error).lower():
            return jsonify(error="An account with that email already exists."), 409
        raise
    session["user_id"] = user_id
    return jsonify(user=current_user())


@app.post("/api/login")
def login():
    data = json_body()
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=?", (data.get("email", "").strip().lower(),)).fetchone()
    if not user or not check_password_hash(user["password"], data.get("password", "")):
        return jsonify(error="Email or password is incorrect."), 401
    session["user_id"] = user["id"]
    return jsonify(user=current_user())


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
def me():
    return jsonify(user=current_user())


@app.patch("/api/profile")
@login_required
def update_profile():
    data = json_body()
    allowed = ("name", "phone", "address", "experience", "pets")
    fields = {key: data[key] for key in allowed if key in data}
    if fields:
        sql = ",".join(f"{key}=?" for key in fields)
        with db() as conn:
            conn.execute(f"UPDATE users SET {sql} WHERE id=?", (*fields.values(), session["user_id"]))
    return jsonify(user=current_user())


@app.get("/api/animals")
def list_animals():
    filters = {key: request.args.get(key, "").strip() for key in ("search", "species", "breed", "age", "size", "gender", "status")}
    query, values = "SELECT * FROM animals WHERE 1=1", []
    for key, value in filters.items():
        if value:
            if key == "search":
                query += " AND (name LIKE ? OR breed LIKE ? OR description LIKE ?)"
                values.extend([f"%{value}%"] * 3)
            elif key == "age":
                query += " AND age LIKE ?"; values.append(f"%{value}%")
            else:
                query += f" AND {key} LIKE ?"; values.append(f"%{value}%")
    query += " ORDER BY id DESC"
    with db() as conn:
        animals = [dict(row) for row in conn.execute(query, values).fetchall()]
    return jsonify(animals=animals)


@app.get("/api/animals/<int:animal_id>")
def animal_detail(animal_id):
    with db() as conn:
        animal = conn.execute("SELECT * FROM animals WHERE id=?", (animal_id,)).fetchone()
    if not animal:
        return jsonify(error="Animal not found."), 404
    return jsonify(animal=dict(animal))


@app.route("/api/favorites/<int:animal_id>", methods=["POST", "DELETE"])
@login_required
def favorite(animal_id):
    with db() as conn:
        if request.method == "POST":
            conn.execute("INSERT OR IGNORE INTO favorites(user_id,animal_id) VALUES(?,?)", (session["user_id"], animal_id))
        else:
            conn.execute("DELETE FROM favorites WHERE user_id=? AND animal_id=?", (session["user_id"], animal_id))
    return jsonify(ok=True)


@app.get("/api/favorites")
@login_required
def list_favorites():
    with db() as conn:
        rows = conn.execute("SELECT a.* FROM animals a JOIN favorites f ON a.id=f.animal_id WHERE f.user_id=?", (session["user_id"],)).fetchall()
    return jsonify(animals=[dict(row) for row in rows])


@app.route("/api/applications", methods=["GET", "POST"])
@login_required
def applications():
    if request.method == "GET":
        with db() as conn:
            rows = conn.execute("SELECT a.*,animal.name AS animal_name FROM adoptions a JOIN animals animal ON animal.id=a.animal_id WHERE a.user_id=? ORDER BY a.created_at DESC", (session["user_id"],)).fetchall()
        return jsonify(applications=[dict(row) for row in rows])
    data, user = json_body(), current_user()
    required = ("animal_id", "name", "email", "phone", "housing", "experience")
    if any(not data.get(field) for field in required):
        return jsonify(error="Please complete all required application fields."), 400
    with db() as conn:
        item_id = insert_id(conn, "INSERT INTO adoptions(user_id,animal_id,name,email,phone,housing,other_pets,experience) VALUES(?,?,?,?,?,?,?,?)", (user["id"], data["animal_id"], data["name"], data["email"], data["phone"], data["housing"], data.get("other_pets", ""), data["experience"]))
    return jsonify(id=item_id, status="Submitted"), 201


@app.get("/api/opportunities")
def opportunities():
    with db() as conn:
        rows = conn.execute("SELECT * FROM opportunities ORDER BY id").fetchall()
    return jsonify(opportunities=[dict(row) for row in rows])


@app.post("/api/volunteers")
def volunteer_apply():
    data, user = json_body(), current_user()
    if not data.get("name") or not data.get("email") or not data.get("availability"):
        return jsonify(error="Name, email, and availability are required."), 400
    with db() as conn:
        item_id = insert_id(conn, "INSERT INTO volunteer_applications(user_id,name,email,phone,interests,availability,experience) VALUES(?,?,?,?,?,?,?)", ((user["id"] if user else None), data["name"], data["email"], data.get("phone", ""), data.get("interests", ""), data.get("availability", ""), data.get("experience", "")))
    return jsonify(id=item_id, status="Submitted"), 201


@app.post("/api/contact")
def contact():
    data = json_body()
    if not data.get("name") or not data.get("email") or not data.get("message"):
        return jsonify(error="Please enter your name, email, and message."), 400
    with db() as conn:
        conn.execute("INSERT INTO messages(name,email,animal_id,message) VALUES(?,?,?,?)", (data["name"], data["email"], data.get("animal_id") or None, data["message"]))
    return jsonify(message="Your message has been sent."), 201


@app.get("/api/admin/applications")
@roles_required("staff", "administrator")
def admin_applications():
    with db() as conn:
        adoptions = conn.execute("SELECT a.*,u.email AS account_email,an.name AS animal_name FROM adoptions a JOIN users u ON u.id=a.user_id JOIN animals an ON an.id=a.animal_id ORDER BY a.created_at DESC").fetchall()
        volunteers = conn.execute("SELECT * FROM volunteer_applications ORDER BY created_at DESC").fetchall()
    return jsonify(adoptions=[dict(r) for r in adoptions], volunteers=[dict(r) for r in volunteers])


@app.patch("/api/admin/applications/<kind>/<int:item_id>")
@roles_required("staff", "administrator")
def update_application(kind, item_id):
    table = {"adoption": "adoptions", "volunteer": "volunteer_applications"}.get(kind)
    status = json_body().get("status")
    if not table or status not in {"Submitted", "In Review", "Approved", "Declined"}:
        return jsonify(error="Invalid application type or status."), 400
    with db() as conn:
        conn.execute(f"UPDATE {table} SET status=? WHERE id=?", (status, item_id))
    return jsonify(ok=True)


@app.route("/api/admin/animals", defaults={"animal_id": None}, methods=["POST"])
@app.route("/api/admin/animals/<int:animal_id>", methods=["PUT", "DELETE"])
@roles_required("administrator")
def manage_animal(animal_id):
    with db() as conn:
        if request.method == "DELETE":
            conn.execute("DELETE FROM animals WHERE id=?", (animal_id,))
            return jsonify(ok=True)
        animal = clean_animal(json_body())
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


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
