"""Flask application setup and the public website entry points."""

import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

# Each blueprint groups related web addresses and the Python functions that
# answer them. Keeping these imports separate makes the app easier to navigate.
from database import DATABASE_URL, init_db
from auth_routes import bp as auth_blueprint
from animal_routes import bp as animal_blueprint
from application_routes import bp as application_blueprint
from admin_routes import bp as admin_blueprint

# Create the Flask application object. Other files add their routes to this app.
app = Flask(__name__)
# Flask uses this key to sign session cookies so it can recognize a logged-in user.
app.secret_key = "local-shelter-demo-key"
# Reject very large requests so an oversized photo cannot overwhelm the app.
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
# ROOT is the folder containing this file and the website's HTML/CSS/JS files.
ROOT = Path(__file__).resolve().parent
# This flag remembers whether this process already checked that database tables exist.
_db_ready = False


@app.before_request
def check_vercel_database():
    """Make sure an API request has a usable database before it runs.

    A Vercel Function may start as a brand-new process, so the database tables
    are prepared the first time that process receives an API request. Static
    files do not need a database, so they are allowed through without setup.
    If setup fails, return a JSON error the browser can display.
    """
    # global lets this function update the flag created above.
    global _db_ready
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
    """Turn Flask's upload-size error into a message the website can show.

    ``MAX_CONTENT_LENGTH`` above limits all incoming requests to 8 MB. Flask
    calls this function if a visitor tries to send a larger image.
    """
    return jsonify(error="That image is too large. Choose an image under 8 MB."), 413


@app.get("/")
def home():
    """Send the website's starting HTML page when someone visits the root URL."""
    return send_from_directory(ROOT, "index.html")


@app.get("/<path:filename>")
def website_files(filename):
    """Send a requested website file, such as its CSS or JavaScript file.

    Flask fills in ``filename`` from the URL path. ``send_from_directory``
    safely finds that file in this project's folder and sends it to the browser.
    """
    return send_from_directory(ROOT, filename)


# Register each feature group with Flask. This makes its URL decorators active.
for blueprint in (auth_blueprint, animal_blueprint, application_blueprint, admin_blueprint):
    app.register_blueprint(blueprint)


if __name__ == "__main__":
    # This block runs only when starting this file directly for local development.
    init_db()
    app.run(debug=True)
