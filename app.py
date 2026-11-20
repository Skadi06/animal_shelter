from pathlib import Path
import json
import mimetypes
import os
import sqlite3
import uuid
from functools import wraps
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Flask, jsonify, request, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "local-shelter-demo-key"
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "shelter.db"
# Supabase's Vercel integration provides POSTGRES_URL; DATABASE_URL also works.
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
_db_ready = False
ROLES = {"volunteer", "staff", "administrator"}
ANIMAL_FIELDS = ("name", "species", "breed", "age", "gender", "size", "description", "status", "photo", "vaccinated", "spayed_neutered", "dietary_needs", "behavior", "special_care")


@app.before_request
def check_vercel_database():
    """Prepare the hosted database before API routes use it.

    Vercel functions are short-lived, so the schema is initialized lazily on
    the first API request in each process. If configuration or initialization
    fails, return a readable JSON error instead of a generic HTML error page.
    """
    global _db_ready
    # Return useful API messages instead of crashing during a function cold start.
    if request.path.startswith("/api/") and os.environ.get("VERCEL") and not DATABASE_URL:
        return jsonify(error="Vercel is missing a PostgreSQL connection string. Add DATABASE_URL or POSTGRES_URL, then redeploy."), 503
    if request.path.startswith("/api/") and DATABASE_URL and not _db_ready:
        try:
            init_db()
            _db_ready = True
        except Exception:
            app.logger.exception("Database initialization failed")
            return jsonify(error="Database initialization failed. Check the Vercel function logs."), 503


@app.errorhandler(413)
def image_too_large(_error):
    """Convert Flask's request-size error into a friendly JSON response."""
    return jsonify(error="That image is too large. Choose an image under 8 MB."), 413


class Database:
    """Use hosted PostgreSQL on Vercel, or a local SQLite file for development."""
    def __init__(self):
        """Open PostgreSQL when configured, otherwise open the local SQLite DB.

        PostgreSQL connection options are filtered to options supported by
        Psycopg; SQLite keeps its row and foreign-key behavior for local work.
        """
        if DATABASE_URL:
            import psycopg
            from psycopg.rows import dict_row
            # The Supabase/Vercel integration can append a hint for Vercel's
            # JavaScript driver; libpq/Psycopg rejects unknown URI options.
            parts = urlsplit(DATABASE_URL)
            psycopg_options = {
                "sslmode", "sslcert", "sslkey", "sslrootcert", "connect_timeout",
                "application_name", "channel_binding", "gssencmode", "keepalives",
                "keepalives_idle", "keepalives_interval", "keepalives_count",
                "target_session_attrs", "load_balance_hosts", "hostaddr",
            }
            query = urlencode([
                (key, value)
                for key, value in parse_qsl(parts.query, keep_blank_values=True)
                if key.lower() in psycopg_options
            ])
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
        """Let a Database instance be used with Python's ``with`` statement."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Finish the transaction and always close its underlying connection."""
        try:
            return self.connection.__exit__(exc_type, exc_value, traceback)
        finally:
            self.connection.close()

    def execute(self, sql, values=()):
        """Run shared route SQL, translating placeholders for PostgreSQL."""
        if self.postgres:
            # Existing routes use SQLite-style question marks. Convert them
            # here so the same route code can run against PostgreSQL.
            sql = sql.replace("INSERT OR IGNORE INTO favorites", "INSERT INTO favorites")
            sql = sql.replace("VALUES(?,?)", "VALUES(%s,%s) ON CONFLICT (user_id, animal_id) DO NOTHING") if "INSERT INTO favorites" in sql else sql
            sql = sql.replace("?", "%s")
        return self.connection.execute(sql, values)

    def executemany(self, sql, values):
        """Run one SQL statement for each parameter row in ``values``."""
        for row in values:
            self.execute(sql, row)


def db():
    """Create a database wrapper for the configured database engine."""
    return Database()


def init_db():
    """Create shelter tables and insert starter records when they are absent.

    The operation is safe to repeat: schema uses ``IF NOT EXISTS`` and demo
    records are added only to empty tables or when a sample dog is missing.
    """
    # Keep table definitions shared across local SQLite and hosted PostgreSQL;
    # only their auto-increment and timestamp default syntax differ.
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
            # Add demo listings only to a new database, so staff data is never
            # overwritten when a Vercel function starts again.
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
    """Return the signed-in user's public profile, or ``None`` if logged out."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    with db() as conn:
        row = conn.execute("SELECT id,email,role,name,phone,address,experience,pets FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def login_required(fn):
    """Reject account-only actions when the session has no logged-in user."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        """Check for a session user before calling the protected route."""
        if not current_user():
            return jsonify(error="Please log in first."), 401
        return fn(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    """Restrict management endpoints to the requested staff roles."""
    def decorate(fn):
        """Attach the role check and login check to one route function."""
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            """Allow the route only when the signed-in account has a role."""
            if current_user()["role"] not in roles:
                return jsonify(error="You don't have permission to do that."), 403
            return fn(*args, **kwargs)
        return wrapped
    return decorate


def json_body():
    """Read a JSON request body, using an empty dictionary for invalid/empty JSON."""
    return request.get_json(silent=True) or {}


def insert_id(conn, sql, values):
    """Insert one row and return its generated ID for either database engine."""
    cursor = conn.execute(sql + (" RETURNING id" if DATABASE_URL else ""), values)
    return cursor.fetchone()["id"] if DATABASE_URL else cursor.lastrowid


def clean_animal(data):
    """Keep only supported animal fields from an incoming form or JSON object."""
    return {key: data.get(key, "") for key in ANIMAL_FIELDS}


def storage_call(path, method="GET", body=None, content_type="application/json"):
    """Send one authenticated request to the Supabase Storage REST API.

    The service key stays on the backend. Dictionary payloads are encoded as
    JSON, while byte payloads are passed through for image uploads. HTTP and
    network errors become concise ``ValueError`` messages for the API route.
    """
    project_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    storage_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SECRET_KEY")
    if not project_url or not storage_key:
        raise ValueError("Supabase Storage is not configured. Check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in Vercel.")
    payload = json.dumps(body).encode() if isinstance(body, dict) else body
    req = Request(
        f"{project_url}/storage/v1/{path.lstrip('/')}",
        data=payload,
        method=method,
        headers={
            "apikey": storage_key,
            "Authorization": f"Bearer {storage_key}",
            "Content-Type": content_type,
            "x-upsert": "true",
        },
    )
    try:
        with urlopen(req, timeout=20) as response:
            return response.read()
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise ValueError(f"Supabase Storage returned {error.code}: {details[:250]}") from error
    except URLError as error:
        raise ValueError(f"Could not reach Supabase Storage: {error.reason}") from error


def upload_animal_photo(photo):
    """Validate and upload an animal image, returning its public URL.

    Creates the public bucket on first use if it does not exist. A unique
    filename prevents one uploaded image from accidentally replacing another.
    """
    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    content_type = photo.mimetype or mimetypes.guess_type(photo.filename or "")[0]
    if content_type not in allowed_types:
        raise ValueError("Choose a JPG, PNG, WebP, or GIF image.")

    bucket = "animal-photos"
    try:
        storage_call(f"bucket/{bucket}")
    except ValueError as error:
        missing_bucket = "NoSuchBucket" in str(error) or "Bucket not found" in str(error) or "returned 404" in str(error)
        if not missing_bucket:
            raise
        storage_call("bucket", "POST", {"id": bucket, "name": bucket, "public": True})

    safe_name = secure_filename(photo.filename or "animal-image")
    suffix = Path(safe_name).suffix or mimetypes.guess_extension(content_type) or ".jpg"
    object_name = f"{uuid.uuid4().hex}{suffix.lower()}"
    storage_call(f"object/{bucket}/{quote(object_name)}", "POST", photo.read(), content_type)
    project_url = os.environ["SUPABASE_URL"].rstrip("/")
    return f"{project_url}/storage/v1/object/public/{bucket}/{object_name}"


@app.get("/")
def home():
    """Serve the shelter website's main HTML page."""
    return send_from_directory(ROOT, "index.html")


@app.get("/<path:filename>")
def website_files(filename):
    """Serve a static website asset such as CSS or JavaScript."""
    return send_from_directory(ROOT, filename)


@app.post("/api/register")
def register():
    """Create an account, start its session, and return the public user data."""
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
    """Verify email and password, then store the account ID in the session."""
    data = json_body()
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=?", (data.get("email", "").strip().lower(),)).fetchone()
    if not user or not check_password_hash(user["password"], data.get("password", "")):
        return jsonify(error="Email or password is incorrect."), 401
    session["user_id"] = user["id"]
    return jsonify(user=current_user())


@app.post("/api/logout")
def logout():
    """Clear the current browser session and report success."""
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
def me():
    """Return the current account profile, or JSON null when logged out."""
    return jsonify(user=current_user())


@app.patch("/api/profile")
@login_required
def update_profile():
    """Update only the signed-in user's editable profile fields."""
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
    """Return one page of animals matching optional case-insensitive filters.

    The response includes the current page, total page count, and total match
    count so the frontend can display short lists with previous/next controls.
    """
    # Read every filter the visitor entered; empty values are ignored below.
    filters = {key: request.args.get(key, "").strip() for key in ("search", "species", "breed", "age", "size", "gender", "status")}
    conditions, values = [], []
    for key, value in filters.items():
        if value:
            if key == "search":
                # Lowercase both sides so searches match regardless of capitalization
                # in SQLite locally or PostgreSQL on Vercel.
                conditions.append("(LOWER(name) LIKE LOWER(?) OR LOWER(breed) LIKE LOWER(?) OR LOWER(description) LIKE LOWER(?))")
                values.extend([f"%{value}%"] * 3)
            elif key == "age":
                conditions.append("LOWER(age) LIKE LOWER(?)")
                values.append(f"%{value}%")
            elif key == "gender":
                # Match a selected gender exactly: a partial search for "Male"
                # would otherwise also match "Female" because it contains it.
                conditions.append("LOWER(gender) = LOWER(?)")
                values.append(value)
            else:
                conditions.append(f"LOWER({key}) LIKE LOWER(?)")
                values.append(f"%{value}%")
    # Apply all chosen filters together, then count the full matching result set
    # before loading only the requested page of animals.
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    page_size = 12
    page = max(1, request.args.get("page", 1, type=int) or 1)
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS total FROM animals{where}", values).fetchone()["total"]
        pages = max(1, (total + page_size - 1) // page_size)
        # Clamp stale page numbers after filtering or removing the last animal on a page.
        page = min(page, pages)
        animals = conn.execute(
            f"SELECT * FROM animals{where} ORDER BY id DESC LIMIT ? OFFSET ?",
            (*values, page_size, (page - 1) * page_size),
        ).fetchall()
    return jsonify(animals=[dict(row) for row in animals], page=page, pages=pages, total=total)


@app.get("/api/animals/<int:animal_id>")
def animal_detail(animal_id):
    """Return one animal profile, or a 404 JSON response if it is missing."""
    with db() as conn:
        animal = conn.execute("SELECT * FROM animals WHERE id=?", (animal_id,)).fetchone()
    if not animal:
        return jsonify(error="Animal not found."), 404
    return jsonify(animal=dict(animal))


@app.get("/api/animals/options")
def animal_options():
    """Return animal IDs and names for the contact form's animal selector."""
    with db() as conn:
        rows = conn.execute("SELECT id, name FROM animals ORDER BY name").fetchall()
    return jsonify(animals=[dict(row) for row in rows])


@app.route("/api/favorites/<int:animal_id>", methods=["POST", "DELETE"])
@login_required
def favorite(animal_id):
    """Add or remove the signed-in user's saved-animal relationship."""
    with db() as conn:
        if request.method == "POST":
            conn.execute("INSERT OR IGNORE INTO favorites(user_id,animal_id) VALUES(?,?)", (session["user_id"], animal_id))
        else:
            conn.execute("DELETE FROM favorites WHERE user_id=? AND animal_id=?", (session["user_id"], animal_id))
    return jsonify(ok=True)


@app.get("/api/favorites")
@login_required
def list_favorites():
    """Return complete animal profiles saved by the signed-in user."""
    with db() as conn:
        rows = conn.execute("SELECT a.* FROM animals a JOIN favorites f ON a.id=f.animal_id WHERE f.user_id=?", (session["user_id"],)).fetchall()
    return jsonify(animals=[dict(row) for row in rows])


@app.route("/api/applications", methods=["GET", "POST"])
@login_required
def applications():
    """List the user's adoption applications or create a new application."""
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
    """Return the volunteer opportunities shown on the public website."""
    with db() as conn:
        rows = conn.execute("SELECT * FROM opportunities ORDER BY id").fetchall()
    return jsonify(opportunities=[dict(row) for row in rows])


@app.post("/api/volunteers")
def volunteer_apply():
    """Save a volunteer application and associate it with a user if logged in."""
    data, user = json_body(), current_user()
    if not data.get("name") or not data.get("email") or not data.get("availability"):
        return jsonify(error="Name, email, and availability are required."), 400
    with db() as conn:
        item_id = insert_id(conn, "INSERT INTO volunteer_applications(user_id,name,email,phone,interests,availability,experience) VALUES(?,?,?,?,?,?,?)", ((user["id"] if user else None), data["name"], data["email"], data.get("phone", ""), data.get("interests", ""), data.get("availability", ""), data.get("experience", "")))
    return jsonify(id=item_id, status="Submitted"), 201


@app.post("/api/contact")
def contact():
    """Save a visitor message, optionally associating it with an animal."""
    data = json_body()
    if not data.get("name") or not data.get("email") or not data.get("message"):
        return jsonify(error="Please enter your name, email, and message."), 400
    with db() as conn:
        conn.execute("INSERT INTO messages(name,email,animal_id,message) VALUES(?,?,?,?)", (data["name"], data["email"], data.get("animal_id") or None, data["message"]))
    return jsonify(message="Your message has been sent."), 201


@app.get("/api/admin/applications")
@roles_required("staff", "administrator")
def admin_applications():
    """Return adoption and volunteer applications for authorized staff."""
    with db() as conn:
        adoptions = conn.execute("SELECT a.*,u.email AS account_email,an.name AS animal_name FROM adoptions a JOIN users u ON u.id=a.user_id JOIN animals an ON an.id=a.animal_id ORDER BY a.created_at DESC").fetchall()
        volunteers = conn.execute("SELECT * FROM volunteer_applications ORDER BY created_at DESC").fetchall()
    return jsonify(adoptions=[dict(r) for r in adoptions], volunteers=[dict(r) for r in volunteers])


@app.patch("/api/admin/applications/<kind>/<int:item_id>")
@roles_required("staff", "administrator")
def update_application(kind, item_id):
    """Change an adoption or volunteer application's review status."""
    table = {"adoption": "adoptions", "volunteer": "volunteer_applications"}.get(kind)
    status = json_body().get("status")
    if not table or status not in {"Submitted", "In Review", "Approved", "Declined"}:
        return jsonify(error="Invalid application type or status."), 400
    with db() as conn:
        conn.execute(f"UPDATE {table} SET status=? WHERE id=?", (status, item_id))
    return jsonify(ok=True)


@app.route("/api/admin/animals", defaults={"animal_id": None}, methods=["POST"])
@app.route("/api/admin/animals/<int:animal_id>", methods=["PUT", "DELETE"])
@roles_required("staff", "administrator")
def manage_animal(animal_id):
    """Create, edit, or remove an animal profile for staff and administrators.

    Create/edit requests accept multipart form data for optional image upload;
    when an edit has no new image, the animal's existing photo is preserved.
    """
    # Admin form submissions are multipart so they can contain both regular
    # animal fields and an optional image file. A photo-less edit keeps the
    # animal's existing image URL.
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


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
