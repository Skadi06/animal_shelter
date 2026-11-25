# Shared helpers used by the shelter's API route modules.

import json
import mimetypes
import os
import uuid
from functools import wraps
from pathlib import Path
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import jsonify, request, session
from werkzeug.utils import secure_filename

from database import db
ANIMAL_FIELDS = (
    "name", "species", "breed", "age", "gender", "size", "description",
    "status", "photo", "vaccinated", "spayed_neutered", "dietary_needs",
    "behavior", "special_care",
)

def current_user():
    # Look up the account stored in this browser's Flask session.
    #
    # Logging in saves the user's database ID in ``session``. This function uses
    # that ID to load the profile fields needed by the website, leaving the
    # password out of the returned data. It returns ``None`` when no account is
    # signed in or the saved ID no longer belongs to an account.
    #
    user_id = session.get("user_id")
    if not user_id:
        return None
    with db() as conn:
        row = conn.execute("SELECT id,email,role,name,phone,address,experience,pets FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None

def login_required(fn):
    # Protect a route so only a signed-in visitor can use it.
    #
    # This is a decorator: it wraps a route function and runs the login check
    # first. If there is no current account, the browser gets an HTTP 401 JSON
    # response instead of the route being run.
    #
    @wraps(fn)
    def wrapped(*args, **kwargs):
        # Check the session, then call the original route when logged in.
        if not current_user():
            return jsonify(error="Please log in first."), 401
        return fn(*args, **kwargs)
    return wrapped

def roles_required(*roles):
    # Protect a route so only logged-in accounts with a listed role can use it.
    #
    # Example: ``@roles_required("staff", "administrator")`` means the route
    # accepts either of those account roles. Everyone else receives HTTP 403.
    #
    def decorate(fn):
        # Build the wrapper that will be attached to the decorated route.
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            # Check the account role before the original route can run.
            if current_user()["role"] not in roles:
                return jsonify(error="You don't have permission to do that."), 403
            return fn(*args, **kwargs)
        return wrapped
    return decorate

def json_body():
    # Read JSON sent by the browser and always give routes a dictionary.
    #
    # ``silent=True`` prevents Flask from raising an error for an empty or
    # malformed JSON body. In those cases this helper returns ``{}``, allowing
    # the route to respond with its normal missing-field message.
    #
    return request.get_json(silent=True) or {}

def insert_id(conn, sql, values):
    # Insert one database row and return the ID assigned to that new row.
    #
    # PostgreSQL returns the new ID through ``RETURNING id``. ``conn`` is the
    # open connection; ``sql`` is the INSERT statement; and ``values`` contains
    # the data to insert.
    #
    return conn.execute(sql + " RETURNING id", values).fetchone()["id"]

def clean_animal(data):
    # Create an animal dictionary containing only fields the app supports.
    #
    # ``data`` may come from the admin form or a JSON request. Missing fields
    # become empty strings, and unknown keys are ignored so they cannot become
    # part of a generated SQL statement.
    #
    return {key: data.get(key, "") for key in ANIMAL_FIELDS}

def storage_call(path, method="GET", body=None, content_type="application/json"):
    # Send a request to Supabase Storage to check a bucket or transfer a file.
    #
    # ``path`` is the part after ``/storage/v1/``; ``method`` is GET, POST, etc.;
    # ``body`` is either a dictionary (converted to JSON) or raw file bytes; and
    # ``content_type`` tells Supabase what kind of body is being sent. The secret
    # service key is read on the server and never sent to browser code. Network
    # problems are turned into readable ``ValueError`` messages for the route.
    #
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
    # Check an uploaded animal image, store it, and return its public URL.
    #
    # ``photo`` is the uploaded file from Flask's request. Only common image
    # formats are accepted. The function makes the public storage bucket if it
    # is missing, gives the file a unique name, uploads its bytes, and returns the
    # URL that can be saved in the animal record and displayed on the website.
    #
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
