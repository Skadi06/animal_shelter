# Flask application setup and the public website entry points.

from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from database import DATABASE_URL, init_db
from auth import bp as auth_blueprint
from animals import bp as animal_blueprint
from applications import bp as application_blueprint
from admin import bp as admin_blueprint
app = Flask(__name__)
app.secret_key = "local-shelter-demo-key"
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
ROOT = Path(__file__).resolve().parent
_db_ready = False

@app.before_request
def check_database():
    # Make sure an API request has a usable database before it runs.
    #
    # The database tables are prepared the first time this process receives an
    # API request. Static files do not need a database, so they are allowed
    # through without setup. If setup fails, return a JSON error to the browser.
    #
    global _db_ready
    if request.path.startswith("/api/") and not DATABASE_URL:
        return jsonify(error="PostgreSQL is required. Set DATABASE_URL or POSTGRES_URL."), 503
    if request.path.startswith("/api/") and DATABASE_URL and not _db_ready:
        try:
            init_db()
            _db_ready = True
        except Exception:
            app.logger.exception("Database initialization failed")
            return jsonify(error="Database initialization failed. Check the server logs."), 503

@app.errorhandler(413)
def image_too_large(_error):
    # Turn Flask's upload-size error into a message the website can show.
    #
    # ``MAX_CONTENT_LENGTH`` above limits all incoming requests to 8 MB. Flask
    # calls this function if a visitor tries to send a larger image.
    #
    return jsonify(error="That image is too large. Choose an image under 8 MB."), 413

@app.get("/")
def home():
    # Send the website's starting HTML page when someone visits the root URL.
    return send_from_directory(ROOT, "index.html")

@app.get("/<path:filename>")
def website_files(filename):
    # Send a requested website file, such as its CSS or JavaScript file.
    #
    # Flask fills in ``filename`` from the URL path. ``send_from_directory``
    # safely finds that file in this project's folder and sends it to the browser.
    #
    return send_from_directory(ROOT, filename)
for blueprint in (auth_blueprint, animal_blueprint, application_blueprint, admin_blueprint):
    app.register_blueprint(blueprint)

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
